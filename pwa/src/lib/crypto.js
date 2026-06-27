// End-to-end-encryption crypto for the PWA — the JS twin of the desktop's
// app/sync_crypto.py. Same libsodium primitives (XChaCha20-Poly1305 + Argon2id),
// same envelope/vault formats, same canonical JSON — so the two stacks produce
// and consume byte-identical blobs. Locked by the shared golden vectors in
// docs/sync-spec/fixtures/crypto/ (see test/crypto.test.js).

import sodium from 'libsodium-wrappers-sumo';

export const ready = sodium.ready;

// ── versioned constants (mirror SPEC.md / sync_crypto.py) ────────────
export const ENV_VERSION = 1;
export const AEAD_ALG = 'xchacha20poly1305';
export const KDF_ALG = 'argon2id';
export const VAULT_VERSION = 1;
export const KDF_OPSLIMIT = 3;
export const KDF_MEMLIMIT = 67108864; // 64 MiB
export const SALT_BYTES = 16;
export const VK_BYTES = 32;
export const NONCE_BYTES = 24;
export const RECOVERY_BYTES = 32;

// 32-byte domain-separation label, identical bytes to sync_crypto._RECOVERY_CONTEXT
const RECOVERY_CONTEXT = (() => {
  const ctx = new Uint8Array(32);
  ctx.set(new TextEncoder().encode('index.life recovery-wrap v1'));
  return ctx;
})();

const utf8 = new TextEncoder();
const fromUtf8 = new TextDecoder();

// ── base64 / hex (standard alphabet, padded — matches Python b64encode) ─
const b64e = (bytes) => sodium.to_base64(bytes, sodium.base64_variants.ORIGINAL);
const b64d = (str) => sodium.from_base64(str, sodium.base64_variants.ORIGINAL);
export const toHex = (bytes) => sodium.to_hex(bytes);
export const fromHex = (hex) => sodium.from_hex(hex);

// ── canonical JSON (RFC 8785-compatible for our value subset) ────────
// Sorted object keys, compact separators, UTF-8. Matches Python
// json.dumps(sort_keys=True, ensure_ascii=False, separators=(',',':')).
// Float formatting is the documented open item; canonical contexts use ints.
export function canonicalString(value) {
  if (value === null) return 'null';
  const t = typeof value;
  if (t === 'boolean') return value ? 'true' : 'false';
  if (t === 'number') {
    if (!Number.isFinite(value)) throw new Error('non-finite number');
    return JSON.stringify(value);
  }
  if (t === 'string') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalString).join(',') + ']';
  if (t === 'object') {
    const keys = Object.keys(value).sort();
    return '{' + keys.map((k) => JSON.stringify(k) + ':' + canonicalString(value[k])).join(',') + '}';
  }
  throw new Error('unserializable: ' + t);
}
export function canonicalJSON(value) {
  return utf8.encode(canonicalString(value));
}

// ── AEAD: XChaCha20-Poly1305 ─────────────────────────────────────────
export function randomNonce() {
  return sodium.randombytes_buf(NONCE_BYTES);
}
export function aeadEncrypt(key, plaintext, nonce, aad = new Uint8Array(0)) {
  return sodium.crypto_aead_xchacha20poly1305_ietf_encrypt(plaintext, aad, null, nonce, key);
}
export function aeadDecrypt(key, nonce, ciphertext, aad = new Uint8Array(0)) {
  return sodium.crypto_aead_xchacha20poly1305_ietf_decrypt(null, ciphertext, aad, nonce, key);
}

// ── KDF: Argon2id passphrase → 256-bit key ───────────────────────────
export function deriveKey(passphrase, salt, opslimit = KDF_OPSLIMIT, memlimit = KDF_MEMLIMIT) {
  const pw = typeof passphrase === 'string' ? utf8.encode(passphrase) : passphrase;
  return sodium.crypto_pwhash(VK_BYTES, pw, salt, opslimit, memlimit,
    sodium.crypto_pwhash_ALG_ARGON2ID13);
}

