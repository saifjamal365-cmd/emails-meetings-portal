import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { EmailBadges } from '../components/Badges.jsx'
import EmailDetail from '../components/EmailDetail.jsx'
import { formatTime } from '../format.js'
import PageHeader from '../components/PageHeader.jsx'
import SyncButton from '../components/SyncButton.jsx'

// The High Priority and Low Priority pages. Same layout; the Low page also has bulk actions.

// What each inbox holds, in plain words, with real examples.
const ABOUT = {
  High: {
    description:
      'Emails that need you: from clients, partners or your company, or about a recent meeting. Each one has a draft reply that you can edit and send.',
    examples: ['A client asks for a price offer', 'Your manager needs a report by Thursday', 'An email about a recent meeting'],
  },
  Low: {
    description:
      'Emails that can wait or need no answer. Nothing is sent from here unless you choose to. Move an email to High if it needs you.',
    examples: ['Newsletters', 'LinkedIn and Facebook notifications', 'Promotions and offers', 'No-reply messages'],
  },
}
export default function Inbox({ priority }) {
  const view = priority.toLowerCase()
  const [emails, setEmails] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [showDone, setShowDone] = useState(false)
  const [checked, setChecked] = useState([])
  const [error, setError] = useState('')

  const load = useCallback(() => {
    api(`/emails?view=${view}&show_done=${showDone}`)
      .then((list) => {
        setEmails(list)
        setError('')
      })
      .catch((e) => setError(e.message))
  }, [view, showDone])

  useEffect(() => {
    load()
  }, [load])

  function changeShowDone(value) {
    setShowDone(value)
    setSelectedId(null)
    setChecked([])
  }

  async function bulk(action) {
    try {
      await api('/emails/bulk', { method: 'POST', body: { ids: checked, action } })
      setChecked([])
      load()
    } catch (e) {
      setError(e.message)
    }
  }

  function toggle(id) {
    setChecked((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]))
  }

  return (
    <div className="-m-8 flex h-screen flex-col">
      <PageHeader
        bar
        title={`${priority} Priority`}
        meta={`${emails.length} email${emails.length === 1 ? '' : 's'} · ${priority === 'High' ? 'deadlines first' : 'newest first'}`}
        {...ABOUT[priority]}
      >
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={showDone} onChange={(e) => changeShowDone(e.target.checked)} />
          Show done
        </label>
        <SyncButton onDone={load} />
      </PageHeader>

      {priority === 'Low' && emails.length > 0 && (
        <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-6 py-2 text-sm">
          <button
            onClick={() => setChecked(checked.length === emails.length ? [] : emails.map((e) => e.id))}
            className="text-brand-700 hover:underline"
          >
            {checked.length === emails.length ? 'Select none' : 'Select all'}
          </button>
          <span className="text-slate-500">{checked.length} selected</span>
          <button
            onClick={() => bulk('mark_read')}
            disabled={!checked.length}
            className="rounded border border-slate-300 bg-surface px-2 py-1 disabled:opacity-50"
          >
            Mark as read
          </button>
          <button
            onClick={() => bulk('archive')}
            disabled={!checked.length}
            className="rounded border border-slate-300 bg-surface px-2 py-1 disabled:opacity-50"
          >
            Archive
          </button>
        </div>
      )}

      {error && <p className="bg-red-50 px-6 py-2 text-sm text-red-700">{error}</p>}

      <div className="flex min-h-0 flex-1">
        <ul
          className={`${selectedId ? 'hidden lg:block' : 'block'} w-full shrink-0 overflow-y-auto border-r border-slate-200 bg-surface lg:w-96`}
        >
          {emails.length === 0 && (
            <li className="p-6 text-sm text-slate-500">
              No {priority} emails. Click Refresh to check Gmail.
            </li>
          )}
          {emails.map((email) => (
            <li
              key={email.id}
              onClick={() => setSelectedId(email.id)}
              className={`flex cursor-pointer gap-3 border-b border-slate-100 px-4 py-3 ${
                selectedId === email.id ? 'bg-brand-50' : 'hover:bg-slate-50'
              }`}
            >
              {priority === 'Low' && (
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={checked.includes(email.id)}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => toggle(email.id)}
                />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex justify-between gap-2">
                  <span className={`truncate text-sm ${email.is_read ? '' : 'font-semibold'}`}>
                    {email.sender_name || email.sender}
                  </span>
                  <span className="shrink-0 text-xs text-slate-500">{formatTime(email.received_at)}</span>
                </div>
                <p dir="auto" className="truncate text-sm">{email.subject || '(no subject)'}</p>
                <p dir="auto" className="mb-1 truncate text-xs text-slate-500">{email.snippet}</p>
                <EmailBadges email={email} />
              </div>
            </li>
          ))}
        </ul>
        <section className={`${selectedId ? 'flex' : 'hidden lg:flex'} min-w-0 flex-1 flex-col bg-slate-50`}>
          {selectedId && (
            <button
              onClick={() => setSelectedId(null)}
              className="border-b border-slate-200 bg-surface px-6 py-2 text-left text-sm text-brand-700 hover:bg-slate-50 lg:hidden"
            >
              ← Back to list
            </button>
          )}
          {selectedId ? (
            <EmailDetail key={selectedId} emailId={selectedId} onChanged={load} />
          ) : (
            <p className="p-6 text-sm text-slate-500">Select an email to read it and reply.</p>
          )}
        </section>
      </div>
    </div>
  )
}
