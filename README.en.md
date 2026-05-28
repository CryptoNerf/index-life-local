# index.life — Local app for tracking your mood and daily notes

> **English version** | [Русская версия](README.md)

Helps you better remember and become aware of yourself and your time.

![Version](https://img.shields.io/badge/version-3.0.0-blue)
![Python](https://img.shields.io/badge/python-3.12-green)
![Flask](https://img.shields.io/badge/flask-3.0.0-lightgrey)
![License](https://img.shields.io/badge/license-AGPL--3.0-blue)
[![Downloads](https://img.shields.io/github/downloads/CryptoNerf/index-life-local/total)](https://github.com/CryptoNerf/index-life-local/releases)

![index.life — your whole year as a heatmap calendar](docs/images/index.life.png)

> **Full documentation:** [docs/](docs/README.md) — the app & database, sync, modules, AI psychologist, neural map, every chart, customization.

---

## About

**index.life** is an app for tracking your mood and keeping notes about your
days. It's meant to help you better remember and become aware of yourself and
your time — which otherwise blurs into one indistinct stream of days.

At its heart is a simple daily practice: stop for a moment each day and write
down how the day went, how you felt, and what was on your mind. I'm convinced
that making this kind of reflection a habit has a positive effect on a person's
life.

**What index.life is for:**

- **Building a daily reflection habit** — gently encouraging you to write about
  your well-being and your day, every day.
- **Archiving your well-being and thoughts** — keeping your entries and mood
  ratings for the long term, so you can return to them later: reread them,
  notice how things changed, remember what mattered.
- **Understanding yourself through your own data** — turning your accumulated
  entries into observations about your mood and the themes, people, and
  activities that shape it.
- **Privacy and ownership of your data** — a diary is personal, so index.life
  runs entirely locally and offline: no accounts, no servers, no telemetry, and
  your data never leaves your device. Your data belongs to you alone.

## What's inside

The foundation of index.life is a **notes calendar** (the whole year as a
heatmap that motivates you not to skip days), a **Markdown editor** for entries,
a **life-in-weeks** view, **Markdown export**, and **sync** across your devices
through your own cloud folder.

To help you make sense of what you write, index.life adds four optional modules:

1. **AI psychologist** — a chat with a local language model that has access to
   your diary: it reflects back what you write, notices patterns, and grounds
   its answers in your real entries. [Read more »](docs/en/ai-psychologist.md)
2. **Neural map of your thoughts** — your entries grouped into topics you can
   explore visually. [Read more »](docs/en/neural-map.md)
3. **Charts** — visualizations of different aspects of your well-being over
   time. [Read more »](docs/en/graphics.md)
4. **Customization** — restyle the whole interface to your taste.
   [Read more »](docs/en/customization.md)

The AI psychologist and neural map are enabled on demand (a local model is
downloaded once); charts and customization switch on right inside the app.

---

## Installation

### Option 1: Pre-built Releases (Recommended)

Download the ready-to-use version for your operating system from Releases:

**Windows:**
1. Download `windows-build.zip`
2. Unzip the archive
3. Run `index-life.exe`

> **First launch — "Windows protected your PC" (SmartScreen)**
> Because index.life is free and open-source, the `.exe` isn't signed with a
> paid certificate, so Windows SmartScreen shows a blue warning the first time.
> The app is safe to run — to continue:
> 1. Click **More info** in the dialog.
> 2. Click **Run anyway**.
>
> You only need to do this once per version. If the warning keeps coming back,
> right-click the downloaded `.zip` → **Properties** → tick **Unblock** →
> **OK**, then unzip it again.

**macOS:**
1. Download `index-life_macos.dmg`
2. Open the DMG and drag **index.life** into your Applications folder
3. **First launch.** Double-click index.life. macOS shows *"Apple could not
   verify 'index.life' is free of malware…"* with two buttons — click **Done**
   (do **not** click "Move to Trash").
4. Open **System Settings → Privacy & Security**, scroll down to the
   **Security** section. There you'll see *"'index.life' was blocked…"* — click
   **Open Anyway**, then confirm with **Open** (Touch ID / password if asked).
5. index.life opens — and from now on it launches normally with a double-click.

> **Why does this happen (on both Windows and macOS)?** index.life is free and
> open-source, so its app isn't signed/notarized with a paid developer
> certificate (Apple Developer is $99/yr; a Windows cert costs too). Both
> systems therefore show a one-time warning for software downloaded from the
> internet that isn't paid-signed. The app is safe and runs entirely on your
> device — these steps just tell your OS you trust it once.
>
> *Alternative (Terminal):* `xattr -d com.apple.quarantine /Applications/index.life.app`

**Linux:**
1. Download `index-life_linux_x86_64.AppImage`
2. Make the file executable:
   ```bash
   chmod +x index-life_linux_x86_64.AppImage
   ```
3. Run:
   ```bash
   ./index-life_linux_x86_64.AppImage
   ```

**Optional modules.** Install them right inside the app: open the **Modules**
page and click "Install" on the module you want — this is the main way on every
OS, with progress shown in the window. Restart the app after installing a heavy
module (AI psychologist or neural map — a local model is downloaded once).
See [docs/en/modules.md](docs/en/modules.md).

### Option 2: Installation via Scripts (From Source)

If you want to run from source code:

**Windows:**
```bash
# Double-click install.bat (first time)
# Double-click start.bat (subsequent runs)
```

**Linux/macOS:**
```bash
chmod +x install.sh start.sh
./install.sh  # First run (installs Python if needed)
./start.sh    # Subsequent runs
```

**Optional modules.** Same as above — via the **Modules** page in the app. For a
source setup you can also run the `install_modules.bat` / `install_modules.sh`
script. See `MODULES.md` for details.

---

## Updating

index.life keeps your data **separately from the app itself**, so upgrading is
just replacing the binary — your diary, AI models and settings stay put.

**Where your data lives:**

| OS | Data folder |
|---|---|
| **Windows** | next to `index-life.exe` (portable); legacy users may have it in `%APPDATA%\index.life` (the app finds it automatically) |
| **macOS** | `~/Library/Application Support/index.life` |
| **Linux** | `~/.index-life` |

Inside: `diary.db` (your main database), `models/` (downloaded AI models),
`modules_venv/` (the modules' Python environment), `profile_photos/`,
`backups/`, `customization_uploads/` and `*_enabled` marker files.

### How to update

**macOS:**
1. Download the new `.dmg` from Releases.
2. Open the DMG and drag `index.life` into `Applications`, **replacing** the
   old one. The data folder is separate from `.app` — nothing to move by hand.
3. Open the app. (macOS will show its first-run security dialog again; same
   steps as during install.)

**Windows:**
1. Download the new `windows-build.zip`.
2. **Simple path:** extract the archive **on top of** your existing app folder
   and allow file replacement. The zip only contains `index-life.exe`, DLLs and
   bundled assets — your `diary.db`, `models/`, `modules_venv/` and other data
   subfolders are untouched.
3. **Tidy path:** extract into a **new** folder next to the old one, then move
   the following from the old folder: `diary.db`, `diary.db-wal`,
   `diary.db-shm`, `models/`, `modules_venv/`, `profile_photos/`, `backups/`,
   `customization_uploads/` and every `*_enabled` file. Run `index-life.exe`
   from the new folder.

**Linux (AppImage):**
1. Download the new `index-life_linux_x86_64.AppImage`.
2. Replace the old file with it and make it executable:
   `chmod +x index-life_linux_x86_64.AppImage`
3. Run it. Your data in `~/.index-life` is preserved.

**From source (any OS):**
```bash
git pull
./install.sh        # refreshes dependencies (install.bat on Windows)
./start.sh          # normal launch
```
The project folder doubles as the data folder, so everything is in place.

### What the app does for you

- **Automatic backup** of the database on every startup (the last 10 copies are
  kept under `backups/`) — there's always a recent snapshot to roll back to.
- **Schema migrations** run on the first launch of a new version. They are
  idempotent and additive — they only add new columns/tables, never drop.
- If you have optional modules installed and the new build **changed Python's
  minor version**, the app will prompt you to reinstall the modules. The
  downloaded AI model (~5 GB under `models/`) is **kept** — you don't have to
  re-download it.

### Manual backup, just in case

If you want extra peace of mind, copy `diary.db` (plus `diary.db-wal` and
`diary.db-shm` if present) somewhere safe before updating. That's enough to
restore your diary to any prior state if anything goes wrong.

---

## Project Structure

```
index-life-local/
├─ app/
│  ├─ modules/            # Optional modules (assistant, etc.)
│  ├─ templates/          # HTML templates
│  └─ static/             # Static files (CSS, JS, images)
├─ tools/                 # Helper scripts (module installer)
├─ config.py              # Configuration
├─ run.py                 # Application entry point
├─ requirements.txt       # Python dependencies
├─ install.bat/.sh        # Base installation
├─ start.bat/.sh          # App launch
├─ install_modules.bat/.sh# Module installer
├─ MODULES.md             # Modules guide
└─ diary.db               # SQLite database (created on first run)
```

---

## Technologies

- **Backend**: Flask 3.0.0
- **Database**: SQLite (via Flask-SQLAlchemy)
- **Frontend**: HTML, CSS, Vanilla JavaScript
- **Images**: Pillow (Python Imaging Library)
- **Optional**: llama-cpp-python, sentence-transformers

---

## FAQ

**Where is my data stored?**
In the `diary.db` file in the application directory. For backups, simply copy this file.

**Can I use this on multiple devices?**
Yes — built-in sync keeps the current version of your diary on every device through a shared folder (Dropbox, Google Drive, iCloud…) or a WebDAV link (Nextcloud, Yandex.Disk, Box…). Set it up on the **Sync** page. See [docs/en/sync.md](docs/en/sync.md). (Do **not** just share the `diary.db` file across a cloud — the built-in sync handles merging and conflicts safely.)

**Is my data encrypted?**
The database is not encrypted by default. Make sure your device is password protected.

**Do I need internet to use this?**
No, the application works completely offline on your computer.

**Can I export my data?**
Yes, all data is stored in standard SQLite format in the `diary.db` file, which can be copied and opened with any SQLite tools.

**Do I need to register or log in?**
No, just launch the application and start using it. No accounts or passwords required.

**How do I update to a new version without losing data?**
Your data lives separately from the app, so updating is just replacing the binary: on macOS drag the new `.app` over the old one, on Windows extract the new zip over your existing app folder, on Linux replace the `.AppImage`. Full step-by-step and where exactly the data lives is in the [Updating](#updating) section above. The app takes an automatic backup of your database on first launch and runs schema migrations for you.

**How do I enable the AI psychologist (or other modules)?**
Open the **Modules** page inside the app and click "Install" on the module — it works on every OS, with progress shown in the window. Restart the app afterward. (For a source install you can also run the `install_modules` script.)

**Which Python version is required?**
Python 3.12 is recommended — it matches the interpreter in the prebuilt releases and the optional modules' environment.

---

## License

index.life is licensed under the **GNU Affero General Public License v3.0
(AGPL-3.0)** — see the [LICENSE](LICENSE) file.

In short: you are free to use, study, modify, and share index.life. But if you
distribute it — or run a modified version as a network service — you must make
your full source code available under the same license. This keeps index.life
free and open for everyone and prevents it from being turned into a closed,
proprietary product.

Copyright (C) 2026 Émile Alexanyan

---

## Author

**Émile Alexanyan**

Created to help remember and understand yourself better through daily reflection.
