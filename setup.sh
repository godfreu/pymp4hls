#!/bin/bash
# setup.sh - One-time setup script for PyMP4HLS
# This script installs dependencies and sets up the necessary directory structure

# Print a formatted message
print_message() {
    echo -e "\e[1;34m>>>\e[0m \e[1m$1\e[0m"
}

# Print error message
print_error() {
    echo -e "\e[1;31m>>>\e[0m \e[1m$1\e[0m"
}

# Check if script is run as root
if [ "$EUID" -eq 0 ]; then
    print_error "Please do not run this script as root or with sudo"
    exit 1
fi

# Working directory (where this script is located)
SCRIPT_DIR=$(dirname "$(realpath "$0")")
cd "$SCRIPT_DIR"

print_message "Setting up PyMP4HLS at $SCRIPT_DIR"

# Create necessary directories
print_message "Creating directory structure..."
mkdir -p videos/input videos/output urls uploads logs downloads conversions

# Check if Python is installed
if ! command -v python3 &>/dev/null; then
    print_error "Python 3 is not installed. Please install Python 3.10 or newer."
    exit 1
fi

# Check if pip is installed
if ! command -v pip3 &>/dev/null; then
    print_error "pip3 is not installed. Please install pip for Python 3."
    exit 1
fi

# Check if FFmpeg is installed
if ! command -v ffmpeg &>/dev/null; then
    print_error "FFmpeg is not installed. Please install FFmpeg to continue."
    print_message "You can install FFmpeg with:"
    echo "  - macOS: brew install ffmpeg"
    echo "  - Ubuntu/Debian: sudo apt-get install ffmpeg"
    echo "  - CentOS/RHEL: sudo yum install ffmpeg"
    exit 1
fi

# Install Python dependencies
print_message "Installing Python dependencies..."
pip3 install -r requirements.txt

# Check if .env file exists, create from example if not
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        print_message "Creating .env file from .env.example..."
        cp .env.example .env
        print_message "Please edit the .env file with your actual configuration values."
    else
        print_error ".env.example file not found. Please create a .env file manually."
        exit 1
    fi
fi

# Make scripts executable
print_message "Making Python scripts executable..."
chmod +x s1-urlscraper.py s2-downloader.py s3-converter.py s4-uploader.py s5-urlupdater.py

# Create empty main CSV file if it doesn't exist
if [ ! -f mp4hls-videos.csv ]; then
    print_message "Creating empty mp4hls-videos.csv file..."
    touch mp4hls-videos.csv
fi

print_message "Setup complete!"
print_message "Next steps:"
echo "1. Edit the .env file with your database and AWS credentials"
echo "2. Run the pipeline with: ./start.sh"
