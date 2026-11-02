import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Badge } from './Badges.jsx'

const LANGUAGES = [
  { value: 'same', label: 'Same as meeting' },
  { value: 'ar', label: 'Arabic' },
  { value: 'en', label: 'English' },
]

const LOG_TEXT = {
  transcript_downloaded: (d) => `Transcript downloaded from Google Meet (${d.lines} lines)`,
  transcript_uploaded: (d) => `Transcript uploaded (${d.lines} lines)`,
  recording_started: () => 'Recording started on this computer',
  joined_call: () => 'You joined the Google Meet call (Meet helper) - recording started',
  left_call: () => 'You left the Google Meet call (Meet helper) - recording stopped',
  voices_named_by_meet: (d) =>
    `Named from Google Meet's captions: ${Object.entries(d.voices).map(([label, name]) => `${label} = ${name}`).join(', ')}`,
  recording_recovered: () => 'Recording finished after a restart',
  transcript_recorded: (d) => `Transcript written by the recorder (${d.lines} lines, ${d.minutes} min)`,
  echo_removed: (d) => `${d.lines} line${d.lines === 1 ? '' : 's'} on your microphone were the others' voices (echo) and were removed`,
  voices_recognized: (d) =>
    `Voice memory recognized: ${Object.entries(d.voices).map(([label, name]) => `${label} = ${name}`).join(', ')}`,
  voices_learned: (d) => `Voice memory learned: ${d.names.join(', ')}`,
  voice_named: (d) => `You named ${d.label}: ${d.name}${d.remembered ? ' (remembered)' : ''}`,
  not_mine_blocked: (d) => `Not added to your tasks (another person's task): ${d.titles.join('; ')}`,
  summarized: (d) => `Summarized by ${d.model} (${d.input_tokens} in / ${d.output_tokens} out tokens)`,
  tasks_created: (d) => `${d.count} task${d.count === 1 ? '' : 's'} created: ${d.titles.join('; ')}`,
  emails_linked: (d) => `${d.email_ids.length} unread email${d.email_ids.length === 1 ? '' : 's'} linked to this meeting`,
}

function Section({ title, children }) {
  return (
    <section>
      <h4 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
      {children}
    </section>
  )
}

