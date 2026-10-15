// Connect N offline-mode bots, walk and chat briefly, report what worked.
import mineflayer from 'mineflayer'

const [host = '127.0.0.1', port = '25599', count = '5'] = process.argv.slice(2)
const results = []

function runBot (i) {
  return new Promise(resolve => {
    const r = { name: `bot${i}`, spawned: false, moved: false, chatted: false, error: null }
    const bot = mineflayer.createBot({ host, port: Number(port), username: r.name, auth: 'offline' })
    const finish = () => { clearTimeout(timer); try { bot.quit() } catch {} resolve(r) }
    const timer = setTimeout(() => { r.error ??= 'timeout'; finish() }, 30000)
    bot.once('spawn', () => {
      r.spawned = true
      r.version = bot.version
      const start = bot.entity.position.clone()
      bot.setControlState('forward', true)
      setTimeout(() => {
        bot.setControlState('forward', false)
        r.moved = bot.entity.position.distanceTo(start) > 1
        bot.chat(`hello from ${r.name}`)
      }, 3000)
    })
    bot.on('chat', (user, msg) => { if (user === r.name) { r.chatted = true; finish() } })
    bot.on('kicked', reason => { r.error = `kicked: ${JSON.stringify(reason)}`; finish() })
    bot.on('error', err => { r.error = String(err.message || err); finish() })
  })
}

const all = await Promise.all(Array.from({ length: Number(count) }, (_, i) => runBot(i)))
console.log(JSON.stringify(all, null, 1))
process.exit(all.every(r => r.spawned && r.moved && r.chatted) ? 0 : 1)
