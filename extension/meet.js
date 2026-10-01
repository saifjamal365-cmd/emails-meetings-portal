// Email & Meeting Portal - Meet helper: runs on meet.google.com.
//
// During a Google Meet call it
//   1. tells the portal when you join and when you leave (the recorder starts and stops with you),
//   2. turns on Google Meet's live captions,
//   3. notes WHO speaks WHEN, and the caption words, for the portal.
// The background part sends this only to the portal on this computer (localhost:8000).
//
// Google changes the Meet page from time to time, so this looks for things that stay the same:
// the "call_end" / "closed_caption_off" icons, the captions region, and each speaker's picture.
;(() => {
  const CODE = /^\/([a-z]{3}-[a-z]{4}-[a-z]{3})(?:[/?#]|$)/
  const meetingCode = () => CODE.exec(location.pathname)?.[1] ?? null

  function send(message) {
    try {
      chrome.runtime.sendMessage(message)?.catch?.(() => {}) // no reply is expected
    } catch {
      // the extension was reloaded: this old page cannot send any more
    }
  }

  // ---- in the call or not ----------------------------------------------------------------

  function iconButton(icons) {
    return [...document.querySelectorAll('button')].find((button) =>
      [...button.querySelectorAll('i, span')].some((el) => icons.includes(el.textContent.trim())),
    )
  }

  // The red "Leave call" button exists only inside a call.
  const inCall = () =>
    Boolean(
      iconButton(['call_end']) ||
        document.querySelector('button[aria-label*="Leave call" i], button[aria-label*="مغادرة"]'),
    )

  // ---- captions on ---------------------------------------------------------------------------

  const captionsRegion = () =>
    document.querySelector('[role="region"][aria-label*="caption" i]') ||
    document.querySelector('[role="region"][aria-label*="ترجم"]') ||
    document.querySelector('[role="region"][aria-label*="شرح"]')

  let captionTries = 0

  function turnOnCaptions() {
    if (captionsRegion() || captionTries >= 5) return
    const button =
      document.querySelector('button[aria-label*="Turn on captions" i]') ||
      document.querySelector('button[aria-label*="caption" i][aria-pressed="false"]') ||
      iconButton(['closed_caption_off'])
    if (button) {
      captionTries += 1
      button.click()
    }
  }

  // ---- who speaks when -------------------------------------------------------------------------
  // The captions region shows one block per speaker turn: the speaker's picture and name, then
  // the words, which grow while the person talks. One block = one caption line for the portal.

  // block element -> {id, name, start, end, text, spans, sent}. `spans` = when the words really
  // grew ([start, end] pairs): Meet can keep ONE box open for a speaker for many minutes while
  // others talk, so "start to end" alone would say she talked the whole time.
  const lines = new Map()
  const SPAN_GAP = 2000 // ms without new words = a new speaking moment
  const MAX_SPANS = 500

  function blocksIn(region) {
    const blocks = new Set()
    for (const picture of region.querySelectorAll('img')) {
      let block = picture.parentElement
      // the biggest box around this picture that has no other speaker's picture
      while (
        block.parentElement &&
        block.parentElement !== region &&
        block.parentElement.querySelectorAll('img').length === 1
      ) {
        block = block.parentElement
      }
      blocks.add(block)
    }
    return [...blocks]
  }

  function readBlock(block) {
    const rows = (block.innerText || '')
      .split('\n')
      .map((row) => row.trim())
      .filter(Boolean)
    if (rows.length < 2) return null
    return { name: rows[0], text: rows.slice(1).join(' ') }
  }

  const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`

  function readCaptions() {
    const region = captionsRegion()
    if (!region) return
    const now = Date.now()
    for (const block of blocksIn(region)) {
      const found = readBlock(block)
      if (!found) continue
      const line = lines.get(block)
      if (!line) {
        const spans = [[now, now]]
        lines.set(block, { id: newId(), name: found.name, start: now, end: now, text: found.text, spans, sent: false })
        linesRead += 1
      } else if (line.text !== found.text) {
        const last = line.spans[line.spans.length - 1]
        if (now - last[1] <= SPAN_GAP) last[1] = now
        else if (line.spans.length < MAX_SPANS) line.spans.push([now, now])
        Object.assign(line, { text: found.text, end: now, sent: false })
      }
    }
  }

  // Read the captions the moment they change (timers can be slowed down by the browser), and
  // also on every tick.
  const observer = new MutationObserver(() => joinedCode && readCaptions())
  let watched = null

  function watchCaptions() {
    const region = captionsRegion()
    if (region && region !== watched) {
      observer.disconnect()
      observer.observe(region, { childList: true, subtree: true, characterData: true })
      watched = region
    }
  }

  function sendCaptions(code) {
    const ready = [...lines.values()].filter((line) => !line.sent)
    if (ready.length) {
      send({
        type: 'captions',
        code,
        lines: ready.map(({ id, name, start, end, text, spans }) => ({
          id,
          name,
          start,
          end,
          text: text.slice(0, 5000),
          spans: spans.map((span) => [...span]),
        })),
      })
      ready.forEach((line) => (line.sent = true))
    }
    for (const [block, line] of lines) {
      if (line.sent && !block.isConnected) lines.delete(block) // gone from the screen, sent
    }
  }

  // When the captions cannot be turned on: which buttons and regions this Meet page has (their
  // labels and icon names only), so the portal's log shows what to look for.
  function pageReport() {
    const buttons = [...document.querySelectorAll('button')]
      .map((button) => ({
        label: (button.getAttribute('aria-label') || '').slice(0, 60),
        icon: (button.querySelector('i, span')?.textContent || '').trim().slice(0, 30),
        pressed: button.getAttribute('aria-pressed'),
      }))
      .filter((b) => b.label || b.icon)
      .slice(0, 60)
    const regions = [...document.querySelectorAll('[role="region"]')].map((r) => r.getAttribute('aria-label'))
    return { buttons, regions, width: window.innerWidth }
  }

  // ---- the loop --------------------------------------------------------------------------------

  let joinedCode = null
  let joinedAt = 0
  let lastInCall = 0
  let linesRead = 0 // for the health report in the portal's log
  let reported = false

  function call(state, code, page = undefined) {
    const captionsOn = Boolean(captionsRegion())
    send({ type: 'call', state, code, at: Date.now(), captionsOn, linesRead, page })
  }

  function tick() {
    const code = meetingCode()
    const now = Date.now()
    if (code && inCall()) {
      if (joinedCode !== code) {
        joinedCode = code
        joinedAt = now
        captionTries = 0
        linesRead = 0
        reported = false
        lastInCall = now
        call('joined', code)
      } else if (!reported && now - joinedAt > 15000 && !captionsRegion()) {
        reported = true // once per call: the captions are still not on after 15 seconds
        lastInCall = now
        call('in_call', code, pageReport())
      } else if (now - lastInCall > 60000) {
        lastInCall = now
        call('in_call', code) // "still here": the recorder does not stop for silence
      }
      turnOnCaptions()
      watchCaptions()
      readCaptions()
    } else if (joinedCode) {
      sendCaptions(joinedCode)
      call('left', joinedCode)
      joinedCode = null
    }
  }

  setInterval(tick, 500)
  setInterval(() => joinedCode && sendCaptions(joinedCode), 5000)
  window.addEventListener('pagehide', () => {
    if (!joinedCode) return
    sendCaptions(joinedCode)
    call('left', joinedCode)
  })
})()
