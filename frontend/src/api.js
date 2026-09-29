// Small helper for calling the backend. All paths start with /api (see the proxy in vite.config.js).

// Sent when the backend says "Please log in" (the login cookie expired): App shows the login page.
export const LOGGED_OUT_EVENT = 'portal:logged-out'

export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json' },
    body: options.body ? JSON.stringify(options.body) : undefined,
  })
  const data = await response.json().catch(() => ({}))
  if (response.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new Event(LOGGED_OUT_EVENT))
  }
  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`)
  }
  return data
}
