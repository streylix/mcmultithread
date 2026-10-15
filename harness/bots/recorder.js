// Passive recorder: joins as a client and writes every packet the server sends it, from
// login success onward, in ReplayMod's packet format (file format 14). Renders nothing.
//
// Usage: node recorder.js HOST PORT NAME OUT_DIR
// Writes OUT_DIR/recording.tmcpr and OUT_DIR/metaData.json; the run script zips them
// into a .mcpr. Stops on SIGINT/SIGTERM or disconnect.
//
// Entry layout (big-endian): int32 ms since start, int32 length, packet id + payload.
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import mineflayer from 'mineflayer'

const mcData = createRequire(import.meta.url)('minecraft-data')

const [host = '127.0.0.1', port = '25599', name = 'rec0', outDir = '.'] = process.argv.slice(2)
fs.mkdirSync(outDir, { recursive: true })
const out = fs.createWriteStream(path.join(outDir, 'recording.tmcpr'))
const startWall = Date.now()
const start = process.hrtime.bigint()
let recording = false
let packets = 0
let protocol = null
let version = null
const players = new Set()

const bot = mineflayer.createBot({ host, port: Number(port), username: name, auth: 'offline', viewDistance: 'far' })
const client = bot._client

client.on('packet', (data, meta, buffer, fullBuffer) => {
  // Recording starts at login success, as ReplayMod's own recorder does.
  if (!recording) {
    if (meta.state !== 'login' || meta.name !== 'success') return
    recording = true
  }
  const ms = Number((process.hrtime.bigint() - start) / 1000000n)
  const header = Buffer.alloc(8)
  header.writeInt32BE(ms, 0)
  header.writeInt32BE(fullBuffer.length, 4)
  out.write(header)
  out.write(fullBuffer)
  packets++
  if (meta.name === 'player_info' && Array.isArray(data.data)) {
    for (const entry of data.data) if (entry.uuid) players.add(entry.uuid)
  }
})

bot.once('login', () => {
  version = bot.version
  protocol = mcData(bot.version).version.version
  console.log(JSON.stringify({ event: 'login', protocol, version, wall_ms: startWall }))
})
bot.once('spawn', () => console.log(JSON.stringify({ event: 'spawn', packets })))
bot.on('kicked', r => console.error('kicked', JSON.stringify(r)))
bot.on('error', e => console.error('error', e.message))

let finished = false
function finish (code = 0) {
  if (finished) return
  finished = true
  const duration = Number((process.hrtime.bigint() - start) / 1000000n)
  out.end(() => {
    const meta = {
      singleplayer: false,
      serverName: 'project5k',
      duration,
      date: startWall,
      mcversion: process.env.MC_VERSION || version,
      fileFormat: 'MCPR',
      fileFormatVersion: 14,
      protocol,
      generator: 'project5k recorder',
      selfId: -1,
      players: [...players]
    }
    fs.writeFileSync(path.join(outDir, 'metaData.json'), JSON.stringify(meta))
    console.log(JSON.stringify({ event: 'stopped', packets, duration_ms: duration }))
    process.exit(code)
  })
  try { bot.quit() } catch {}
}
process.on('SIGINT', () => finish(0))
process.on('SIGTERM', () => finish(0))
bot.on('end', () => finish(0))
