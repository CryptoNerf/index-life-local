// Cross-stack crypto conformance: the JS crypto (src/lib/crypto.js) must
// reproduce the SAME golden vectors the Python desktop produces
// (docs/sync-spec/fixtures/crypto/). This is the guarantee that an encrypted
// snapshot written by one stack can be read by the other, byte-for-byte.

import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import * as crypto from '../src/lib/crypto.js';

const FX = new URL('../../docs/sync-spec/fixtures/crypto/', import.meta.url);
const load = (name) => JSON.parse(readFileSync(new URL(name, FX), 'utf8'));
const enc = (s) => new TextEncoder().encode(s);
const rand = (n) => globalThis.crypto.getRandomValues(new Uint8Array(n));

beforeAll(async () => {
  await crypto.ready;
});

describe('golden vectors (Python ⇄ JS interop)', () => {
  it('argon2id derives the same key', () => {
    const v = load('argon2id.json');
    const key = crypto.deriveKey(v.passphrase_utf8, crypto.fromHex(v.salt_hex), v.opslimit, v.memlimit);
    expect(crypto.toHex(key)).toBe(v.key_hex);
  });

  it('aead produces the same ciphertext', () => {
    const v = load('aead.json');
    const ct = crypto.aeadEncrypt(
      crypto.fromHex(v.key_hex), enc(v.plaintext_utf8),
      crypto.fromHex(v.nonce_hex), enc(v.aad_utf8)
    );
    expect(crypto.toHex(ct)).toBe(v.ciphertext_hex);
    const pt = crypto.aeadDecrypt(crypto.fromHex(v.key_hex), crypto.fromHex(v.nonce_hex), ct, enc(v.aad_utf8));
    expect(new TextDecoder().decode(pt)).toBe(v.plaintext_utf8);
  });

  it('blob: canonical JSON, envelope text and ciphertext all match', () => {
    const v = load('blob.json');
    const vk = crypto.fromHex(v.vk_hex);

    expect(crypto.toHex(crypto.canonicalJSON(v.snapshot))).toBe(v.canonical_plaintext_hex);

    const envelope = crypto.sealEnvelope(v.snapshot, vk, {
      device: v.header.device,
      snapshotVersion: v.header.snapshot_version,
      writtenAt: v.header.written_at,
      nonce: crypto.fromHex(v.nonce_hex)
    });
    // envelope_text contains the base64 ciphertext, so an exact match here is
    // also the ciphertext_hex check.
    expect(envelope).toBe(v.envelope_text);
    expect(crypto.openEnvelope(envelope, vk)).toEqual(v.snapshot);
  });
});

describe('round-trips & authentication', () => {
  it('envelope round-trips with a random key', () => {
    const vk = rand(32);
    const snap = { snapshot_version: 4, entities: { mood_entries: [{ uuid: 'b1', rating: 7, note: 'тест "кавычки" ✓' }] }, tombstones: [] };
    const env = crypto.sealEnvelope(snap, vk, { device: '9f2c', snapshotVersion: 4, writtenAt: '2026-06-27T10:00:00Z' });
    expect(crypto.openEnvelope(env, vk)).toEqual(snap);
  });

  it('rejects a wrong key', () => {
    const env = crypto.sealEnvelope({ x: 1 }, rand(32), { device: 'd', snapshotVersion: 4, writtenAt: 't' });
    expect(() => crypto.openEnvelope(env, rand(32))).toThrow();
  });

  it('rejects header tampering (bound as AAD)', () => {
    const vk = rand(32);
    const env = JSON.parse(crypto.sealEnvelope({ x: 1 }, vk, { device: 'd', snapshotVersion: 4, writtenAt: 't' }));
    env.device = 'EVIL';
    expect(() => crypto.openEnvelope(JSON.stringify(env), vk)).toThrow();
  });
});

describe('vault', () => {
  const CHEAP = [2, 65536]; // [opslimit, memlimit] — fast for tests

  it('unwraps with passphrase and recovery key', () => {
    const { vault, vaultKey, recoveryKey } = crypto.createVault('correct horse battery staple', ...CHEAP);
    expect(crypto.toHex(crypto.unwrapWithPassphrase(vault, 'correct horse battery staple'))).toBe(crypto.toHex(vaultKey));
    expect(crypto.toHex(crypto.unwrapWithRecovery(vault, recoveryKey))).toBe(crypto.toHex(vaultKey));
  });

  it('rejects a wrong passphrase', () => {
    const { vault } = crypto.createVault('right', ...CHEAP);
    expect(() => crypto.unwrapWithPassphrase(vault, 'wrong')).toThrow();
  });

  it('vault.json carries no plaintext key', () => {
    const { vault, vaultKey } = crypto.createVault('pw', ...CHEAP);
    const blob = JSON.stringify(vault);
    expect(blob).not.toContain(crypto.toHex(vaultKey));
  });

  it('recovery-key encoding round-trips (tolerant of spacing/case)', () => {
    const raw = rand(32);
    const text = crypto.encodeRecoveryKey(raw);
    expect(crypto.toHex(crypto.decodeRecoveryKey(text))).toBe(crypto.toHex(raw));
    expect(crypto.toHex(crypto.decodeRecoveryKey(text.toLowerCase().replace(/-/g, ' ')))).toBe(crypto.toHex(raw));
  });
});
