import { AlertTriangle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { EmailBadges } from './Badges.jsx'
import { useConfirm } from './ConfirmDialog.jsx'
import Highlight from './Highlight.jsx'

const button = 'rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50'
const secondary = `${button} border border-slate-300 bg-surface hover:bg-slate-50`

// The right side of the High / Low pages: the email, the reason, and the reply box.
export default function EmailDetail({ emailId, onChanged }) {
  const [email, setEmail] = useState(null)
  const [reply, setReply] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState('')
  const [moving, setMoving] = useState(false) // shows "only this email / always for this sender"
  const [message, setMessage] = useState({ text: '', error: false })
  const [confirmDialog, confirm] = useConfirm()

  useEffect(() => {
    api(`/emails/${emailId}`)
      .then((e) => {
        setEmail(e)
        setReply(e.draft_reply)
      })
      .catch((e) => setMessage({ text: e.message, error: true }))
  }, [emailId])

  async function run(name, request, successText) {
    setBusy(name)
    setMessage({ text: '', error: false })
    try {
      const result = await request()
      if (result?.id) {
        setEmail(result)
        setReply(result.draft_reply)
      }
      setMessage({ text: successText, error: false })
      onChanged?.()
    } catch (e) {
      setMessage({ text: e.message, error: true })
    } finally {
      setBusy('')
    }
  }

  if (!email) {
    return <div className="p-6 text-sm text-slate-500">{message.text || 'Loading...'}</div>
  }

  const edited = reply !== email.draft_reply
  const closed = ['Sent', 'Skipped', 'Archived'].includes(email.reply_status)
  const other = email.priority === 'High' ? 'Low' : 'High'

  function move(remember) {
    setMoving(false)
    run(
      'move',
      () => api(`/emails/${email.id}/priority`, { method: 'POST', body: { priority: other, remember } }),
      remember ? `Moved to ${other}. New emails from ${email.sender} go to ${other} too.` : `Moved to ${other}.`,
    )
  }

  async function send() {
    const ok = await confirm(`Send this reply to ${email.sender}? It is sent from your Gmail.`, {
      confirmLabel: 'Send',
    })
    if (!ok) return
    run('send', () => api(`/emails/${email.id}/send`, { method: 'POST', body: { reply } }), 'Reply sent.')
  }

  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-6">
      {confirmDialog}
      <div>
        <h3 dir="auto" className="text-lg font-semibold">{email.subject || '(no subject)'}</h3>
        <p className="text-sm text-slate-600">
          {email.sender_name} &lt;{email.sender}&gt; · {new Date(email.received_at).toLocaleString()}
        </p>
        <div className="mt-2">
          <EmailBadges email={email} />
        </div>
      </div>

      {email.warning && (
        <p role="alert" className="flex gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span>
            <span className="font-medium">Check the sender: </span>
            {email.warning}
          </span>
        </p>
      )}

      {email.reason && (
        <p className="rounded-md bg-brand-50 px-3 py-2 text-sm text-brand-900">
          <span className="font-medium">Why {email.priority}: </span>
          {email.reason}
        </p>
      )}

      {email.meeting_links.map((link) => (
        <div key={link.id} className="flex flex-wrap items-center gap-2 rounded-md bg-indigo-50 px-3 py-2 text-sm text-indigo-900">
          <span>
            <span className="font-medium">Connected to meeting: </span>
            <Link to={`/meetings?open=${link.meeting_id}`} className="underline">
              {link.label}
            </Link>
            <span className="text-indigo-700">
              {' '}· matched: {link.matched_keywords.join(', ')}
              {link.confirmed_by_llm && ' (checked by the LLM)'}
            </span>
          </span>
          <button
            onClick={() =>
              run('unlink', () => api(`/emails/${email.id}/links/${link.id}`, { method: 'DELETE' }), 'Link removed.')
            }
            disabled={!!busy}
            className="ms-auto rounded border border-indigo-200 bg-surface px-2 py-0.5 text-xs hover:bg-indigo-100"
          >
            Not related
          </button>
        </div>
      ))}

      <div dir="auto" className="max-h-[50vh] min-h-24 overflow-y-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-surface p-4 text-sm leading-relaxed">
        {email.body ? (
          <Highlight text={email.body} words={email.meeting_links.flatMap((l) => l.matched_keywords)} />
        ) : (
          '(empty email)'
        )}
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">
          Reply {email.reply_status === 'No reply needed' && !reply && '(the agent thinks no reply is needed)'}
          {!closed && (
            <span className="ms-2 text-xs font-normal text-slate-500">
              Type in the box to change it, then Save edit or Send.
            </span>
          )}
        </label>
        <textarea
          dir="auto"
          rows={8}
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          disabled={closed}
          className="w-full rounded-md border border-slate-300 p-2 text-sm disabled:bg-slate-50"
          placeholder="Write a reply, or click Regenerate."
        />
      </div>

      {!closed && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={send}
            disabled={!!busy || !reply.trim()}
            className={`${button} bg-brand-600 text-white hover:bg-brand-700`}
          >
            {busy === 'send' ? 'Sending...' : 'Send'}
          </button>
          <button
            onClick={() =>
              run('save', () => api(`/emails/${email.id}/draft`, { method: 'PUT', body: { draft_reply: reply } }), 'Draft saved.')
            }
            disabled={!!busy || !edited}
            className={secondary}
          >
            Save edit
          </button>
          <input
            dir="auto"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder='Note, e.g. "shorter" or "in Arabic"'
            className="w-56 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <button
            onClick={() =>
              run('regen', () => api(`/emails/${email.id}/regenerate`, { method: 'POST', body: { note } }), 'New draft ready.')
            }
            disabled={!!busy}
            className={secondary}
          >
            {busy === 'regen' ? 'Writing...' : 'Regenerate'}
          </button>
        </div>
      )}

      {moving && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
          <span className="font-medium">Move to {other}:</span>
          <button onClick={() => move(false)} disabled={!!busy} className={secondary}>
            Only this email
          </button>
          <button onClick={() => move(true)} disabled={!!busy} className={secondary}>
            Always for {email.sender}
          </button>
          <button onClick={() => setMoving(false)} className="px-2 py-1.5 text-slate-600 hover:underline">
            Cancel
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-2 border-t border-slate-200 pt-4">
        <button onClick={() => setMoving(true)} disabled={!!busy || moving} className={secondary}>
          Move to {other}
        </button>
        <button
          onClick={() => run('task', () => api(`/emails/${email.id}/task`, { method: 'POST' }), 'Added to Daily Tasks.')}
          disabled={!!busy}
          className={secondary}
        >
          Add to tasks
        </button>
        {!closed && (
          <button
            onClick={() => run('skip', () => api(`/emails/${email.id}/skip`, { method: 'POST' }), 'Skipped.')}
            disabled={!!busy}
            className={secondary}
          >
            Skip
          </button>
        )}
      </div>

      {message.text && (
        <p className={`text-sm ${message.error ? 'text-red-600' : 'text-emerald-700'}`}>{message.text}</p>
      )}
    </div>
  )
}
