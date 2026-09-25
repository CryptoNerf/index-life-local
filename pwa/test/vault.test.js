// PWA vault state layer (localStorage-backed). Verifies device-id persistence
// and the enable / unlock / lock state machine, including a fresh device
// joining the same vault via the shared transport.

import { describe, it, expect, beforeEach, beforeAll } from 'vitest';
import * as crypto from '../src/lib/crypto.js';
import { MemoryTransport } from '../src/lib/transport.js';
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
  globalThis.localStorage = localStorageShim(); // fresh "device" per test
});

describe('device identity', () => {
  it('is generated once and stays stable', () => {
    const id = vault.getDeviceId();
    expect(id).toBeTruthy();
    expect(vault.getDeviceId()).toBe(id);
  });
});

describe('enable / unlock / lock', () => {
  it('enable creates a vault and unlocks this device', async () => {
    const t = new MemoryTransport();
    const { recoveryKey, vaultKey } = await vault.enableEncryption(t, 'pw');
    expect(recoveryKey).toBeTruthy();
    expect(vault.isUnlocked()).toBe(true);
    expect(crypto.toHex(vault.getVaultKey())).toBe(crypto.toHex(vaultKey));
    expect(await vault.status(t)).toEqual({ enabled: true, unlocked: true, vaultInFolder: true });
  });

  it('a fresh device unlocks the same vault with the passphrase', async () => {
    const t = new MemoryTransport();
    const { vaultKey } = await vault.enableEncryption(t, 'pw');

    globalThis.localStorage = localStorageShim(); // device B
    expect(vault.isUnlocked()).toBe(false);
    const vkB = await vault.unlockWithPassphrase(t, 'pw');
    expect(crypto.toHex(vkB)).toBe(crypto.toHex(vaultKey));
    expect(vault.isUnlocked()).toBe(true);
  });

  it('the recovery key unlocks a fresh device', async () => {
    const t = new MemoryTransport();
    const { recoveryKey, vaultKey } = await vault.enableEncryption(t, 'pw');

    globalThis.localStorage = localStorageShim();
    const vk = await vault.unlockWithRecovery(t, recoveryKey);
    expect(crypto.toHex(vk)).toBe(crypto.toHex(vaultKey));
  });

  it('lock forgets the key but stays enabled', async () => {
    const t = new MemoryTransport();
    await vault.enableEncryption(t, 'pw');
    vault.lock();
    expect(vault.getVaultKey()).toBeNull();
    expect(vault.isEncryptionEnabled()).toBe(true);
    expect(vault.isUnlocked()).toBe(false);
  });

  it('enabling on an existing vault is rejected', async () => {
    const t = new MemoryTransport();
    await vault.enableEncryption(t, 'pw');
    globalThis.localStorage = localStorageShim(); // device B
    await expect(vault.enableEncryption(t, 'other')).rejects.toThrow();
  });

  it('a wrong passphrase cannot unlock', async () => {
    const t = new MemoryTransport();
    await vault.enableEncryption(t, 'right');
    globalThis.localStorage = localStorageShim();
    await expect(vault.unlockWithPassphrase(t, 'wrong')).rejects.toThrow();
  });
});

// A vault.json can outlive the key it wraps: two devices each set up
// encryption, then paired, and the folder kept the vault nobody seals with.
// The passphrase still opens it — it just yields the wrong key. Unlocking
// must notice, instead of sealing this device's data where nobody can read
// it and reading nobody (what a real phone did after a change of address).
describe('unlocking checks the key against the other devices', () => {
  const randomVk = () => globalThis.crypto.getRandomValues(new Uint8Array(32));

  async function peerWrites(t, vk, device) {
    const text = crypto.sealEnvelope(
      { snapshot_version: 4, device_id: device, mood_entries: [] }, vk,
      { device, snapshotVersion: 4, writtenAt: '2026-09-25T00:00:00Z',
        nonce: crypto.randomNonce() });
    await t.put(`device_${device}.json`, text);
  }

  async function folderWithVault() {
    const t = new MemoryTransport();
    const made = await vault.enableEncryption(t, 'pw-12345');
    globalThis.localStorage = localStorageShim();   // the joining device
    return { t, ...made };
  }

  it('refuses a passphrase whose vault the peers do not use', async () => {
    const { t } = await folderWithVault();
    await peerWrites(t, randomVk(), 'desktop');       // sealed with another key

    await expect(vault.unlockWithPassphrase(t, 'pw-12345'))
      .rejects.toMatchObject({ code: 'vault-stale' });
    expect(vault.isUnlocked()).toBe(false);
    expect(vault.isEncryptionEnabled()).toBe(false);
  });

  it('refuses the recovery key for the same reason', async () => {
    const { t, recoveryKey } = await folderWithVault();
    await peerWrites(t, randomVk(), 'desktop');

    await expect(vault.unlockWithRecovery(t, recoveryKey))
      .rejects.toMatchObject({ code: 'vault-stale' });
    expect(vault.isUnlocked()).toBe(false);
  });

  it('unlocks when a peer seals with the vault key', async () => {
    const { t, vaultKey } = await folderWithVault();
    await peerWrites(t, vaultKey, 'desktop');

    await vault.unlockWithPassphrase(t, 'pw-12345');
    expect(crypto.toHex(vault.getVaultKey())).toBe(crypto.toHex(vaultKey));
  });

  it('one retired device with an old key does not veto the right one', async () => {
    const { t, vaultKey } = await folderWithVault();
    await peerWrites(t, randomVk(), 'old-phone');
    await peerWrites(t, vaultKey, 'desktop');

    await vault.unlockWithPassphrase(t, 'pw-12345');
    expect(vault.isUnlocked()).toBe(true);
  });

  it('unlocks a folder nobody has written to yet', async () => {
    const { t } = await folderWithVault();
    await vault.unlockWithPassphrase(t, 'pw-12345');
    expect(vault.isUnlocked()).toBe(true);
  });

  it("ignores this device's own blob, sealed with a key it is replacing", async () => {
    const { t, vaultKey } = await folderWithVault();
    await peerWrites(t, randomVk(), vault.getDeviceId());   // our own, stale
    await peerWrites(t, vaultKey, 'desktop');

    await vault.unlockWithPassphrase(t, 'pw-12345');
    expect(vault.isUnlocked()).toBe(true);
  });

  it('a wrong passphrase is still just a wrong passphrase', async () => {
    const { t } = await folderWithVault();
    await expect(vault.unlockWithPassphrase(t, 'not-it'))
      .rejects.not.toMatchObject({ code: 'vault-stale' });
    expect(vault.isUnlocked()).toBe(false);
  });
});
