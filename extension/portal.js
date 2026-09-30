// Email & Meeting Portal - Meet helper: runs on the portal page (localhost:8000).
//
// Connects the extension to the portal by itself: when you are logged in to the portal, it
// takes the extension's key from the portal and gives it to the extension. Nothing to type.
;(() => {
  async function pair() {
    try {
      const response = await fetch('/api/extension/pair', { credentials: 'same-origin' })
      if (!response.ok) return false // not logged in yet
      const { key } = await response.json()
      chrome.runtime.sendMessage({ type: 'key', key }).catch(() => {}) // no reply is expected
      return true
    } catch {
      return false
    }
  }

  pair().then((paired) => {
    if (paired) return
    const timer = setInterval(async () => {
      if (await pair()) clearInterval(timer)
    }, 15000) // try again after you log in
  })
})()
