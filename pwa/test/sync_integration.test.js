// Full local pipeline: IndexedDB ↔ vault (localStorage) ↔ sync engine ↔
// transport ↔ crypto. Uses fake-indexeddb so the real db.js runs in Node.
// This is the proof that a capture saved on the phone gets sealed, pushed,
// and that a peer's encrypted blob is merged back into IndexedDB.

import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { IDBFactory } from 'fake-indexeddb';

import * as crypto from '../src/lib/crypto.js';
import { buildSnapshot } from '../src/lib/snapshot.js';
import { MemoryTransport } from '../src/lib/transport.js';
import * as vault from '../src/lib/vault.js';
import { syncWith } from '../src/lib/app-sync.js';
import { putEntry, allEntries } from '../src/lib/db.js';

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
  globalThis.indexedDB = new IDBFactory(); // fresh DB per test
  globalThis.localStorage = localStorageShim();
});

describe('syncWith (full pipeline)', () => {
  it('seals + pushes our entry, then merges a peer blob back into IndexedDB', async () => {
    const transport = new MemoryTransport();
    await vault.enableEncryption(transport, 'pw'); // creates vault.json, caches vk
    const deviceId = vault.getDeviceId();

    await putEntry({ date: '2026-06-20', rating: 7, note: 'mine' });
    await syncWith(transport);

    // our snapshot is in the cloud as ciphertext only
    const ownBlob = await transport.get(`device_${deviceId}.json`);
    expect(ownBlob).not.toContain('mine');
    expect(JSON.parse(ownBlob).ct).toBeTruthy();

    // a peer writes an encrypted blob to the same folder (same vault key)
    const vk = vault.getVaultKey();
    const peerSnap = buildSnapshot([{
      uuid: 'p21', date: '2026-06-21', rating: 9, note: 'peer day',
      created_at: '2025-01-01T00:00:00', updated_at: '2025-01-01T00:00:00',
      device_id: 'dev-peer', deleted: false
    }], 'dev-peer');
    await transport.put('device_dev-peer.json', crypto.sealEnvelope(peerSnap, vk, {
      device: 'dev-peer', snapshotVersion: peerSnap.snapshot_version, writtenAt: peerSnap.generated_at
    }));

    await syncWith(transport);

    const all = await allEntries();
    const dates = all.map((e) => e.date).sort();
    expect(dates).toEqual(['2026-06-20', '2026-06-21']);
    expect(all.find((e) => e.date === '2026-06-21').note).toBe('peer day');
  });

  it('refuses to sync when the vault is locked', async () => {
    const transport = new MemoryTransport();
    await vault.enableEncryption(transport, 'pw');
    vault.lock();
    await expect(syncWith(transport)).rejects.toThrow(/vault-locked/);
  });

  it('refuses to sync when encryption is not enabled', async () => {
    const transport = new MemoryTransport();
    await expect(syncWith(transport)).rejects.toThrow(/encryption-not-enabled/);
  });
});