const HOW = {
  meet: { text: 'Google Meet', className: 'bg-teal-50 text-teal-700 ring-teal-200' },
  voice: { text: 'voice memory', className: 'bg-violet-50 text-violet-700 ring-violet-200' },
  talk: { text: 'from the talk', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
  you: { text: 'named by you', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
}

// One voice in "Who spoke": its name, how it was found, and "Name" to set it once.
function VoiceRow({ voice, suggestions, canRemember, onSave }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(voice.name || '')
  const how = HOW[voice.how]
  const listId = `names-${voice.label.replace(/\s/g, '')}`

  async function submit(e) {
    e.preventDefault()
    if (!name.trim()) return
    await onSave(name.trim())
    setEditing(false)
  }

  return (
    <li dir="auto">
      <span className="font-medium">{voice.label}</span> → {voice.name || <span className="text-slate-500">not known</span>}{' '}
      {how && voice.name && <Badge className={how.className}>{how.text}</Badge>}
      {voice.clue && voice.how !== 'you' && <span className="text-slate-500"> · {voice.clue}</span>}
      {!editing && (
        <button type="button" onClick={() => setEditing(true)} className="ms-2 text-xs text-brand-700 underline">
          {voice.name ? 'Change' : 'Name'}
        </button>
      )}
      {editing && (
        <form onSubmit={submit} className="mt-1 flex flex-wrap items-center gap-2">
          <input
            dir="auto"
            autoFocus
            list={listId}
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
            placeholder="Who is this?"
            className="w-48 rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
          <datalist id={listId}>
            {suggestions.map((n) => (
              <option key={n} value={n} />
            ))}
          </datalist>
          <button type="submit" className="rounded-md bg-brand-600 px-3 py-1 text-sm font-medium text-white hover:bg-brand-700">
            Save
          </button>
          <button type="button" onClick={() => setEditing(false)} className="text-sm text-slate-600 underline">
            Cancel
          </button>
          <span className="w-full text-xs text-slate-500">
            {canRemember
              ? 'The voice memory keeps this voice, so it is named by itself next time.'
              : 'Only for this meeting (the voice memory was off when it was recorded).'}
          </span>
        </form>
      )}
    </li>
  )
}

// "[10:01] Speaker 1: ..." -> "[10:01] Speaker 1 (Omar): ..." when the agent found the name.
function withNames(transcript, speakers = []) {
  const names = Object.fromEntries((speakers || []).filter((sp) => sp.name).map((sp) => [sp.label, sp.name]))
  return transcript.replace(/^(\[[^\]]*\] )(Speaker \d+):/gm, (line, time, label) =>
    names[label] ? `${time}${label} (${names[label]}):` : line,
  )
}

function List({ items, empty = 'None.' }) {
  if (!items.length) return <p className="text-sm text-slate-500">{empty}</p>
  return (
    <ul className="list-disc space-y-1 ps-5 text-sm" dir="auto">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  )
}

// Right side of the Meetings page: owner/attendees, the summary, tasks, logs and the transcript.
export default function MeetingDetail({ meetingId, onChanged }) {
  const [meeting, setMeeting] = useState(null)
  const [language, setLanguage] = useState('same')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api(`/meetings/${meetingId}`)
      .then(setMeeting)
      .catch((e) => setError(e.message))
  }, [meetingId])

  async function summarize() {
    setBusy(true)
    setError('')
    try {
      setMeeting(await api(`/meetings/${meetingId}/summarize`, { method: 'POST', body: { output_language: language } }))
      onChanged?.()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (!meeting) return <div className="p-6 text-sm text-slate-500">{error || 'Loading...'}</div>

  const s = meeting.summary
  const ready = meeting.transcript_status === 'ready'
  // Every separated voice: the agent's list, plus voices with a print that it did not list.
  const listed = s?.speakers ?? []
  const voices = [
    ...listed,
    ...meeting.voice_labels.filter((l) => !listed.some((sp) => sp.label === l)).map((label) => ({ label, name: '' })),
  ]
  const suggestions = [...new Set([...meeting.participants, ...listed.map((sp) => sp.name).filter(Boolean)])]

  async function nameVoice(label, name) {
    setError('')
    try {
      setMeeting(await api(`/meetings/${meetingId}/voices`, { method: 'POST', body: { label, name } }))
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6">
      <div>
        <h3 dir="auto" className="text-lg font-semibold">{meeting.title}</h3>
        <p className="text-sm text-slate-600">
          {new Date(meeting.date).toLocaleString()} · {{ meet: 'Google Meet', recorded: 'Recorded on this computer' }[meeting.platform] ?? 'Uploaded transcript'}
        </p>
      </div>

      {/* Meeting-owner mapping */}
      <Section title="Owner and attendees">
        <p className="text-sm">
          <span className="font-medium">Owner: </span>
          {meeting.owner || 'Not known'}
        </p>
        {meeting.attendees.length > 0 && (
          <p className="text-sm text-slate-600">
            <span className="font-medium text-slate-900">Attendees: </span>
            {meeting.attendees.join(', ')}
          </p>
        )}
        {meeting.participants.length > 0 && (
          <p dir="auto" className="text-sm text-slate-600">
            <span className="font-medium text-slate-900">Joined the call: </span>
            {meeting.participants.join(', ')}
          </p>
        )}
      </Section>

      <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-200 bg-surface p-3">
        <label className="text-sm text-slate-600">Output language</label>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
        >
          {LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>{l.label}</option>
          ))}
        </select>
        <button
          onClick={summarize}
          disabled={busy || !ready}
          className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {busy ? 'Summarizing...' : s ? 'Summarize again' : 'Summarize'}
        </button>
        {!ready && (
          <span className="text-sm text-slate-500">
            {{
              waiting: 'Waiting for the transcript from Google Meet.',
              recording: 'Recording now. The summary is made automatically when it stops.',
              transcribing: 'Writing the transcript on this computer. The summary follows automatically.',
            }[meeting.transcript_status] ??
              (meeting.platform === 'recorded'
                ? 'No speech was found in the recording.'
                : 'No transcript for this meeting. Use Record now next time, or Upload transcript.')}
          </span>
        )}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {s && (
        <>
          <Section title="Overview">
            <p dir="auto" className="text-sm">{s.overview}</p>
          </Section>

          {s.key_facts?.length > 0 && (
            <Section title="Key facts">
              <List items={s.key_facts} />
            </Section>
          )}

          {voices.length > 0 && (
            <Section title="Who spoke">
              <p className="mb-1 text-xs text-slate-500">
                The other people&apos;s voices were separated on this computer. Names come from Google Meet&apos;s
                captions, the voice memory, what was said, and who joined the call.
              </p>
              <ul className="space-y-1 text-sm">
                {voices.map((sp) => (
                  <VoiceRow
                    key={sp.label}
                    voice={sp}
                    suggestions={suggestions}
                    canRemember={meeting.voice_labels.includes(sp.label)}
                    onSave={(name) => nameVoice(sp.label, name)}
                  />
                ))}
              </ul>
            </Section>
          )}

          <Section title="Action items">
            {s.action_items.length === 0 ? (
              <p className="text-sm text-slate-500">None.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="py-1 pe-3 font-medium">Task</th>
                    <th className="py-1 pe-3 font-medium">Owner</th>
                    <th className="py-1 font-medium">Due</th>
                  </tr>
                </thead>
                <tbody>
                  {s.action_items.map((item, i) => (
                    <tr key={i} className="border-b border-slate-100 align-top">
                      <td dir="auto" className="py-1.5 pe-3">{item.task}</td>
                      <td dir="auto" className="py-1.5 pe-3">
                        {item.owner} {item.owner_is_me && <Badge className="bg-brand-50 text-brand-700 ring-brand-200">me</Badge>}
                      </td>
                      <td className="py-1.5 whitespace-nowrap">{item.due || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
            <Section title="Decisions"><List items={s.decisions} /></Section>
            <Section title="Risks"><List items={s.risks} /></Section>
            <Section title="Blockers"><List items={s.blockers} /></Section>
          </div>

          <Section title="Keywords (used to link emails)">
            <div className="flex flex-wrap gap-1">
              {s.keywords.map((k) => (
                <Badge key={k}>{k}</Badge>
              ))}
            </div>
          </Section>
        </>
      )}

      <Section title="Emails linked to this meeting">
        {meeting.linked_emails.length === 0 ? (
          <p className="text-sm text-slate-500">None yet. Unread emails with these keywords will show here.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {meeting.linked_emails.map((e) => (
              <li key={e.email_id} className="flex flex-wrap items-center gap-2">
                {e.priority && (
                  <Badge className={e.priority === 'High' ? 'bg-red-50 text-red-700 ring-red-200' : undefined}>{e.priority}</Badge>
                )}
                <span className="font-medium">{e.sender}</span>
                <span dir="auto">{e.subject}</span>
                <span className="text-slate-500">· {e.matched_keywords.join(', ')}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Tasks created">
        <List items={meeting.tasks.map((t) => `${t.title}${t.due_date ? ` (due ${t.due_date})` : ''} - ${t.status}`)} />
      </Section>

      <Section title="Integration logs">
        {meeting.logs.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing yet.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {meeting.logs.map((log, i) => (
              <li key={i} className="text-slate-700">
                <span className="text-slate-500">{new Date(log.time).toLocaleString()} · </span>
                {(LOG_TEXT[log.action] || (() => log.action))(log.details)}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {meeting.transcript_text && (
        <details className="rounded-md border border-slate-200 bg-surface p-3">
          <summary className="cursor-pointer text-sm font-medium">Transcript</summary>
          <pre dir="auto" className="mt-2 max-h-96 overflow-y-auto whitespace-pre-wrap font-sans text-sm">
            {withNames(meeting.transcript_text, s?.speakers)}
          </pre>
        </details>
      )}
    </div>
  )
}
