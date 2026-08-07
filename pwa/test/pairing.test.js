// Device pairing on the PWA side: the Vault Key travels as a grouped-base32
// code (same rendering as the recovery key) with a versioned QR prefix.
// Must round-trip with the desktop's sync_vault pairing block.

import { describe, it, expect, beforeEach, beforeAll } from 'vitest';
import * as crypto from '../src/lib/crypto.js';
import * as vault from '../src/lib/vault.js';

function localStorageShim() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k)
  };
}

beforeAll(async () => {
  await crypto.ready;
});

beforeEach(() => {
  globalThis.localStorage = localStorageShim();
});

const randomVk = () => globalThis.crypto.getRandomValues(new Uint8Array(32));

describe('pairing code', () => {
  it('adopting a bare grouped code unlocks the vault with that key', async () => {
    const vk = randomVk();
    await vault.adoptPairingCode(crypto.encodeRecoveryKey(vk));

    expect(vault.isUnlocked()).toBe(true);
    expect(Array.from(vault.getVaultKey())).toEqual(Array.from(vk));
  });

  it('accepts the QR payload with the versioned prefix', async () => {
    const vk = randomVk();
    await vault.adoptPairingCode(vault.PAIRING_PREFIX + crypto.encodeRecoveryKey(vk));
    expect(Array.from(vault.getVaultKey())).toEqual(Array.from(vk));
  });

  it('is tolerant of spacing and case, like the recovery input', async () => {
    const vk = randomVk();
    const sloppy = crypto.encodeRecoveryKey(vk).toLowerCase().replace(/-/g, ' ');
    await vault.adoptPairingCode(sloppy);
    expect(Array.from(vault.getVaultKey())).toEqual(Array.from(vk));
  });

  it('rejects garbage and wrong-length codes without unlocking', async () => {
    for (const bad of ['', 'not-a-code', 'AAAAA-BBBBB']) {
      await expect(vault.adoptPairingCode(bad)).rejects.toThrow();
    }
    expect(vault.isUnlocked()).toBe(false);
  });

  it('shows a code only while unlocked (phone → PC direction)', async () => {
    expect(vault.getPairingCode()).toBe(null);
    expect(vault.getPairingPayload()).toBe(null);

    const vk = randomVk();
    await vault.adoptPairingCode(crypto.encodeRecoveryKey(vk));

    const code = vault.getPairingCode();
    expect(code).toBe(crypto.encodeRecoveryKey(vk));
    expect(vault.getPairingPayload()).toBe(vault.PAIRING_PREFIX + code);
  });
});

// ── verification against the folder (P1: mirror of the desktop rule) ──

import { MemoryTransport } from '../src/lib/transport.js';
import { pullPeers } from '../src/lib/sync.js';

const sealWith = (vk, device = 'pc-1') => crypto.sealEnvelope(
  { snapshot_version: 4, device_id: device, mood_entries: [] },
  vk, { device, snapshotVersion: 4, writtenAt: '2026-07-05T00:00:00Z' }
);

describe('pairing verification against the cloud folder', () => {
  it('adopts when the folder envelope decrypts with the code', async () => {
    const vk = randomVk();
    const t = new MemoryTransport({ 'device_pc-1.json': sealWith(vk) });

    await vault.adoptPairingCode(crypto.encodeRecoveryKey(vk), t);

    expect(vault.isUnlocked()).toBe(true);
  });

  it('rejects a code that does not match the folder (wrong cloud/account)', async () => {
    const t = new MemoryTransport({ 'device_pc-1.json': sealWith(randomVk()) });

    await expect(
      vault.adoptPairingCode(crypto.encodeRecoveryKey(randomVk()), t)
    ).rejects.toThrow(/не подходит/);
    expect(vault.isUnlocked()).toBe(false);
  });

  it('adopts unverified when the folder has nothing encrypted', async () => {
    const vk = randomVk();
    const t = new MemoryTransport({ 'notes.txt': 'x' });

    await vault.adoptPairingCode(crypto.encodeRecoveryKey(vk), t);

    expect(vault.isUnlocked()).toBe(true);
  });
});

// ── unreadable peers are counted, never silently dropped (P3) ─────────

