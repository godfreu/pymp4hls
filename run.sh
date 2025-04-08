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

# Ensure the logs directory exists
mkdir -p "$LOGS_DIR"

# Function to start Python scripts in background
start_python_scripts() {
  echo "$(date): Starting Python scripts..." | tee -a "$LOGFILE"
  
  cd "$PROJECT_DIR"
  
  # Start all scripts in background
  python s1-urlscraper.py &
  echo "$(date): Started s1-urlscraper.py with PID $!" | tee -a "$LOGFILE"
  
  python s2-downloader.py &
  echo "$(date): Started s2-downloader.py with PID $!" | tee -a "$LOGFILE"
  
  python s3-converter.py &
  echo "$(date): Started s3-converter.py with PID $!" | tee -a "$LOGFILE"
  
  python s4-uploader.py &
  echo "$(date): Started s4-uploader.py with PID $!" | tee -a "$LOGFILE"
  
  python s5-urlupdater.py &
  echo "$(date): Started s5-urlupdater.py with PID $!" | tee -a "$LOGFILE"
  
  echo "$(date): All Python scripts started" | tee -a "$LOGFILE"
}

# Establish initial SSH run
if ! nc -z localhost $LOCAL_PORT > /dev/null 2>&1; then
  echo "$(date): Initial run setup..." | tee -a "$LOGFILE"
  ssh -i "$SSH_KEY_PATH" \
      -L $LOCAL_PORT:$RDS_HOST:$REMOTE_PORT \
      -o ServerAliveInterval=60 -o ServerAliveCountMax=120 \
      $SSH_USER@$SSH_HOST -N -f
  
  # Wait for run to be established
  sleep 5
fi

# Start the Python scripts only once at the beginning
start_python_scripts

# Main loop - just maintain the run
while true; do
  # Check if the run port is listening
  if ! nc -z localhost $LOCAL_PORT > /dev/null 2>&1; then
    echo "$(date): run down, reconnecting..." | tee -a "$LOGFILE"
    ssh -i "$SSH_KEY_PATH" \
        -L $LOCAL_PORT:$RDS_HOST:$REMOTE_PORT \
        -o ServerAliveInterval=60 -o ServerAliveCountMax=120 \
        $SSH_USER@$SSH_HOST -N -f
  else
    echo "$(date): run OK" | tee -a "$LOGFILE"
  fi
  sleep 60
done