#!/bin/bash
# filepath: /Users/g.e.bayualfian/Documents/GitHub/pymp4hls/run.sh

# Configuration from environment or defaults - avoids parsing full .env file
DB_HOST="${DB_HOST:-127.0.0.1}"
SSH_USER="${SSH_USER:-ec2-user}"
SSH_HOST="${SSH_HOST:-108.137.154.40}"
RDS_HOST="${RDS_HOST:-development-01.cfe04cwakie2.ap-southeast-3.rds.amazonaws.com}"
LOCAL_PORT="${DB_PORT:-13306}"  
REMOTE_PORT="${REMOTE_PORT:-3306}"
SSH_KEY_PATH="${SSH_KEY_PATH:-/Users/g.e.bayualfian/Documents/GOK/Key/development-gen.pem}"
LOGS_DIR="${LOGS_DIR:-/Users/g.e.bayualfian/Documents/GitHub/pymp4hls/logs}"
LOGFILE="${LOGS_DIR}/run.log"
PROJECT_DIR="${PROJECT_DIR:-/Users/g.e.bayualfian/Documents/GitHub/pymp4hls}"

# List of Python scripts to monitor and keep running
SCRIPTS=("s1-urlscraper.py" "s2-downloader.py" "s3-converter.py" "s4-uploader.py" "s5-urlupdater.py")

# Ensure the logs directory exists
mkdir -p "$LOGS_DIR"

# Function to get formatted timestamp
timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

# Function to log messages
log() {
  echo "$(timestamp): $1" | tee -a "$LOGFILE"
}

# Function to check internet connectivity
check_internet() {
  # Try multiple reliable destinations
  ping -c 1 8.8.8.8 > /dev/null 2>&1 || \
  ping -c 1 1.1.1.1 > /dev/null 2>&1 || \
  curl --connect-timeout 5 -s https://www.google.com > /dev/null 2>&1
  return $?
}

# Function to check SSH tunnel
check_tunnel() {
  nc -z localhost $LOCAL_PORT > /dev/null 2>&1
  return $?
}

# Function to start SSH tunnel
start_tunnel() {
  log "Starting SSH tunnel to $RDS_HOST"
  ssh -i "$SSH_KEY_PATH" -L $LOCAL_PORT:$RDS_HOST:$REMOTE_PORT \
      -o ServerAliveInterval=60 -o ServerAliveCountMax=120 \
      $SSH_USER@$SSH_HOST -N -f
  
  if [ $? -eq 0 ]; then
    log "SSH tunnel established successfully"
    return 0
  else
    log "Failed to establish SSH tunnel"
    return 1
  fi
}

# Function to check if a specific Python script is running
is_script_running() {
  local script_name="$1"
  ps aux | grep "python $script_name$" | grep -v grep > /dev/null
  return $?
}

# Function to start a specific Python script
start_script() {
  local script_name="$1"
  
  if ! is_script_running "$script_name"; then
    log "Starting $script_name"
    cd "$PROJECT_DIR"
    python "$script_name" &
    log "Started $script_name with PID $!"
  else
    log "$script_name is already running"
  fi
}

# Function to start all Python scripts
start_all_scripts() {
  log "Starting all Python scripts..."
  cd "$PROJECT_DIR"
  
  for script in "${SCRIPTS[@]}"; do
    start_script "$script"
  done
  
  log "All Python scripts started"
}

# Function to check and restart any stopped scripts
check_and_restart_scripts() {
  for script in "${SCRIPTS[@]}"; do
    if ! is_script_running "$script"; then
      log "$script is not running, restarting..."
      start_script "$script"
    fi
  done
}

# Function for full system check (internet, tunnel, scripts)
system_check() {
  # Check internet first
  if check_internet; then
    # Internet is up, check tunnel
    if ! check_tunnel; then
      log "SSH tunnel is down, reestablishing..."
      start_tunnel
      # Give the tunnel time to establish
      sleep 5
    fi
    
    # Check all scripts and restart any that have stopped
    check_and_restart_scripts
    
    return 0
  else
    # Internet is down
    log "Internet connectivity issue detected"
    return 1
  fi
}

# Main loop with intelligent reconnection
log "Starting PyMP4HLS service monitor"
internet_status=true  # Start assuming internet is available

# Initial system setup
if check_internet; then
  log "Internet connectivity confirmed"
  
  # Start tunnel if needed
  if ! check_tunnel; then
    start_tunnel
    sleep 5
  fi
  
  # Start all scripts
  start_all_scripts
else
  log "No internet connectivity, waiting to start services..."
  internet_status=false
fi

# Main monitoring loop
while true; do
  if check_internet; then
    # Internet is available
    if [ "$internet_status" = false ]; then
      # Internet just came back
      log "Internet connectivity restored"
      internet_status=true
      
      # Do a full system check
      system_check
    else
      # Normal operation, regular check
      if ! check_tunnel; then
        log "SSH tunnel is down, reconnecting..."
        start_tunnel
      fi
      
      # Check scripts every cycle
      check_and_restart_scripts
    fi
  else
    # Internet is down
    if [ "$internet_status" = true ]; then
      log "Internet connectivity lost, waiting for restoration..."
      internet_status=false
    fi
  fi
  
  # Wait before next check
  sleep 60
done