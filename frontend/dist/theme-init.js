// Runs before the page draws, so dark mode never flashes white. (A file, not an inline
// script: the portal's security policy allows scripts only from its own files.)
// The same logic, with the switch, is in src/theme.js.
;(function () {
  var choice = 'auto'
  try {
    choice = localStorage.getItem('portal-theme') || 'auto'
  } catch (e) {}
  var dark = choice === 'dark' || (choice === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
})()
