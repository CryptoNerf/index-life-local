// Don't re-download a diary that hasn't changed.
//
// The phone used to fetch every peer blob and re-upload its own on every
// cycle — with a 300-entry diary that is about 800 KB per sync, roughly
// 10 MB per hour of use on mobile data, almost always with nothing new in it.
// The desktop had skipped unchanged blobs for a while; this brings the phone
// in line, using the checksum both cloud APIs already return in their
// listings.

import { describe, it, expect, beforeEach } from 'vitest';
import { MemoryTransport } from '../src/lib/transport.js';
import { pullPeers, pushSnapshot, fullSync, snapshotContentHash } from '../src/lib/sync.js';
import { buildSnapshot } from '../src/lib/snapshot.js';
import * as crypto from '../src/lib/crypto.js';

const VK = new Uint8Array(32).fill(7);
const OWN = 'dev-phone';

// A transport that counts downloads, so "skipped" is measured, not assumed.
class CountingTransport extends MemoryTransport {
  constructor(initial) {
    super(initial);
    this.gets = 0;
    this.puts = 0;
  }

  async get(name) {
    this.gets++;
    return super.get(name);
  }

  async put(name, text) {
    this.puts++;
    return super.put(name, text);
  }
}

async function peerBlob(deviceId, entries) {
  await crypto.ready;
  const snap = buildSnapshot(entries, deviceId, 'MacBook');
  return crypto.sealEnvelope(snap, VK, {
    device: deviceId,
    snapshotVersion: snap.snapshot_version,
    writtenAt: snap.generated_at
  });
}

const entry = (date, over = {}) => ({
  uuid: `u-${date}`, date, rating: 6, note: 'peer note',
  created_at: '2026-07-01T10:00:00Z', updated_at: '2026-07-01T10:00:00Z',
  deleted: false, ...over
});

beforeEach(async () => {
  await crypto.ready;
});

describe('skipping peers that have not changed', () => {
  it('downloads a peer once, then skips it while its tag is the same', async () => {
    const t = new CountingTransport({
      'device_dev-desktop.json': await peerBlob('dev-desktop', [entry('2026-07-01')])
    });

    const first = { locked: 0, errors: 0 };
    const merged = await pullPeers(t, OWN, [], VK, first, {});
    expect(merged).toHaveLength(1);
    expect(t.gets).toBe(1);
    expect(first.tags['device_dev-desktop.json']).toBeTruthy();

    // Second cycle with the marks from the first: nothing downloaded.
    const second = { locked: 0, errors: 0 };
    const again = await pullPeers(t, OWN, merged, VK, second, first.tags);
    expect(t.gets).toBe(1);
    expect(second.skipped).toBe(1);
    expect(again).toHaveLength(1);
  });

  it('downloads again once the peer writes something new', async () => {
    const t = new CountingTransport({
      'device_dev-desktop.json': await peerBlob('dev-desktop', [entry('2026-07-01')])
    });
    const first = { locked: 0, errors: 0 };
    let merged = await pullPeers(t, OWN, [], VK, first, {});

    await t.put('device_dev-desktop.json',
                await peerBlob('dev-desktop', [entry('2026-07-01'), entry('2026-07-02')]));

    const second = { locked: 0, errors: 0 };
    merged = await pullPeers(t, OWN, merged, VK, second, first.tags);
    expect(second.skipped).toBeUndefined();
    expect(merged.map((e) => e.date).sort()).toEqual(['2026-07-01', '2026-07-02']);
  });

  it('never marks a peer it could not read', async () => {
    // Wrong key: the blob stays unread, so it must be retried next time
    // rather than remembered as "already merged".
    const other = new Uint8Array(32).fill(9);
    const t = new CountingTransport({
      'device_dev-desktop.json': await peerBlob('dev-desktop', [entry('2026-07-01')])
    });
    const stats = { locked: 0, errors: 0 };
    await pullPeers(t, OWN, [], other, stats, {});
    expect(stats.locked).toBe(1);
    expect(stats.tags).toBeUndefined();
  });

  it('still works against a transport with no listMeta', async () => {
    const plain = {
      files: new Map([['device_dev-desktop.json',
                       await peerBlob('dev-desktop', [entry('2026-07-01')])]]),
      async list() { return [...this.files.keys()]; },
      async get(n) { return this.files.get(n) ?? null; },
      async put(n, t) { this.files.set(n, t); }
    };
    const merged = await pullPeers(plain, OWN, [], VK, { locked: 0, errors: 0 }, {});
    expect(merged).toHaveLength(1);
  });
});

describe('skipping a push with nothing new in it', () => {
  it('publishes once, then stops re-uploading the same diary', async () => {
    const t = new CountingTransport();
    const entries = [entry('2026-07-01')];

    const hash = await pushSnapshot(t, OWN, entries, VK, 'Телефон', null);
    expect(t.puts).toBe(1);
    expect(hash).toBeTruthy();

    const again = await pushSnapshot(t, OWN, entries, VK, 'Телефон', hash);
    expect(again).toBe(null);
    expect(t.puts).toBe(1);        // no second upload
  });

  it('publishes again after an entry changes', async () => {
    const t = new CountingTransport();
    const hash = await pushSnapshot(t, OWN, [entry('2026-07-01')], VK, 'Телефон', null);
    await pushSnapshot(t, OWN,
                       [entry('2026-07-01', { rating: 9, updated_at: '2026-07-02T10:00:00Z' })],
                       VK, 'Телефон', hash);
    expect(t.puts).toBe(2);
  });

  it('ignores the build timestamp when deciding', () => {
    const a = buildSnapshot([entry('2026-07-01')], OWN, 'Телефон');
    const b = { ...a, generated_at: '2099-01-01T00:00:00.000Z' };
    expect(snapshotContentHash(a)).toBe(snapshotContentHash(b));
  });
});

describe('a full idle cycle', () => {
  it('costs one listing and nothing else', async () => {
    const t = new CountingTransport({
      'device_dev-desktop.json': await peerBlob('dev-desktop', [entry('2026-07-01')])
    });

    const s1 = { locked: 0, errors: 0 };
    const merged = await fullSync(t, OWN, [], VK, s1, 'Телефон', {});
    const busyGets = t.gets;
    const busyPuts = t.puts;
    expect(busyGets).toBe(1);
    expect(busyPuts).toBe(1);

    // Nothing changed anywhere: no downloads, no upload.
    const s2 = { locked: 0, errors: 0 };
    await fullSync(t, OWN, merged, VK, s2, 'Телефон',
                   { seen: s1.tags, lastHash: s1.pushHash });
    expect(t.gets).toBe(busyGets);
    expect(t.puts).toBe(busyPuts);
    expect(s2.pushHash).toBe(null);
  });
});
