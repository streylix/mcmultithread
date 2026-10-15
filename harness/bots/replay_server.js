// Replay server: plays a recorder .mcpr (ReplayMod format 14) back into a real Minecraft
// client, so footage is filmed after the test, never during it.
//
// The protocol library handles handshake and offline login; from login acknowledgement on,
// the recorded configuration packets are sent raw, then the recorded play packets at their
// original timing. The camera is moved by injected position packets along a keyframed path.
//
// Usage: node replay_server.js MCPR PATH_JSON PORT [FROM_MS]
//   stdout protocol: READY (world up to FROM_MS sent; waiting) -> stdin "GO" -> DONE
//   PATH_JSON: {"segments": [...]}, times in seconds relative to GO. Segment kinds:
//     {"mode": "path", "t0", "t1", "keyframes": [{"t","x","y","z","yaw","pitch"}, ...]}
//     {"mode": "follow", "t0", "t1", "target": "b3", "distance": 6, "height": 3}
//       third-person view behind a player, positioned from the recorded entity packets.
//   A bare {"keyframes": [...]} file is one path segment.
import fs from 'node:fs'
import { createRequire } from 'node:module'
import readline from 'node:readline'
import mc from 'minecraft-protocol'

const require = createRequire(import.meta.url)
const [mcprPath, pathFile, port = '25600', fromArg = '0'] = process.argv.slice(2)
const fromMs = Number(fromArg)
const spec = JSON.parse(fs.readFileSync(pathFile, 'utf8'))
const segments = spec.segments ?? [{ mode: 'path', t0: 0, t1: spec.keyframes.at(-1).t, keyframes: spec.keyframes }]
const endS = Math.max(...segments.map(s => s.t1))

// --- read the recording ---------------------------------------------------------------
function readMcpr (file) {
  // Minimal zip reader: find the two entries via the central directory.
  const zip = fs.readFileSync(file)
  const zlib = require('node:zlib')
  const eocd = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]))
  const count = zip.readUInt16LE(eocd + 10)
  let p = zip.readUInt32LE(eocd + 16)
  const files = {}
  for (let i = 0; i < count; i++) {
    const method = zip.readUInt16LE(p + 10)
    const size = zip.readUInt32LE(p + 20)
    const nameLen = zip.readUInt16LE(p + 28)
    const extraLen = zip.readUInt16LE(p + 30)
    const commentLen = zip.readUInt16LE(p + 32)
    const local = zip.readUInt32LE(p + 42)
    const name = zip.toString('utf8', p + 46, p + 46 + nameLen)
    const lNameLen = zip.readUInt16LE(local + 26)
    const lExtraLen = zip.readUInt16LE(local + 28)
    const data = zip.subarray(local + 30 + lNameLen + lExtraLen, local + 30 + lNameLen + lExtraLen + size)
    files[name] = method === 8 ? zlib.inflateRawSync(data) : data
    p += 46 + nameLen + extraLen + commentLen
  }
  return files
}

const files = readMcpr(mcprPath)
const meta = JSON.parse(files['metaData.json'].toString())
const version = meta.mcversion
const proto = require('minecraft-data')(version).protocol
const ids = (state, name) => Number(Object.entries(proto[state].toClient.types.packet[1][0].type[1].mappings)
  .find(([, v]) => v === name)[0])
const FINISH_CONFIG = ids('configuration', 'finish_configuration')
const START_CONFIG = ids('play', 'start_configuration')
const PLAY_POSITION = ids('play', 'position')

function varint (buf, off) {
  let value = 0; let shift = 0; let b
  do { b = buf[off++]; value |= (b & 0x7f) << shift; shift += 7 } while (b & 0x80)
  return value
}

// Split the stream into configuration and play packets, tracking protocol state.
const raw = files['recording.tmcpr']
const config = []; const play = []
let state = 'login'
for (let o = 0; o < raw.length;) {
  const t = raw.readInt32BE(o); const len = raw.readInt32BE(o + 4)
  const pkt = raw.subarray(o + 8, o + 8 + len)
  o += 8 + len
  const id = varint(pkt, 0)
  if (state === 'login') { state = 'configuration'; continue } // login success: sent by the library
  if (state === 'configuration') {
    config.push(pkt)
    if (id === FINISH_CONFIG) state = 'play'
    continue
  }
  if (id === START_CONFIG) break // reconfiguration is not replayed
  if (id === PLAY_POSITION) continue // the scripted camera owns the player position
  play.push([t, pkt])
}
const playStart = play.length ? play[0][0] : 0

// --- entity tracking (from the recorded packets as they are replayed) ------------------
const deserializer = mc.createDeserializer({ state: mc.states.PLAY, isServer: false, version, noErrorLogging: true })
const TRACKED = new Set(['spawn_entity', 'rel_entity_move', 'entity_move_look', 'sync_entity_position',
  'entity_teleport', 'entity_destroy', 'entity_look', 'player_info'])
