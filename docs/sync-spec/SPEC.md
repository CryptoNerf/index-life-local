# index.life — Sync & Crypto Spec

> **Source of truth** for the encrypted sync protocol. The Python desktop
> implements it (`app/sync_crypto.py`, `app/sync.py`); future clients — a
> libsodium.js **PWA** and a Flutter app — must implement it identically.
> The fixtures in `fixtures/` are the contract: both stacks reproduce them
> byte-for-byte (`tests/test_sync_crypto.py` does so on the Python side).
>
> Living doc. Versioned: changing any wire format = edit this spec + the
> fixtures + every client in one change. Last updated: 2026-06-27.

## Status

| Part | State |
|---|---|
| §1 Crypto envelope + vault | **Implemented + golden vectors** (`app/sync_crypto.py`) |
| §2 Canonical JSON | Implemented (subset; float rule open — see §2) |
| §3 Metric registry | `metric-registry.json` (documents the live `daily_signals` sources) |
| §4 Snapshot shape | **JSON Schema + conformance test** (`snapshot.schema.json`) |
| §4 Merge rules | Documented from the running code; shared golden merge fixtures deferred to the PWA-merge stage |
| Wiring crypto into the live sync path | **Not yet** — crypto ships standalone first (zero regression) |

---

## 0. Model (why the cloud stays dumb)

Sync exchanges one JSON *snapshot* per device through shared storage (a
cloud folder or WebDAV — `app/sync_backends.py`). A device only ever
**writes its own** snapshot and **reads peers'** snapshots to merge
locally. So the store needs zero logic and can hold only ciphertext:
encryption is a seal around blob I/O, and the merge code is unchanged.

```text
on sync, each device:
  1. backend.list_files()                      → peer blobs + vault.json
  2. unwrap Vault Key once (cached in OS secure storage)
  3. for each peer blob: open_envelope(VK) → snapshot → existing merge
  4. seal_envelope(my snapshot, VK) → backend.write_atomic(my blob)
```

---

## 1. Crypto envelope + vault

All primitives are **libsodium** (Python: PyNaCl; PWA: libsodium.js;
Flutter: `sodium`) so the three stacks interoperate exactly.

### 1.1 Primitives & parameters

| Role | Algorithm | Params |
|---|---|---|
| AEAD | XChaCha20-Poly1305 (IETF) | key 32 B, nonce **24 B random per write**, 16 B tag |
| KDF (passphrase) | Argon2id v1.3 | salt 16 B, `opslimit`/`memlimit` from `vault.json` (defaults `3` / `67108864` = 64 MiB) |
| Recovery-key wrap | keyed BLAKE2b → 32 B | the recovery key is already 256-bit, so no Argon2; domain-separated by a fixed context label |

Default Argon2id cost is **64 MiB / ops 3**: 256 MiB (libsodium MODERATE)
risks OOM in a mobile Safari/WASM tab, while ops 3 adds margin over
INTERACTIVE. The actual values live in `vault.json`, so a vault can be
re-tuned without a format change.

### 1.2 Key hierarchy

- **Vault Key (VK)** — random 256-bit key, created once per vault,
  encrypts every snapshot, shared by all devices. The cloud never sees it
  in plaintext. Each device caches the unwrapped VK in OS secure storage
  (Keychain / Keystore / Credential Manager); it is never synced.
- VK is **wrapped** two independent ways in `vault.json`; either unlocks it:
  - **passphrase**: `KEK = Argon2id(passphrase, salt)` → `AEAD(VK, KEK)`.
  - **recovery key**: a one-time 256-bit key shown once at setup →
    `AEAD(VK, BLAKE2b(recovery))`. Survives a lost passphrase.
  - **QR pairing** (handing VK device-to-device, offline) is a client
    transport concern, not a primitive — outside `sync_crypto.py`.

### 1.3 `vault.json` (stored in the cloud — safe; only wrapped keys + salt)

```json
{
  "v": 1,
  "kdf": { "alg": "argon2id", "salt": "<b64,16B>",
           "opslimit": 3, "memlimit": 67108864 },
  "wrapped": {
    "passphrase": { "nonce": "<b64,24B>", "ct": "<b64>" },
    "recovery":   { "nonce": "<b64,24B>", "ct": "<b64>" }
  }
}
```

### 1.4 Snapshot envelope (the device blob)

