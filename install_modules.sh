#!/usr/bin/env bash
set -euo pipefail

PYTHON="python3"
if [ -x "venv/bin/python" ]; then
  PYTHON="venv/bin/python"
else
  if [ -z "${INDEXLIFE_MODULES_VENV:-}" ]; then
    export INDEXLIFE_MODULES_VENV="modules_venv"
  fi
fi

install_python() {
  echo ""
  echo "[1/3] Detecting operating system..."

  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Operating System: macOS"
    echo ""
    if ! command -v brew &> /dev/null; then
      echo "[2/3] Installing Homebrew first..."
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install Homebrew"
        return 1
      fi
    fi
    echo "[2/3] Installing Python 3 via Homebrew..."
    brew install python3
    if [ $? -ne 0 ]; then
      echo "ERROR: Failed to install Python"
      return 1
    fi
  elif [[ -f /etc/debian_version ]]; then
    echo "Operating System: Debian/Ubuntu"
    echo ""
    echo "[2/3] Installing Python 3..."
    sudo apt update
    sudo apt install -y python3 python3-venv python3-pip
    if [ $? -ne 0 ]; then
      echo "ERROR: Failed to install Python"
      return 1
    fi
  elif [[ -f /etc/redhat-release ]]; then
    echo "Operating System: Fedora/RHEL/CentOS"
    echo ""
    echo "[2/3] Installing Python 3..."
    sudo dnf install -y python3 python3-pip
    if [ $? -ne 0 ]; then
      echo "ERROR: Failed to install Python"
      return 1
    fi
  elif [[ -f /etc/arch-release ]]; then
    echo "Operating System: Arch Linux"
    echo ""
    echo "[2/3] Installing Python 3..."
    sudo pacman -S --noconfirm python python-pip
    if [ $? -ne 0 ]; then
      echo "ERROR: Failed to install Python"
      return 1
    fi
  else
    echo "ERROR: Unsupported operating system"
    echo "Please install Python 3.10+ manually (3.8+ supported)"
    return 1
  fi

  echo ""
  echo "[3/3] Verifying installation..."
  if command -v python3 &> /dev/null; then
    python3 --version
    return 0
  fi
  echo "ERROR: Python installation verification failed"
  return 1
}

python_ok=0
if command -v python3 &> /dev/null; then
  python3 - <<'PY'
import sys
sys.exit(0 if sys.version_info >= (3, 8) else 1)
PY
  if [ $? -eq 0 ]; then
    python_ok=1
  fi
fi

if [ $python_ok -ne 1 ]; then
  echo "Python 3.10 is recommended to install modules (3.8+ supported)."
  echo "Python not found or too old. Installing..."
  install_python
fi

"$PYTHON" tools/install_modules.py "$@"
