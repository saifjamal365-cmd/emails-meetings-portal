import { useCallback, useEffect, useRef, useState } from 'react'

// A confirm box inside the page. The browser's window.confirm() is blocked in some browsers
// and app panels (it answers "no" at once without showing anything), so the portal uses this.
//
//   const [confirmDialog, confirm] = useConfirm()
//   if (await confirm('Send this reply?', { confirmLabel: 'Send' })) { ... }
//   ...and render {confirmDialog} somewhere in the component.
export function useConfirm() {
  const [question, setQuestion] = useState(null) // { message, confirmLabel, danger }
  const answer = useRef(null)

  const confirm = useCallback(
    (message, { confirmLabel = 'OK', danger = false } = {}) =>
      new Promise((resolve) => {
        answer.current = resolve
        setQuestion({ message, confirmLabel, danger })
      }),
    [],
  )

  const close = useCallback((yes) => {
    answer.current?.(yes)
    answer.current = null
    setQuestion(null)
  }, [])

  useEffect(() => {
    if (!question) return undefined
    const onKey = (e) => e.key === 'Escape' && close(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [question, close])

  const dialog = question && (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => close(false)}>
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <p dir="auto" className="mb-5 text-sm text-slate-800">
          {question.message}
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => close(false)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            autoFocus
            onClick={() => close(true)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium text-white ${
              question.danger ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'
            }`}
          >
            {question.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )

  return [dialog, confirm]
}
