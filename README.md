# index.life - Local Mood Diary

> **English version** | [🇷🇺 Русская версия](README.ru.md)

A private, offline mood tracking application that runs entirely on your computer.

![Version](https://img.shields.io/badge/version-2.0.0--local-blue)
![Python](https://img.shields.io/badge/python-3.8+-green)
![Flask](https://img.shields.io/badge/flask-3.0.0-lightgrey)
![License](https://img.shields.io/badge/license-MIT-yellow)

## Features

- 📅 **Calendar View** - Visual heatmap-inspired calendar showing all your mood entries
- ✍️ **Daily Entries** - Rate your day (1-10) and add personal notes
- 📊 **Statistics** - Track your average mood and total entries
- 👤 **Profile** - Customize with your name, email, and photo
- 🔒 **100% Private** - All data stored locally on your device (SQLite)
- 🚀 **Easy to Use** - Simple web interface, no installation complexity

## Quick Start

### Windows

1. Double-click `install.bat` (first time)
   - ✨ If Python is not installed, the script will offer to install it automatically!
   - Just agree, wait a few minutes, and run it again
2. Double-click `start.bat`
3. Browser opens automatically at `http://localhost:5000`

### Linux/Mac

```bash
chmod +x install.sh start.sh
./install.sh  # First run (Python will install automatically if needed)
./start.sh    # Subsequent runs
```

That's it! 🎉

> 💡 **Automatic Python Installation**:
> - **Windows**: `install.bat` installs Python automatically
> - **Linux/Mac**: `install.sh` installs Python via your package manager (apt, dnf, pacman, or brew)
> - Just agree when prompted and enter your sudo password if requested

## Manual Installation

> ⚠️ **Usually not needed!** Automatic installation scripts work on all platforms.

If automatic scripts don't work for some reason:

### Requirements

- Python 3.8 or higher (installation scripts install automatically)
- pip (Python package manager)

### Installation Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/index-life-local.git
   cd index-life-local
   ```

2. **Create virtual environment** (optional but recommended)
   ```bash
   python -m venv venv

   # Windows
   venv\Scripts\activate

   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**
   ```bash
   python run.py
   ```

5. **Open in browser**
   Navigate to: `http://127.0.0.1:5000`

## Usage

### Adding Entries

1. Click on any day in the calendar
2. Select your mood rating (1-10) by clicking the cubes
3. Add optional notes about your day
4. Click "Save"

### Viewing Statistics

Go to **Account** page to see:
- Your average mood rating
- Total number of entries
- Upload a profile photo

### Backing Up Data

Your data is stored in `diary.db`. To backup:

```bash
# Windows
copy diary.db backups\diary_backup_%date%.db

# Linux/Mac
cp diary.db backups/diary_backup_$(date +%Y%m%d).db
```

## Configuration

Edit `config.py` to customize:

- **PORT**: Change server port (default: 5000)
- **AUTO_OPEN_BROWSER**: Auto-open browser on startup (default: True)
- **MAX_CONTENT_LENGTH**: Max upload file size (default: 16MB)

## Project Structure

```
index-life-local/
├── app/
│   ├── __init__.py          # Flask app initialization
│   ├── models.py            # Database models
│   ├── routes.py            # Application routes
│   ├── templates/           # HTML templates
│   │   ├── mood_grid.html
│   │   ├── edit_day.html
│   │   ├── account.html
│   │   └── what_is_index.html
│   └── static/              # Static files (CSS, images)
├── config.py                # Configuration
├── run.py                   # Application entry point
├── requirements.txt         # Python dependencies
├── install.bat/sh           # Installation scripts
├── start.bat/sh             # Startup scripts
└── diary.db                 # SQLite database (created on first run)
```

## Technologies

- **Backend**: Flask 3.0.0
- **Database**: SQLite (via Flask-SQLAlchemy)
- **Frontend**: HTML, CSS, Vanilla JavaScript
- **Images**: Pillow (Python Imaging Library)

## Migrating from Django Version

If you're migrating from the Django/VPS version:

1. Export your data using the provided `convert_django_dump.py` script
2. Run `python import_data.py your_export.json`
3. Your data will be imported into the local database

See the migration scripts in the repository for details.

## Development

### Running in Debug Mode

Edit `config.py`:

```python
DEBUG = True
```

Then run:

```bash
python run.py
```

### Building Standalone Executable

```bash
pyinstaller build.spec
```

The executable will be in `dist/index-life/`

## FAQ

**Q: Do I need to install Python before running?**
A: No! Just run the installation script (`install.bat` for Windows or `install.sh` for Linux/Mac) - it will automatically install Python if it's not present. On Linux/Mac you may need to enter your sudo password. No additional steps needed!

**Q: Where is my data stored?**
A: In `diary.db` SQLite database file in the application directory.

**Q: Can I access this from multiple devices?**
A: This is a local-only application. For multi-device access, consider syncing the `diary.db` file via cloud storage.

**Q: Is my data encrypted?**
A: The database is not encrypted by default. Keep your device secure.

**Q: Can I export my data?**
A: Yes, the `diary.db` file can be backed up and the data is in standard SQLite format.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - See LICENSE file for details

## Author

**Émile Alexanyan**

Created to help remember and understand yourself better through daily reflection.

## Acknowledgments

- Inspired by GitHub's contribution heatmap
- Built with love and the need for privacy

---

**Note**: This is a personal diary application. All data stays on your local device.
