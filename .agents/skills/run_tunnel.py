#!/usr/bin/env python
"""
SSH Tunnel Manager for Learnext
- Ensures a persistent SSH tunnel is active, with auto-reconnect.
- To be run in: Terminal #1 (or any dedicated terminal)
- Usage: python run_tunnel.py
"""
import os
import sys
import time
import json
import subprocess
import signal
import socket
import psutil
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
def resolve_project_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parent, *here.parents]
    required_files = (
        "s1-urlscraper.py",
        "s2-downloader.py",
        "s3-converter.py",
        "s4-uploader.py",
        "s5-urlupdater.py",
    )
    for candidate in candidates:
        if all((candidate / name).exists() for name in required_files):
            return candidate
    # fallback: old behavior if expected files are not found
    return here.parent


PROJECT_ROOT = resolve_project_root()
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# SSH tunnel configuration
SSH_HOST = "34.101.77.69"
SSH_USER = "bayu"
LOCAL_PORT = 13306
REMOTE_HOST = "10.65.161.12"
REMOTE_PORT = 3306
TUNNEL_FORWARD = f"{LOCAL_PORT}:{REMOTE_HOST}:{REMOTE_PORT}"
TUNNEL_TARGET = f"{SSH_USER}@{SSH_HOST}"
KNOWN_HOSTS_FILE = "NUL" if sys.platform == "win32" else "/dev/null"


def resolve_ssh_key() -> Path:
    from_env = os.getenv("LEARNEXT_SSH_KEY")
    if from_env:
        return Path(from_env).expanduser()
    if sys.platform == "win32":
        return Path("C:/Users/imanuel/Code/key/id_bayulearnext")
    return Path.home() / ".ssh" / "id_bayulearnext"


SSH_KEY = resolve_ssh_key()

# State file
STATE_FILE = LOG_DIR / "tunnel_state.json"

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
def log(msg: str):
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_DIR / "tunnel.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_last_nonempty_line(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return ""


def is_matching_tunnel_process(proc: psutil.Process) -> bool:
    try:
        cmdline = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    if not cmdline:
        return False
    executable = Path(cmdline[0]).name.lower()
    if executable not in {"ssh", "ssh.exe"}:
        return False
    joined = " ".join(cmdline)
    return TUNNEL_FORWARD in joined and TUNNEL_TARGET in joined


def terminate_stale_tunnels(exclude_pid=None):
    terminated = []
    try:
        process_iter = psutil.process_iter()
    except (psutil.Error, PermissionError) as exc:
        log(f"Skipping stale tunnel cleanup: {exc}")
        return

    for proc in process_iter:
        pid = proc.pid
        if exclude_pid and pid == exclude_pid:
            continue
        if not is_matching_tunnel_process(proc):
            continue
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        terminated.append(pid)
    if terminated:
        joined = ", ".join(str(pid) for pid in terminated)
        log(f"Terminated stale tunnel PID(s): {joined}")

# ---------------------------------------------------------------------------
# TUNNEL LOGIC
# ---------------------------------------------------------------------------
def is_port_open(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def start_tunnel_process() -> subprocess.Popen:
    if not SSH_KEY.exists():
        log(f"WARNING: SSH key file does not exist: {SSH_KEY}")

    cmd = [
        "ssh",
        "-i", str(SSH_KEY),
        "-L", TUNNEL_FORWARD,
        "-o", "ServerAliveInterval=60",
        "-o", "ServerAliveCountMax=1200",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS_FILE}",
        "-N",
        "-n",
        TUNNEL_TARGET,
    ]
    log(f"Starting SSH tunnel...")
    # Redirect stdout/stderr to log files for debugging
    out_handle = open(LOG_DIR / "tunnel.stdout.log", "a", encoding="utf-8")
    err_handle = open(LOG_DIR / "tunnel.stderr.log", "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=out_handle,
            stderr=err_handle,
            # Ensure the process doesn't die when this script exits if we didn't want it to,
            # but here we manage its lifecycle.
        )
    finally:
        out_handle.close()
        err_handle.close()

    log(f"SSH tunnel started with PID {proc.pid}")
    # Save state
    state = {
        "pid": proc.pid,
        "status": "starting",
        "last_update": datetime.now().isoformat(),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return proc

def save_state(pid: int, status: str):
    state = {
        "pid": pid,
        "status": status,
        "last_update": datetime.now().isoformat(),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def main():
    log("=" * 60)
    log("SSH Tunnel Manager started")
    log("Press Ctrl+C to stop")
    log("=" * 60)

    tunnel_proc = None

    def shutdown(signum, frame):
        log("Shutdown signal received, stopping tunnel...")
        if tunnel_proc and tunnel_proc.poll() is None:
            tunnel_proc.terminate()
            try:
                tunnel_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel_proc.kill()
        save_state(0, "stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    terminate_stale_tunnels()

    # Main loop: ensure tunnel is always running and healthy
    while True:
        # Check if current tunnel process is alive
        if tunnel_proc is None or tunnel_proc.poll() is not None:
            if tunnel_proc is not None and tunnel_proc.poll() is not None:
                last_err = read_last_nonempty_line(LOG_DIR / "tunnel.stderr.log")
                if last_err:
                    log(f"Tunnel process exited. Last stderr: {last_err}")
            terminate_stale_tunnels(exclude_pid=tunnel_proc.pid if tunnel_proc else None)
            log("Tunnel process not running (or dead). Restarting...")
            tunnel_proc = start_tunnel_process()
            time.sleep(3)  # Give some time to establish

        # Check if the local port is actually reachable
        if is_port_open("127.0.0.1", LOCAL_PORT):
            save_state(tunnel_proc.pid, "running")
        else:
            log("Tunnel process exists but port is not open. Killing and restarting...")
            last_err = read_last_nonempty_line(LOG_DIR / "tunnel.stderr.log")
            if last_err:
                log(f"Latest SSH stderr: {last_err}")
            tunnel_proc.terminate()
            try:
                tunnel_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel_proc.kill()
            tunnel_proc = None
            continue

        time.sleep(5)

if __name__ == "__main__":
    main()
