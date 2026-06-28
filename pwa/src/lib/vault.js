// PWA vault state — the device-local layer between crypto.js and the sync
// engine, mirroring the desktop app/sync_vault.py. The Vault Key and the
// enabled flag live in localStorage (device-local, never synced — like the
// desktop's sync_meta), so the key never leaves the phone. The encrypted
// cloud holds only ciphertext + the wrapped-key vault.json.

import * as crypto from './crypto.js';
import { VAULT_FILENAME } from './sync.js';

const DEVICE_KEY = 'indexlife:device-id';
const ENABLED_KEY = 'indexlife:enc-enabled';
const VK_KEY = 'indexlife:vault-key'; // hex

// ── device identity ──────────────────────────────────────────────────
export function getDeviceId() {
  let id = localStorage.getItem(DEVICE_KEY);
  if (!id) {
    id = globalThis.crypto.randomUUID();
    localStorage.setItem(DEVICE_KEY, id);
  }
  return id;
}

// ── local state ──────────────────────────────────────────────────────
export function isEncryptionEnabled() {
  return localStorage.getItem(ENABLED_KEY) === 'true';
}

export function getVaultKey() {
  const hex = localStorage.getItem(VK_KEY);
  if (!hex) return null;
  try {
    const vk = crypto.fromHex(hex);
    return vk.length === crypto.VK_BYTES ? vk : null;
  } catch {
    return null;
  }
}

export function isUnlocked() {
  return isEncryptionEnabled() && getVaultKey() !== null;
}

function cacheVaultKey(vk) {
  localStorage.setItem(VK_KEY, crypto.toHex(vk));
  localStorage.setItem(ENABLED_KEY, 'true');
}

// Forget the key on this device (stays enabled; sync pauses until unlocked).
export function lock() {
  localStorage.removeItem(VK_KEY);
}

// ── vault.json in the shared folder ──────────────────────────────────
export async function vaultExists(transport) {
  return (await transport.get(VAULT_FILENAME)) != null;
}

async function loadVault(transport) {
  const text = await transport.get(VAULT_FILENAME);
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// ── lifecycle ────────────────────────────────────────────────────────
export async function enableEncryption(transport, passphrase) {
  await crypto.ready;
  if (await vaultExists(transport)) {
    throw new Error('a vault already exists — unlock it instead');
  }
  const { vault, vaultKey, recoveryKey } = crypto.createVault(passphrase);
  await transport.put(VAULT_FILENAME, JSON.stringify(vault));
  cacheVaultKey(vaultKey);
  return { recoveryKey, vaultKey };
}

export async function unlockWithPassphrase(transport, passphrase) {
  await crypto.ready;
  const vault = await loadVault(transport);
  if (!vault) throw new Error('no vault.json in the cloud folder');
  const vk = crypto.unwrapWithPassphrase(vault, passphrase);
  cacheVaultKey(vk);
  return vk;
}

export async function unlockWithRecovery(transport, recoveryKey) {
  await crypto.ready;
  const vault = await loadVault(transport);
  if (!vault) throw new Error('no vault.json in the cloud folder');
  const vk = crypto.unwrapWithRecovery(vault, recoveryKey);
  cacheVaultKey(vk);
  return vk;
}

export async function status(transport) {
  return {
    enabled: isEncryptionEnabled(),
    unlocked: isUnlocked(),
    vaultInFolder: await vaultExists(transport)
  };
}
