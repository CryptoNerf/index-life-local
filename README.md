# index.life - Local Mood Diary

> **English version** | [Русская версия](README.ru.md)

A local, offline mood diary built around one daily question — **"How was my day?"**

![Version](https://img.shields.io/badge/version-3.0.0-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-green)
![Flask](https://img.shields.io/badge/flask-3.0.0-lightgrey)
![License](https://img.shields.io/badge/license-MIT-yellow)

> 📖 **Full documentation:** [docs/](docs/README.md) — the app & database, sync, modules, AI psychologist, neural map, every chart, customization.

---

## About

**index.life** is an app for tracking your mood and keeping notes about your
days. Its main goal is simple: to get you to ask yourself *"How was my day?"*
every day — and to write the answer down. I'm convinced this small daily
practice has a genuinely positive effect on people's lives. index.life is also
about archiving how you felt and what you were thinking, so you can look back
on it later.

Everything runs **locally and offline** — no accounts, no servers, no
telemetry. Your diary stays on your device.

## What's inside

Beyond the notes **calendar** and the **Markdown editor**, index.life gives you
a set of tools to support the habit:

- 🧠 **AI psychologist** — chat with a local language model that can read your
  diary: it reflects back what you write, notices patterns, and grounds its
  answers in your real entries. [Read more »](docs/en/ai-psychologist.md)
- 🌌 **Neural map of your thoughts** — your entries clustered into topics you
  can explore visually. [Read more »](docs/en/neural-map.md)
- 📊 **Charts** that visualize different aspects of your well-being over time.
  [Read more »](docs/en/graphics.md)
- 🎨 **Customization & sync** — restyle the whole interface to your taste, and
  keep your diary in step across devices.
  [Customization »](docs/en/customization.md) · [Sync »](docs/en/sync.md)

> The **AI psychologist** and **neural map** are optional modules you install on
> demand (a local model is downloaded once). The calendar, editor, charts,
> customization and sync are built in.

---

## Installation

### Option 1: Pre-built Releases (Recommended)

Download the ready-to-use version for your operating system from Releases:

**Windows:**
1. Download `index-life_windows_x64.zip`
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

**Optional modules (AI):**
- In the release folder, run `install_modules.bat` (Windows) or `install_modules.sh` (macOS/Linux).
- Python 3.10 is recommended. On Windows the installer auto-installs Python if missing.

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

**Optional modules (AI):**
- Run `install_modules.bat` / `install_modules.sh`
- See `MODULES.md` for details

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

**How do I enable the AI module?**
Run `install_modules.bat` (Windows) or `install_modules.sh` (macOS/Linux) and follow the prompts.

**Which Python version is required?**
Python 3.10 is recommended. The app also works with Python 3.8+.

---

## License

MIT License - See LICENSE file for details

---

## Author

**Émile Alexanyan**

Created to help remember and understand yourself better through daily reflection.
