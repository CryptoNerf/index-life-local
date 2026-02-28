# Modules / Модули

[English](#english) | [Русский](#русский)

## English

This project supports optional modules. You can add or remove them by copying
module folders into `app/modules/`. Modules are auto‑discovered at startup and
enabled only if their dependencies are installed.

### Available modules

- `assistant` — AI psychologist chat
- `voice` — voice dictation for notes

### Install (Windows)

- Double‑click `install_modules.bat` and follow prompts

Common commands:
- `install_modules.bat --module assistant --profile cpu`
- `install_modules.bat --module assistant --profile cuda --cuda-version 121`
- `install_modules.bat --module voice`

### Install (macOS / Linux)

- `bash install_modules.sh`

Common commands:
- `bash install_modules.sh --module assistant --profile cpu`
- `bash install_modules.sh --module assistant --profile metal`
- `bash install_modules.sh --module voice`

### Notes

- If a module exists but dependencies are missing, the app skips it and logs a message.
- The `assistant` module requires a GGUF model file in `app/modules/assistant/models/`.
- When using the packaged app (EXE/DMG), the installer creates `modules_venv` next to the app.
  The app will load module dependencies from that folder.
- Python 3.10 is recommended (3.8+ supported). The installer will auto-install Python if missing on Windows.

---

## Русский

Проект поддерживает опциональные модули. Вы можете добавлять или удалять их,
копируя папки модулей в `app/modules/`. Модули автоматически обнаруживаются
при запуске и включаются только если установлены зависимости.

### Доступные модули

- `assistant` — чат‑психолог
- `voice` — голосовая диктовка заметок

### Установка (Windows)

- Двойной клик по `install_modules.bat` и следуйте подсказкам

Частые команды:
- `install_modules.bat --module assistant --profile cpu`
- `install_modules.bat --module assistant --profile cuda --cuda-version 121`
- `install_modules.bat --module voice`

### Установка (macOS / Linux)

- `bash install_modules.sh`

Частые команды:
- `bash install_modules.sh --module assistant --profile cpu`
- `bash install_modules.sh --module assistant --profile metal`
- `bash install_modules.sh --module voice`

### Примечания

- Если папка модуля есть, но зависимости не установлены, приложение пропустит модуль и выведет сообщение в лог.
- Для модуля `assistant` нужен GGUF‑файл модели в `app/modules/assistant/models/`.
- При использовании готовой сборки (EXE/DMG) установщик создаёт `modules_venv` рядом с приложением.
  Приложение подхватит зависимости модулей из этой папки.
- Для установки модулей рекомендуется Python 3.10 (поддерживается 3.8+). В Windows установщик поставит Python автоматически, если его нет.