// ── snapshot envelope ────────────────────────────────────────────────
function envelopeHeader(env) {
  return {
    env: env.env, alg: env.alg, device: env.device,
    snapshot_version: env.snapshot_version, written_at: env.written_at
  };
}

export function sealEnvelope(snapshot, vk, { device, snapshotVersion, writtenAt, nonce }) {
  const header = {
    env: ENV_VERSION, alg: AEAD_ALG, device,
    snapshot_version: snapshotVersion, written_at: writtenAt
  };
  const n = nonce || randomNonce();
  const ct = aeadEncrypt(vk, canonicalJSON(snapshot), n, canonicalJSON(header));
  // insertion order matches Python (header fields, then nonce, ct); compact JSON
  const envelope = { ...header, nonce: b64e(n), ct: b64e(ct) };
  return JSON.stringify(envelope);
}

export function openEnvelope(envelopeText, vk) {
  const env = JSON.parse(envelopeText);
  if (env.env !== ENV_VERSION) throw new Error(`unsupported envelope version: ${env.env}`);
  if (env.alg !== AEAD_ALG) throw new Error(`unsupported AEAD alg: ${env.alg}`);
  const pt = aeadDecrypt(vk, b64d(env.nonce), b64d(env.ct), canonicalJSON(envelopeHeader(env)));
  return JSON.parse(fromUtf8.decode(pt));
}

// ── vault: VK creation + wrapping ────────────────────────────────────
function wrap(vk, kek) {
  const nonce = randomNonce();
  return { nonce: b64e(nonce), ct: b64e(aeadEncrypt(kek, vk, nonce)) };
}
function unwrap(wrapped, kek) {
  return aeadDecrypt(kek, b64d(wrapped.nonce), b64d(wrapped.ct));
}
function recoveryWrapKey(recovery) {
  return sodium.crypto_generichash(VK_BYTES, recovery, RECOVERY_CONTEXT);
}

const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
export function encodeRecoveryKey(recovery) {
  let bits = 0, val = 0, out = '';
  for (const byte of recovery) {
    val = (val << 8) | byte;
    bits += 8;
    while (bits >= 5) { out += B32[(val >>> (bits - 5)) & 31]; bits -= 5; }
  }
  if (bits > 0) out += B32[(val << (5 - bits)) & 31];
  return out.match(/.{1,5}/g).join('-');
}
export function decodeRecoveryKey(text) {
  const clean = text.replace(/[\s-]/g, '').toUpperCase();
  let bits = 0, val = 0;
  const out = [];
  for (const ch of clean) {
    const idx = B32.indexOf(ch);
    if (idx < 0) continue;
    val = (val << 5) | idx;
    bits += 5;
    if (bits >= 8) { out.push((val >>> (bits - 8)) & 0xff); bits -= 8; }
  }
  return Uint8Array.from(out);
}

export function createVault(passphrase, opslimit = KDF_OPSLIMIT, memlimit = KDF_MEMLIMIT) {
  const vk = sodium.randombytes_buf(VK_BYTES);
  const salt = sodium.randombytes_buf(SALT_BYTES);
  const kek = deriveKey(passphrase, salt, opslimit, memlimit);
  const recovery = sodium.randombytes_buf(RECOVERY_BYTES);
  const vault = {
    v: VAULT_VERSION,
    kdf: { alg: KDF_ALG, salt: b64e(salt), opslimit, memlimit },
    wrapped: { passphrase: wrap(vk, kek), recovery: wrap(vk, recoveryWrapKey(recovery)) }
  };
  return { vault, vaultKey: vk, recoveryKey: encodeRecoveryKey(recovery) };
}

export function unwrapWithPassphrase(vault, passphrase) {
  const kek = deriveKey(passphrase, b64d(vault.kdf.salt),
    Number(vault.kdf.opslimit), Number(vault.kdf.memlimit));
  return unwrap(vault.wrapped.passphrase, kek);
}

export function unwrapWithRecovery(vault, recoveryKeyText) {
  return unwrap(vault.wrapped.recovery, recoveryWrapKey(decodeRecoveryKey(recoveryKeyText)));
}
