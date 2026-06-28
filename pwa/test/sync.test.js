// Sync engine: a two-device encrypted round-trip through one shared transport
// (the JS twin of the desktop's test_sync_vault.py). Proves zero-knowledge (the
// note text never appears on the "disk" blob), dual-read migration, and the
// fail-safe (a locked vault refuses to push).

import { describe, it, expect, beforeAll } from 'vitest';
import * as crypto from '../src/lib/crypto.js';
import { buildSnapshot } from '../src/lib/snapshot.js';
import { MemoryTransport } from '../src/lib/transport.js';
import { pullPeers, pushSnapshot, VAULT_FILENAME } from '../src/lib/sync.js';

const CHEAP = [2, 65536]; // fast Argon2id for tests
const entry = (date, over = {}) => ({
  uuid: `u-${date}`, date, rating: 7, note: 'x',
  created_at: '2025-01-01T00:00:00', updated_at: '2025-01-01T00:00:00',
  device_id: 'dev-a', deleted: false, ...over
});

beforeAll(async () => {
  await crypto.ready;
});

describe('encrypted round-trip between two devices', () => {
  it('A pushes ciphertext only; B unlocks and reads it', async () => {
    const t = new MemoryTransport();
    const { vault, vaultKey: vkA } = crypto.createVault('open sesame', ...CHEAP);
    await t.put(VAULT_FILENAME, JSON.stringify(vault));

    await pushSnapshot(t, 'dev-a', [entry('2026-06-20', { note: 'a private confession 42' })], vkA);

    const blob = await t.get('device_dev-a.json');
    expect(blob).not.toContain('a private confession 42'); // zero-knowledge on disk
    expect(JSON.parse(blob).ct).toBeTruthy();

    const vkB = crypto.unwrapWithPassphrase(vault, 'open sesame');
    const merged = await pullPeers(t, 'dev-b', [], vkB);
    expect(merged).toHaveLength(1);
    expect(merged[0].note).toBe('a private confession 42');
  });
});

describe('fail-safe & migration', () => {
  it('a locked vault refuses to push (no plaintext leak)', async () => {
    const t = new MemoryTransport();
    await expect(pushSnapshot(t, 'dev-a', [entry('2026-06-20')], null)).rejects.toThrow();
    expect(await t.list()).toHaveLength(0);
  });

  it('a locked peer (no key) skips encrypted blobs instead of failing', async () => {
    const t = new MemoryTransport();
    const { vaultKey: vk } = crypto.createVault('pw', ...CHEAP);
    await pushSnapshot(t, 'dev-a', [entry('2026-06-20')], vk);
    const merged = await pullPeers(t, 'dev-b', [], null);
    expect(merged).toHaveLength(0);
  });

  it('dual-read: a legacy plaintext desktop snapshot is still merged', async () => {
    const t = new MemoryTransport();
    const plain = buildSnapshot([entry('2026-06-20', { note: 'plaintext day' })], 'dev-a');
    await t.put('device_dev-a.json', JSON.stringify(plain));
    const { vaultKey: vk } = crypto.createVault('pw', ...CHEAP);
    const merged = await pullPeers(t, 'dev-b', [], vk);
    expect(merged.find((e) => e.date === '2026-06-20')?.note).toBe('plaintext day');
  });
});

describe('listing hygiene', () => {
  it('does not merge vault.json or our own blob', async () => {
    const t = new MemoryTransport();
    const { vault, vaultKey: vk } = crypto.createVault('pw', ...CHEAP);
    await t.put(VAULT_FILENAME, JSON.stringify(vault));
    await pushSnapshot(t, 'dev-a', [entry('2026-06-20')], vk);
    // same device pulls: vault.json skipped, own blob skipped → nothing merged
    const merged = await pullPeers(t, 'dev-a', [], vk);
    expect(merged).toHaveLength(0);
  });
});
