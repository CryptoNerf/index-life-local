// Appearance customization — theme (light/dark/system), accent colour and
// note font. Persisted locally, applied by toggling root data-attributes and
// CSS variables, so the whole UI re-themes instantly with no reload.

const KEY = 'indexlife:appearance';

const DEFAULTS = { theme: 'system', font: 'serif' };

export function loadAppearance() {
  try {
    return { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY)) || {}) };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveAppearance(a) {
  try {
    localStorage.setItem(KEY, JSON.stringify(a));
  } catch {
    /* storage disabled — appearance is best-effort */
  }
}

export function applyAppearance(a) {
  const root = document.documentElement;

  // theme: explicit light/dark sets data-theme; "system" removes it so the
  // CSS `prefers-color-scheme` media query takes over.
  if (a.theme === 'light' || a.theme === 'dark') root.dataset.theme = a.theme;
  else delete root.dataset.theme;

  root.dataset.font = a.font;

  // Match the iOS status bar / Android toolbar to the resolved background.
  const dark = a.theme === 'dark'
    || (a.theme === 'system'
        && window.matchMedia('(prefers-color-scheme: dark)').matches);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', dark ? '#121212' : '#ffffff');
}
