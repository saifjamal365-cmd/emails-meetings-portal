// Small colored labels used on email lists and the email detail view.

const PRIORITY = {
  High: 'bg-red-50 text-red-700 ring-red-200',
  Low: 'bg-slate-100 text-slate-600 ring-slate-200',
}

export function Badge({ children, className = 'bg-slate-100 text-slate-600 ring-slate-200' }) {
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${className}`}>
      {children}
    </span>
  )
}

export function EmailBadges({ email }) {
  return (
    <div className="flex flex-wrap gap-1">
      {email.priority && <Badge className={PRIORITY[email.priority]}>{email.priority}</Badge>}
      {email.category && <Badge>{email.category}</Badge>}
      {email.deadline && <Badge className="bg-amber-50 text-amber-800 ring-amber-200">Due {email.deadline}</Badge>}
      {email.meeting_label && (
        <Badge className="bg-indigo-50 text-indigo-700 ring-indigo-200">Meeting: {email.meeting_label}</Badge>
      )}
      {email.reply_status && ['Edited', 'Sent', 'Skipped', 'Archived'].includes(email.reply_status) && (
        <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-200">{email.reply_status}</Badge>
      )}
    </div>
  )
}
