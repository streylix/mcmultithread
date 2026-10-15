// Scripted player swarm. Each bot follows a seeded script inside the city: walk between
// waypoints, place and break blocks, attack nearby mobs, chat. Every action is logged as
// attempted, then as completed (with latency) or failed, so lag-induced divergence is visible.
//
// Usage: node swarm.js HOST PORT COUNT SEED OUT_FILE [PREFIX] [HALF] [DURATION_S] [CENTER_X] [CENTER_Z]
// Bots stay within +-HALF of the centre. Movement uses mineflayer-pathfinder (routes around
// buildings and through doorways, never digs); targets are checked before acting.
// Log lines (JSONL): {t: wall ms, bot, action, phase: attempt|done|fail, ms?, pos}
// The run script puts bots in creative mode and teleports them to start points.
import fs from 'node:fs'
import { createRequire } from 'node:module'
import mineflayer from 'mineflayer'
import { Vec3 } from 'vec3'

const { pathfinder, Movements, goals } = createRequire(import.meta.url)('mineflayer-pathfinder')

const [host = '127.0.0.1', port = '25599', countArg = '5', seedArg = '1', outFile = 'actions.jsonl',
  prefix = 'b', halfArg = '480', durationArg = '0', cxArg = '0', czArg = '0'] = process.argv.slice(2)
const centre = { x: Number(cxArg), z: Number(czArg) }
const count = Number(countArg)
const half = Number(halfArg)
const log = fs.createWriteStream(outFile, { flags: 'a' })
const CONNECT_SPACING_MS = 250

