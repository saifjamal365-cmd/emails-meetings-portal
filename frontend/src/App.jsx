import { useEffect, useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import { api, LOGGED_OUT_EVENT } from './api.js'
import Layout from './components/Layout.jsx'
import AllEmails from './pages/AllEmails.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Inbox from './pages/Inbox.jsx'
import Login from './pages/Login.jsx'
import Meetings from './pages/Meetings.jsx'
import Settings from './pages/Settings.jsx'
import Tasks from './pages/Tasks.jsx'

export default function App() {
  // null = checking, then { login_required, logged_in }
  const [auth, setAuth] = useState(null)

  function checkLogin() {
    api('/auth/me')
      .then(setAuth)
      .catch(() => setAuth({ login_required: false, logged_in: true })) // backend down: pages show the error
  }

  useEffect(() => {
    checkLogin()
    const onLoggedOut = () => setAuth((a) => (a ? { ...a, logged_in: false } : a))
    window.addEventListener(LOGGED_OUT_EVENT, onLoggedOut)
    return () => window.removeEventListener(LOGGED_OUT_EVENT, onLoggedOut)
  }, [])

  async function logout() {
    await api('/auth/logout', { method: 'POST' })
    checkLogin()
  }

  if (!auth) return null
  if (!auth.logged_in) return <Login onLoggedIn={checkLogin} />

  return (
    <Routes>
      <Route element={<Layout onLogout={auth.login_required ? logout : null} />}>
        <Route index element={<Dashboard />} />
        <Route path="high" element={<Inbox key="high" priority="High" />} />
        <Route path="low" element={<Inbox key="low" priority="Low" />} />
        <Route path="emails" element={<AllEmails />} />
        <Route path="meetings" element={<Meetings />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="settings" element={<Settings loginRequired={auth.login_required} />} />
      </Route>
    </Routes>
  )
}
