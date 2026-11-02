import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

const CHECK_EVERY_MS = 5000

function clock(seconds) {
  const m = Math.floor(seconds / 60)
  const s = String(seconds % 60).padStart(2, '0')
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}:${s}` : `${m}:${s}`
}

// The meeting recorder on the Meetings page: shows a running recording (started by you or
// automatically from the calendar), and lets you record a meeting that is not in the calendar.
export default function RecorderBar({ onChanged }) {
  const [status, setStatus] = useState(null)
  const [showStart, setShowStart] = useState(false)
  const [title, setTitle] = useState('')
  const [message, setMessage] = useState({ text: '', error: false })
  const [round, setRound] = useState(0)
  const onChangedRef = useRef(onChanged)
  useEffect(() => {
    onChangedRef.current = onChanged
  })

  useEffect(() => {
    let timer
    let stopped = false
    let wasRunning = null
    async function check() {
      try {
        const s = await api('/meetings/recorder')
        if (stopped) return
        setStatus(s)
        if (wasRunning !== null && wasRunning !== s.running) onChangedRef.current?.() // started/stopped
        wasRunning = s.running
      } catch {
        // the page shows other errors; try again next time
      }
      if (!stopped) timer = setTimeout(check, CHECK_EVERY_MS)
    }
    check()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [round])

  async function start() {
    setMessage({ text: '', error: false })
    try {
      await api('/meetings/record', { method: 'POST', body: { title } })
      setShowStart(false)
      setTitle('')
      setRound((r) => r + 1)
      onChanged?.()
    } catch (e) {
      setMessage({ text: e.message, error: true })
    }
  }

  async function stop() {
    try {
      await api('/meetings/record/stop', { method: 'POST' })
      setMessage({
        text: 'Recording stopped. The transcript and the summary are made now - you get a notification when they are ready.',
        error: false,
      })
      setRound((r) => r + 1)
      onChanged?.()
    } catch (e) {
      setMessage({ text: e.message, error: true })
    }
  }

  if (!status) return null

  return (
    <div className="border-b border-slate-200 bg-surface px-6 py-3">
      {status.running ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="h-3 w-3 animate-pulse rounded-full bg-red-600" />
          <span className="font-medium text-red-700">Recording</span>
          <span dir="auto" className="font-medium">{status.title}</span>
          <span className="text-slate-500">
            {clock(status.seconds)}
            {status.until && ` · stops at ${new Date(status.until).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`}
          </span>
          <button onClick={stop} className="ms-auto rounded-md bg-red-600 px-3 py-1.5 font-medium text-white hover:bg-red-700">
            Stop
          </button>
        </div>
      ) : showStart ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <input
            dir="auto"
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && start()}
            placeholder="Meeting title"
            className="w-64 rounded-md border border-slate-300 px-2 py-1.5"
          />
          <button onClick={start} className="rounded-md bg-red-600 px-3 py-1.5 font-medium text-white hover:bg-red-700">
            Start recording
          </button>
          <button onClick={() => setShowStart(false)} className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-50">
            Cancel
          </button>
          <span className="text-xs text-slate-500">
            Records your microphone (you) and your speakers (the others). Tell the others first. Headphones work best.
          </span>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">
          <span>
            Not recording. Meetings in your calendar are recorded automatically when <b>Auto-record</b> is on
            (Settings).
          </span>
          <button onClick={() => setShowStart(true)} className="ms-auto rounded-md border border-slate-300 bg-surface px-3 py-1.5 font-medium hover:bg-slate-50">
            ● Record now
          </button>
        </div>
      )}
      {status.error && !status.running && <p className="mt-2 text-sm text-red-600">{status.error}</p>}
      {message.text && <p className={`mt-2 text-sm ${message.error ? 'text-red-600' : 'text-emerald-700'}`}>{message.text}</p>}
    </div>
  )
}