```json
{ "env": 1, "alg": "xchacha20poly1305",
  "device": "<id>", "snapshot_version": 4, "written_at": "<iso8601>",
  "nonce": "<b64,24B>", "ct": "<b64 ciphertext+tag>" }
```

- `env` (envelope version) evolves **independently** of the inner
  `snapshot_version`, so crypto can be rotated without touching the data
  model.
- The header (`env`, `alg`, `device`, `snapshot_version`, `written_at`) is
  plaintext so peers can list/sort without decrypting, **but it is bound as
  AEAD associated data** (the canonical JSON of those five fields) — any
  edit to it fails the tag check. Everything sensitive is inside `ct`.
- Inner plaintext = `canonical_json(snapshot)` (§2).

### 1.5 Recovery-key display

256-bit recovery key → grouped Base32 (`XXXXX-XXXXX-…`) for the user to
write down; decoding tolerates spacing/case/dashes. A BIP39-style mnemonic
can wrap this later without changing the stored bytes.

---

## 2. Canonical JSON (RFC 8785-compatible)

`canonical_json`: UTF-8, object keys sorted, no insignificant whitespace
(`separators=(',',':')`). Needed only so a fixed (snapshot → key → nonce)
yields one fixed ciphertext for golden vectors — **decryption never needs
canonical form** (a peer decrypts whatever bytes were sealed).

**OPEN ITEM — float formatting.** RFC 8785 mandates ECMAScript
Number-to-String for non-integers; that exact algorithm is **not yet
pinned** here. The blob golden vector uses integer-only numbers so it does
not depend on it. The float rule (and a float vector) get locked when the
JS client lands and there is a second implementation to diff against. Key
ordering uses Unicode codepoints; snapshot keys are ASCII, so this equals
RFC 8785's UTF-16 ordering.

---

## 3. Metric registry

See `metric-registry.json`: `(source, metric) → {kind, unit, label_key,
aggregation, higher_is}`. It documents the `daily_signals` rows already in
snapshots (weather is live; `health.steps` is the `device`-mode stub that
the phone will populate). Clients read it for labels, units, chart type and
same-day aggregation — no hard-coded per-metric logic.

---

## 4. Snapshot & merge

`app/sync.py`: `SNAPSHOT_VERSION = 4`; a device writes only its own
`device_<id>.json`; merge is additive union + last-write-wins on
`updated_at` + tombstones.

**Shape — `snapshot.schema.json`** (JSON Schema 2020-12) describes the
exact v4 snapshot. It is kept honest by `tests/test_sync_spec.py`, which
validates a real `build_snapshot()` against it (so the schema cannot drift
from the code), plus the all-branches example `fixtures/snapshot.sample.json`.
Forward-compatible: unknown future fields are allowed and ignored.

**Merge identities & rules** (what a second implementation must replicate):

| section | identity | rule |
|---|---|---|
| `mood_entries` | **date** (one/day) | LWW on `updated_at`; `deleted:true` = tombstone (kept, keeps propagating); a peer merely lacking an entry is NOT a delete; diverging live-vs-live overwrite is logged |
| `daily_signals` | `(date, source, metric)` | insert, else LWW on `updated_at` |
| `chat_messages` | `uuid` | append-only, de-duped; dropped if older than local `chat_cleared_at` |
| `user_profile` | singleton | LWW on `updated_at` |
| `entry_summaries`/`entry_people`/`entry_activities` | entry `uuid` | strictly additive (fill gaps; never overwrite local) |
| `period_summaries` | `period_key` | additive |
| `person_aliases` | `alias` | additive |
| `psych_profile` | singleton | adopt peer's only if it analysed MORE entries |

These rules are exhaustively covered today by `tests/test_sync_merge.py` +
`tests/test_sync_derived.py`. The remaining spec item is **shared** golden
merge fixtures (`fixtures/merge/{a,b,expected}.json`) that BOTH the Python
and PWA suites load — authored alongside the PWA's merge implementation
(its first consumer), so the fixtures are validated against two stacks from
the start rather than locking one stack's behaviour speculatively.

---

## Fixtures

```text
fixtures/crypto/
  argon2id.json   {passphrase, salt, ops, mem} → key            (live params)
  aead.json       {key, nonce, plaintext, aad} → ciphertext
  blob.json       snapshot → canonical bytes → {VK, nonce} → ciphertext + envelope
```

Regenerate only deliberately (a change here is a wire-format change). Both
the Python suite and future JS/Dart suites must reproduce these exactly.
