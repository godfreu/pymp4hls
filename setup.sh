#!/usr/bin/env bash
# setup.sh - One-time setup script for PyMP4HLS (Windows/macOS/Linux)

set -euo pipefail

print_message() {
  echo -e "\e[1;34m>>>\e[0m \e[1m$1\e[0m"
}

print_error() {
  echo -e "\e[1;31m>>>\e[0m \e[1m$1\e[0m"
}

print_warning() {
  echo -e "\e[1;33m>>>\e[0m \e[1m$1\e[0m"
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$SCRIPT_DIR"

if [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ]; then
  print_error "Please do not run this script as root or with sudo."
  exit 1
fi

resolve_base_python() {
  if [ -n "${LEARNEXT_PYTHON:-}" ]; then
    echo "$LEARNEXT_PYTHON"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  return 1
}

resolve_venv_python() {
  if [ -x "$SCRIPT_DIR/venv/Scripts/python.exe" ]; then
    echo "$SCRIPT_DIR/venv/Scripts/python.exe"
    return 0
  fi
  if [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
    echo "$SCRIPT_DIR/venv/bin/python"
    return 0
  fi
  return 1
}

print_message "Setting up PyMP4HLS at $SCRIPT_DIR"

print_message "Creating directory structure..."
mkdir -p videos/input videos/output urls uploads logs downloads conversions

if ! command -v ffmpeg >/dev/null 2>&1; then
  print_error "FFmpeg is not installed. Please install FFmpeg before continuing."
  print_message "Install hint:"
  echo "  - Windows (choco): choco install ffmpeg"
  echo "  - macOS: brew install ffmpeg"
  echo "  - Ubuntu/Debian: sudo apt-get install ffmpeg"
  exit 1
fi

if ! resolve_venv_python >/dev/null 2>&1; then
  BASE_PYTHON="$(resolve_base_python || true)"
  if [ -z "${BASE_PYTHON:-}" ]; then
    print_error "Python is not installed. Install Python 3.10+ first."
    exit 1
  fi
  print_message "Creating virtual environment with: $BASE_PYTHON"
  "$BASE_PYTHON" -m venv venv
fi

VENV_PYTHON="$(resolve_venv_python || true)"
if [ -z "${VENV_PYTHON:-}" ]; then
  print_error "Could not find venv Python interpreter after creation."
  exit 1
fi

print_message "Using Python: $VENV_PYTHON"
print_message "Installing Python dependencies..."
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r requirements.txt

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    print_message "Creating .env file from .env.example..."
    cp .env.example .env
    print_warning "Please edit .env with your actual values."
  else
    print_warning ".env.example not found. Create .env manually before running pipeline."
  fi
fi

print_message "Making scripts executable..."
chmod +x setup.sh start.sh get-pip.py s1-urlscraper.py s2-downloader.py s3-converter.py s4-uploader.py s5-urlupdater.py
if [ -d ".agents/skills" ]; then
  chmod +x .agents/skills/*.py 2>/dev/null || true
fi

if [ ! -f mp4hls-videos.csv ]; then
  print_message "Creating empty mp4hls-videos.csv..."
  touch mp4hls-videos.csv
fi

print_message "Setup complete."
print_message "Next steps:"
echo "1. (Windows Git Bash) source venv/Scripts/activate"
echo "2. (macOS/Linux) source venv/bin/activate"
echo "3. Edit .env"
echo "4. Run: ./start.sh"
