import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

const CHECK_EVERY_MS = 3000

function progressText(s) {
  if (s.stage === 'fetching') return 'Reading new emails from Gmail...'
  return `Analyzing emails: ${s.analyzed} of ${s.to_analyze} done`
}

function resultText(s) {
  if (s.error) return s.error
  const text = `${s.new} new, ${s.analyzed} analyzed (High ${s.high}, Low ${s.low})`
  return s.errors?.length ? `${text}. ${s.errors[0]}` : text
}

// "Refresh" = read unread emails from Gmail and let the Email agent analyze them.
// The sync runs in the background; this button shows its progress and reloads the list
// while emails are analyzed. It also shows a sync that is already running (for example the
// automatic one every 5 minutes, or after the page was reloaded).
export default function SyncButton({ onDone }) {
  const [status, setStatus] = useState(null)
  const [message, setMessage] = useState('')
  const [round, setRound] = useState(0) // +1 after each Refresh click: follow the new sync

  // The parent may pass a new onDone on every render; keep the latest without restarting.
  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onDoneRef.current = onDone
  })

  useEffect(() => {
    let timer
    let stopped = false
    let lastAnalyzed = -1
    let wasRunning = round > 0

    async function check() {
      try {
        const s = await api('/emails/sync-status')
        if (stopped) return
        setStatus(s)
        if (s.running) {
          wasRunning = true
          if (s.analyzed !== lastAnalyzed) {
            lastAnalyzed = s.analyzed
            onDoneRef.current?.() // show the emails analyzed so far
          }
          timer = setTimeout(check, CHECK_EVERY_MS)
        } else if (wasRunning) {
          wasRunning = false
          setMessage(resultText(s))
          onDoneRef.current?.()
        }
      } catch (e) {
        if (!stopped) setMessage(e.message)
      }
    }

    check()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [round])

  async function sync() {
    setMessage('')
    try {
      await api('/emails/sync', { method: 'POST' })
      setRound((r) => r + 1)
    } catch (e) {
      setMessage(e.message)
    }
  }

  const running = status?.running

  return (
    <div className="flex items-center gap-3">
      {running ? (
        <span className="flex items-center gap-2 text-sm text-blue-700">
          <span className="h-2 w-2 animate-pulse rounded-full bg-blue-600" />
          {progressText(status)}
        </span>
      ) : (
        message && <span className="text-sm text-slate-600">{message}</span>
      )}
      <button
        onClick={sync}
        disabled={running}
        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
      >
        {running ? 'Checking Gmail...' : 'Refresh'}
      </button>
    </div>
  )
}
