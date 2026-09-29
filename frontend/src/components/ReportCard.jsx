import { useState } from 'react'
import { api } from '../api.js'
import { useConfirm } from './ConfirmDialog.jsx'

const TITLES = {
  morning: { title: 'Start of day', subtitle: 'What to do today', button: 'Make morning plan' },
  evening: { title: 'End of day', subtitle: 'Day summary', button: 'Make day summary' },
}

// Shows the planner's simple format: "## " headings, "- " bullets, "1. " numbered items.
function ReportText({ text }) {
  return (
    <div dir="auto" className="space-y-1 text-sm">
      {text.split('\n').map((line, i) => {
        if (line.startsWith('## ')) {
          return (
            <h5 key={i} className="pt-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {line.slice(3)}
            </h5>
          )
        }
        if (!line.trim()) return null
        const item = line.match(/^(\s*)(- |\d+\. )(.*)$/)
        if (item) {
          return (
            <p key={i} className={item[1] ? 'ps-8 text-slate-600' : 'ps-3'}>
              <span className="text-slate-400">{item[2].trim() === '-' ? '•' : item[2]}</span> {item[3]}
            </p>
          )
        }
        return <p key={i}>{line}</p>
      })}
    </div>
  )
}

// One daily report (morning plan or day summary): make it, read it, edit it.
export default function ReportCard({ kind, day, report, isToday, onChanged }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState({ text: '', error: false })
  const t = TITLES[kind]
  const [confirmDialog, confirm] = useConfirm()

  async function generate() {
    if (report?.edited_by_user) {
      const ok = await confirm('Make a new one? Your edits to this text will be replaced.', { confirmLabel: 'Make again' })
      if (!ok) return
    }
    setBusy(true)
    setMessage({ text: '', error: false })
    try {
      const r = await api(`/reports/${kind}/generate?day=${day}`, { method: 'POST' })
      setMessage(r.warning ? { text: r.warning, error: true } : { text: '', error: false })
      onChanged()
    } catch (e) {
      setMessage({ text: e.message, error: true })
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    try {
      await api(`/reports/${report.id}`, { method: 'PUT', body: { content: text } })
      setEditing(false)
      onChanged()
    } catch (e) {
      setMessage({ text: e.message, error: true })
    }
  }

  return (
    <section className="flex flex-col rounded-lg border border-slate-200 bg-white p-4">
      {confirmDialog}
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold">{t.title}</h3>
          <p className="text-xs text-slate-500">
            {t.subtitle}
            {report && ` · made ${new Date(report.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`}
            {report?.made_by === 'basic' && ' · basic (no LLM)'}
            {report?.edited_by_user && ' · edited by you'}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          {report && !editing && (
            <button
              onClick={() => {
                setText(report.content)
                setEditing(true)
              }}
              className="rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50"
            >
              Edit
            </button>
          )}
          {isToday && !editing && (
            <button
              onClick={generate}
              disabled={busy}
              className="rounded-md bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {busy ? 'Making...' : report ? 'Make again' : t.button}
            </button>
          )}
        </div>
      </div>

      {message.text && <p className={`mb-2 text-xs ${message.error ? 'text-amber-700' : 'text-slate-600'}`}>{message.text}</p>}

      {editing ? (
        <>
          <textarea
            dir="auto"
            rows={12}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="w-full rounded-md border border-slate-300 p-2 font-mono text-xs"
          />
          <div className="mt-2 flex gap-2">
            <button onClick={save} className="rounded-md bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700">
              Save
            </button>
            <button onClick={() => setEditing(false)} className="rounded-md border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </>
      ) : report ? (
        <div className="max-h-80 overflow-y-auto">
          <ReportText text={report.content} />
        </div>
      ) : (
        <p className="text-sm text-slate-500">
          {isToday
            ? `Not made yet. It is made automatically at ${kind === 'morning' ? '8:00' : '18:00'}, or click the button.`
            : 'Nothing was made on this day.'}
        </p>
      )}
    </section>
  )
}
