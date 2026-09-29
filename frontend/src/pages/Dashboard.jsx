import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { EmailBadges } from '../components/Badges.jsx'
import SyncButton from '../components/SyncButton.jsx'

// Counts, today's plan, the High emails that need an answer, system status, LLM test.
export default function Dashboard() {
  const [health, setHealth] = useState(null)
  const [healthError, setHealthError] = useState('')
  const [message, setMessage] = useState('Say hello in English and in Arabic, in one short line each.')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const [counts, setCounts] = useState(null)
  const [taskCounts, setTaskCounts] = useState(null)
  const [plan, setPlan] = useState(null)
  const [urgent, setUrgent] = useState([])

  function loadCounts() {
    api('/emails/counts').then(setCounts).catch(() => setCounts(null))
    api('/tasks/counts').then(setTaskCounts).catch(() => setTaskCounts(null))
    api('/reports').then((r) => setPlan(r.morning)).catch(() => setPlan(null))
    api('/emails?view=high').then((list) => setUrgent(list.slice(0, 5))).catch(() => setUrgent([]))
  }

  useEffect(() => {
    api('/health')
      .then(setHealth)
      .catch(() => setHealthError('Backend is not running. Start it with: uvicorn app.main:app --reload'))
    loadCounts()
  }, [])

  async function testLlm() {
    setLoading(true)
    setError('')
    setResult(null)
    try {
      setResult(await api('/llm/test', { method: 'POST', body: { message } }))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-5xl">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-2xl font-semibold">Dashboard</h2>
        <SyncButton onDone={loadCounts} />
      </div>

      {counts && taskCounts && (
        <section className="mb-6 grid grid-cols-4 gap-3">
          {[
            { label: 'High to answer', value: counts.high, to: '/high', color: 'text-red-700' },
            { label: 'Low', value: counts.low, to: '/low', color: 'text-slate-700' },
            { label: 'Unread', value: counts.unread, to: '/emails', color: 'text-slate-700' },
            { label: 'Replies sent today', value: counts.sent_today, to: '/emails', color: 'text-emerald-700' },
            { label: 'Late tasks', value: taskCounts.late, to: '/tasks', color: 'text-red-700' },
            { label: 'Tasks due today', value: taskCounts.due_today, to: '/tasks', color: 'text-amber-700' },
            { label: 'Open tasks', value: taskCounts.open, to: '/tasks', color: 'text-slate-700' },
            { label: 'Tasks done today', value: taskCounts.done_today, to: '/tasks', color: 'text-emerald-700' },
          ].map((card) => (
            <Link
              key={card.label}
              to={card.to}
              className="rounded-lg border border-slate-200 bg-white p-4 hover:border-blue-300"
            >
              <p className={`text-2xl font-semibold ${card.color}`}>{card.value}</p>
              <p className="text-sm text-slate-600">{card.label}</p>
            </Link>
          ))}
        </section>
      )}

      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-medium">Today's plan</h3>
            <Link to="/tasks" className="text-sm text-blue-700 hover:underline">Open Daily Tasks</Link>
          </div>
          {plan ? (
            <p dir="auto" className="line-clamp-[10] whitespace-pre-wrap text-sm text-slate-700">
              {plan.content.replace(/^## /gm, '').trim()}
            </p>
          ) : (
            <p className="text-sm text-slate-500">No morning plan yet. It is made at 8:00, or on the Daily Tasks page.</p>
          )}
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-medium">Needs your answer</h3>
            <Link to="/high" className="text-sm text-blue-700 hover:underline">High Priority</Link>
          </div>
          {urgent.length === 0 ? (
            <p className="text-sm text-slate-500">No High emails waiting.</p>
          ) : (
            <ul className="space-y-3">
              {urgent.map((e) => (
                <li key={e.id}>
                  <Link to="/high" className="block hover:underline">
                    <span className="text-sm font-medium">{e.sender_name || e.sender}: </span>
                    <span dir="auto" className="text-sm">{e.subject}</span>
                  </Link>
                  <EmailBadges email={e} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-2 font-medium">System status</h3>
        {healthError && <p className="text-sm text-red-600">{healthError}</p>}
        {health && (
          <ul className="text-sm text-slate-700">
            <li>API: {health.status}</li>
            <li>Database: {health.database}</li>
            <li>LLM model: {health.llm_model}</li>
            <li>
              LLM key set: {health.llm_key_set ? 'yes' : 'no - add GEMINI_API_KEY to backend/.env'}
            </li>
          </ul>
        )}
        {!health && !healthError && <p className="text-sm text-slate-500">Checking...</p>}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-2 font-medium">Test the LLM</h3>
        <textarea
          dir="auto"
          className="mb-3 w-full rounded-md border border-slate-300 p-2 text-sm"
          rows={3}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <button
          onClick={testLlm}
          disabled={loading || !message.trim()}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Asking...' : 'Send to LLM'}
        </button>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        {result && (
          <div className="mt-4">
            <p dir="auto" className="whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm">
              {result.reply}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              {result.model} · {result.input_tokens} in / {result.output_tokens} out tokens
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
