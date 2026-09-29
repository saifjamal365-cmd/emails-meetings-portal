import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Badge } from '../components/Badges.jsx'
import ReportCard from '../components/ReportCard.jsx'
import TaskForm from '../components/TaskForm.jsx'

const COLUMNS = ['To do', 'In progress', 'Done']
const PRIORITY_STYLE = {
  High: 'bg-red-50 text-red-700 ring-red-200',
  Medium: 'bg-amber-50 text-amber-800 ring-amber-200',
  Low: 'bg-slate-100 text-slate-600 ring-slate-200',
}

// Local date as YYYY-MM-DD (toISOString would use UTC and can give yesterday's date).
function localDay(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function TaskCard({ task, today, onOpen }) {
  const late = task.status !== 'Done' && task.due_date && task.due_date < today
  return (
    <li
      draggable
      onDragStart={(e) => e.dataTransfer.setData('text/plain', String(task.id))}
      onClick={() => onOpen(task)}
      className="cursor-pointer rounded-md border border-slate-200 bg-white p-3 shadow-sm hover:border-blue-300"
    >
      <p dir="auto" className={`text-sm font-medium ${task.status === 'Done' ? 'text-slate-400 line-through' : ''}`}>
        {task.title}
      </p>
      {task.source_label && (
        <p dir="auto" className="truncate text-xs text-slate-500">{task.source_label}</p>
      )}
      <div className="mt-2 flex flex-wrap gap-1">
        <Badge className={PRIORITY_STYLE[task.priority]}>{task.priority}</Badge>
        {task.due_date && (
          <Badge className={late ? 'bg-red-600 text-white ring-red-600' : undefined}>
            {late ? 'Late · ' : task.due_date === today ? 'Today · ' : 'Due '}
            {task.due_date}
          </Badge>
        )}
      </div>
    </li>
  )
}

export default function Tasks() {
  const today = localDay()
  const [tasks, setTasks] = useState([])
  const [allDone, setAllDone] = useState(false)
  const [editing, setEditing] = useState(null) // null = closed, 'new', or a task
  const [dragOver, setDragOver] = useState(null)
  const [day, setDay] = useState(today)
  const [days, setDays] = useState([])
  const [reports, setReports] = useState({ morning: null, evening: null })
  const [error, setError] = useState('')

  const loadTasks = useCallback(() => {
    api(`/tasks?all_done=${allDone}`)
      .then(setTasks)
      .catch((e) => setError(e.message))
  }, [allDone])

  const loadReports = useCallback(() => {
    api(`/reports?day=${day}`).then(setReports).catch((e) => setError(e.message))
    api('/reports/days').then(setDays).catch(() => {})
  }, [day])

  useEffect(loadTasks, [loadTasks])
  useEffect(loadReports, [loadReports])

  async function save(body) {
    try {
      if (editing === 'new') await api('/tasks', { method: 'POST', body })
      else await api(`/tasks/${editing.id}`, { method: 'PUT', body })
      setEditing(null)
      loadTasks()
    } catch (e) {
      setError(e.message)
    }
  }

  async function remove() {
    await api(`/tasks/${editing.id}`, { method: 'DELETE' })
    setEditing(null)
    loadTasks()
  }

  async function drop(status, e) {
    e.preventDefault()
    setDragOver(null)
    const id = Number(e.dataTransfer.getData('text/plain'))
    const task = tasks.find((t) => t.id === id)
    if (!task || task.status === status) return
    setTasks(tasks.map((t) => (t.id === id ? { ...t, status } : t))) // move now, save in the background
    try {
      await api(`/tasks/${id}`, { method: 'PUT', body: { status } })
    } catch (err) {
      setError(err.message)
    }
    loadTasks()
  }

  const dayOptions = days.includes(today) ? days : [today, ...days]

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center gap-4">
        <h2 className="text-2xl font-semibold">Daily Tasks</h2>
        <span className="text-slate-500">
          {new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' })}
        </span>
        <button
          onClick={() => setEditing('new')}
          className="ms-auto rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          + New task
        </button>
      </header>

      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div>
        <div className="mb-2 flex items-center gap-2 text-sm">
          <span className="text-slate-600">Plans for</span>
          <select value={day} onChange={(e) => setDay(e.target.value)} className="rounded-md border border-slate-300 px-2 py-1">
            {dayOptions.map((d) => (
              <option key={d} value={d}>
                {d === today ? `Today (${d})` : d}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {['morning', 'evening'].map((kind) => (
            <ReportCard
              key={`${kind}-${day}`}
              kind={kind}
              day={day}
              report={reports[kind]}
              isToday={day === today}
              onChanged={loadReports}
            />
          ))}
        </div>
      </div>

      {editing && (
        <TaskForm
          key={editing === 'new' ? 'new' : editing.id}
          task={editing === 'new' ? null : editing}
          onSave={save}
          onDelete={remove}
          onCancel={() => setEditing(null)}
        />
      )}

      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm text-slate-500">Drag a task to change its status. Click a task to edit it.</p>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={allDone} onChange={(e) => setAllDone(e.target.checked)} />
            Show all done tasks
          </label>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {COLUMNS.map((status) => {
            const column = tasks.filter((t) => t.status === status)
            return (
              <div
                key={status}
                onDragOver={(e) => {
                  e.preventDefault()
                  setDragOver(status)
                }}
                onDragLeave={() => setDragOver(null)}
                onDrop={(e) => drop(status, e)}
                className={`min-h-40 rounded-lg p-3 ${dragOver === status ? 'bg-blue-100' : 'bg-slate-100'}`}
              >
                <h3 className="mb-2 text-sm font-semibold text-slate-700">
                  {status} <span className="font-normal text-slate-500">({column.length})</span>
                </h3>
                <ul className="space-y-2">
                  {column.map((task) => (
                    <TaskCard key={task.id} task={task} today={today} onOpen={setEditing} />
                  ))}
                </ul>
                {status === 'Done' && !allDone && column.length === 0 && (
                  <p className="text-xs text-slate-500">Tasks you finish today show here.</p>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
