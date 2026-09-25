# Modules / Модули

[English](#english) | [Русский](#русский)

## English

This project supports optional modules. The easiest way to install one is the
**Modules** page inside the app: pick a module and press Install. Modules are
auto‑discovered at startup and enabled only if their dependencies are installed.

### Available modules

- `graphics` — Graphics: year, weekly rhythm, people, activities, weather
- `customization` — Customization: fonts, colours, background, calendar look
- `assistant` — AI Psychologist: a local language model that reads the diary
- `deep_mind` — Neural Map: the diary grouped into topics (needs `assistant`)

### AI Psychologist requirements

The model runs on your own computer, so the app only offers the install where
it can actually run:

- **Apple Silicon** (M1 or newer) with **16 GB** of memory, **or**
- an **NVIDIA GPU** with **8 GB** of video memory **plus 16 GB** of RAM;
- and **10 GB of free disk space** (4 GB if the model is already downloaded).

On other computers the Install button is disabled and the page says why. The
Neural Map needs an active AI Psychologist, so the same bar applies to it.

The model is Qwen3.5 9B (`Qwen3.5-9B-Q4_K_M.gguf`, ~5.7 GB, from
`unsloth/Qwen3.5-9B-GGUF` on Hugging Face). It is downloaded during the install.

**Advanced:** the command-line installer below checks only the free disk
space, not the hardware, and `INDEXLIFE_ALLOW_ASSISTANT=1` makes the app offer
the install anyway. Use them if you know your machine can run a 9B model (for
example a large AMD or Intel GPU, which the app cannot measure).

### Install (Windows)

- Double‑click `install_modules.bat` and follow prompts

Common commands:

- `install_modules.bat --module assistant --profile auto`
- `install_modules.bat --module assistant --profile cpu`
- `install_modules.bat --module assistant --profile vulkan`
- `install_modules.bat --module assistant --profile cuda`

### Install (macOS Apple Silicon — M1/M2/M3/M4)

**DMG users:** double-click `Install Modules.command` next to the app — it handles everything automatically.

**Source users:**

- `bash install_modules.sh --module assistant --profile metal`

### Install (macOS Intel / Linux)

- `bash install_modules.sh --module assistant --profile auto`
- `bash install_modules.sh --module assistant --profile cpu`

### Assistant profiles

| Profile | GPU | Speed | Requirements |
|---|---|---|---|
| `auto` | Auto-detect | Varies | Auto-selects best option |
| `cpu` | None | ~3-5 tok/s | 16 GB RAM; command line only, very slow |
| `vulkan` | Any GPU | ~40-55 tok/s | Any GPU with Vulkan support (NVIDIA/AMD/Intel) |
| `cuda` | NVIDIA | ~40-50 tok/s | NVIDIA GPU 8 GB+ VRAM, 16 GB RAM, driver 452.39+ |
| `vulkan-source` | Any GPU | ~40-55 tok/s | Vulkan SDK (build from source) |
| `cuda-source` | NVIDIA | ~40-50 tok/s | CUDA Toolkit + Visual Studio (build from source) |
| `metal` | Apple | ~15-25 tok/s | Apple Silicon Mac with 16 GB memory |

**Which profile to choose?**

- `auto` — **recommended**. Automatically detects your GPU and selects the best pre-built option. No SDK needed.
- `vulkan` — pre-built wheel, works on any GPU (NVIDIA, AMD, Intel). No SDK needed.
- `cuda` — pre-built CUDA 12.4 wheels for NVIDIA GPUs. No CUDA Toolkit needed, just a modern driver (452.39+).
- `vulkan-source` / `cuda-source` — build from source. Only use if pre-built options don't work.
- `metal` — for Apple Silicon Macs.

The GGUF model (~5.7 GB) is downloaded automatically during installation.

`cpu` and `vulkan` on AMD/Intel GPUs are for the command-line installer: the
app itself only offers the AI Psychologist on Apple Silicon or NVIDIA (see the
requirements above). On the CPU alone a 9B model is very slow.

### NVIDIA GPU requirements

- **Driver**: 452.39 or newer. Check your driver: `nvidia-smi`
- **VRAM**: 8 GB minimum, plus 16 GB of system RAM
- **Update driver**: Download from [nvidia.com/drivers](https://www.nvidia.com/drivers/)

### Notes

- If a module exists but dependencies are missing, the app skips it and logs a message.
- Python 3.10 is recommended (3.8+ supported). The installer will auto-install Python if missing on Windows.

---

## Русский

Проект поддерживает опциональные модули. Проще всего ставить их со страницы
**«Модули»** внутри приложения: выберите модуль и нажмите «Установить». Модули
автоматически обнаруживаются при запуске и включаются, только если установлены
их зависимости.

### Доступные модули

- `graphics` — Графики: год, недельный ритм, люди, занятия, погода
- `customization` — Кастомизация: шрифты, цвета, фон, вид календаря
- `assistant` — AI-психолог: локальная языковая модель, которая читает дневник
- `deep_mind` — Нейронная карта: дневник, собранный в темы (нужен `assistant`)

### Требования AI-психолога

Модель работает на вашем компьютере, поэтому приложение предлагает установку
только там, где она действительно запустится:

- **Apple Silicon** (M1 и новее) с **16 ГБ** памяти, **или**
- **видеокарта NVIDIA** с **8 ГБ** видеопамяти **и 16 ГБ** оперативной памяти;
- и **10 ГБ свободного места на диске** (4 ГБ, если модель уже скачана).

На других компьютерах кнопка «Установить» неактивна, а страница объясняет
почему. Нейронной карте нужен работающий AI-психолог, поэтому к ней относятся
те же требования.

Модель — Qwen3.5 9B (`Qwen3.5-9B-Q4_K_M.gguf`, ~5,7 ГБ, из
`unsloth/Qwen3.5-9B-GGUF` на Hugging Face). Она скачивается во время установки.

**Для опытных:** установщик из командной строки (ниже) проверяет только
свободное место, но не железо, а переменная `INDEXLIFE_ALLOW_ASSISTANT=1`
заставляет приложение предложить установку в любом случае. Пользуйтесь ими,
если знаете, что ваш компьютер потянет модель на 9B (например, мощная
видеокарта AMD или Intel, которую приложение измерить не умеет).

### Установка (Windows)

- Двойной клик по `install_modules.bat` и следуйте подсказкам

Частые команды:

- `install_modules.bat --module assistant --profile auto`
- `install_modules.bat --module assistant --profile cpu`
- `install_modules.bat --module assistant --profile vulkan`
- `install_modules.bat --module assistant --profile cuda`

### Установка (macOS / Linux)

- `bash install_modules.sh`

Частые команды:

- `bash install_modules.sh --module assistant --profile auto`
- `bash install_modules.sh --module assistant --profile cpu`
- `bash install_modules.sh --module assistant --profile vulkan`
- `bash install_modules.sh --module assistant --profile metal`

### Профили assistant

| Профиль | GPU | Скорость | Требования |
|---|---|---|---|
| `auto` | Автодетект | Зависит от GPU | Автоматически выбирает лучший вариант |
| `cpu` | Нет | ~3-5 ток/с | 16 ГБ RAM; только из командной строки, очень медленно |
| `vulkan` | Любой GPU | ~40-55 ток/с | Любой GPU с поддержкой Vulkan (NVIDIA/AMD/Intel) |
| `cuda` | NVIDIA | ~40-50 ток/с | NVIDIA GPU 8 ГБ+ VRAM, 16 ГБ RAM, драйвер 452.39+ |
| `vulkan-source` | Любой GPU | ~40-55 ток/с | Vulkan SDK (сборка из исходников) |
| `cuda-source` | NVIDIA | ~40-50 ток/с | CUDA Toolkit + Visual Studio (сборка из исходников) |
| `metal` | Apple | ~15-25 ток/с | Mac с Apple Silicon и 16 ГБ памяти |

**Какой профиль выбрать?**

- `auto` — **рекомендуется**. Автоматически определяет GPU и выбирает лучшую готовую сборку. SDK не нужен.
- `vulkan` — готовая сборка, работает на любом GPU (NVIDIA, AMD, Intel). SDK не нужен.
- `cuda` — готовые CUDA 12.4 сборки для NVIDIA. CUDA Toolkit не нужен, только современный драйвер (452.39+).
- `vulkan-source` / `cuda-source` — сборка из исходников. Используйте только если готовые сборки не работают.
- `metal` — для Mac с Apple Silicon.

GGUF-модель (~5,7 ГБ) скачивается автоматически при установке.

Профили `cpu` и `vulkan` на видеокартах AMD/Intel доступны только через
установщик из командной строки: само приложение предлагает AI-психолога лишь на
Apple Silicon и NVIDIA (см. требования выше). Только на процессоре модель на 9B
работает очень медленно.

### Требования для NVIDIA GPU

- **Драйвер**: 452.39 или новее. Проверить: `nvidia-smi`
- **VRAM**: минимум 8 ГБ, плюс 16 ГБ оперативной памяти
- **Обновить драйвер**: скачайте с [nvidia.com/drivers](https://www.nvidia.com/drivers/)

### Примечания

- Если папка модуля есть, но зависимости не установлены, приложение пропустит модуль и выведет сообщение в лог.
- Для установки модулей рекомендуется Python 3.10 (поддерживается 3.8+). В Windows установщик поставит Python автоматически, если его нет.
