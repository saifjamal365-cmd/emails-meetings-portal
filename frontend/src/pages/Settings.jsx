import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useConfirm } from '../components/ConfirmDialog.jsx'

const toText = (list) => list.join('\n')
const toList = (text) => text.split(/[\n,]/).map((d) => d.trim()).filter(Boolean)

export default function Settings({ loginRequired }) {
  const [params, setParams] = useSearchParams()
  const [google, setGoogle] = useState(null)
  const [high, setHigh] = useState('')
  const [low, setLow] = useState('')
  const [autoSummarize, setAutoSummarize] = useState(false)
  const [autoRecord, setAutoRecord] = useState(false)
  const [meetingWords, setMeetingWords] = useState('')
  const [rememberVoices, setRememberVoices] = useState(false)
  const [voices, setVoices] = useState([])
  const [meetHelper, setMeetHelper] = useState(null)
  const [confirmText, setConfirmText] = useState('')
  const [confirmDialog, confirm] = useConfirm()
  // Message after coming back from the Google login page.
  const [message, setMessage] = useState(() => {
    const connected = params.get('google_connected')
    const error = params.get('google_error')
    if (connected) return { text: `Google connected: ${connected}`, error: false }
    if (error) return { text: `Google login failed: ${error}`, error: true }
    return { text: '', error: false }
  })

  useEffect(() => {
    if (params.size) setParams({}, { replace: true })
  }, [params, setParams])

  function loadGoogle() {
    api('/auth/google/status').then(setGoogle).catch(() => setGoogle(null))
  }

  function loadVoices() {
    api('/voices').then(setVoices).catch(() => setVoices([]))
  }

  // The Meet helper connects by itself a moment after a portal page loads: check again
  // every few seconds until it is connected.
  useEffect(() => {
    const check = () => api('/extension/status').then(setMeetHelper).catch(() => setMeetHelper(null))
    check()
    const timer = setInterval(check, 5000)
    return () => clearInterval(timer)
  }, [])
  const meetHelperActive = meetHelper?.active

  useEffect(() => {
    loadGoogle()
    loadVoices()
    api('/settings').then((s) => {
      setHigh(toText(s.high_domains))
      setLow(toText(s.low_domains))
      setAutoSummarize(s.auto_summarize)
      setAutoRecord(s.auto_record)
      setMeetingWords(toText(s.meeting_words))
      setRememberVoices(s.remember_voices)
    })
  }, [])

  async function save(changes = {}, successText = 'Settings saved.') {
    try {
      const body = {
        high_domains: toList(high),
        low_domains: toList(low),
        auto_summarize: autoSummarize,
        auto_record: autoRecord,
        meeting_words: toList(meetingWords),
        remember_voices: rememberVoices,
        ...changes,
      }
      const s = await api('/settings', { method: 'PUT', body })
      setHigh(toText(s.high_domains))
      setLow(toText(s.low_domains))
      setAutoSummarize(s.auto_summarize)
      setAutoRecord(s.auto_record)
      setMeetingWords(toText(s.meeting_words))
      setRememberVoices(s.remember_voices)
      setMessage({ text: successText, error: false })
    } catch (e) {
      setMessage({ text: e.message, error: true })
    }
  }

  async function forgetVoice(voice) {
    if (!(await confirm(`Forget the voice of ${voice.name}?`, { confirmLabel: 'Forget', danger: true }))) return
    await api(`/voices/${voice.id}`, { method: 'DELETE' })
    loadVoices()
  }

  async function forgetAllVoices() {
    const ok = await confirm('Delete every remembered voice and every saved voice print?', {
      confirmLabel: 'Delete all voices',
      danger: true,
    })
    if (!ok) return
    await api('/voices', { method: 'DELETE' })
    loadVoices()
    setMessage({ text: 'All voice prints were deleted.', error: false })
  }

  async function deleteData() {
    const ok = await confirm(
      'Delete all saved emails, meetings, tasks and plans from the portal? This cannot be undone.',
      { confirmLabel: 'Delete my data', danger: true },
    )
    if (!ok) return
    try {
      const r = await api('/data', { method: 'DELETE', body: { confirm: confirmText } })
      const total = Object.values(r.deleted).reduce((a, b) => a + b, 0)
      setConfirmText('')
      setMessage({ text: `Deleted ${total} saved items. Settings and the Google connection are kept.`, error: false })
    } catch (e) {
      setMessage({ text: e.message, error: true })
    }
  }

  async function disconnect() {
    if (!(await confirm('Disconnect Google (Gmail, Calendar, Meet) from the portal?', { confirmLabel: 'Disconnect' })))
      return
    await api('/auth/google/disconnect', { method: 'POST' })
    loadGoogle()
  }

  return (
    <div className="max-w-2xl space-y-6">
      {confirmDialog}
      <h2 className="text-2xl font-semibold">Settings</h2>

      {message.text && (
        <p className={`rounded-md px-3 py-2 text-sm ${message.error ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-800'}`}>
          {message.text}
        </p>
      )}

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-1 font-medium">Google account</h3>
        <p className="mb-3 text-sm text-slate-600">One login for Gmail (emails), Calendar and Meet (meeting transcripts).</p>
        {!google && <p className="text-sm text-slate-500">Checking...</p>}
        {google && !google.configured && (
          <p className="text-sm text-slate-600">
            Google is not set up yet. Add <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code> to{' '}
            <code>backend/.env</code> and restart the backend (see README, "Connect Google").
          </p>
        )}
        {google?.configured && !google.connected && (
          <div className="flex items-center gap-3">
            <p className="text-sm text-slate-600">Not connected.</p>
            {/* Full page navigation: the backend redirects to Google, then back here. */}
            <a
              href="/api/auth/google/start"
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
            >
              Connect Google
            </a>
          </div>
        )}
        {google?.connected && (
          <div className="flex items-center gap-3">
            <p className="text-sm text-slate-700">
              Connected as <span className="font-medium">{google.account}</span>
            </p>
            <button onClick={disconnect} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
              Disconnect
            </button>
          </div>
        )}
        {google?.connected && google.missing_scopes.length > 0 && (
          <div className="mt-3 flex items-center gap-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
            <p>New features need more permissions (Calendar / Meet). Connect again to allow them.</p>
            <a href="/api/auth/google/start" className="shrink-0 rounded-md bg-amber-600 px-3 py-1.5 font-medium text-white hover:bg-amber-700">
              Reconnect
            </a>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-1 font-medium">Meetings</h3>
        <label className="mb-4 flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={autoRecord}
            onChange={(e) => save({ auto_record: e.target.checked }, e.target.checked ? 'Auto-record is on.' : 'Auto-record is off.')}
          />
          <span>
            <span className="font-medium">Auto-record my online meetings (free, on this computer)</span>
            <span className="block text-slate-600">
              When a meeting with a Meet, Zoom or Teams link in your calendar starts, the portal records your microphone
              (you) and your speakers (the others). When it ends, Whisper writes the transcript on this computer and the
              agent summarizes it and adds your tasks. The audio is deleted afterwards. The backend must be running.
            </span>
            <span className="mt-1 block rounded-md bg-amber-50 p-2 text-amber-900">
              Always tell the other people that the meeting is recorded - in many countries recording without telling
              them is not allowed. Use headphones for the best transcript.
            </span>
          </span>
        </label>
        <div className="mb-4 text-sm">
          <span className="font-medium">Meeting words</span>
          <span className="block text-slate-600">
            Names and words that come up in your meetings: people, clients, projects, short words like HR. One per
            line. They help the transcript and the summary get them right.
          </span>
          <textarea
            dir="auto"
            rows={5}
            value={meetingWords}
            onChange={(e) => setMeetingWords(e.target.value)}
            placeholder={'Al-Noor\nشركة النور\nProject Falcon\nAhmad\nHR\nميزانية'}
            className="mt-2 w-full rounded-md border border-slate-300 p-2 font-mono text-sm"
          />
          <button
            onClick={() => save({}, 'Meeting words saved.')}
            className="mt-2 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            Save meeting words
          </button>
        </div>
        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={autoSummarize}
            onChange={(e) => save({ auto_summarize: e.target.checked }, e.target.checked ? 'Auto-summarize is on.' : 'Auto-summarize is off.')}
          />
          <span>
            <span className="font-medium">Auto-summarize my meetings</span>
            <span className="block text-slate-600">
              Every 10 minutes the agent checks your calendar. When a Meet transcript is ready, it is summarized and
              your tasks are created. You click nothing.
            </span>
          </span>
        </label>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-1 font-medium">Google Meet helper (browser extension)</h3>
        <p className="mb-2 text-sm text-slate-600">
          In Google Meet calls it records from the moment you join until you leave, turns on the captions by itself,
          and gives every voice its Google Meet name. It talks only to this portal, on this computer.
        </p>
        {meetHelperActive ? (
          <p className="rounded-md bg-emerald-50 p-2 text-sm text-emerald-800">
            Connected. Last message: {new Date(meetHelper.last_seen).toLocaleString()}.
          </p>
        ) : (
          <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
            <p className="mb-1 font-medium">Not connected yet. Install it once (Chrome or Edge):</p>
            <ol className="list-decimal space-y-0.5 ps-5">
              <li>
                Open <code>chrome://extensions</code> (or <code>edge://extensions</code>) and turn on{' '}
                <b>Developer mode</b>.
              </li>
              <li>
                Click <b>Load unpacked</b> and choose the folder <code>week8\email-meeting-portal\extension</code>.
              </li>
              <li>
                In that same browser, <b>reload this portal page (F5)</b> and log in: it connects by itself in a few
                seconds, nothing to type.
              </li>
            </ol>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-1 font-medium">Voice memory</h3>
        <label className="mb-3 flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={rememberVoices}
            onChange={(e) =>
              save({ remember_voices: e.target.checked }, e.target.checked ? 'Voice memory is on.' : 'Voice memory is off.')
            }
          />
          <span>
            <span className="font-medium">Remember the voices of people in my meetings</span>
            <span className="block text-slate-600">
              The portal learns a voice when a person says their own name, or when you name a voice once on a meeting
              page. In the next meetings it knows them by their voice, even if nobody says their name. Voice prints stay
              on this computer, encrypted.
            </span>
            <span className="mt-1 block rounded-md bg-amber-50 p-2 text-amber-900">
              A voice print is biometric personal data. Turn this on only after the people in your meetings agreed.
            </span>
          </span>
        </label>
        {voices.length === 0 ? (
          <p className="text-sm text-slate-500">No voices remembered yet.</p>
        ) : (
          <>
            <ul className="mb-2 divide-y divide-slate-100 text-sm">
              {voices.map((v) => (
                <li key={v.id} className="flex items-center gap-3 py-1.5">
                  <span dir="auto" className="font-medium">{v.name}</span>
                  <span className="text-slate-500">
                    learned from {v.meetings} meeting{v.meetings === 1 ? '' : 's'}
                  </span>
                  <button
                    type="button"
                    onClick={() => forgetVoice(v)}
                    className="ms-auto rounded-md border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
                  >
                    Forget
                  </button>
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={forgetAllVoices}
              className="rounded-md border border-red-200 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50"
            >
              Delete all voices
            </button>
          </>
        )}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-1 font-medium">Sender rules</h3>
        <p className="mb-3 text-sm text-slate-600">
          One domain per line. Rules are checked before the LLM. Leave High empty to let the agent decide
          (companies, clients and products become High).
        </p>
        <div className="grid grid-cols-2 gap-4">
          <label className="text-sm">
            <span className="mb-1 block font-medium">Always High</span>
            <textarea
              rows={8}
              value={high}
              onChange={(e) => setHigh(e.target.value)}
              placeholder="acme.com"
              className="w-full rounded-md border border-slate-300 p-2 font-mono text-sm"
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Always Low</span>
            <textarea
              rows={8}
              value={low}
              onChange={(e) => setLow(e.target.value)}
              className="w-full rounded-md border border-slate-300 p-2 font-mono text-sm"
            />
          </label>
        </div>
        <button onClick={() => save({}, 'Sender rules saved.')} className="mt-3 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
          Save rules
        </button>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-1 font-medium">Portal login</h3>
        {loginRequired ? (
          <p className="text-sm text-slate-600">
            The portal is protected with a password. Change it with <code>PORTAL_PASSWORD</code> in{' '}
            <code>backend/.env</code> and restart the backend.
          </p>
        ) : (
          <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
            No password is set, so anyone who can open this address can use the portal. Add{' '}
            <code>PORTAL_PASSWORD=...</code> to <code>backend/.env</code> and restart the backend. (It is required
            in production.)
          </p>
        )}
      </section>

      <section className="rounded-lg border border-red-200 bg-white p-4">
        <h3 className="mb-1 font-medium text-red-800">Delete my data</h3>
        <p className="mb-3 text-sm text-slate-600">
          Deletes the portal's copies of your emails, meetings, transcripts, summaries, tasks, plans, notifications,
          logs and remembered voices. Your emails stay in Gmail. Settings and the Google connection are kept.
        </p>
        <div className="flex items-center gap-2">
          <input
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="Type DELETE"
            className="w-40 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <button
            onClick={deleteData}
            disabled={confirmText !== 'DELETE'}
            className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            Delete my data
          </button>
        </div>
      </section>
    </div>
  )
}
