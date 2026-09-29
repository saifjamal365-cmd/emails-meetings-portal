import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { Badge } from '../components/Badges.jsx'
import MeetingDetail from '../components/MeetingDetail.jsx'
import RecorderBar from '../components/RecorderBar.jsx'

const STATUS = {
  ready: { text: 'Transcript ready', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  waiting: { text: 'Waiting for transcript', className: 'bg-amber-50 text-amber-800 ring-amber-200' },
  none: { text: 'No transcript', className: 'bg-slate-100 text-slate-500 ring-slate-200' },
  recording: { text: '● Recording', className: 'bg-red-50 text-red-700 ring-red-200' },
  transcribing: { text: 'Writing transcript...', className: 'bg-blue-50 text-blue-700 ring-blue-200' },
}

// Backup way: upload a transcript file (.txt / .vtt / .srt) when the API has none.
function UploadForm({ onUploaded, onCancel }) {
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState('')

  async function readFile(file) {
    if (!file) return
    setText(await file.text())
    if (!title) setTitle(file.name.replace(/\.[^.]+$/, ''))
  }

  async function submit() {
    try {
      const meeting = await api('/meetings/upload', { method: 'POST', body: { title, text } })
      onUploaded(meeting.id)
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="space-y-2 border-b border-slate-200 bg-white px-6 py-4">
      <p className="text-sm text-slate-600">
        Only for meetings without a Google Meet transcript (for example Zoom or Teams for now).
      </p>
      <div className="flex gap-2">
        <input
          dir="auto"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Meeting title"
          className="w-72 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
        />
        <input type="file" accept=".txt,.vtt,.srt" onChange={(e) => readFile(e.target.files[0])} className="text-sm" />
      </div>
      <textarea
        dir="auto"
        rows={5}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="...or paste the transcript here"
        className="w-full rounded-md border border-slate-300 p-2 text-sm"
      />
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex gap-2">
        <button
          onClick={submit}
          disabled={!text.trim()}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Add meeting
        </button>
        <button onClick={onCancel} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          Cancel
        </button>
      </div>
    </div>
  )
}

export default function Meetings() {
  const [tab, setTab] = useState('recent') // "recent" or "past" (past summaries)
  const [query, setQuery] = useState('')
  const [meetings, setMeetings] = useState([])
  const [params] = useSearchParams()
  const [selectedId, setSelectedId] = useState(() => Number(params.get('open')) || null)
  const [showUpload, setShowUpload] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const load = useCallback(() => {
    const params = new URLSearchParams({ q: query, summarized: tab === 'past' })
    api(`/meetings?${params}`)
      .then(setMeetings)
      .catch((e) => setMessage(e.message))
  }, [query, tab])

  useEffect(() => {
    const timer = setTimeout(load, 300)
    return () => clearTimeout(timer)
  }, [load])

  // While a meeting is being recorded or transcribed, check again every 5 seconds,
  // so "Writing transcript..." changes to the summary without reloading the page.
  const working = meetings.some((m) => ['recording', 'transcribing'].includes(m.transcript_status))
  useEffect(() => {
    if (!working) return undefined
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [working, load])

  // The open meeting is loaded again when its status or summary changes.
  const selected = meetings.find((m) => m.id === selectedId)
  const detailKey = `${selectedId}-${selected?.transcript_status}-${selected?.has_summary}`

  async function refresh() {
    setBusy(true)
    setMessage('')
    try {
      const r = await api('/meetings/refresh', { method: 'POST' })
      setMessage(
        `${r.found} meetings found: ${r.ready} with transcript, ${r.waiting} waiting, ${r.no_transcript} without.`,
      )
      load()
    } catch (e) {
      setMessage(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="-m-8 flex h-screen flex-col">
      <header className="flex flex-wrap items-center gap-4 border-b border-slate-200 bg-white px-6 py-4">
        <h2 className="text-xl font-semibold">Meetings</h2>
        <div className="flex rounded-md border border-slate-300 text-sm">
          {[
            ['recent', 'Recent meetings'],
            ['past', 'Past summaries'],
          ].map(([value, label]) => (
            <button
              key={value}
              onClick={() => setTab(value)}
              className={`px-3 py-1.5 ${tab === value ? 'bg-blue-50 font-medium text-blue-700' : 'hover:bg-slate-50'}`}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          dir="auto"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search title, keywords, text..."
          className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        />
        <div className="ms-auto flex items-center gap-3">
          {message && <span className="text-sm text-slate-600">{message}</span>}
          <button
            onClick={() => setShowUpload((v) => !v)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Upload transcript
          </button>
          <button
            onClick={refresh}
            disabled={busy}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
          >
            {busy ? 'Checking...' : 'Refresh'}
          </button>
        </div>
      </header>

      <RecorderBar onChanged={load} />

      {showUpload && (
        <UploadForm
          onCancel={() => setShowUpload(false)}
          onUploaded={(id) => {
            setShowUpload(false)
            setSelectedId(id)
            load()
          }}
        />
      )}

      <div className="flex min-h-0 flex-1">
        <ul
          className={`${selectedId ? 'hidden lg:block' : 'block'} w-full shrink-0 overflow-y-auto border-r border-slate-200 bg-white lg:w-96`}
        >
          {meetings.length === 0 && (
            <li className="p-6 text-sm text-slate-500">
              {tab === 'past' ? 'No summaries yet.' : 'No meetings yet. Click Refresh to check your calendar.'}
            </li>
          )}
          {meetings.map((m) => (
            <li
              key={m.id}
              onClick={() => setSelectedId(m.id)}
              className={`cursor-pointer border-b border-slate-100 px-4 py-3 ${
                selectedId === m.id ? 'bg-blue-50' : 'hover:bg-slate-50'
              }`}
            >
              <p dir="auto" className="truncate text-sm font-medium">{m.title}</p>
              <p className="mb-1 text-xs text-slate-500">
                {new Date(m.date).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                {m.attendees.length > 0 && ` · ${m.attendees.length} people`}
              </p>
              {m.overview && <p dir="auto" className="mb-1 line-clamp-2 text-xs text-slate-600">{m.overview}</p>}
              <div className="flex gap-1">
                {m.has_summary ? (
                  <Badge className="bg-blue-50 text-blue-700 ring-blue-200">Summarized</Badge>
                ) : (
                  <Badge className={(STATUS[m.transcript_status] ?? STATUS.none).className}>
                    {(STATUS[m.transcript_status] ?? STATUS.none).text}
                  </Badge>
                )}
              </div>
            </li>
          ))}
        </ul>
        <section className={`${selectedId ? 'flex' : 'hidden lg:flex'} min-w-0 flex-1 flex-col bg-slate-50`}>
          {selectedId && (
            <button
              onClick={() => setSelectedId(null)}
              className="border-b border-slate-200 bg-white px-6 py-2 text-left text-sm text-blue-700 hover:bg-slate-50 lg:hidden"
            >
              ← Back to list
            </button>
          )}
          {selectedId ? (
            <MeetingDetail key={detailKey} meetingId={selectedId} onChanged={load} />
          ) : (
            <p className="p-6 text-sm text-slate-500">Select a meeting to see or make its summary.</p>
          )}
        </section>
      </div>
    </div>
  )
}
