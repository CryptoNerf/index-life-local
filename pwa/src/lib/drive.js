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

// Get a valid access token. `interactive` triggers the consent popup (must be
// called from a user gesture the first time); otherwise it refreshes silently.
async function getToken(interactive) {
  await loadGIS();
  if (!interactive && accessToken && Date.now() < tokenExpiry - 60000) {
    return accessToken;
  }
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
      accessToken = resp.access_token;
      tokenExpiry = Date.now() + (resp.expires_in || 3600) * 1000;
      resolve(accessToken);
    };
    try {
      tokenClient.requestAccessToken({ prompt: interactive ? 'consent' : '' });
    } catch (e) {
      reject(e);
    }
  });
}

// ── Drive REST helper ────────────────────────────────────────────────
async function api(path, opts = {}) {
  const token = await getToken(false);
  const resp = await fetch(`https://www.googleapis.com/${path}`, {
    ...opts,
    headers: { Authorization: `Bearer ${token}`, ...(opts.headers || {}) }
  });
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
async function refreshIndex() {
  const fid = await getFolderId();
  const q = encodeURIComponent(`'${escapeQ(fid)}' in parents and trashed=false`);
  const data = await (await api(
    `drive/v3/files?q=${q}&fields=files(id,name)&spaces=drive&pageSize=1000`
  )).json();
  index = new Map((data.files || []).map((f) => [f.name, f.id]));
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
    return accessToken != null && Date.now() < tokenExpiry;
  }

  async list() {
    await refreshIndex();
    return [...index.keys()];
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
