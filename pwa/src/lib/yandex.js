// Yandex.Disk transport — implements the SyncTransport interface over the
// Yandex.Disk REST API (cloud-api.yandex.net), with OAuth via the implicit
// token flow (popup → yandex-callback.html). Scope cloud_api:disk.app_folder,
// so blobs live in the app's own folder (path prefix `app:/`). CORS is enabled
// on the API (verified), so the browser talks to it directly — no proxy.
//
// Reachable in Russia without a VPN, unlike Google. Tokens are long-lived
// (~1 year), kept in localStorage so they survive reloads.

import { YANDEX_CLIENT_ID } from './config.js';

const API = 'https://cloud-api.yandex.net/v1/disk';
const APP = 'app:/';
const TOKEN_KEY = 'indexlife:yandex-token';

function loadToken() {
  try {
    const t = JSON.parse(localStorage.getItem(TOKEN_KEY) || 'null');
    return t && Date.now() < t.expiry ? t.token : null;
  } catch {
    return null;
  }
}

function saveToken(token, expiresIn) {
  localStorage.setItem(TOKEN_KEY, JSON.stringify({
    token,
    expiry: Date.now() + (Number(expiresIn) || 31536000) * 1000
  }));
}

// Sign out on this device. Without this, "switch cloud" kept the year-long
// token and silently reused the previous Yandex account.
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// Interactive sign-in: open Yandex OAuth in a popup; the callback page posts
// the token back. Must be called from a user gesture (popups).
function authorize() {
  return new Promise((resolve, reject) => {
    const redirect = `${location.origin}/yandex-callback.html`;
    const url = 'https://oauth.yandex.ru/authorize?response_type=token'
      + `&client_id=${YANDEX_CLIENT_ID}`
      + `&redirect_uri=${encodeURIComponent(redirect)}`;
    const popup = window.open(url, 'yandex-oauth', 'width=640,height=720');
    if (!popup) return reject(new Error('Браузер заблокировал окно входа Яндекса'));

    function onMessage(e) {
      if (e.origin !== location.origin || e.data?.source !== 'yandex-oauth') return;
      window.removeEventListener('message', onMessage);
      try { popup.close(); } catch {}
      if (e.data.error) return reject(new Error(e.data.error));
      saveToken(e.data.access_token, e.data.expires_in);
      resolve(e.data.access_token);
    }
    window.addEventListener('message', onMessage);
  });
}

async function api(path, opts = {}) {
  const token = loadToken();
  if (!token) throw new Error('not-connected');
  const resp = await fetch(API + path, {
    ...opts,
    headers: { Authorization: `OAuth ${token}`, ...(opts.headers || {}) }
  });
  if (resp.status === 401) {
    // Token revoked/expired server-side: drop it and tell the UI to offer
    // a re-login instead of failing every background sync silently.
    clearToken();
    throw new Error('auth-expired');
  }
  if (!resp.ok) throw new Error(`Yandex ${resp.status}: ${await resp.text()}`);
  return resp;
}

const is404 = (e) => String(e?.message || e).includes('404');
const at = (name) => encodeURIComponent(APP + name);

export class YandexDiskTransport {
  async connect() {
    await authorize();
  }

  isConnected() {
    return loadToken() != null;
  }

  async list() {
    try {
      const data = await (await api(
        `/resources?path=${encodeURIComponent(APP)}&limit=1000`
        + `&fields=${encodeURIComponent('_embedded.items.name')}`
      )).json();
      return (data._embedded?.items || []).map((i) => i.name);
    } catch (e) {
      if (is404(e)) return []; // app folder not created yet
      throw e;
    }
  }

  async get(name) {
    let href;
    try {
      href = (await (await api(`/resources/download?path=${at(name)}`)).json()).href;
    } catch (e) {
      if (is404(e)) return null;
      throw e;
    }
    const resp = await fetch(href); // temporary signed URL, no auth header
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error(`Yandex download ${resp.status}`);
    return resp.text();
  }

  async put(name, text) {
    const href = (await (await api(
      `/resources/upload?path=${at(name)}&overwrite=true`
    )).json()).href;
    const resp = await fetch(href, { method: 'PUT', body: text });
    if (!resp.ok) throw new Error(`Yandex upload ${resp.status}`);
  }

  async delete(name) {
    try {
      await api(`/resources?path=${at(name)}&permanently=true`, { method: 'DELETE' });
    } catch (e) {
      if (!is404(e)) throw e;
    }
  }
}
