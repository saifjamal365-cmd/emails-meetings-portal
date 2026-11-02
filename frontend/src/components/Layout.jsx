import {
  CalendarCheck,
  Inbox,
  LayoutDashboard,
  LogOut,
  Mail,
  MailWarning,
  Monitor,
  Moon,
  Settings,
  Sun,
  Video,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { api } from '../api.js'
import { useTheme } from '../theme.js'
import NotificationBell from './NotificationBell.jsx'

// The left rail: the portal's name, the pages in two groups with live counts, then
// notifications, the theme switch and log out.
const groups = [
  { links: [{ to: '/', label: 'Dashboard', icon: LayoutDashboard }] },
  {
    title: 'Emails',
    links: [
      { to: '/high', label: 'High Priority', icon: MailWarning, count: 'high', urgent: true },
      { to: '/low', label: 'Low Priority', icon: Inbox, count: 'low' },
      { to: '/emails', label: 'All Emails', icon: Mail },
    ],
  },
  {
    title: 'Work',
    links: [
      { to: '/meetings', label: 'Meetings', icon: Video },
      { to: '/tasks', label: 'Daily Tasks', icon: CalendarCheck, count: 'late', urgent: true },
    ],
  },
  { links: [{ to: '/settings', label: 'Settings', icon: Settings }] },
]

const themes = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'auto', label: 'Auto', icon: Monitor, title: 'Follow Windows' },
]

function useCounts() {
  const [counts, setCounts] = useState({})
  const { pathname } = useLocation()
  useEffect(() => {
    // Again after every page change, so a reply sent or a task finished shows at once.
    const load = () =>
      Promise.all([api('/emails/counts'), api('/tasks/counts')])
        .then(([emails, tasks]) => setCounts({ high: emails.high, low: emails.low, late: tasks.late }))
        .catch(() => {})
    load()
    const timer = setInterval(load, 60_000)
    return () => clearInterval(timer)
  }, [pathname])
  return counts
}

function Count({ value, urgent }) {
  if (!value) return null
  return (
    <span
      className={`tabular ms-auto min-w-6 rounded-full px-1.5 text-center text-xs font-semibold leading-5 ${
        urgent ? 'bg-rose-500 text-white' : 'bg-rail-line text-rail-muted'
      }`}
    >
      {value}
    </span>
  )
}

export default function Layout({ onLogout }) {
  const counts = useCounts()
  const [theme, setTheme] = useTheme()

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-52 shrink-0 flex-col border-r border-rail-line bg-rail px-3 py-5 text-rail-ink lg:w-60">
        <div className="mb-7 flex items-center gap-2.5 px-2">
          <img src="/favicon.svg" alt="" className="size-8" />
          <span className="text-base font-semibold leading-tight tracking-tight">Communication Portal</span>
        </div>

        <nav className="flex flex-col gap-5" aria-label="Pages">
          {groups.map((group, i) => (
            <div key={group.title ?? i}>
              {group.title && (
                <p className="mb-1 px-3 text-xs font-medium text-rail-muted">{group.title}</p>
              )}
              <ul className="flex flex-col gap-0.5">
                {group.links.map(({ to, label, icon: Icon, count, urgent }) => (
                  <li key={to}>
                    <NavLink
                      to={to}
                      end={to === '/'}
                      className={({ isActive }) =>
                        `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors duration-150 ${
                          isActive
                            ? 'bg-rail-active font-medium text-rail-ink'
                            : 'text-rail-muted hover:bg-rail-hover hover:text-rail-ink'
                        }`
                      }
                    >
                      <Icon className="size-4.5 shrink-0" strokeWidth={1.75} aria-hidden="true" />
                      {label}
                      {count && <Count value={counts[count]} urgent={urgent} />}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div className="mt-6 border-t border-rail-line pt-4">
          <NotificationBell />
        </div>

        <div className="mt-auto space-y-3">
          <div
            role="radiogroup"
            aria-label="Theme"
            className="flex rounded-md bg-rail-hover p-0.5 text-xs"
          >
            {themes.map(({ value, label, icon: Icon, title }) => (
              <button
                key={value}
                role="radio"
                aria-checked={theme === value}
                title={title ?? label}
                onClick={() => setTheme(value)}
                className={`flex flex-1 items-center justify-center gap-1 rounded px-1.5 py-1.5 transition-colors duration-150 ${
                  theme === value ? 'bg-rail-active font-medium text-rail-ink' : 'text-rail-muted hover:text-rail-ink'
                }`}
              >
                <Icon className="size-3.5" aria-hidden="true" />
                {label}
              </button>
            ))}
          </div>
          {onLogout && (
            <button
              onClick={onLogout}
              className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-rail-muted hover:bg-rail-hover hover:text-rail-ink"
            >
              <LogOut className="size-4.5" strokeWidth={1.75} aria-hidden="true" />
              Log out
            </button>
          )}
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-8">
        <Outlet />
      </main>
    </div>
  )
}
