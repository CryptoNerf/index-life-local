// listDevices — the "did my phone and PC actually meet?" panel. Reads only
// plaintext headers (envelope routing header / legacy snapshot fields), so
// it must work before the vault is unlocked and never throw on junk.

import { describe, it, expect, beforeEach } from 'vitest';
import { listDevices } from '../src/lib/app-sync.js';
import { MemoryTransport } from '../src/lib/transport.js';

// listDevices reads localStorage (own/peer display names) — shim it for node.
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
});

const envelope = (device, writtenAt) => JSON.stringify({
  env: 1, alg: 'xchacha20poly1305', device,
  snapshot_version: 4, written_at: writtenAt,
  nonce: 'AAAA', ct: 'AAAA'
});

const plain = (device, generatedAt) => JSON.stringify({
  snapshot_version: 4, device_id: device,
  generated_at: generatedAt, mood_entries: []
});

describe('listDevices', () => {
  it('lists self and peers from headers only, self first', async () => {
    const t = new MemoryTransport({
      'device_me.json': envelope('phone-1', '2026-07-05T09:00:00Z'),
      'device_pc.json': plain('pc-1', '2026-07-04T10:00:00'),   // desktop naive UTC
      'vault.json': '{}',
      'unrelated.txt': 'x'
    });

    const devices = await listDevices(t, 'phone-1');

    expect(devices).toHaveLength(2);
    expect(devices[0].self).toBe(true);
    expect(devices[0].encrypted).toBe(true);
    expect(devices[1].id).toBe('pc-1');
    // naive desktop timestamp parsed as UTC, not local
    expect(devices[1].at).toBe(Date.parse('2026-07-04T10:00:00Z'));
  });

  it('sorts peers by recency', async () => {
    const t = new MemoryTransport({
      'device_a.json': envelope('old-peer', '2026-07-01T00:00:00Z'),
      'device_b.json': envelope('new-peer', '2026-07-05T00:00:00Z')
    });

    const devices = await listDevices(t, 'phone-1');

    expect(devices.map((d) => d.id)).toEqual(['new-peer', 'old-peer']);
  });

  it('skips junk blobs without throwing', async () => {
    const t = new MemoryTransport({ 'device_broken.json': '{nope' });
    expect(await listDevices(t, 'phone-1')).toEqual([]);
  });
});

// ── display names (device_name in the snapshot body) ─────────────────

const plainNamed = (device, name) => JSON.stringify({
  snapshot_version: 4, device_id: device, device_name: name,
  generated_at: '2026-07-05T10:00:00Z', mood_entries: []
});

describe('device display names', () => {
  it('plaintext peers show their embedded name directly', async () => {
    const t = new MemoryTransport({ 'device_pc.json': plainNamed('pc-1', 'MacBook-Pro') });

    const devices = await listDevices(t, 'phone-1');

    expect(devices[0].name).toBe('MacBook-Pro');
  });

  it('encrypted peers use the merge-time cache', async () => {
    localStorage.setItem('indexlife:peer-name:pc-1', 'Рабочий ПК');
    const t = new MemoryTransport({
      'device_pc.json': envelope('pc-1', '2026-07-05T09:00:00Z')
    });

    const devices = await listDevices(t, 'phone-1');

    expect(devices[0].name).toBe('Рабочий ПК');
    expect(devices[0].encrypted).toBe(true);
  });
});
