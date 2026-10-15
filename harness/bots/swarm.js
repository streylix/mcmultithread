// Scripted player swarm. Each bot follows a seeded script inside the city: walk between
// waypoints, place and break blocks, attack nearby mobs, chat. Every action is logged as
// attempted, then as completed (with latency) or failed, so lag-induced divergence is visible.
//
// Usage: node swarm.js HOST PORT COUNT SEED OUT_FILE [PREFIX] [HALF] [DURATION_S]
// Log lines (JSONL): {t: wall ms, bot, action, phase: attempt|done|fail, ms?, pos}
// The run script puts bots in creative mode and teleports them to start points.
import fs from 'node:fs'
import mineflayer from 'mineflayer'
import { Vec3 } from 'vec3'

const [host = '127.0.0.1', port = '25599', countArg = '5', seedArg = '1', outFile = 'actions.jsonl',
  prefix = 'b', halfArg = '480', durationArg = '0'] = process.argv.slice(2)
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

function walkTo (bot, target, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const started = Date.now()
    let last = bot.entity.position.clone()
    let stuckTicks = 0
    const onTick = () => {
      const pos = bot.entity.position
      const dist = Math.hypot(target.x - pos.x, target.z - pos.z)
      if (dist < 1.5) return done()
      if (Date.now() - started > timeoutMs) return done(new Error('walk timeout'))
      bot.lookAt(new Vec3(target.x, pos.y + 1.6, target.z), true)
      bot.setControlState('forward', true)
      bot.setControlState('sprint', dist > 6)
      stuckTicks = pos.distanceTo(last) < 0.05 ? stuckTicks + 1 : 0
      bot.setControlState('jump', stuckTicks > 5)
      last = pos.clone()
    }
    const done = (err) => {
      bot.removeListener('physicsTick', onTick)
      bot.clearControlStates()
      err ? reject(err) : resolve()
    }
    bot.on('physicsTick', onTick)
  })
}

async function placeBlock (bot) {
  const below = bot.blockAt(bot.entity.position.offset(1, -1, 0).floored())
  if (!below || below.name === 'air') throw new Error('no support block')
  const item = bot.inventory.items().find(i => i.name === 'oak_planks')
  if (!item) throw new Error('no blocks in inventory')
  await bot.equip(item, 'hand')
  await bot.placeBlock(below, new Vec3(0, 1, 0))
}

async function breakBlock (bot) {
  const target = bot.findBlock({ matching: b => b.name === 'oak_planks', maxDistance: 4 })
  if (!target) throw new Error('nothing to break')
  await bot.dig(target, true)
}

async function attackMob (bot) {
  const mob = bot.nearestEntity(e => e.type === 'mob' || e.type === 'hostile' || e.type === 'animal')
  if (!mob || mob.position.distanceTo(bot.entity.position) > 4) throw new Error('no mob in reach')
  await bot.lookAt(mob.position.offset(0, mob.height / 2, 0), true)
  bot.attack(mob)
}

async function script (bot, rand) {
  const waypoint = () => new Vec3(-half + rand() * 2 * half, 0, -half + rand() * 2 * half)
  let n = 0
  while (bot.entity) {
    const roll = rand()
    if (roll < 0.55) {
      const here = bot.entity.position
      const near = waypoint().scaled(0.05).plus(new Vec3(here.x, 0, here.z)) // short hop near current spot
      await timed(bot, 'walk', () => walkTo(bot, near))
    } else if (roll < 0.70) {
      await timed(bot, 'place', () => placeBlock(bot))
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
  const bot = mineflayer.createBot({ host, port: Number(port), username: `${prefix}${i}`, auth: 'offline', viewDistance: 'short' })
  bot.once('spawn', () => {
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
