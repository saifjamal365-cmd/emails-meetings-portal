// Email & Meeting Portal - Meet helper: the background part.
//
// Sends what meet.js noted to the portal on THIS computer (nowhere else), with the key the
// portal gave (portal.js). If the portal is not running, the messages wait and are sent later.

const PORTAL = 'http://127.0.0.1:8000'
const MAX_WAITING = 2000

let chain = Promise.resolve() // one change of the waiting list at a time
let sending = false

async function waiting() {
  return (await chrome.storage.local.get('queue')).queue ?? []
}

async function setWaiting(queue) {
  await chrome.storage.local.set({ queue: queue.slice(-MAX_WAITING) })
}

async function post(path, body) {
  const { key } = await chrome.storage.local.get('key')
  if (!key) return 'no key'
  const response = await fetch(PORTAL + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Portal-Extension': key },
    body: JSON.stringify(body),
  })
  if (response.status === 401) {
    await chrome.storage.local.remove('key') // the key changed: the portal page gives a new one
    return 'no key'
  }
  // 422 = the portal does not accept this message: do not send it again and again
  return response.ok || response.status === 422 ? 'sent' : 'later'
}

async function flush() {
  if (sending) return
  sending = true
  try {
    for (;;) {
      const queue = await waiting()
      if (!queue.length) return
      let result
      try {
        result = await post(queue[0].path, queue[0].body)
      } catch {
        result = 'later' // the portal is not running
      }
      if (result !== 'sent') return
      chain = chain.then(async () => setWaiting((await waiting()).slice(1)))
      await chain
    }
  } finally {
    sending = false
  }
}

function add(path, body) {
  chain = chain.then(async () => setWaiting([...(await waiting()), { path, body }]))
  chain.then(flush)
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'key') {
    chrome.storage.local
      .set({ key: message.key })
      .then(() => post('/api/extension/hello', {}))
      .catch(() => {})
      .then(flush)
  } else if (message.type === 'call') {
    add('/api/extension/call', {
      meeting_code: message.code,
      state: message.state,
      at: message.at,
      captions_on: message.captionsOn,
      caption_lines: message.linesRead,
      page: message.page,
    })
  } else if (message.type === 'captions') {
    add('/api/extension/captions', { meeting_code: message.code, lines: message.lines })
  }
})

chrome.alarms.create('send-again', { periodInMinutes: 1 })
chrome.alarms.onAlarm.addListener(flush)
