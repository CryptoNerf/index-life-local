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

// Where the callback page leaves the result when it cannot postMessage.
const RESULT_KEY = 'indexlife:yandex-oauth-result';
// Long enough for a password plus two-factor, short enough that a dead flow
// does not leave the button spinning forever.
const AUTH_TIMEOUT_MS = 3 * 60 * 1000;
const POLL_MS = 400;

function takeStoredResult(startedAt) {
  try {
    const raw = localStorage.getItem(RESULT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    localStorage.removeItem(RESULT_KEY);
    // Ignore a leftover from an earlier attempt.
    if (!parsed || !parsed.at || parsed.at < startedAt) return null;
    return parsed.msg || null;
  } catch {
    return null;
  }
}

// Interactive sign-in: open Yandex OAuth in a popup; the callback page hands
// the token back by postMessage, or through localStorage when it has no
// opener to talk to. Must be called from a user gesture (popups).
//
// Every ending settles the promise. It used to have exactly one: the message
// arriving. A closed popup, a browser that gives the callback no opener, or
// simply walking away left it pending forever — the connect button stayed on
// "Подключение…" with no way out but restarting the app.
function authorize() {
  return new Promise((resolve, reject) => {
    const startedAt = Date.now();
    try { localStorage.removeItem(RESULT_KEY); } catch { /* ignore */ }

    const redirect = `${location.origin}/yandex-callback.html`;
    const url = 'https://oauth.yandex.ru/authorize?response_type=token'
      + `&client_id=${YANDEX_CLIENT_ID}`
      + `&redirect_uri=${encodeURIComponent(redirect)}`;
    const popup = window.open(url, 'yandex-oauth', 'width=640,height=720');
    if (!popup) {
      return reject(new Error(
        'Браузер заблокировал окно входа Яндекса — разрешите всплывающие окна и попробуйте снова'
      ));
    }

    let settled = false;
    function finish(fn, arg) {
      if (settled) return;
      settled = true;
      clearInterval(poll);
      clearTimeout(timer);
      window.removeEventListener('message', onMessage);
      try { popup.close(); } catch { /* already gone */ }
      fn(arg);
    }

    function accept(msg) {
      if (msg?.error) return finish(reject, new Error(msg.error));
      if (!msg?.access_token) {
        return finish(reject, new Error('Яндекс не вернул токен — попробуйте ещё раз'));
      }
      saveToken(msg.access_token, msg.expires_in);
      finish(resolve, msg.access_token);
    }

    function onMessage(e) {
      if (e.origin !== location.origin || e.data?.source !== 'yandex-oauth') return;
      accept(e.data);
    }
    window.addEventListener('message', onMessage);

    const poll = setInterval(() => {
      const stored = takeStoredResult(startedAt);
      if (stored) return accept(stored);
      if (popup.closed) {
        // Give the callback a moment to write its result before deciding the
        // user simply closed the window.
        setTimeout(() => {
          const late = takeStoredResult(startedAt);
          if (late) accept(late);
          else finish(reject, new Error('Окно входа закрыто — вход не завершён'));
        }, 600);
      }
    }, POLL_MS);

    const timer = setTimeout(() => {
      finish(reject, new Error('Вход в Яндекс не завершён — попробуйте ещё раз'));
    }, AUTH_TIMEOUT_MS);
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
    return (await this.listMeta()).map((i) => i.name);
  }

  // md5 (and modified as a fallback) ride along in the same listing, so the
  // engine can skip peer blobs it has already merged.
  async listMeta() {
    try {
      const fields = '_embedded.items.name,_embedded.items.md5,_embedded.items.modified';
      const data = await (await api(
        `/resources?path=${encodeURIComponent(APP)}&limit=1000`
        + `&fields=${encodeURIComponent(fields)}`
      )).json();
      return (data._embedded?.items || []).map((i) => ({
        name: i.name, tag: i.md5 || i.modified || null
      }));
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
