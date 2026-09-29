import { NavLink, Outlet } from 'react-router-dom'
import NotificationBell from './NotificationBell.jsx'

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/high', label: 'High Priority' },
  { to: '/low', label: 'Low Priority' },
  { to: '/emails', label: 'All Emails' },
  { to: '/meetings', label: 'Meetings' },
  { to: '/tasks', label: 'Daily Tasks' },
  { to: '/settings', label: 'Settings' },
]

export default function Layout({ onLogout }) {
  return (
    <div className="flex min-h-screen">
      <aside className="flex w-44 shrink-0 flex-col border-r border-slate-200 bg-white p-3 lg:w-56 lg:p-4">
        <h1 className="mb-6 text-lg font-semibold">Email &amp; Meeting Portal</h1>
        <nav className="flex flex-col gap-1">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === '/'}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm ${
                  isActive ? 'bg-blue-50 font-medium text-blue-700' : 'text-slate-600 hover:bg-slate-100'
                }`
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-6 border-t border-slate-100 pt-4">
          <NotificationBell />
        </div>
        {onLogout && (
          <button onClick={onLogout} className="mt-auto rounded-md px-3 py-2 text-left text-sm text-slate-500 hover:bg-slate-100">
            Log out
          </button>
        )}
      </aside>
      <main className="min-w-0 flex-1 p-8">
        <Outlet />
      </main>
    </div>
  )
}
