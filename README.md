# index.life - Local Mood Diary

> **English version** | [Русская версия](README.ru.md)

A mood tracker app designed to help people remember and become more aware of themselves and their time.

![Version](https://img.shields.io/badge/version-2.1.0-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-green)
![Flask](https://img.shields.io/badge/flask-3.0.0-lightgrey)
![License](https://img.shields.io/badge/license-MIT-yellow)

---

## Installation

### Option 1: Pre-built Releases (Recommended)

Download the ready-to-use version for your operating system from Releases:

**Windows:**
1. Download `index-life_windows_x64.zip`
2. Unzip the archive
3. Run `index-life.exe`

> On first launch, Windows may show an "Unrecognized Publisher" warning. This is normal for applications without a paid digital signature. Click "More info" → "Run anyway".

**macOS:**
1. Download `index-life_macos.dmg`
2. Open the DMG file and drag the application to your Applications folder
3. **Important!** macOS blocks unsigned apps. Open Terminal and run:
   ```bash
   xattr -d com.apple.quarantine /Applications/index.life.app
   ```
4. Now launch index.life from Applications

> The app will start the Flask server in the background and automatically open your browser.

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

**Optional modules (AI + Voice):**
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

**Optional modules (AI + Voice):**
- Run `install_modules.bat` / `install_modules.sh`
- See `MODULES.md` for details

---

## Features

- Calendar with visual heatmap of all your entries
- Daily entries with mood rating (1-10) and notes
- Statistics showing average mood and total entries
- Profile with name, email, and photo
- 100% privacy - all data stored locally (SQLite)
- Works completely offline
- Simple web interface
- Optional AI psychologist chat and voice dictation (after installing modules)

---

## Project Structure

```
index-life-local/
├─ app/
│  ├─ modules/            # Optional modules (assistant, voice)
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
- **Optional**: llama-cpp-python, sentence-transformers, faster-whisper

---

## FAQ

**Where is my data stored?**
In the `diary.db` file in the application directory. For backups, simply copy this file.

**Can I use this on multiple devices?**
This is a local-only application. For syncing between devices, you can use cloud storage (Dropbox, Google Drive) for the `diary.db` file.

**Is my data encrypted?**
The database is not encrypted by default. Make sure your device is password protected.

**Do I need internet to use this?**
No, the application works completely offline on your computer.

**Can I export my data?**
Yes, all data is stored in standard SQLite format in the `diary.db` file, which can be copied and opened with any SQLite tools.

**Do I need to register or log in?**
No, just launch the application and start using it. No accounts or passwords required.

**How do I enable AI and voice modules?**
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
