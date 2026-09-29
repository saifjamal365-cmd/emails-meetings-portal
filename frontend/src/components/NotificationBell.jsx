import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'

const CHECK_EVERY_MS = 60_000
const ICON = { email: '✉', meeting: '🗓', plan: '✓', problem: '!' }

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
        className="flex w-full items-center justify-between rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
      >
        <span>Notifications</span>
        {data.unread > 0 && (
          <span className="rounded-full bg-red-600 px-2 py-0.5 text-xs font-semibold text-white">{data.unread}</span>
        )}
      </button>

      {open && (
        <div className="absolute left-full top-0 z-20 ms-2 w-80 rounded-lg border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
            <span className="text-sm font-semibold">Notifications</span>
            {data.unread > 0 && (
              <button onClick={readAll} className="text-xs text-blue-700 hover:underline">
                Mark all as read
              </button>
            )}
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {data.items.length === 0 && <li className="p-3 text-sm text-slate-500">Nothing yet.</li>}
            {data.items.map((n) => (
              <li key={n.id}>
                <button
                  onClick={() => openItem(n)}
                  className={`flex w-full gap-2 border-b border-slate-50 px-3 py-2 text-left hover:bg-slate-50 ${n.read ? 'text-slate-500' : ''}`}
                >
                  <span className={`w-4 shrink-0 text-center ${n.kind === 'problem' ? 'font-bold text-red-600' : ''}`}>
                    {ICON[n.kind]}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span dir="auto" className={`block text-sm ${n.read ? '' : 'font-medium'}`}>{n.title}</span>
                    {n.body && <span dir="auto" className="block truncate text-xs text-slate-500">{n.body}</span>}
                    <span className="block text-xs text-slate-400">{new Date(n.time).toLocaleString()}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {desktop === 'default' && (
            <button onClick={turnOnDesktop} className="w-full border-t border-slate-100 px-3 py-2 text-left text-xs text-blue-700 hover:bg-slate-50">
              Also show them as desktop notifications
            </button>
          )}
        </div>
      )}
    </div>
  )
}
