// The Google session must survive a reload.
//
// Regression: the access token lived only in a module variable, so every
// reload (and iOS unloads a backgrounded PWA readily) signed the phone out.
// The sync that runs on open then failed silently — the app looked connected
// and quietly stopped receiving the desktop's entries.

import { describe, it, expect, beforeEach } from 'vitest';
import { GoogleDriveTransport, clearToken } from '../src/lib/drive.js';

const TOKEN_KEY = 'indexlife:google-token';

function lsShim() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k)
  };
}

beforeEach(() => {
  globalThis.localStorage = lsShim();
  clearToken(); // drop whatever a previous test left in module memory
});

const transport = () => new GoogleDriveTransport();

describe('Google token persistence', () => {
  it('reports disconnected with nothing stored', () => {
    expect(transport().isConnected()).toBe(false);
  });

  it('picks a stored token up after a reload', () => {
    localStorage.setItem(TOKEN_KEY, JSON.stringify({
      token: 'ya29.stored', expiry: Date.now() + 30 * 60 * 1000
    }));
    // A fresh transport, as after a page load: no in-memory state at all.
    expect(transport().isConnected()).toBe(true);
  });

  it('treats an expired token as signed out', () => {
    localStorage.setItem(TOKEN_KEY, JSON.stringify({
      token: 'ya29.old', expiry: Date.now() - 1000
    }));
    expect(transport().isConnected()).toBe(false);
  });

  it('refuses a token inside the one-minute safety margin', () => {
    // Using a token that dies mid-request would surface as a bare 401.
    localStorage.setItem(TOKEN_KEY, JSON.stringify({
      token: 'ya29.expiring', expiry: Date.now() + 30 * 1000
    }));
    expect(transport().isConnected()).toBe(false);
  });

  it('clearToken erases the stored token, not just the cached one', () => {
    localStorage.setItem(TOKEN_KEY, JSON.stringify({
      token: 'ya29.stored', expiry: Date.now() + 30 * 60 * 1000
    }));
    expect(transport().isConnected()).toBe(true);
    clearToken();
    expect(localStorage.getItem(TOKEN_KEY)).toBe(null);
    expect(transport().isConnected()).toBe(false);
  });

  it('survives junk in storage instead of throwing', () => {
    localStorage.setItem(TOKEN_KEY, 'not json at all');
    expect(transport().isConnected()).toBe(false);
  });

  it('a background call without a token asks the UI to re-auth', async () => {
    // No token and no user gesture: the transport must say 'auth-expired'
    // (which the UI maps to "sign in again") rather than opening a popup
    // that the browser will block and swallow.
    await expect(transport().list()).rejects.toThrow('auth-expired');
  });
});
