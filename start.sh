#!/bin/bash
# Startup script for index.life local application (Linux/Mac)

echo "========================================"
echo "  Starting index.life Local Diary"
echo "========================================"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo ""
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Check if dependencies are installed
if ! pip show Flask &> /dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
    echo ""
fi

# Run the application
echo "Starting application..."
echo ""
python run.py

# Handle errors
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Application failed to start"
    read -p "Press Enter to exit..."
fi