// Small deterministic PRNG (mulberry32) so each bot's script depends only on SEED and index.
function rng (seed) {
  return () => {
    seed = (seed + 0x6D2B79F5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function record (bot, action, phase, extra = {}) {
  const p = bot.entity?.position
  log.write(JSON.stringify({
    t: Date.now(), bot: bot.username, action, phase,
    pos: p ? [+p.x.toFixed(2), +p.y.toFixed(2), +p.z.toFixed(2)] : null, ...extra
  }) + '\n')
}

async function timed (bot, action, fn) {
  record(bot, action, 'attempt')
  const t0 = performance.now()
  try {
    await fn()
    record(bot, action, 'done', { ms: +(performance.now() - t0).toFixed(1) })
  } catch (e) {
    record(bot, action, 'fail', { ms: +(performance.now() - t0).toFixed(1), err: String(e.message || e).slice(0, 120) })
  }
}

async function goNear (bot, pos, range, timeoutMs = 15000) {
  // pathfinder.stop() is deferred to a later tick and would cancel the *next* goal, so a
  // timeout clears the goal immediately instead.
  let timer
  try {
    await Promise.race([
      bot.pathfinder.goto(new goals.GoalNear(pos.x, pos.y, pos.z, range)),
      new Promise((resolve, reject) => {
        timer = setTimeout(() => { bot.pathfinder.setGoal(null); reject(new Error('path timeout')) }, timeoutMs)
      })
    ])
  } finally {
    clearTimeout(timer)
  }
}

const OFFSETS = [[2, 0], [-2, 0], [0, 2], [0, -2], [2, 2], [-2, 2], [2, -2], [-2, -2], [3, 0], [0, 3]]

function freeSpot (bot, pos) {
  // Placeable: solid support below, air at the spot, nobody standing in it.
  const below = bot.blockAt(pos.offset(0, -1, 0))
  const at = bot.blockAt(pos)
  if (!below || below.boundingBox !== 'block' || !at || at.name !== 'air') return null
  const occupied = Object.values(bot.entities).some(e => e.position && e.position.floored().equals(pos))
  return occupied ? null : below
}

async function placeBlock (bot, rand) {
  const item = bot.inventory.items().find(i => i.name === 'oak_planks')
  if (!item) throw new Error('no blocks in inventory')
  await bot.equip(item, 'hand')
  const base = bot.entity.position.floored()
  const start = Math.floor(rand() * OFFSETS.length)
  for (let k = 0; k < OFFSETS.length; k++) {
    const [dx, dz] = OFFSETS[(start + k) % OFFSETS.length]
    const spot = base.offset(dx, 0, dz)
    const support = freeSpot(bot, spot)
    if (support) {
      await bot.placeBlock(support, new Vec3(0, 1, 0))
      return
    }
  }
  throw new Error('no free spot nearby')
}

async function breakBlock (bot) {
  const target = bot.findBlock({ matching: b => b.name === 'oak_planks', maxDistance: 24 })
  if (!target) throw new Error('no planks within 24')
  if (target.position.distanceTo(bot.entity.position.offset(0, 1.6, 0)) > 4) await goNear(bot, target.position, 2, 10000)
  await bot.dig(target, true)
}

async function attackMob (bot) {
  const mob = bot.nearestEntity(e => (e.type === 'animal' || e.type === 'mob' || e.type === 'hostile') &&
    e.position.distanceTo(bot.entity.position) < 32)
  if (!mob) throw new Error('no mob within 32')
  if (mob.position.distanceTo(bot.entity.position) > 3) await goNear(bot, mob.position, 2, 10000)
  if (!mob.isValid || mob.position.distanceTo(bot.entity.position) > 3.5) throw new Error('mob moved out of reach')
  await bot.lookAt(mob.position.offset(0, mob.height / 2, 0), true)
  bot.attack(mob)
}

async function script (bot, rand) {
  // A waypoint must be loaded and standable: solid below, two blocks of air (not in a wall).
  const waypoint = () => {
    let p
    for (let k = 0; k < 20; k++) {
      p = new Vec3(Math.floor(centre.x - half + rand() * 2 * half), 0, Math.floor(centre.z - half + rand() * 2 * half))
      const below = bot.blockAt(p.offset(0, -1, 0))
      const feet = bot.blockAt(p)
      const head = bot.blockAt(p.offset(0, 1, 0))
      if (below?.boundingBox === 'block' && feet?.boundingBox === 'empty' && head?.boundingBox === 'empty') return p
    }
    return p
  }
  let n = 0
  while (bot.entity) {
    const roll = rand()
    if (roll < 0.55) {
      await timed(bot, 'walk', () => goNear(bot, waypoint(), 2, 20000))
    } else if (roll < 0.70) {
      await timed(bot, 'place', () => placeBlock(bot, rand))
    } else if (roll < 0.80) {
      await timed(bot, 'break', () => breakBlock(bot))
    } else if (roll < 0.92) {
      await timed(bot, 'attack', () => attackMob(bot))
    } else {
      const msg = `${bot.username} step ${n}`
      await timed(bot, 'chat', () => new Promise((resolve, reject) => {
        const timer = setTimeout(() => { bot.removeListener('chat', onChat); reject(new Error('chat echo timeout')) }, 10000)
        const onChat = (user, text) => {
          if (user === bot.username && text === msg) { clearTimeout(timer); bot.removeListener('chat', onChat); resolve() }
        }
        bot.on('chat', onChat)
        bot.chat(msg)
      }))
    }
    n++
    await new Promise(resolve => setTimeout(resolve, 500 + rand() * 1500))
  }
}

function startBot (i) {
  const rand = rng(Number(seedArg) * 100003 + i)
  const bot = mineflayer.createBot({ host, port: Number(port), username: `${prefix}${i}`, auth: 'offline', viewDistance: 'normal' })
  bot.loadPlugin(pathfinder)
  bot.once('spawn', () => {
    const moves = new Movements(bot)
    moves.canDig = false
    moves.allow1by1towers = false
    moves.scafoldingBlocks = []
    bot.pathfinder.setMovements(moves)
    record(bot, 'spawn', 'done')
    setTimeout(() => script(bot, rand).catch(e => record(bot, 'script', 'fail', { err: String(e) })), 3000)
  })
  bot.on('kicked', reason => record(bot, 'kicked', 'fail', { err: JSON.stringify(reason).slice(0, 200) }))
  bot.on('error', e => record(bot, 'error', 'fail', { err: String(e.message || e).slice(0, 200) }))
  bot.on('end', () => record(bot, 'disconnect', 'done'))
  return bot
}

const bots = []
for (let i = 0; i < count; i++) {
  bots.push(startBot(i))
  await new Promise(resolve => setTimeout(resolve, CONNECT_SPACING_MS))
}

function stop () {
  for (const b of bots) { try { b.quit() } catch {} }
  setTimeout(() => log.end(() => process.exit(0)), 1500)
}
process.on('SIGINT', stop)
process.on('SIGTERM', stop)
if (Number(durationArg) > 0) setTimeout(stop, Number(durationArg) * 1000)
