// Google Drive transport — implements the SyncTransport interface over the
// Drive REST API, with OAuth via Google Identity Services (GIS) token client.
// Scope: drive.file (the app sees only files it creates). Blobs live in a
// visible folder (config.DRIVE_FOLDER_NAME) so a desktop client can share it.
//
// Not unit-tested (needs a browser + real Google); the sync engine it plugs
// into is covered headless. Verify in-browser via the CloudSync UI.

import { GOOGLE_CLIENT_ID, DRIVE_FOLDER_NAME } from './config.js';
import { VAULT_FILENAME } from './sync.js';

const GIS_SRC = 'https://accounts.google.com/gsi/client';
const SCOPE = 'https://www.googleapis.com/auth/drive.file';
const FOLDER_MIME = 'application/vnd.google-apps.folder';

// ── Google Identity Services (token client) ──────────────────────────
let gisReady = null;
function loadGIS() {
  if (gisReady) return gisReady;
  gisReady = new Promise((resolve, reject) => {
    if (globalThis.google?.accounts?.oauth2) return resolve();
    const s = document.createElement('script');
    s.src = GIS_SRC;
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('failed to load Google Identity Services'));
    document.head.appendChild(s);
  });
  return gisReady;
}

let tokenClient = null;
let accessToken = null;
let tokenExpiry = 0;

// The token OUTLIVES the page. It used to live only in this module, so every
// reload — and iOS unloads a backgrounded PWA readily — left the phone
// signed out. The background sync that runs on open then asked GIS for a
// token without a user gesture, the browser blocked the popup, and the
// failure was swallowed because background syncs are silent: the app looked
// connected and quietly stopped receiving the desktop's entries.
// Google access tokens are short-lived (~1h) and scoped to drive.file, so
// localStorage is the right home for them — same as the Yandex transport.
const TOKEN_KEY = 'indexlife:google-token';

function loadToken() {
  try {
    const t = JSON.parse(localStorage.getItem(TOKEN_KEY) || 'null');
    if (!t || !t.token || !(Date.now() < t.expiry)) return null;
    accessToken = t.token;
    tokenExpiry = t.expiry;
    return t.token;
  } catch {
    return null;
  }
}

function saveToken(token, expiresIn) {
  accessToken = token;
  tokenExpiry = Date.now() + (Number(expiresIn) || 3600) * 1000;
  try {
    localStorage.setItem(TOKEN_KEY, JSON.stringify({ token, expiry: tokenExpiry }));
  } catch {
    /* private mode / quota — the in-memory copy still serves this session */
  }
}

// A live token with a minute of headroom, from memory or from storage.
function cachedToken() {
  if (accessToken && Date.now() < tokenExpiry - 60000) return accessToken;
  const stored = loadToken();
  return stored && Date.now() < tokenExpiry - 60000 ? stored : null;
}

// Get a valid access token. `interactive` triggers the consent popup (must be
// called from a user gesture). Without a gesture we never ask GIS — a
// blocked popup would surface as an opaque failure; 'auth-expired' lets the
// UI say "sign in again" instead.
async function getToken(interactive) {
  if (!interactive) {
    const token = cachedToken();
    if (token) return token;
    throw new Error('auth-expired');
  }
  await loadGIS();
  if (!tokenClient) {
    tokenClient = globalThis.google.accounts.oauth2.initTokenClient({
      client_id: GOOGLE_CLIENT_ID,
      scope: SCOPE,
      callback: () => {}
    });
  }
  // GIS calls back on success and on an explicit error, but says nothing at
  // all if the user closes the Google window — without the timeout the
  // connect button would spin until the app is restarted.
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error('Вход в Google не завершён — попробуйте ещё раз'));
    }, 3 * 60 * 1000);

    tokenClient.callback = (resp) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (resp.error) {
        return reject(new Error(
          resp.error === 'popup_closed_by_user' || resp.error === 'popup_failed_to_open'
            ? 'Окно входа Google закрыто — вход не завершён'
            : resp.error
        ));
      }
      saveToken(resp.access_token, resp.expires_in);
      resolve(accessToken);
    };
    try {
      // 'consent' only when we have never had a token: with an existing
      // grant Google can hand one back without a second consent screen.
      tokenClient.requestAccessToken({ prompt: loadToken() ? '' : 'consent' });
    } catch (e) {
      settled = true;
      clearTimeout(timer);
      reject(e);
    }
  });
}

// Sign out on this device: drop the token (stored and cached) and the folder
// index tied to the account so the next connect() asks Google again.
export function clearToken() {
  accessToken = null;
  tokenExpiry = 0;
  folderId = null;
  index = null;
  tags = null;
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* best-effort */
  }
}

