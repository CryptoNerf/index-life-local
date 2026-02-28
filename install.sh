#!/bin/bash
# Installation script for index.life local application (Linux/Mac)
# Now with automatic Python installation!

echo "========================================"
echo "  index.life - Installation"
echo "========================================"
echo ""

# Function to install Python automatically
install_python() {
    echo ""
    echo "[1/3] Detecting operating system..."

    # Detect OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        echo "Operating System: macOS"
        echo ""

        # Check if Homebrew is installed
        if ! command -v brew &> /dev/null; then
            echo "[2/3] Installing Homebrew first..."
            echo "This may take a few minutes..."
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
        # Debian/Ubuntu
        echo "Operating System: Debian/Ubuntu"
        echo ""
        echo "[2/3] Installing Python 3..."
        echo "This requires administrator privileges (sudo)"

        sudo apt update
        sudo apt install -y python3 python3-venv python3-pip

        if [ $? -ne 0 ]; then
            echo "ERROR: Failed to install Python"
            return 1
        fi

    elif [[ -f /etc/redhat-release ]]; then
        # Fedora/RHEL/CentOS
        echo "Operating System: Fedora/RHEL/CentOS"
        echo ""
        echo "[2/3] Installing Python 3..."
        echo "This requires administrator privileges (sudo)"

        sudo dnf install -y python3 python3-pip

        if [ $? -ne 0 ]; then
            echo "ERROR: Failed to install Python"
            return 1
        fi

    elif [[ -f /etc/arch-release ]]; then
        # Arch Linux
        echo "Operating System: Arch Linux"
        echo ""
        echo "[2/3] Installing Python 3..."
        echo "This requires administrator privileges (sudo)"

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
        echo "Python installed successfully!"
        python3 --version
        return 0
    else
        echo "ERROR: Python installation verification failed"
        return 1
    fi
}

# Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed. Starting automatic installation..."
    echo ""
    echo "This will install Python 3 automatically."
    echo "Installation will take a few minutes and may require administrator privileges."
    echo ""
    read -p "Continue with automatic Python installation? (y/n): " CONFIRM

    if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
        echo ""
        echo "Installation cancelled. Please install Python manually:"
        echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
        echo "  Fedora/RHEL:   sudo dnf install python3 python3-pip"
        echo "  Arch Linux:    sudo pacman -S python python-pip"
        echo "  macOS:         brew install python3"
        echo ""
        exit 1
    fi

    install_python

    if [ $? -ne 0 ]; then
        echo ""
        echo "ERROR: Python installation failed"
        echo "Please install Python manually using the commands above"
        exit 1
    fi

    echo ""
    echo "Python has been installed successfully!"
    echo ""
fi

echo "Python found:"
python3 --version
echo ""

# Create virtual environment
if [ -d "venv" ]; then
    echo "Virtual environment already exists."
    read -p "Recreate virtual environment? (y/n): " RECREATE
    if [ "$RECREATE" = "y" ] || [ "$RECREATE" = "Y" ]; then
        echo "Removing old virtual environment..."
        rm -rf venv
    fi
fi

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo ""
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
python -m pip install --upgrade pip
echo ""

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt
echo ""

echo "========================================"
echo "Installation completed successfully!"
echo "========================================"
echo ""
echo "To start the application, run:"
echo "  ./start.sh"
echo ""
echo "Make sure to make it executable first:"
echo "  chmod +x start.sh"
echo ""
