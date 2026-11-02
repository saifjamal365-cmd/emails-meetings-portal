import { useEffect, useState } from 'react'
import { api } from '../api.js'
import PageHeader from '../components/PageHeader.jsx'
import { EmailBadges } from '../components/Badges.jsx'
import EmailDetail from '../components/EmailDetail.jsx'
import { formatTime } from '../format.js'

// Search and read every saved email (read and unread).
export default function AllEmails() {
  const [query, setQuery] = useState('')
  const [emails, setEmails] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => {
      api(`/emails?view=all&q=${encodeURIComponent(query)}`)
        .then(setEmails)
        .catch((e) => setError(e.message))
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  return (
    <div className="-m-8 flex h-screen flex-col">
      <PageHeader
        bar
        title="All Emails"
        meta={`${emails.length} shown`}
        description="Every email the portal has read, High and Low, in one list. Search it, or open an email to move it between High and Low."
      >
        <input
          dir="auto"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search subject, sender or text..."
          aria-label="Search emails"
          className="w-80 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        />
      </PageHeader>
      {error && <p className="bg-red-50 px-6 py-2 text-sm text-red-700">{error}</p>}
      <div className="flex min-h-0 flex-1">
        <ul
          className={`${selectedId ? 'hidden lg:block' : 'block'} w-full shrink-0 overflow-y-auto border-r border-slate-200 bg-surface lg:w-96`}
        >
          {emails.map((email) => (
            <li
              key={email.id}
              onClick={() => setSelectedId(email.id)}
              className={`cursor-pointer border-b border-slate-100 px-4 py-3 ${
                selectedId === email.id ? 'bg-brand-50' : 'hover:bg-slate-50'
              }`}
            >
              <div className="flex justify-between gap-2">
                <span className={`truncate text-sm ${email.is_read ? '' : 'font-semibold'}`}>
                  {email.sender_name || email.sender}
                </span>
                <span className="shrink-0 text-xs text-slate-500">{formatTime(email.received_at)}</span>
              </div>
              <p dir="auto" className="mb-1 truncate text-sm">{email.subject || '(no subject)'}</p>
              <EmailBadges email={email} />
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
            <EmailDetail key={selectedId} emailId={selectedId} />
          ) : (
            <p className="p-6 text-sm text-slate-500">Select an email.</p>
          )}
        </section>
      </div>
    </div>
  )
}
