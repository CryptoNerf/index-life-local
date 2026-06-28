// Sync transport — the dumb blob store the sync engine talks to. Same tiny
// contract as the desktop's SyncBackend (app/sync_backends.py): the store holds
// only opaque files and runs no logic. Real backends (Google Drive, Yandex.Disk,
// WebDAV) implement this interface; the engine never knows which one it is.
//
//   list()        -> Promise<string[]>          file names in the folder
//   get(name)     -> Promise<string|null>       file text, null if absent
//   put(name,txt) -> Promise<void>              create/overwrite
//   delete(name)  -> Promise<void>
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
