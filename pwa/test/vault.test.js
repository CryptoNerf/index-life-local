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
