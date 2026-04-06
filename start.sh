#!/bin/bash
# Startup script for index.life local application (Linux/Mac)

echo "========================================"
echo "  Starting index.life Local Diary"
echo "========================================"
echo ""

# Resolve script directory so it works from any location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Run ./install.sh first."
    echo "  macOS Apple Silicon: ./install_macos_arm.sh"
    echo "  Other platforms:     ./install.sh"
    exit 1
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Check if base dependencies are installed
if ! python -c "import flask" &>/dev/null 2>&1; then
    echo "Installing base dependencies..."
    pip install -r requirements.txt -q
    echo ""
fi

# Kill any previous instance on the app port
PORT=$(python -c "from config import Config; print(Config.PORT)" 2>/dev/null || echo "5001")
PREV_PID=$(lsof -ti tcp:"$PORT" 2>/dev/null)
if [ -n "$PREV_PID" ]; then
    echo "Stopping previous instance on port $PORT (PID $PREV_PID)..."
    kill "$PREV_PID" 2>/dev/null
    sleep 1
fi

# Run the application
echo "Starting application..."
echo ""
python run.py

# Handle errors
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Application failed to start"
    echo "Try running: ./install_macos_arm.sh  (macOS Apple Silicon)"
    read -p "Press Enter to exit..."
fi