// ── Drive REST helper ────────────────────────────────────────────────
async function api(path, opts = {}) {
  const token = await getToken(false);
  const resp = await fetch(`https://www.googleapis.com/${path}`, {
    ...opts,
    headers: { Authorization: `Bearer ${token}`, ...(opts.headers || {}) }
  });
  if (resp.status === 401) {
    // The silent refresh produced a stale/revoked token — sign-in state is
    // gone. Drop it and tell the UI to offer a re-login.
    clearToken();
    throw new Error('auth-expired');
  }
  if (!resp.ok) {
    throw new Error(`Drive API ${resp.status}: ${await resp.text()}`);
  }
  return resp;
}

const escapeQ = (s) => s.replace(/'/g, "\\'");

// ── folder + file index (lazy, cached) ───────────────────────────────
let folderId = null;
// The sync folder among however many are named index.life.
//
// Drive lets several folders share a name, and both clients used to take
// whichever the search happened to list first — so a phone and a desktop
// could settle on different folders and never meet again, each showing "the
// other device isn't here". Prefer a folder that actually holds a vault
// (that is what makes it *the* sync folder), then the most recently touched.
// The desktop applies the same rule, so both ends converge on one answer.
async function pickFolder() {
  const q = encodeURIComponent(
    `name='${escapeQ(DRIVE_FOLDER_NAME)}' and mimeType='${FOLDER_MIME}' and trashed=false`
  );
  const found = await (await api(
    `drive/v3/files?q=${q}&fields=files(id,modifiedTime)&spaces=drive&pageSize=50`
  )).json();
  const candidates = found.files || [];
  if (!candidates.length) return null;
  if (candidates.length === 1) return candidates[0].id;

  const byTouched = (a, b) => String(b.modifiedTime || '').localeCompare(String(a.modifiedTime || ''));
  const withVault = [];
  for (const f of [...candidates].sort(byTouched)) {
    const inner = encodeURIComponent(
      `'${escapeQ(f.id)}' in parents and name='${VAULT_FILENAME}' and trashed=false`
    );
    try {
      const res = await (await api(`drive/v3/files?q=${inner}&fields=files(id)&spaces=drive`)).json();
      if (res.files?.length) withVault.push(f);
    } catch {
      /* can't look inside — judge it by its timestamp alone */
    }
  }
  return (withVault.length ? withVault : [...candidates].sort(byTouched))[0].id;
}

async function getFolderId() {
  if (folderId) return folderId;
  const picked = await pickFolder();
  if (picked) {
    folderId = picked;
    return folderId;
  }
  const created = await (await api('drive/v3/files?fields=id', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: DRIVE_FOLDER_NAME, mimeType: FOLDER_MIME })
  })).json();
  folderId = created.id;
  if (!folderId) {
    throw new Error('не удалось создать папку index.life в Google Drive');
  }
  return folderId;
}

let index = null; // name -> fileId
let tags = null;  // name -> change tag (md5, else modifiedTime)
async function refreshIndex() {
  const fid = await getFolderId();
  const q = encodeURIComponent(`'${escapeQ(fid)}' in parents and trashed=false`);
  // md5Checksum and modifiedTime cost nothing extra here and let the engine
  // skip downloading blobs it has already merged.
  const data = await (await api(
    `drive/v3/files?q=${q}&fields=files(id,name,md5Checksum,modifiedTime)`
    + '&spaces=drive&pageSize=1000'
  )).json();
  const files = data.files || [];
  index = new Map(files.map((f) => [f.name, f.id]));
  tags = new Map(files.map((f) => [f.name, f.md5Checksum || f.modifiedTime || null]));
  return index;
}

// ── the transport ────────────────────────────────────────────────────
export class GoogleDriveTransport {
  // Interactive sign-in / consent. Call from a click handler.
  async connect() {
    await getToken(true);
    await refreshIndex();
  }

  isConnected() {
    return cachedToken() != null;
  }

  async list() {
    await refreshIndex();
    return [...index.keys()];
  }

  async listMeta() {
    await refreshIndex();
    return [...index.keys()].map((name) => ({ name, tag: tags.get(name) || null }));
  }

  async get(name) {
    if (!index) await refreshIndex();
    const id = index.get(name);
    if (!id) return null;
    return (await api(`drive/v3/files/${id}?alt=media`)).text();
  }

  async put(name, text) {
    if (!index) await refreshIndex();
    const id = index.get(name);
    if (id) {
      await api(`upload/drive/v3/files/${id}?uploadType=media`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: text
      });
      return;
    }
    const fid = await getFolderId();
    const created = await (await api('drive/v3/files?fields=id', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, parents: [fid], mimeType: 'application/json' })
    })).json();
    await api(`upload/drive/v3/files/${created.id}?uploadType=media`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: text
    });
    index.set(name, created.id);
  }

  async delete(name) {
    if (!index) await refreshIndex();
    const id = index.get(name);
    if (!id) return;
    await api(`drive/v3/files/${id}`, { method: 'DELETE' });
    index.delete(name);
  }
}
