import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useConfirm } from './ConfirmDialog.jsx'

const input = 'w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm'

// Add a new task, or edit one. `task` = null for a new task.
export default function TaskForm({ task, onSave, onDelete, onCancel }) {
  const [form, setForm] = useState({
    title: task?.title ?? '',
    description: task?.description ?? '',
    notes: task?.notes ?? '',
    due_date: task?.due_date ?? '',
    priority: task?.priority ?? 'Medium',
    status: task?.status ?? 'To do',
  })
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })
  const [confirmDialog, confirm] = useConfirm()

  function submit(e) {
    e.preventDefault()
    const body = { ...form, due_date: form.due_date || null }
    if (!task) delete body.status
    onSave(body)
  }

  const sourceLink =
    task?.source_type === 'meeting'
      ? `/meetings?open=${task.source_id}`
      : task?.source_type === 'email'
        ? '/emails'
        : null

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border border-blue-200 bg-white p-4 shadow-sm">
      {confirmDialog}
      <h3 className="font-semibold">{task ? 'Edit task' : 'New task'}</h3>
      {task?.source_label && (
        <p className="text-xs text-slate-500">
          From{' '}
          {sourceLink ? (
            <Link to={sourceLink} className="text-blue-700 underline">
              {task.source_label}
            </Link>
          ) : (
            task.source_label
          )}
          {task.owner && ` · owner: ${task.owner}`}
        </p>
      )}
      <input dir="auto" required autoFocus value={form.title} onChange={set('title')} placeholder="Task title" className={input} />
      <textarea dir="auto" rows={2} value={form.description} onChange={set('description')} placeholder="Description" className={input} />
      <div className="grid grid-cols-3 gap-2">
        <label className="text-xs text-slate-600">
          Due date
          <input type="date" value={form.due_date} onChange={set('due_date')} className={input} />
        </label>
        <label className="text-xs text-slate-600">
          Priority
          <select value={form.priority} onChange={set('priority')} className={input}>
            <option>High</option>
            <option>Medium</option>
            <option>Low</option>
          </select>
        </label>
        {task && (
          <label className="text-xs text-slate-600">
            Status
            <select value={form.status} onChange={set('status')} className={input}>
              <option>To do</option>
              <option>In progress</option>
              <option>Done</option>
            </select>
          </label>
        )}
      </div>
      <textarea dir="auto" rows={2} value={form.notes} onChange={set('notes')} placeholder="Notes" className={input} />
      <div className="flex gap-2">
        <button type="submit" className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700">
          {task ? 'Save' : 'Add task'}
        </button>
        <button type="button" onClick={onCancel} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          Cancel
        </button>
        {task && (
          <button
            type="button"
            onClick={async () => (await confirm(`Delete "${task.title}"?`, { confirmLabel: 'Delete', danger: true })) && onDelete()}
            className="ms-auto rounded-md border border-red-200 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50"
          >
            Delete
          </button>
        )}
      </div>
    </form>
  )
}
