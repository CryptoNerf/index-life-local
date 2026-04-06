#!/bin/bash
# Install Modules.command
# Double-click this file in Finder to install optional modules for index.life
# Supports: macOS 13+ on Apple Silicon (M1/M2/M3/M4)

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
info() { echo -e "${YELLOW}→${NC} $1"; }
err()  { echo -e "${RED}✗  $1${NC}"; echo ""; read -p "Нажмите Enter для выхода..."; exit 1; }

clear
echo -e "${BOLD}"
echo "  ┌─────────────────────────────────────────┐"
echo "  │   index.life — Установка модулей        │"
echo "  │   macOS Apple Silicon (M1/M2/M3/M4)     │"
echo "  └─────────────────────────────────────────┘"
echo -e "${NC}"
echo "  Этот установщик добавит в приложение:"
echo "  • ИИ-психолог (Qwen3.5-9B, Metal GPU)  ~5 GB"
echo "  • Нейро-карта тем (Deep Mind)"
echo ""
read -p "  Начать установку? (y/n): " CONFIRM
[[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]] && echo "Отменено." && exit 0
echo ""

# ── 1. Найти index.life.app ───────────────────────────────────────────────────
echo -e "${BOLD}[1/6] Поиск приложения...${NC}"

APP_PATH=""
# Проверяем /Applications первым, потом рядом со скриптом
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for candidate in \
    "/Applications/index.life.app" \
    "$SCRIPT_DIR/index.life.app" \
    "$HOME/Applications/index.life.app"; do
    if [[ -d "$candidate" ]]; then
        APP_PATH="$candidate"
        break
    fi
done

if [[ -z "$APP_PATH" ]]; then
    err "index.life.app не найден.\nПереместите приложение в /Applications и повторите запуск."
fi
ok "Приложение: $APP_PATH"

# Путь к внутренностям .app (PyInstaller bundle)
APP_MACOS="$APP_PATH/Contents/MacOS"
APP_INTERNAL="$APP_MACOS/_internal"
INSTALL_SCRIPT="$APP_INTERNAL/tools/install_modules.py"

if [[ ! -f "$INSTALL_SCRIPT" ]]; then
    err "Файл установщика модулей не найден внутри .app.\nПоврежденное или устаревшее приложение."
fi

# modules_venv создаётся рядом с исполняемым файлом приложения
MODULES_VENV="$APP_MACOS/modules_venv"

# ── 2. Архитектура ────────────────────────────────────────────────────────────
echo -e "${BOLD}[2/6] Проверка системы...${NC}"
ARCH=$(uname -m)
[[ "$ARCH" != "arm64" ]] && err "Этот установщик только для Apple Silicon (arm64).\nОбнаружен: $ARCH"
ok "Apple Silicon (arm64)"

# ── 3. Xcode CLT и лицензия ───────────────────────────────────────────────────
echo -e "${BOLD}[3/6] Проверка инструментов разработчика...${NC}"

if ! xcode-select -p &>/dev/null; then
    info "Устанавливаем Xcode Command Line Tools..."
    xcode-select --install
    echo ""
    echo -e "${YELLOW}  После завершения установки в всплывающем окне —"
    echo -e "  закройте этот терминал и запустите установщик снова.${NC}"
    read -p "  Нажмите Enter для выхода..."
    exit 0
fi

# Проверяем лицензию через тестовую компиляцию
if ! clang -x c - -o /dev/null <<< "int main(){}" &>/dev/null 2>&1; then
    echo ""
    echo -e "${YELLOW}  ⚠ Лицензия Xcode не принята.${NC}"
    echo "  Выполните в терминале и перезапустите установщик:"
    echo ""
    echo -e "  ${BOLD}sudo xcodebuild -license accept${NC}"
    echo ""
    read -p "  Нажмите Enter для выхода..."
    exit 1
fi
ok "Xcode CLT готов"

# ── 4. Homebrew и Python 3.12 ─────────────────────────────────────────────────
echo -e "${BOLD}[4/6] Проверка Python...${NC}"

# Убедимся что Homebrew в PATH (Apple Silicon)
if [[ -f /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi

PYTHON=""
for candidate in \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/bin/python3 \
    python3.12 python3; do
    if command -v "$candidate" &>/dev/null; then
        if "$candidate" -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>/dev/null; then
            PYTHON=$(command -v "$candidate")
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    info "Python 3.10+ не найден. Устанавливаем через Homebrew..."
    if ! command -v brew &>/dev/null; then
        info "Устанавливаем Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    brew install python@3.12
    PYTHON="/opt/homebrew/bin/python3.12"
fi
ok "Python: $($PYTHON --version) — $PYTHON"

# ── 5. Создаём modules_venv ────────────────────────────────────────────────────
echo -e "${BOLD}[5/6] Настройка окружения модулей...${NC}"

if [[ -d "$MODULES_VENV" ]]; then
    ok "Окружение модулей уже существует — переиспользуем"
else
    info "Создаём modules_venv внутри приложения..."
    "$PYTHON" -m venv "$MODULES_VENV"
    ok "modules_venv создан: $MODULES_VENV"
fi

VENV_PYTHON="$MODULES_VENV/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip -q

# ── 6. Устанавливаем модули ────────────────────────────────────────────────────
echo -e "${BOLD}[6/6] Установка модулей...${NC}"
echo ""
echo "  Устанавливаем: ИИ-психолог (Metal GPU) + Нейро-карта"
echo "  Сборка llama-cpp-python займёт ~3-5 минут..."
echo ""

# Запускаем install_modules.py с нужным Python из venv
INDEXLIFE_MODULES_VENV="$MODULES_VENV" \
CMAKE_ARGS="-DGGML_METAL=on" \
FORCE_CMAKE=1 \
"$VENV_PYTHON" "$INSTALL_SCRIPT" --module assistant --profile metal --module deep_mind

if [[ $? -ne 0 ]]; then
    err "Установка завершилась с ошибкой. Попробуйте запустить установщик снова."
fi

# ── Готово ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║   Модули успешно установлены!             ║"
echo "  ║   Запустите index.life — ИИ будет готов.  ║"
echo "  ╚═══════════════════════════════════════════╝"
echo -e "${NC}"
echo ""
read -p "  Нажмите Enter для закрытия..."
