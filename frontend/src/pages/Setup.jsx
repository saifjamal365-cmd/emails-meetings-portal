import { useEffect, useState } from 'react'
import { api } from '../api.js'

// The portal password and the keys. Shown by itself on the first run, and later from
// Settings -> "Password and keys". Saved values are never shown again, only "saved".
const KEYS = [
  {
    field: 'gemini_api_key',
    label: 'Gemini API key',
    help: (
      <>
        Free, for the AI. Open{' '}
        <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer" className="text-brand-600 underline">
          aistudio.google.com/apikey
        </a>{' '}
        and click <b>Create API key</b>.
      </>
    ),
  },
  {
    field: 'google_client_id',
    label: 'Google Client ID',
    help: 'For Gmail, Calendar and Meet. It ends with .apps.googleusercontent.com (see "How to get the Google keys" below).',
  },
  { field: 'google_client_secret', label: 'Google Client secret', help: 'Shown next to the Client ID when you create it.' },
]

function Saved() {
  return <span className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5 text-xs font-medium text-emerald-700">saved</span>
}

export default function Setup({ firstRun = false, onDone }) {
  const [status, setStatus] = useState(null)
  const [values, setValues] = useState({ portal_password: '', confirm: '', gemini_api_key: '', google_client_id: '', google_client_secret: '' })
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api('/setup/status').then(setStatus).catch((e) => setError(e.message))
  }, [])

  const set = (field) => (e) => setValues((v) => ({ ...v, [field]: e.target.value }))
  const passwordSet = status?.is_set.portal_password

  async function submit(e) {
    e.preventDefault()
    setError('')
    setMessage('')
    if (values.portal_password !== values.confirm) {
      setError('The two passwords are not the same.')
      return
    }
    setBusy(true)
    try {
      const { confirm: _, ...body } = values
      const next = await api('/setup', { method: 'POST', body })
      setStatus(next)
      setValues({ portal_password: '', confirm: '', gemini_api_key: '', google_client_id: '', google_client_secret: '' })
      if (firstRun && !next.needs_setup) onDone?.()
      else setMessage('Saved. The new values work now - no restart needed.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const input = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm'
  const form = (
    <form onSubmit={submit} className="w-full max-w-xl space-y-5 rounded-lg border border-slate-200 bg-surface p-6 shadow-sm">
      <div>
        {firstRun && (
          <div className="mb-4 flex items-center gap-2.5">
            <img src="/favicon.svg" alt="" className="size-8" />
            <span className="font-semibold tracking-tight">Communication Portal</span>
          </div>
        )}
        <h1 className="text-lg font-semibold">{firstRun ? 'Welcome - set up your portal' : 'Password and keys'}</h1>
        <p className="text-sm text-slate-500">
          {firstRun
            ? 'Only once. Everything stays on this computer, in backend/.env. Do not share these keys with anyone.'
            : 'Fill in only what you want to change. Empty fields keep the saved value.'}
        </p>
      </div>

      <fieldset className="space-y-2">
        <label className="block text-sm font-medium">
          Portal password {passwordSet && <Saved />}
        </label>
        <p className="text-xs text-slate-500">You choose it (8 characters or more). You use it to open the portal.</p>
        <input type="password" autoComplete="new-password" value={values.portal_password} onChange={set('portal_password')}
          placeholder={passwordSet ? 'New password (empty = keep)' : 'Password'} className={input} />
        <input type="password" autoComplete="new-password" value={values.confirm} onChange={set('confirm')}
          placeholder="Type it again" className={input} />
      </fieldset>

      {KEYS.map(({ field, label, help }) => (
        <div key={field} className="space-y-1">
          <label htmlFor={field} className="block text-sm font-medium">
            {label} {status?.is_set[field] && <Saved />}
          </label>
          <p className="text-xs text-slate-500">{help}</p>
          <input id={field} type="password" autoComplete="off" spellCheck={false} value={values[field]} onChange={set(field)}
            placeholder={status?.is_set[field] ? 'Saved (empty = keep)' : ''} className={input} />
        </div>
      ))}

      <details className="rounded-md bg-slate-50 p-3 text-sm text-slate-700">
        <summary className="cursor-pointer font-medium">How to get the Google keys (about 15 minutes, free)</summary>
        <ol className="mt-2 list-decimal space-y-1 pl-5">
          <li>
            Open{' '}
            <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noreferrer" className="text-brand-600 underline">
              Google Cloud
            </a>{' '}
            and create a project named <b>Communication Portal</b>. No payment method is needed.
          </li>
          <li>APIs &amp; Services -&gt; Library: enable <b>Gmail API</b>, <b>Google Calendar API</b> and <b>Google Meet REST API</b>.</li>
          <li>OAuth consent screen: <b>External</b>, your email, and add your Gmail under <b>Test users</b>.</li>
          <li>
            Credentials -&gt; Create OAuth client ID -&gt; <b>Web application</b>, with this redirect URI:
            <code className="mt-1 block select-all rounded bg-surface px-2 py-1 text-xs">{status?.redirect_uri}</code>
          </li>
          <li>Copy the Client ID and the Client secret here. Then click <b>Publish app</b> on the consent screen.</li>
        </ol>
      </details>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {message && <p className="text-sm text-emerald-700">{message}</p>}
      <button type="submit" disabled={busy || !status}
        className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">
        {busy ? 'Saving...' : firstRun ? 'Save and start' : 'Save'}
      </button>
      {firstRun && (
        <p className="text-xs text-slate-500">
          The password and the Gemini key are needed to start. The Google keys can wait: then emails and meetings stay
          empty until you add them (Settings -&gt; Password and keys).
        </p>
      )}
    </form>
  )

  return firstRun ? <div className="flex min-h-screen items-center justify-center p-4">{form}</div> : form
}
