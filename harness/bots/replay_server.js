// Replay server: plays a recorder .mcpr (ReplayMod format 14) back into a real Minecraft
// client, so footage is filmed after the test, never during it.
//
// The protocol library handles handshake and offline login; from login acknowledgement on,
// the recorded configuration packets are sent raw, then the recorded play packets at their
// original timing. The camera is moved by injected position packets along a keyframed path.
//
// Usage: node replay_server.js MCPR PATH_JSON PORT [FROM_MS]
//   stdout protocol: READY (world up to FROM_MS sent; waiting) -> stdin "GO" -> DONE
//   PATH_JSON: {"keyframes":[{"t":s,"x","y","z","yaw","pitch"}, ...]}, t relative to GO.
import fs from 'node:fs'
import { createRequire } from 'node:module'
import readline from 'node:readline'
import mc from 'minecraft-protocol'

const require = createRequire(import.meta.url)
const [mcprPath, pathFile, port = '25600', fromArg = '0'] = process.argv.slice(2)
const fromMs = Number(fromArg)
const keyframes = JSON.parse(fs.readFileSync(pathFile, 'utf8')).keyframes

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

// --- camera path ----------------------------------------------------------------------
function cameraAt (t) {
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
  while (i < play.length && play[i][0] - playStart < fromMs) client.writeRaw(play[i++][1])
  place(client, cameraAt(0))
  await new Promise(resolve => setTimeout(resolve, 10000)) // client builds chunk meshes
  console.log(JSON.stringify({ event: 'READY', from_ms: fromMs, recording_date: meta.date, play_start_ms: playStart }))
  await go
  const t0 = performance.now()
  const end = keyframes[keyframes.length - 1].t * 1000
  const tick = setInterval(() => {
    const now = performance.now() - t0
    while (i < play.length && play[i][0] - playStart - fromMs <= now) client.writeRaw(play[i++][1])
    place(client, cameraAt(now / 1000))
    if (now >= end) {
      clearInterval(tick)
      console.log(JSON.stringify({ event: 'DONE', packets_sent: i }))
    }
  }, 50)
}
console.log(JSON.stringify({ event: 'LISTENING', port: Number(port), config: config.length, play: play.length }))
