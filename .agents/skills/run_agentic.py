#!/usr/bin/env python3
"""
SSH Tunnel Manager + Sequential Pipeline Orchestrator
for Learnext MP4-to-HLS conversion (s1..s5).

Features:
- Starts/keeps an SSH tunnel alive (auto-reconnect on failure).
- Runs s1..s5 sequentially in a *separate* shell session (terminal #2).
- Exposes PID info so the parent Hermes session can monitor progress.

Usage:
  # Terminal #1: Hermes launches this (background)
  python run_agentic.py

  # Terminal #2: (already used by the orchestrator internally)
  # No manual action needed.
"""
import os
import sys
import time
import json
import subprocess
import signal
import psutil
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

# ---------------------------------------------------------------------------
# CONFIGURATION (read from environment or fallback)
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

# SSH parameters
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

# Scripts to run (order matters)
STEPS = [
    "s1-urlscraper.py",
    "s2-downloader.py",
    "s3-converter.py",
    "s4-uploader.py",
    "s5-urlupdater.py",
]

# State file so Hermes (or you) can inspect current status
STATE_FILE = LOG_DIR / "agentic_state.json"

@dataclass
class StepState:
    name: str
    status: str  # pending, running, completed, failed
    start_time: str = ""
    end_time: str = ""
    exit_code: int = 0
    pid: int = 0

class PipelineState:
    def __init__(self):
        self.tunnel_pid: int = 0
        self.tunnel_status: str = "stopped"  # stopped, starting, running, error
        self.steps: list[StepState] = [StepState(name=s, status="pending") for s in STEPS]
        self.overall_status: str = "idle"
        self.message: str = ""

    def to_dict(self):
        return {
            "tunnel": {"pid": self.tunnel_pid, "status": self.tunnel_status},
            "overall": self.overall_status,
            "message": self.message,
            "steps": [asdict(s) for s in self.steps],
        }

    def save(self):
        STATE_FILE.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
def log(msg: str):
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_DIR / "agentic.log", "a", encoding="utf-8") as f:
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
# SSH TUNNEL
# ---------------------------------------------------------------------------
def start_tunnel(state: PipelineState) -> subprocess.Popen:
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
    log(f"Starting SSH tunnel: {' '.join(cmd)}")
    out_handle = open(LOG_DIR / "tunnel.stdout.log", "a", encoding="utf-8")
    err_handle = open(LOG_DIR / "tunnel.stderr.log", "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=out_handle,
            stderr=err_handle,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    finally:
        out_handle.close()
        err_handle.close()

    state.tunnel_pid = proc.pid
    state.tunnel_status = "starting"
    state.save()
    log(f"SSH tunnel started with PID {proc.pid}")
    return proc

def tunnel_is_healthy() -> bool:
    """Check if localhost:LOCAL_PORT is reachable."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", LOCAL_PORT), timeout=5):
            return True
    except Exception:
        return False

def kill_tunnel(state: PipelineState):
    if state.tunnel_pid:
        try:
            p = psutil.Process(state.tunnel_pid)
            p.terminate()
            p.wait(timeout=5)
            log(f"Tunnel PID {state.tunnel_pid} terminated.")
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            log(f"Error killing tunnel: {e}")
        state.tunnel_pid = 0
        state.tunnel_status = "stopped"
        state.save()
    terminate_stale_tunnels()

# ---------------------------------------------------------------------------
# PIPELINE STEP RUNNER
# ---------------------------------------------------------------------------
def run_step(script: str, state: PipelineState, index: int) -> bool:
    step = state.steps[index]
    step.status = "running"
    step.start_time = datetime.now().isoformat()
    step.end_time = ""
    step.exit_code = 0
    state.save()

    venv_python = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = PROJECT_ROOT / "venv" / "bin" / "python"

    cmd = [str(venv_python), str(PROJECT_ROOT / script)]
    log(f"Running step {index+1}/{len(STEPS)}: {script}")

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=open(LOG_DIR / f"{script}.stdout.log", "a", encoding="utf-8"),
        stderr=open(LOG_DIR / f"{script}.stderr.log", "a", encoding="utf-8"),
    )
    step.pid = proc.pid
    state.save()

    try:
        exit_code = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        raise

    step.exit_code = exit_code
    step.end_time = datetime.now().isoformat()

    if exit_code == 0:
        step.status = "completed"
        log(f"✅ {script} completed successfully.")
        state.save()
        return True
    else:
        step.status = "failed"
        log(f"❌ {script} failed with exit code {exit_code}.")
        state.save()
        return False

# ---------------------------------------------------------------------------
# MAIN ORCHESTRATOR
# ---------------------------------------------------------------------------
def main():
    log("=" * 60)
    log("Learnext MP4-to-HLS Agentic Pipeline Started")
    log("=" * 60)

    state = PipelineState()
    state.overall_status = "running"
    state.message = "Starting pipeline..."
    state.save()

    # Register signal handlers for clean shutdown
    def on_signal(signum, frame):
        log(f"Received signal {signum}, shutting down gracefully...")
        kill_tunnel(state)
        state.overall_status = "cancelled"
        state.message = "Pipeline cancelled by user."
        state.save()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    terminate_stale_tunnels()

    # 1) Start SSH Tunnel
    tunnel_proc = start_tunnel(state)
    log("Waiting for SSH tunnel to become healthy...")
    for attempt in range(30):
        if tunnel_proc.poll() is not None:
            last_err = read_last_nonempty_line(LOG_DIR / "tunnel.stderr.log")
            if last_err:
                log(f"SSH tunnel exited prematurely. Last stderr: {last_err}")
            else:
                log("SSH tunnel exited prematurely. Quietly retrying...")
            time.sleep(1)
            terminate_stale_tunnels(exclude_pid=tunnel_proc.pid)
            tunnel_proc = start_tunnel(state)
            continue
        if tunnel_is_healthy():
            state.tunnel_status = "running"
            state.save()
            log("SSH tunnel is healthy.")
            break
        time.sleep(1)
    else:
        last_err = read_last_nonempty_line(LOG_DIR / "tunnel.stderr.log")
        if last_err:
            log(f"Tunnel setup failed. Last stderr: {last_err}")
        log("SSH tunnel failed to become healthy after 30s.")
        kill_tunnel(state)
        state.overall_status = "failed"
        state.message = "SSH tunnel failed to establish."
        state.save()
        sys.exit(1)

    # 2) Run pipeline steps sequentially
    try:
        for idx, script in enumerate(STEPS):
            success = run_step(script, state, idx)
            if not success:
                state.overall_status = "failed"
                state.message = f"Pipeline stopped at {script} due to failure."
                state.save()
                log("Pipeline halted due to step failure.")
                break
        else:
            state.overall_status = "completed"
            state.message = "All steps completed successfully!"
            state.save()
            log("🎉 All steps completed successfully!")
    except KeyboardInterrupt:
        log("Pipeline interrupted by user.")
        state.overall_status = "cancelled"
        state.message = "Pipeline cancelled by user."
        state.save()
    finally:
        kill_tunnel(state)

    log("=" * 60)
    log("Pipeline finished. Check logs/ and agentic_state.json for details.")
    log("=" * 60)

if __name__ == "__main__":
    main()
