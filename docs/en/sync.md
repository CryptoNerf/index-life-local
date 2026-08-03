# Sync between devices

[← back to index](../README.md) · [Русский](../ru/sync.md)

Sync moves the current version of your diary between all your devices through shared storage (a cloud folder or a WebDAV server). The app **doesn't talk to any cloud API directly** — it only reads and writes files; distributing them between devices is the chosen service's job.

---

## The idea: one snapshot per device

Each device keeps **exactly one file** in shared storage — `device_<id>.json` — holding its **full state** (all entries including deletion tombstones, chat, profile).

The sync cycle:

1. **Read** every *other* device's snapshot.
2. **Merge** them into the local database.
3. **Rewrite** our own snapshot (atomically).

Why this and not a "change log": with a log, each device must acknowledge receiving each file before it can be deleted. Otherwise a device that sat in a drawer for a week loses those edits permanently. Here the file is **never deleted, only overwritten** — any device that opens the app even a year later reads the current state. And the folder doesn't grow: one file per device.

---

## Safety guarantees

Sync is designed so it **can never wipe your data**:

- **A peer's snapshot is a declaration, not a directive.** Another device's file says "here's what I have", not "here's what should exist everywhere". Merging only **adds** and resolves conflicts by edit time. A peer simply not having an entry **does not mean delete**.
- **Deletion is an explicit tombstone** (`deleted=True`) that replicates correctly. No physical deletes, so an entry never "resurrects" and is always recoverable from a backup.
- **Atomic writes** (`temp file → rename`). A crash mid-write leaves peers the previous valid file, not a fragment. A corrupt/empty file is skipped on read — the local DB is untouched.
- **A backup before every merge** (separate pool `backups/pre-sync/`). If something goes wrong, "Restore" brings the previous state back.
- **Schema validation on import.** An entry missing required fields is skipped, but the rest of the snapshot still applies — one bad item never breaks the whole file.
- **Idempotency.** Re-applying the same snapshot changes nothing.

**Conflict resolution.** If the same date was edited on two devices, the version with the later `updated_at` wins. The losing version is saved to the conflict log (Sync page, kept 30 days) — you can review it and copy it over manually if you want.

---

## Two storage backends

### 1. Local folder

A folder a cloud desktop client mirrors to the internet. Works with **any service that has a desktop client**: Dropbox, Google Drive, iCloud Drive, OneDrive, Mega, Sync.com, etc.

Setup: on the **Sync** page choose "Local folder" and enter the path to the synced folder, e.g.:
```
/Users/you/Dropbox/index-life-sync
C:\Users\you\Google Drive\index-life-sync
```
Point all devices at the **same folder** (inside your cloud).

### 2. WebDAV link

If you'd rather not install a cloud desktop client — paste a direct **WebDAV link** to a folder. Works with **Nextcloud, ownCloud, Yandex.Disk, Box, pCloud, kDrive (Infomaniak)** and any self-hosted WebDAV server.

Setup: choose "WebDAV link" and fill in:
- **Folder URL** — e.g. `https://dav.example.com/remote.php/dav/files/me/diary/`
- **Username and password** — your WebDAV account credentials (e.g. your Nextcloud account, or a Yandex "app password"). Stored locally on this device and only sent to the server you entered.

The **"Test connection"** button checks in advance whether the server is reachable and the credentials are right.

> **What the WebDAV link doesn't cover:** Dropbox, Google Drive, iCloud, OneDrive — these have no open WebDAV (they need OAuth). Use "Local folder" via their desktop client instead.

---

## When sync happens

- On app **startup** (if sync is configured).
- **Periodically** in the background (every ~2 minutes).
- On **saving/deleting an entry** — your snapshot is pushed immediately (best-effort).
- Manually — the **"Sync now"**, **"Export"** (push your snapshot only), and **"Import"** (pull peers only) buttons.

---

## Setting it up from scratch (example)

![Sync settings page](../images/sync.png)

1. On device A: **Sync** page → choose a mode → enter folder/URL → "Save".
2. Click "Sync now" — `device_<A>.json` appears in storage.
3. On device B: point at the **same** storage → "Sync now". B pulls A's entries and writes its own `device_<B>.json`.
4. From then on it's automatic. Each device sees every other's snapshot.

