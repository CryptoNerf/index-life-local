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

- `install_modules.bat --module assistant --profile auto`
- `install_modules.bat --module assistant --profile cpu`
- `install_modules.bat --module assistant --profile vulkan`
- `install_modules.bat --module assistant --profile cuda`
- `install_modules.bat --module voice`

### Install (macOS / Linux)

- `bash install_modules.sh`

Common commands:

- `bash install_modules.sh --module assistant --profile auto`
- `bash install_modules.sh --module assistant --profile cpu`
- `bash install_modules.sh --module assistant --profile vulkan`
- `bash install_modules.sh --module assistant --profile metal`
- `bash install_modules.sh --module voice`

### Assistant profiles

| Profile | GPU | Speed | Requirements |
|---|---|---|---|
| `auto` | Auto-detect | Varies | Auto-selects best option |
| `cpu` | None | ~3-5 tok/s | Any system with 16GB RAM |
| `vulkan` | Any GPU | ~40-55 tok/s | Any GPU with Vulkan support (NVIDIA/AMD/Intel) |
| `cuda` | NVIDIA | ~40-50 tok/s | NVIDIA GPU 6GB+ VRAM, driver 452.39+ |
| `vulkan-source` | Any GPU | ~40-55 tok/s | Vulkan SDK (build from source) |
| `cuda-source` | NVIDIA | ~40-50 tok/s | CUDA Toolkit + Visual Studio (build from source) |
| `metal` | Apple | ~15-25 tok/s | Apple Silicon Mac |

**Which profile to choose?**

- `auto` — **recommended**. Automatically detects your GPU and selects the best pre-built option. No SDK needed.
- `vulkan` — pre-built wheel, works on any GPU (NVIDIA, AMD, Intel). No SDK needed.
- `cuda` — pre-built CUDA 12.4 wheels for NVIDIA GPUs. No CUDA Toolkit needed, just a modern driver (452.39+).
- `vulkan-source` / `cuda-source` — build from source. Only use if pre-built options don't work.
- `metal` — for Apple Silicon Macs.

The GGUF model (~4.7 GB) is downloaded automatically during installation.

### NVIDIA GPU requirements

- **Driver**: 452.39 or newer. Check your driver: `nvidia-smi`
- **VRAM**: 6GB minimum, 8GB+ recommended for Qwen3-8B
- **Update driver**: Download from [nvidia.com/drivers](https://www.nvidia.com/drivers/)

### Notes

- If a module exists but dependencies are missing, the app skips it and logs a message.
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

- `install_modules.bat --module assistant --profile auto`
- `install_modules.bat --module assistant --profile cpu`
- `install_modules.bat --module assistant --profile vulkan`
- `install_modules.bat --module assistant --profile cuda`
- `install_modules.bat --module voice`

### Установка (macOS / Linux)

- `bash install_modules.sh`

Частые команды:

- `bash install_modules.sh --module assistant --profile auto`
- `bash install_modules.sh --module assistant --profile cpu`
- `bash install_modules.sh --module assistant --profile vulkan`
- `bash install_modules.sh --module assistant --profile metal`
- `bash install_modules.sh --module voice`

### Профили assistant

| Профиль | GPU | Скорость | Требования |
|---|---|---|---|
| `auto` | Автодетект | Зависит от GPU | Автоматически выбирает лучший вариант |
| `cpu` | Нет | ~3-5 ток/с | Любая система с 16ГБ RAM |
| `vulkan` | Любой GPU | ~40-55 ток/с | Любой GPU с поддержкой Vulkan (NVIDIA/AMD/Intel) |
| `cuda` | NVIDIA | ~40-50 ток/с | NVIDIA GPU 6ГБ+ VRAM, драйвер 452.39+ |
| `vulkan-source` | Любой GPU | ~40-55 ток/с | Vulkan SDK (сборка из исходников) |
| `cuda-source` | NVIDIA | ~40-50 ток/с | CUDA Toolkit + Visual Studio (сборка из исходников) |
| `metal` | Apple | ~15-25 ток/с | Mac с Apple Silicon |

**Какой профиль выбрать?**

- `auto` — **рекомендуется**. Автоматически определяет GPU и выбирает лучшую готовую сборку. SDK не нужен.
- `vulkan` — готовая сборка, работает на любом GPU (NVIDIA, AMD, Intel). SDK не нужен.
- `cuda` — готовые CUDA 12.4 сборки для NVIDIA. CUDA Toolkit не нужен, только современный драйвер (452.39+).
- `vulkan-source` / `cuda-source` — сборка из исходников. Используйте только если готовые сборки не работают.
- `metal` — для Mac с Apple Silicon.

GGUF-модель (~4.7 ГБ) скачивается автоматически при установке.

### Требования для NVIDIA GPU

- **Драйвер**: 452.39 или новее. Проверить: `nvidia-smi`
- **VRAM**: минимум 6ГБ, рекомендуется 8ГБ+ для Qwen3-8B
- **Обновить драйвер**: скачайте с [nvidia.com/drivers](https://www.nvidia.com/drivers/)

### Примечания

- Если папка модуля есть, но зависимости не установлены, приложение пропустит модуль и выведет сообщение в лог.
- Для установки модулей рекомендуется Python 3.10 (поддерживается 3.8+). В Windows установщик поставит Python автоматически, если его нет.
