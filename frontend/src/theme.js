import { useEffect, useState } from 'react'

// The user's theme choice: 'light', 'dark' or 'auto' (follow Windows). Saved in this browser.
const KEY = 'portal-theme'
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)')

function saved() {
  try {
    return localStorage.getItem(KEY) || 'auto'
  } catch {
    return 'auto' // private window or blocked storage: follow Windows
  }
}

function apply(choice) {
  const dark = choice === 'dark' || (choice === 'auto' && darkQuery.matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
}

export function useTheme() {
  const [choice, setChoice] = useState(saved)

  useEffect(() => {
    apply(choice)
    try {
      localStorage.setItem(KEY, choice)
    } catch {
      // not saved: it still applies until the page is closed
    }
    if (choice !== 'auto') return
    const follow = () => apply('auto') // Windows switched between light and dark
    darkQuery.addEventListener('change', follow)
    return () => darkQuery.removeEventListener('change', follow)
  }, [choice])

  return [choice, setChoice]
}
