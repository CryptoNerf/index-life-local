// Sync transport — the dumb blob store the sync engine talks to. Same tiny
// contract as the desktop's SyncBackend (app/sync_backends.py): the store holds
// only opaque files and runs no logic. Real backends (Google Drive, Yandex.Disk,
// WebDAV) implement this interface; the engine never knows which one it is.
//
//   list()        -> Promise<string[]>          file names in the folder
//   get(name)     -> Promise<string|null>       file text, null if absent
//   put(name,txt) -> Promise<void>              create/overwrite
//   delete(name)  -> Promise<void>
//   listMeta()    -> Promise<{name,tag}[]>      OPTIONAL: names + a change tag
//
// `listMeta` is what keeps a phone off mobile data: both cloud APIs return a
// checksum (or a modified time) in the same listing call the engine already
// makes, so a peer blob that hasn't changed since the last merge never has to
// be downloaded again. A transport without it simply always downloads.
//
// To stay interoperable with the desktop through one shared cloud folder, the
// PWA uses the SAME names the desktop does: snapshots are `device_<id>.json`
// (envelope JSON inside) and the wrapped key is `vault.json`.

// In-memory transport for tests (and a reference implementation). Simulates a
// shared folder two devices read/write.
export class MemoryTransport {
  constructor(initial = {}) {
    this.files = new Map(Object.entries(initial));
  }

  async list() {
    return [...this.files.keys()];
  }

  // The tag is the content itself here — a memory store has nothing cheaper,
  // and tests want exact "changed / unchanged" semantics.
  async listMeta() {
    return [...this.files.entries()].map(([name, text]) => ({ name, tag: text }));
  }

  async get(name) {
    return this.files.has(name) ? this.files.get(name) : null;
  }

  async put(name, text) {
    this.files.set(name, text);
  }

  async delete(name) {
    this.files.delete(name);
  }
}