describe('pullPeers stats', () => {
  it('counts key-mismatched envelopes and junk blobs', async () => {
    const vkMine = randomVk();
    const vkOther = randomVk();
    const t = new MemoryTransport({
      'device_good.json': sealWith(vkMine, 'good-peer'),
      'device_alien.json': sealWith(vkOther, 'alien-peer'),
      'device_junk.json': '{broken'
    });

    const stats = { locked: 0, errors: 0 };
    const merged = await pullPeers(t, 'phone-1', [], vkMine, stats);

    expect(merged).toEqual([]);            // good peer had no entries
    expect(stats.locked).toBe(1);          // the alien envelope
    expect(stats.errors).toBe(1);          // the junk blob
  });

  it('counts every encrypted peer as locked when the vault key is missing', async () => {
    const t = new MemoryTransport({ 'device_pc.json': sealWith(randomVk()) });

    const stats = { locked: 0, errors: 0 };
    await pullPeers(t, 'phone-1', [], null, stats);

    expect(stats.locked).toBe(1);
  });
});

// ── peer names travel inside the (decrypted) snapshot body ───────────

describe('peer name collection on pull', () => {
  it('stats.names carries device_name from a decrypted peer snapshot', async () => {
    const vk = randomVk();
    const text = crypto.sealEnvelope(
      { snapshot_version: 4, device_id: 'pc-1', device_name: 'MacBook-Pro',
        mood_entries: [] },
      vk, { device: 'pc-1', snapshotVersion: 4, writtenAt: '2026-07-05T00:00:00Z' }
    );
    const t = new MemoryTransport({ 'device_pc-1.json': text });

    const stats = { locked: 0, errors: 0 };
    await pullPeers(t, 'phone-1', [], vk, stats);

    expect(stats.names).toEqual({ 'pc-1': 'MacBook-Pro' });
  });
});

// ── Pairing when both devices are already in the folder ──────────────
// The case that deadlocked a real setup: the phone and the computer had each
// set up encryption for the same cloud folder separately, so each held a key
// the other could not read. Verification tested whatever blob came first —
// including the phone's own, sealed with the very key being replaced — and
// treated one failure as proof of a bad code. Scanning a perfectly good QR
// answered "the code is wrong", in both directions.

describe('adopting a code while stale blobs sit in the folder', () => {
  const OURS = new Uint8Array(32).fill(2);
  const THEIRS = new Uint8Array(32).fill(1);

  const sealed = (vk, device) => crypto.sealEnvelope(
    { snapshot_version: 4, device_id: device,
      generated_at: '2026-08-07T14:25:05.492Z', mood_entries: [] },
    vk, { device, snapshotVersion: 4, writtenAt: '2026-08-07T14:25:05.492Z' });

  it('ignores our own snapshot, which can only fail', async () => {
    await crypto.ready;
    const own = vault.getDeviceId();
    vault.cacheVaultKey?.(OURS);
    const t = new MemoryTransport({
      [`device_${own}.json`]: sealed(OURS, own),
      'device_dev-desktop.json': sealed(THEIRS, 'dev-desktop')
    });

    await vault.adoptPairingCode(crypto.encodeRecoveryKey(THEIRS), t);
    expect(vault.getVaultKey()).toEqual(THEIRS);
  });

  it('keeps looking past a third device left on an old key', async () => {
    await crypto.ready;
    const t = new MemoryTransport({
      'device_aaa-orphan.json': sealed(new Uint8Array(32).fill(9), 'dev-orphan'),
      'device_dev-desktop.json': sealed(THEIRS, 'dev-desktop')
    });

    await vault.adoptPairingCode(crypto.encodeRecoveryKey(THEIRS), t);
    expect(vault.getVaultKey()).toEqual(THEIRS);
  });

  it('adopts unverified when only our own snapshot is there', async () => {
    await crypto.ready;
    const own = vault.getDeviceId();
    const t = new MemoryTransport({ [`device_${own}.json`]: sealed(OURS, own) });

    await vault.adoptPairingCode(crypto.encodeRecoveryKey(THEIRS), t);
    expect(vault.getVaultKey()).toEqual(THEIRS);
  });

  it('still refuses a code that opens nothing in the folder', async () => {
    await crypto.ready;
    const t = new MemoryTransport({
      'device_dev-desktop.json': sealed(THEIRS, 'dev-desktop')
    });

    await expect(
      vault.adoptPairingCode(crypto.encodeRecoveryKey(new Uint8Array(32).fill(7)), t)
    ).rejects.toThrow(/не подходит/i);
  });
});
