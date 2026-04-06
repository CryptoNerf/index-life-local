#!/bin/bash
# First Launch.command
# Double-click this file after dragging index.life.app to /Applications.
# It removes the macOS quarantine flag and opens the app.

GREEN='\033[0;32m'; BOLD='\033[1m'; NC='\033[0m'

clear
echo ""
echo -e "${BOLD}  index.life — Первый запуск${NC}"
echo ""

APP_PATH=""
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
    echo "  ✗ index.life.app не найден."
    echo "  Переместите приложение в /Applications и запустите снова."
    echo ""
    read -p "  Нажмите Enter для выхода..."
    exit 1
fi

echo "  Снимаем блокировку macOS..."
xattr -cr "$APP_PATH" 2>/dev/null

echo -e "  ${GREEN}✓${NC} Готово! Запускаем index.life..."
echo ""

open "$APP_PATH"
