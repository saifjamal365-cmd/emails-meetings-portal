import { AlertTriangle, Bell, CalendarCheck, ListChecks, Mail } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'

const CHECK_EVERY_MS = 60_000
const ICON = { email: Mail, meeting: CalendarCheck, plan: ListChecks, problem: AlertTriangle }

function canUseDesktop() {
  return typeof window !== 'undefined' && 'Notification' in window
}

// The bell in the side menu: new High emails, meeting summaries, plans, problems.
export default function NotificationBell() {
  const [data, setData] = useState({ unread: 0, items: [] })
  const [open, setOpen] = useState(false)
  const [desktop, setDesktop] = useState(canUseDesktop() ? window.Notification.permission : 'unsupported')
  const lastSeenId = useRef(null)
  const navigate = useNavigate()

  const load = useCallback(() => {
    api('/notifications')
      .then((d) => {
        // Show new unread items as desktop notifications (not on the first load).
        if (lastSeenId.current !== null && canUseDesktop() && window.Notification.permission === 'granted') {
          d.items
            .filter((n) => !n.read && n.id > lastSeenId.current)
            .forEach((n) => new window.Notification(n.title, { body: n.body }))
        }
        lastSeenId.current = Math.max(0, ...d.items.map((n) => n.id))
        setData(d)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, CHECK_EVERY_MS)
    return () => clearInterval(timer)
  }, [load])

  async function openItem(n) {
    if (!n.read) await api(`/notifications/${n.id}/read`, { method: 'POST' }).catch(() => {})
    setOpen(false)
    load()
    if (n.link) navigate(n.link)
  }

  async function readAll() {
    await api('/notifications/read-all', { method: 'POST' })
    load()
  }

  async function turnOnDesktop() {
    setDesktop(await window.Notification.requestPermission())
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-rail-muted transition-colors duration-150 hover:bg-rail-hover hover:text-rail-ink"
      >
        <Bell className="size-4.5" strokeWidth={1.75} aria-hidden="true" />
        Notifications
        {data.unread > 0 && (
          <span className="tabular ms-auto min-w-6 rounded-full bg-rose-500 px-1.5 text-center text-xs font-semibold leading-5 text-white">
            {data.unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute left-full top-0 z-20 ms-3 w-80 rounded-lg border border-slate-200 bg-surface text-slate-900 shadow-[0_8px_24px_-6px_rgb(0_0_0/0.25)]">
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
            <span className="text-sm font-semibold">Notifications</span>
            {data.unread > 0 && (
              <button onClick={readAll} className="text-xs text-brand-700 hover:underline">
                Mark all as read
              </button>
            )}
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {data.items.length === 0 && <li className="p-3 text-sm text-slate-500">Nothing yet.</li>}
            {data.items.map((n) => {
              const Icon = ICON[n.kind] ?? Bell
              return (
              <li key={n.id}>
                <button
                  onClick={() => openItem(n)}
                  className={`flex w-full gap-2 border-b border-slate-100 px-3 py-2 text-left hover:bg-slate-50 ${n.read ? 'text-slate-500' : ''}`}
                >
                  <Icon
                    className={`mt-0.5 size-4 shrink-0 ${n.kind === 'problem' ? 'text-red-600' : 'text-slate-500'}`}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1">
                    <span dir="auto" className={`block text-sm ${n.read ? '' : 'font-medium'}`}>{n.title}</span>
                    {n.body && <span dir="auto" className="block truncate text-xs text-slate-500">{n.body}</span>}
                    <span className="block text-xs text-slate-400">{new Date(n.time).toLocaleString()}</span>
                  </span>
                </button>
              </li>
              )
            })}
          </ul>
          {desktop === 'default' && (
            <button onClick={turnOnDesktop} className="w-full border-t border-slate-100 px-3 py-2 text-left text-xs text-brand-700 hover:bg-slate-50">
              Also show them as desktop notifications
            </button>
          )}
        </div>
      )}
    </div>
  )
}
