#!/bin/bash
# start.sh - Script to run the PyMP4HLS conversion pipeline
# This script runs all 5 steps of the pipeline sequentially

# Working directory (where this script is located)
SCRIPT_DIR=$(dirname "$(realpath "$0")")
cd "$SCRIPT_DIR"

# Color formatting
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Print a formatted message
print_step() {
    echo -e "${BLUE}${BOLD}=== STEP $1: $2 ===${NC}"
}

print_success() {
    echo -e "${GREEN}${BOLD}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}${BOLD}✗ ERROR: $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}${BOLD}! $1${NC}"
}

# Load environment variables from .env file
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo -e "${GREEN}Loaded environment variables from .env${NC}"
else
    print_error ".env file not found. Please run setup.sh first."
    exit 1
fi

# Ensure all required directories exist
mkdir -p videos/input videos/output urls uploads logs downloads conversions

# Helper function to run a script and check for errors
run_script() {
    local script_name=$1
    local step_number=$2
    local step_description=$3
    
    print_step "$step_number" "$step_description"
    echo "Starting $script_name at $(date)"
    
    # Run the script
    python3 "$script_name"
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        print_success "$script_name completed successfully"
    else
        print_error "$script_name failed with exit code $exit_code"
        echo -e "${YELLOW}Check logs/$(basename "$script_name" .py).log for details${NC}"
        echo -e "${YELLOW}Pipeline will continue with the next step${NC}"
    fi
    
    echo ""
}

# Main pipeline execution
echo -e "${BOLD}Starting PyMP4HLS Pipeline at $(date)${NC}"
echo "Working directory: $SCRIPT_DIR"
echo "Log files will be stored in: $SCRIPT_DIR/logs/"
echo ""

# Step 1: URL Scraper
run_script "s1-urlscraper.py" "1" "URL Scraper"

# Step 2: Downloader
run_script "s2-downloader.py" "2" "Downloader"

# Step 3: Converter
run_script "s3-converter.py" "3" "Converter"

# Step 4: Uploader
run_script "s4-uploader.py" "4" "Uploader"

# Step 5: URL Updater
run_script "s5-urlupdater.py" "5" "URL Updater"

echo -e "${BOLD}PyMP4HLS Pipeline completed at $(date)${NC}"
echo -e "${GREEN}${BOLD}All steps have been executed.${NC}"
echo "Check the log files in $SCRIPT_DIR/logs/ for detailed information on each step."
