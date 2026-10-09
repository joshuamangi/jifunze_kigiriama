// Dark is the default. The choice is a per-device convenience kept in localStorage; the app
// works the same if storage is blocked.
const KEY = 'jifunze-theme';

export function currentTheme() {
  return document.documentElement.classList.contains('light') ? 'light' : 'dark';
}

export function applyTheme(theme) {
  document.documentElement.classList.toggle('light', theme === 'light');
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', getComputedStyle(document.documentElement).getPropertyValue('--bg').trim());
  document.dispatchEvent(new CustomEvent('themechange', { detail: theme }));
}

export function setTheme(theme) {
  try { localStorage.setItem(KEY, theme); } catch { /* storage unavailable: still applies for this visit */ }
  applyTheme(theme);
}

export function initTheme() {
  let stored = null;
  try { stored = localStorage.getItem(KEY); } catch { /* ignore */ }
  applyTheme(stored === 'light' ? 'light' : 'dark');
}
