#!/bin/bash
# Install FFmpeg for MP4 export functionality
# Supports: Ubuntu/Debian, macOS (via Homebrew), Alpine, RHEL/CentOS/Fedora

set -e

echo "════════════════════════════════════════════════════════════════════════════════"
echo "  Installing FFmpeg"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

# Check if ffmpeg is already installed
if command -v ffmpeg >/dev/null 2>&1; then
    FFMPEG_VERSION=$(ffmpeg -version 2>&1 | head -n1 | awk '{print $3}')
    echo "✓ FFmpeg is already installed: $FFMPEG_VERSION"
    echo ""
    exit 0
fi

# Detect OS and install accordingly
install_ffmpeg() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        echo "Detected: macOS"
        if command -v brew >/dev/null 2>&1; then
            echo "Installing FFmpeg via Homebrew..."
            brew install ffmpeg
        else
            echo "ERROR: Homebrew not found. Install it first:"
            echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            exit 1
        fi

    elif [ -f /etc/debian_version ] || [ -f /etc/lsb-release ]; then
        # Debian/Ubuntu
        echo "Detected: Debian/Ubuntu"
        echo "Installing FFmpeg via apt..."
        sudo apt-get update
        sudo apt-get install -y ffmpeg

    elif [ -f /etc/alpine-release ]; then
        # Alpine Linux
        echo "Detected: Alpine Linux"
        echo "Installing FFmpeg via apk..."
        sudo apk add --no-cache ffmpeg

    elif [ -f /etc/redhat-release ] || [ -f /etc/fedora-release ]; then
        # RHEL/CentOS/Fedora
        echo "Detected: RHEL/CentOS/Fedora"
        if command -v dnf >/dev/null 2>&1; then
            echo "Installing FFmpeg via dnf..."
            sudo dnf install -y ffmpeg
        elif command -v yum >/dev/null 2>&1; then
            echo "Installing FFmpeg via yum..."
            sudo yum install -y ffmpeg
        else
            echo "ERROR: Neither dnf nor yum found."
            exit 1
        fi

    elif [ -f /etc/arch-release ]; then
        # Arch Linux
        echo "Detected: Arch Linux"
        echo "Installing FFmpeg via pacman..."
        sudo pacman -S --noconfirm ffmpeg

    elif grep -qi microsoft /proc/version 2>/dev/null; then
        # Windows Subsystem for Linux (WSL)
        echo "Detected: WSL (Windows Subsystem for Linux)"
        echo "Installing FFmpeg via apt..."
        sudo apt-get update
        sudo apt-get install -y ffmpeg

    else
        echo "ERROR: Unsupported OS. Please install FFmpeg manually:"
        echo "  - Ubuntu/Debian: sudo apt install ffmpeg"
        echo "  - macOS: brew install ffmpeg"
        echo "  - Windows: Download from https://ffmpeg.org/download.html"
        exit 1
    fi
}

install_ffmpeg

# Verify installation
if command -v ffmpeg >/dev/null 2>&1; then
    FFMPEG_VERSION=$(ffmpeg -version 2>&1 | head -n1 | awk '{print $3}')
    echo ""
    echo "════════════════════════════════════════════════════════════════════════════════"
    echo "  ✅ FFmpeg installed successfully: $FFMPEG_VERSION"
    echo "════════════════════════════════════════════════════════════════════════════════"
else
    echo ""
    echo "════════════════════════════════════════════════════════════════════════════════"
    echo "  ❌ FFmpeg installation failed"
    echo "════════════════════════════════════════════════════════════════════════════════"
    exit 1
fi
