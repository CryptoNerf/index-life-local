#!/bin/bash
# install_macos_arm.sh — One-command installer for index.life on macOS Apple Silicon
# Tested on: macOS 14+ (Sonoma/Sequoia/Tahoe), M1/M2/M3/M4 chips
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $1"; }
info() { echo -e "${YELLOW}→${NC} $1"; }
err()  { echo -e "${RED}✗ ERROR:${NC} $1"; exit 1; }
step() { echo ""; echo -e "${BOLD}$1${NC}"; }

echo ""
echo -e "${BOLD}========================================"
echo "  index.life — macOS Apple Silicon Setup"
echo -e "========================================${NC}"
echo ""

# ── 1. Architecture check ────────────────────────────────────────────────────
step "[1/7] Checking system..."
ARCH=$(uname -m)
if [[ "$ARCH" != "arm64" ]]; then
    err "This script is for Apple Silicon (arm64). Detected: $ARCH\nFor Intel Macs use: ./install.sh"
fi
ok "Apple Silicon detected (${ARCH})"
sw_vers -productName && sw_vers -productVersion

# ── 2. Xcode Command Line Tools & license ────────────────────────────────────
step "[2/7] Checking Xcode tools..."
if ! xcode-select -p &>/dev/null; then
    info "Installing Xcode Command Line Tools..."
    xcode-select --install
    echo "  Please complete the Xcode CLT installation popup, then re-run this script."
    exit 0
fi
ok "Xcode CLT found: $(xcode-select -p)"

# Check if Xcode license is accepted (needed to compile llama-cpp-python)
if ! clang --version &>/dev/null 2>&1 || clang --version 2>&1 | grep -qi "license"; then
    echo ""
    echo -e "${YELLOW}⚠ Xcode license not yet accepted. Run this once, then re-run installer:${NC}"
    echo ""
    echo "    sudo xcodebuild -license accept"
    echo ""
    exit 1
fi
ok "Xcode license accepted"

# ── 3. Homebrew ───────────────────────────────────────────────────────────────
step "[3/7] Checking Homebrew..."
if ! command -v brew &>/dev/null; then
    info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add Homebrew to PATH for this session (Apple Silicon default path)
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi
ok "Homebrew: $(brew --version | head -1)"

# Ensure Homebrew ARM path is active
eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true

# ── 4. cmake (required to build llama-cpp-python with Metal) ─────────────────
step "[4/7] Checking cmake..."
if ! command -v cmake &>/dev/null; then
    info "Installing cmake via Homebrew..."
    brew install cmake
fi
ok "cmake: $(cmake --version | head -1)"

# ── 5. Python 3.12 ───────────────────────────────────────────────────────────
step "[5/7] Checking Python..."

# Prefer Homebrew Python 3.12 on Apple Silicon (best compatibility)
PYTHON=""
for candidate in \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/bin/python3 \
    python3.12 \
    python3; do
    if command -v "$candidate" &>/dev/null; then
        VER=$("$candidate" -c "import sys; print(sys.version_info[:2])")
        if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    info "Python 3.10+ not found. Installing Python 3.12 via Homebrew..."
    brew install python@3.12
    PYTHON="/opt/homebrew/bin/python3.12"
fi

ok "Python: $($PYTHON --version) — $PYTHON"

# ── 6. Virtual environment & base dependencies ────────────────────────────────
step "[6/7] Setting up environment..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -d "venv" ]]; then
    ok "Virtual environment already exists — reusing"
else
    info "Creating virtual environment..."
    "$PYTHON" -m venv venv
    ok "Virtual environment created"
fi

source venv/bin/activate
python -m pip install --upgrade pip -q
ok "pip upgraded: $(pip --version | awk '{print $2}')"

info "Installing base dependencies..."
pip install -r requirements.txt -q
ok "Base dependencies installed"

# ── 7. AI Psychologist module (Metal GPU) ─────────────────────────────────────
step "[7/7] Installing AI Psychologist module (Metal GPU)..."

# Install Python deps for assistant
info "Installing sentence-transformers & numpy..."
pip install "sentence-transformers>=2.2.0" "numpy>=1.24.0" -q
ok "sentence-transformers installed"

# Build llama-cpp-python with Metal support
if python -c "import llama_cpp" &>/dev/null 2>&1; then
    ok "llama-cpp-python already installed — skipping build"
else
    info "Building llama-cpp-python with Metal GPU support (this takes 2-5 min)..."
    CMAKE_ARGS="-DGGML_METAL=on" FORCE_CMAKE=1 \
        pip install "llama-cpp-python>=0.2.0,!=0.3.16" --no-cache-dir
    ok "llama-cpp-python built with Metal"
fi

# Download model
MODELS_DIR="app/modules/assistant/models"
MODEL_FILE="$MODELS_DIR/Qwen3.5-9B-Q4_K_M.gguf"
MODEL_URL="https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf"

mkdir -p "$MODELS_DIR"

if ls "$MODELS_DIR"/*.gguf &>/dev/null 2>&1; then
    ok "Model already present: $(ls $MODELS_DIR/*.gguf | xargs basename)"
else
    echo ""
    info "Downloading Qwen3.5-9B-Q4_K_M.gguf (~5 GB)..."
    echo "  This may take 5-20 minutes depending on your connection."
    echo ""
    python - <<PY
import urllib.request, shutil, sys
from pathlib import Path

url = "$MODEL_URL"
dest = Path("$MODEL_FILE")
tmp = dest.with_suffix(".gguf.downloading")

def progress(block, bsize, total):
    done = block * bsize
    if total > 0:
        pct = min(100, done * 100 // total)
        mb, total_mb = done / 1024**2, total / 1024**2
        bar = '█' * (pct // 4) + '░' * (25 - pct // 4)
        print(f"\r  [{bar}] {pct:3d}% — {mb:.0f}/{total_mb:.0f} MB", end="", flush=True)

urllib.request.urlretrieve(url, str(tmp), reporthook=progress)
print()
shutil.move(str(tmp), str(dest))
print(f"  Saved: {dest.name}")
PY
    ok "Model downloaded"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}========================================"
echo "  Installation complete!"
echo -e "========================================${NC}"
echo ""
echo "Start the app:"
echo ""
echo -e "    ${BOLD}./start.sh${NC}"
echo ""
echo "Or with one line:"
echo ""
echo -e "    ${BOLD}source venv/bin/activate && python run.py${NC}"
echo ""
