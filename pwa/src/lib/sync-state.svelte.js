// Sync controller — one reactive place for sync status, used by the manual
// button, the auto-sync-on-open and the debounced auto-sync-after-save. Owns a
// singleton Google Drive transport (drive.js caches the token/folder at module
// level, so all callers share one authenticated session).

import { syncWith } from './app-sync.js';
import { refreshEntries } from './store.svelte.js';
import { GoogleDriveTransport, clearToken as clearGoogleToken } from './drive.js';
import { YandexDiskTransport, clearToken as clearYandexToken } from './yandex.js';
import { isUnlocked } from './vault.js';

const LAST_KEY = 'indexlife:last-sync';
const PROVIDER_KEY = 'indexlife:cloud-provider'; // 'yandex' | 'google'

export function getProvider() {
  return localStorage.getItem(PROVIDER_KEY);
}

export function setProvider(name) {
  if (name) localStorage.setItem(PROVIDER_KEY, name);
  else localStorage.removeItem(PROVIDER_KEY);
  transport = null; // rebuild for the new provider
}

// Sign out of the cloud on this device: forget OAuth tokens of BOTH
// providers and the chosen one. Without this, "switch cloud" kept the
// year-long Yandex token and silently reused the previous account.
export function signOutCloud() {
  try { clearYandexToken(); } catch { /* best-effort */ }
  try { clearGoogleToken(); } catch { /* best-effort */ }
  setProvider(null);
  syncState.status = 'idle';
  syncState.error = '';
}

export const syncState = $state({
  status: 'idle',                                       // idle | syncing | ok | error
  lastSyncedAt: Number(localStorage.getItem(LAST_KEY)) || 0,
  error: '',
  // Peers whose blobs could not be read on the last cycle (key mismatch /
  // junk) — a broken link must never look like a clean sync.
  lastLocked: 0,
  lastErrors: 0
});

let transport = null;
export function getTransport() {
  if (!transport) {
    transport = getProvider() === 'yandex'
      ? new YandexDiskTransport()
      : new GoogleDriveTransport();
  }
  return transport;
}

// Run one sync cycle, tracking status. `silent` suppresses error surfacing
// (for background syncs). Returns true on success.
export async function runSync({ silent = false } = {}) {
  if (!isUnlocked()) {
    if (!silent) syncState.error = 'Сначала включите шифрование';
    return false;
  }
  if (syncState.status === 'syncing') return false; // dedupe concurrent runs
  syncState.status = 'syncing';
  syncState.error = '';
  try {
    const r = await syncWith(getTransport());
    syncState.lastLocked = r.locked || 0;
    syncState.lastErrors = r.errors || 0;
    await refreshEntries();
    syncState.lastSyncedAt = Date.now();
    localStorage.setItem(LAST_KEY, String(syncState.lastSyncedAt));
    syncState.status = 'ok';
    return true;
  } catch (e) {
    const msg = e?.message || '';
    if (msg === 'auth-expired') {
      // Cloud session gone (token revoked / expired server-side) — a
      // distinct state so the UI offers "sign in again" instead of a
      // generic error, and background syncs stop looking mysterious.
      syncState.status = 'auth';
      syncState.error = '';
      return false;
    }
    syncState.status = 'error';
    if (!silent) {
      syncState.error = msg.includes('Failed to fetch')
        ? 'Нет сети или облако недоступно — попробуйте позже'
        : (msg || 'Ошибка синхронизации');
    }
    return false;
  }
}

// Debounced background sync — called after each save so new entries reach the
// cloud promptly without a sync per keystroke.
let debounce = null;
export function scheduleSync(delay = 2500) {
  if (!isUnlocked()) return;
  clearTimeout(debounce);
  debounce = setTimeout(() => runSync({ silent: true }), delay);
}

// ── Auto-sync while the app is open ─────────────────────────────────
// Two triggers: returning to the foreground (the common "opened the PWA
// after editing on the desktop" case) and a gentle interval while visible.
// Both funnel through runSync's isUnlocked guard + concurrent-run dedupe,
// so an install without cloud sync stays completely silent. MIN_GAP keeps
// rapid tab switches from hammering the cloud API.

const AUTO_SYNC_MIN_GAP_MS = 60 * 1000;
const AUTO_SYNC_INTERVAL_MS = 5 * 60 * 1000;

function autoSync() {
  if (Date.now() - syncState.lastSyncedAt < AUTO_SYNC_MIN_GAP_MS) return;
  runSync({ silent: true });
}

let autoSyncStarted = false;
export function initAutoSync() {
  if (autoSyncStarted) return; // idempotent — App mounts once, but be safe
  autoSyncStarted = true;
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') autoSync();
  });
  setInterval(() => {
    if (document.visibilityState === 'visible') autoSync();
  }, AUTO_SYNC_INTERVAL_MS);
}
