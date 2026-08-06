// Signing in must always end — in a token or in a message.
//
// The old flow settled on exactly one event: the callback page's postMessage
// arriving. A closed window, a browser that gives the callback no opener, or
// simply walking away left the promise pending forever, with the connect
// button stuck on "Подключение…" and no way out but restarting the app.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { YandexDiskTransport, clearToken } from '../src/lib/yandex.js';

const RESULT_KEY = 'indexlife:yandex-oauth-result';
const TOKEN_KEY = 'indexlife:yandex-token';

let listeners;
let popup;

function lsShim() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k)
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  globalThis.localStorage = lsShim();
  listeners = new Set();
  popup = { closed: false, close: () => { popup.closed = true; } };
  globalThis.location = { origin: 'https://index.life' };
  globalThis.window = {
    open: () => popup,
    addEventListener: (t, fn) => t === 'message' && listeners.add(fn),
    removeEventListener: (t, fn) => listeners.delete(fn)
  };
});

afterEach(() => {
  vi.useRealTimers();
});

const deliver = (data) =>
  listeners.forEach((fn) => fn({ origin: 'https://index.life', data }));

const storeResult = (msg, at = Date.now()) =>
  localStorage.setItem(RESULT_KEY, JSON.stringify({ at, msg }));

describe('Yandex sign-in', () => {
  it('resolves and keeps the token when the callback posts one', async () => {
    const p = new YandexDiskTransport().connect();
    deliver({ source: 'yandex-oauth', access_token: 'tok-1', expires_in: 3600 });
    await p;

    expect(new YandexDiskTransport().isConnected()).toBe(true);
    expect(JSON.parse(localStorage.getItem(TOKEN_KEY)).token).toBe('tok-1');
  });

  it('accepts the token through storage when there is no opener to post to', async () => {
    const p = new YandexDiskTransport().connect();
    storeResult({ source: 'yandex-oauth', access_token: 'tok-2', expires_in: 3600 });
    await vi.advanceTimersByTimeAsync(500);   // the poll picks it up
    await p;

    expect(new YandexDiskTransport().isConnected()).toBe(true);
  });

  it('rejects when the sign-in window is closed with nothing done', async () => {
    const p = new YandexDiskTransport().connect();
    // Attach the expectation before advancing: the rejection happens inside a
    // fake-timer tick, and node flags a handler attached after the fact.
    const rejected = expect(p).rejects.toThrow(/закрыт/i);
    popup.closed = true;
    await vi.advanceTimersByTimeAsync(400 + 700);
    await rejected;
  });

  it('still takes a result that lands just as the window closes', async () => {
    const p = new YandexDiskTransport().connect();
    popup.closed = true;
    storeResult({ source: 'yandex-oauth', access_token: 'tok-3', expires_in: 3600 });
    await vi.advanceTimersByTimeAsync(400 + 700);
    await p;
    expect(new YandexDiskTransport().isConnected()).toBe(true);
  });

  it('gives up after three minutes instead of waiting forever', async () => {
    const p = new YandexDiskTransport().connect();
    const rejected = expect(p).rejects.toThrow(/не завершён/i);
    await vi.advanceTimersByTimeAsync(3 * 60 * 1000 + 10);
    await rejected;
  });

  it('reports a blocked popup in words the user can act on', async () => {
    globalThis.window.open = () => null;
    await expect(new YandexDiskTransport().connect()).rejects.toThrow(/всплывающие окна/i);
  });

  it('passes an OAuth error through', async () => {
    const p = new YandexDiskTransport().connect();
    deliver({ source: 'yandex-oauth', error: 'access_denied' });
    await expect(p).rejects.toThrow('access_denied');
  });

  it('ignores a result left over from an earlier attempt', async () => {
    storeResult({ source: 'yandex-oauth', access_token: 'stale' }, Date.now() - 60_000);
    const p = new YandexDiskTransport().connect();
    await vi.advanceTimersByTimeAsync(1000);
    // the stale row must not resolve the new attempt
    deliver({ source: 'yandex-oauth', access_token: 'fresh', expires_in: 3600 });
    await p;
    expect(JSON.parse(localStorage.getItem(TOKEN_KEY)).token).toBe('fresh');
  });

  it('ignores messages from another origin', async () => {
    const p = new YandexDiskTransport().connect();
    const rejected = expect(p).rejects.toThrow(/не завершён/i);
    listeners.forEach((fn) => fn({
      origin: 'https://evil.example',
      data: { source: 'yandex-oauth', access_token: 'attacker' }
    }));
    await vi.advanceTimersByTimeAsync(3 * 60 * 1000 + 10);
    await rejected;
    expect(localStorage.getItem(TOKEN_KEY)).toBe(null);
  });
});
