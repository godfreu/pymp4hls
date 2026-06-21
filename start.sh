#!/usr/bin/env bash
# start.sh - Run PyMP4HLS pipeline (agentic by default)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
BOLD='\033[1m'

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

resolve_python_cmd() {
  if [ -n "${LEARNEXT_PYTHON:-}" ]; then
    echo "$LEARNEXT_PYTHON"
    return 0
  fi
  if [ -x "$SCRIPT_DIR/venv/Scripts/python.exe" ]; then
    echo "$SCRIPT_DIR/venv/Scripts/python.exe"
    return 0
  fi
  if [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
    echo "$SCRIPT_DIR/venv/bin/python"
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

run_legacy_pipeline() {
  local py="$1"
  local steps=(
    "s1-urlscraper.py|URL Scraper"
    "s2-downloader.py|Downloader"
    "s3-converter.py|Converter"
    "s4-uploader.py|Uploader"
    "s5-urlupdater.py|URL Updater"
  )

  mkdir -p videos/input videos/output urls uploads logs downloads conversions

  echo -e "${BOLD}Starting PyMP4HLS Legacy Pipeline at $(date)${NC}"
  echo "Using Python: $py"
  echo ""

  local idx=1
  for row in "${steps[@]}"; do
    local script="${row%%|*}"
    local desc="${row##*|}"
    print_step "$idx" "$desc"
    echo "Starting $script at $(date)"
    if "$py" "$script"; then
      print_success "$script completed successfully"
    else
      local exit_code=$?
      print_error "$script failed with exit code $exit_code"
      echo -e "${YELLOW}Check logs/${script}.stderr.log for details${NC}"
    fi
    echo ""
    idx=$((idx + 1))
  done

  echo -e "${BOLD}Legacy pipeline completed at $(date)${NC}"
}

main() {
  local python_cmd
  python_cmd="$(resolve_python_cmd || true)"
  if [ -z "${python_cmd:-}" ]; then
    print_error "Python interpreter not found. Run ./setup.sh first."
    exit 1
  fi

  export LEARNEXT_PYTHON="$python_cmd"
  mkdir -p videos/input videos/output urls uploads logs downloads conversions

  local agentic_script="$SCRIPT_DIR/.agents/skills/run_agentic.py"
  local mode="${1:-agentic}"

  if [ "$mode" = "--legacy" ]; then
    print_warning "Running legacy mode (s1..s5 directly)."
    run_legacy_pipeline "$python_cmd"
    return
  fi

  if [ ! -f "$agentic_script" ]; then
    print_warning "Agentic runner not found, falling back to legacy mode."
    run_legacy_pipeline "$python_cmd"
    return
  fi

  echo -e "${BOLD}Starting PyMP4HLS Agentic Pipeline at $(date)${NC}"
  echo "Using Python: $python_cmd"
  echo "Runner: $agentic_script"
  echo ""

  "$python_cmd" "$agentic_script"
}

main "${1:-}"