You can connect any number of devices — the folder will hold one file per device.

---

## Backups

Sync and backups are independent safety mechanisms:

- **Daily backups** of the database — in `backups/` (last 10).
- **Pre-merge backup** — in `backups/pre-sync/` (last 5).
- Restore on the Sync page, then restart the app.

More in [The application → Backups](application.md#backups--restore).

## Connecting your phone (PWA)

The phone client syncs **encrypted only** — the cloud sees nothing but
ciphertext. Connecting takes a couple of minutes:

### Desktop first (recommended)

1. **Desktop.** Sync page → "Find cloud folders" — pick a discovered folder in
   one click (or "Choose folder…"). Save.
2. **Desktop.** Enable end-to-end encryption (passphrase → store the recovery
   key somewhere safe).
3. **Desktop.** In the encryption section open **"Connect your phone"** — a QR
   code appears.
4. **Phone.** Settings → Sync → pick the same cloud (Google Drive /
   Yandex.Disk) → sign in → **"Scan the code from the computer"** → point the
   camera at the QR. No passphrase needed. If the scanner isn't supported
   (iOS Safari), type the code from the desktop screen instead.
5. Check: "Devices in this folder" (both sides) now lists two devices with
   their last-sync times.

### Phone first

1. **Phone.** Settings → Sync → cloud → OAuth → create a passphrase (store the
   recovery key).
2. **Desktop.** Install the same cloud's desktop client and let it mirror.
3. **Desktop.** "Find cloud folders" — the phone's folder is highlighted as
   "sync folder found". Pick it and save.
4. **Desktop.** In the encryption section enter the passphrase — or, on the
   phone, open "Show pairing code" and enter it on the desktop under
   "Enter a pairing code from another device".

### Where the cloud folders live

- **Google Drive** (macOS): `~/Library/CloudStorage/GoogleDrive-<email>/My Drive/index.life`
- **Yandex.Disk**: `<Yandex.Disk folder>/Приложения (Applications)/<app name>/`
- The "Find cloud folders" button scans these locations automatically.

> ⚠️ The pairing code (and its QR) contains the diary's encryption key. Show
> it only to your own devices — never photograph or share it.

## Each cloud in detail

### Google Drive

> ⚠️ **Important: pairing with the phone requires the desktop's
> "Google Drive (direct)" mode**, not "Local folder". The phone app uses
> the narrow `drive.file` scope and sees **only files created by
> index.life itself**. Files uploaded by the Google Drive desktop client
> are invisible to the phone — a mirrored local folder gives one-way sync:
> the desktop sees the phone, the phone **never receives** the desktop's
> entries.

- **Phone:** Settings → Sync → Google Drive → sign in. The app creates the
  `index.life` folder in My Drive root.
- **Desktop:** Sync page → **"Google Drive (direct)"** mode → **"Sign in
  with Google"** (same account as the phone) → consent in the browser.
  That's all: no Google Drive desktop client, no folder paths, both sides
  see each other.
- The **local Google Drive folder** remains fine for **desktop ↔ desktop**
  sync (no phone involved).

<details><summary>For the distributor: enabling direct mode in a build</summary>

Create a **Desktop app** OAuth client in the **same Google Cloud project**
as the phone app's web client (`drive.file` visibility is per project, so
the two sides see each other's files): console.cloud.google.com → APIs &
Services → Credentials → Create Credentials → OAuth client ID → Desktop
app. Then at build/run time:

Drop the JSON the console gives you into the project root as
**`google_client.json`** — both spec files pick it up, and your users get
the one-click "Sign in to Google". The file is not committed (it is in
`.gitignore`): GitHub blocks pushes containing OAuth credentials, and a
fork should use its own client anyway.

The app looks for a client in this order:

1. environment variables — handy for rotating without a rebuild:
   ```bash
   export GOOGLE_DESKTOP_CLIENT_ID="…apps.googleusercontent.com"
   export GOOGLE_DESKTOP_CLIENT_SECRET="…"
   ```
2. `google_client.json` in the app's data directory — for a user who wants
   to bring their own client;
3. `google_client.json` inside the build — the one you shipped.

With no client anywhere, "Google Drive (direct)" simply reports itself as
unavailable instead of breaking mid-sign-in. Google treats the client secret
of installed (desktop) apps as non-confidential — shipping it in a build is
within Google's guidelines.
</details>

### Yandex.Disk

- **Phone:** Settings → Sync → Yandex.Disk → sign in. Works in Russia
  without a VPN. Data lives in the app folder:
  `Disk → Applications (Приложения) → <app name>`.
- **Desktop, option 1 (simpler):** install the Yandex.Disk desktop client —
  the app folder mirrors under `<Yandex.Disk>/Приложения/…`;
  "Find cloud folders" highlights it.
- **Desktop, option 2 (no client):** "WebDAV link" mode with
  `https://webdav.yandex.ru/Приложения/<app name>/`. Login is your Yandex
  login; the password must be an **app password**
  ([id.yandex.ru → Security → App passwords](https://id.yandex.ru/security/app-passwords)) —
  the regular account password won't work.

### Dropbox / iCloud Drive / OneDrive / Mega and others

These have no index.life phone client — they fit **desktop-to-desktop**
sync: install their desktop client on both PCs and point both at the same
folder (e.g. `Dropbox/index.life`) via "Find cloud folders" or "Choose
folder…".

### Nextcloud / ownCloud / self-hosted (WebDAV)

"WebDAV link" mode: a folder URL like
`https://your-server/remote.php/dav/files/login/index-life/` plus the
server credentials. Use **https** only — over http the password and the
diary travel in clear text (the app warns). "Test connection" confirms the
settings.

## Scenarios

### Two computers

1. PC #1: cloud folder → save → enable encryption → store the recovery key.
2. PC #2 (same cloud account, client installed): "Find cloud folders" →
   pick the same folder → enter the passphrase (or a pairing code from
   PC #1) in the encryption section.

### A new device / recovery

The diary restores fully from the cloud: set up the folder/cloud as usual
and enter the passphrase (or the recovery key if the passphrase is lost).
Everything arrives on the first sync.

### Phone only, no computer

Cloud sync is still worth enabling — it's an encrypted backup: phone
drowns → new phone → same cloud → passphrase → everything is back.

### No cloud at all

Even without sync the entries are protected by three layers:

1. **Persistent storage** — the app asks the browser not to evict its data
   (requested automatically after the first save; status under "Data
   safety").
2. **Internal mirror** — a second copy of all entries in a separate browser
   store; if the main database is corrupted or evicted, entries restore
   automatically on the next open.
3. **Backup file (JSON)** — "Data safety" → "Save file": an exact copy of
   all entries in one file. Imports back losslessly (merged under the same
   rules as cloud sync — never overwrites or deletes anything). Make one
   occasionally and keep it off the phone.

### Moving from the browser to the installed app

- **Android / Chrome:** nothing to do — the browser tab and the installed
  app share the same data.
- **iPhone / Safari:** the Home-Screen app gets a **separate** storage
  container. Transfer: in the Safari version "Data safety" → "Save file" →
  in the installed app "Import file". Or connect the cloud in both — they
  merge on their own.

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| Desktop banner "Another device syncs with encryption…" | This PC has no key. Enter the passphrase in the encryption section — or a pairing code from the phone. |
| Phone: "The code doesn't fit this cloud's data" | The phone is connected to a different cloud or account than the computer. Check the account and rescan. |
| Phone: "⚠ Couldn't decrypt N device(s)" | Some device uses a different key (e.g. it created its own vault in another folder). Re-pair it with a code from a working device. |
| A device never appears in "Devices in this folder" | The devices look at different folders. On the PC check the path ("Find cloud folders" shows where the phone's data lives); give the cloud client time to mirror. |
| Phone: "Cloud session expired" | The OAuth token lapsed. Tap "Sign in again" — no data is affected. |
| "Last sync" updates but no entries arrive | Read the banner above it: it names the file that can't be read and why. Details in index-life.log on the PC. |
| Forgot the passphrase | Enter the recovery key (shown once when encryption was enabled). If that is lost too, the cloud data is unreadable; local entries on devices are intact — disable encryption and set it up again. |
