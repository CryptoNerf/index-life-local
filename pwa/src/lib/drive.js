// Google Drive transport — implements the SyncTransport interface over the
// Drive REST API, with OAuth via Google Identity Services (GIS) token client.
// Scope: drive.file (the app sees only files it creates). Blobs live in a
// visible folder (config.DRIVE_FOLDER_NAME) so a desktop client can share it.
//
// Not unit-tested (needs a browser + real Google); the sync engine it plugs
// into is covered headless. Verify in-browser via the CloudSync UI.

import { GOOGLE_CLIENT_ID, DRIVE_FOLDER_NAME } from './config.js';

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
  return new Promise((resolve, reject) => {
    tokenClient.callback = (resp) => {
      if (resp.error) return reject(new Error(resp.error));
      saveToken(resp.access_token, resp.expires_in);
      resolve(accessToken);
    };
    try {
      // 'consent' only when we have never had a token: with an existing
      // grant Google can hand one back without a second consent screen.
      tokenClient.requestAccessToken({ prompt: loadToken() ? '' : 'consent' });
    } catch (e) {
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
async function getFolderId() {
  if (folderId) return folderId;
  const q = encodeURIComponent(
    `name='${escapeQ(DRIVE_FOLDER_NAME)}' and mimeType='${FOLDER_MIME}' and trashed=false`
  );
  const found = await (await api(`drive/v3/files?q=${q}&fields=files(id)&spaces=drive`)).json();
  if (found.files?.length) {
    folderId = found.files[0].id;
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