const trackedIds = new Set([...TRACKED].map(n => ids('play', n)))
const entities = new Map() // entityId -> {x, y, z, yaw, uuid}
const names = new Map() // uuid -> player name
function track (pkt) {
  if (!trackedIds.has(varint(pkt, 0))) return
  let d
  try { d = deserializer.parsePacketBuffer(pkt).data } catch { return }
  const p = d.params
  switch (d.name) {
    case 'player_info':
      for (const e of p.data ?? []) if (e.player?.name) names.set(e.uuid, e.player.name)
      break
    case 'spawn_entity':
      entities.set(p.entityId, { x: p.x, y: p.y, z: p.z, yaw: p.yaw * 360 / 256, uuid: p.objectUUID })
      break
    case 'rel_entity_move':
    case 'entity_move_look': {
      const e = entities.get(p.entityId)
      if (!e) break
      e.x += p.dX / 4096; e.y += p.dY / 4096; e.z += p.dZ / 4096
      if (d.name === 'entity_move_look') e.yaw = p.yaw * 360 / 256
      break
    }
    case 'entity_look': {
      const e = entities.get(p.entityId)
      if (e) e.yaw = p.yaw * 360 / 256
      break
    }
    case 'sync_entity_position':
    case 'entity_teleport': {
      const e = entities.get(p.entityId)
      if (e) Object.assign(e, { x: p.x, y: p.y, z: p.z, yaw: p.yaw })
      break
    }
    case 'entity_destroy':
      for (const id of p.entityIds) entities.delete(id)
  }
}
function playerEntity (name) {
  for (const e of entities.values()) if (names.get(e.uuid) === name) return e
  return null
}

// --- camera ---------------------------------------------------------------------------
let smooth = null
function followCamera (seg) {
  const e = playerEntity(seg.target)
  if (!e) return null
  const dist = seg.distance ?? 6
  const height = seg.height ?? 3
  const yawRad = e.yaw * Math.PI / 180
  // Minecraft yaw: 0 = +z (south), 90 = -x. "Behind" is opposite the facing direction.
  const want = { x: e.x + Math.sin(yawRad) * dist, y: e.y + height, z: e.z - Math.cos(yawRad) * dist }
  smooth = smooth ? { x: smooth.x + (want.x - smooth.x) * 0.15, y: smooth.y + (want.y - smooth.y) * 0.15, z: smooth.z + (want.z - smooth.z) * 0.15 } : want
  const dx = e.x - smooth.x; const dy = (e.y + 1.4) - smooth.y; const dz = e.z - smooth.z
  return {
    ...smooth,
    yaw: Math.atan2(-dx, dz) * 180 / Math.PI,
    pitch: -Math.atan2(dy, Math.hypot(dx, dz)) * 180 / Math.PI
  }
}

function pathCamera (keyframes, t) {
  if (t <= keyframes[0].t) return keyframes[0]
  for (let i = 0; i + 1 < keyframes.length; i++) {
    const a = keyframes[i]; const b = keyframes[i + 1]
    if (t <= b.t) {
      const f = (t - a.t) / (b.t - a.t)
      const out = {}
      for (const k of ['x', 'y', 'z', 'yaw', 'pitch']) out[k] = a[k] + (b[k] - a[k]) * f
      return out
    }
  }
  return keyframes[keyframes.length - 1]
}

function cameraAt (t) {
  const seg = segments.find(s => t >= s.t0 && t <= s.t1) ?? segments.at(-1)
  if (seg.mode === 'follow') return followCamera(seg)
  smooth = null
  return pathCamera(seg.keyframes, t)
}

// --- server ---------------------------------------------------------------------------
const server = mc.createServer({ 'online-mode': false, port: Number(port), host: '127.0.0.1', version, keepAlive: false })
let teleportId = 1
const go = new Promise(resolve => {
  readline.createInterface({ input: process.stdin }).on('line', l => { if (l.trim() === 'GO') resolve() })
})

server.on('login', client => {
  client.removeAllListeners('login_acknowledged')
  client.once('login_acknowledged', () => {
    client.state = mc.states.CONFIGURATION
    client.once('finish_configuration', () => {
      client.state = mc.states.PLAY
      run(client).catch(e => { console.error(e); process.exit(1) })
    })
    for (const pkt of config) client.writeRaw(pkt)
  })
})

function place (client, p) {
  client.write('position', {
    teleportId: teleportId++, x: p.x, y: p.y, z: p.z, dx: 0, dy: 0, dz: 0, yaw: p.yaw, pitch: p.pitch, flags: {}
  })
}

async function run (client) {
  // Everything before FROM_MS goes out at once, so the world is complete at the start.
  let i = 0
  while (i < play.length && play[i][0] - playStart < fromMs) { track(play[i][1]); client.writeRaw(play[i++][1]) }
  const first = cameraAt(0)
  if (first) place(client, first)
  await new Promise(resolve => setTimeout(resolve, 10000)) // client builds chunk meshes
  console.log(JSON.stringify({ event: 'READY', from_ms: fromMs, recording_date: meta.date, play_start_ms: playStart }))
  await go
  const t0 = performance.now()
  const end = endS * 1000
  const tick = setInterval(() => {
    const now = performance.now() - t0
    while (i < play.length && play[i][0] - playStart - fromMs <= now) { track(play[i][1]); client.writeRaw(play[i++][1]) }
    const cam = cameraAt(now / 1000)
    if (cam) place(client, cam)
    if (now >= end) {
      clearInterval(tick)
      console.log(JSON.stringify({ event: 'DONE', packets_sent: i }))
    }
  }, 50)
}
console.log(JSON.stringify({ event: 'LISTENING', port: Number(port), config: config.length, play: play.length }))
