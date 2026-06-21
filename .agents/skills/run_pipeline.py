#!/usr/bin/env python
"""
Sequential Pipeline Runner for Learnext (s1..s5)
- Runs s1-urlscraper.py -> s2-downloader.py -> s3-converter.py -> s4-uploader.py -> s5-urlupdater.py
- To be run in: Terminal #2
- Assumes the SSH tunnel is already established by run_tunnel.py
- Usage: python run_pipeline.py
"""
import os
import sys
import time
import json
import shutil
import subprocess
import signal
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

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

# Scripts to run sequentially (order matters)
STEPS = [
    "s1-urlscraper.py",
    "s2-downloader.py",
    "s3-converter.py",
    "s4-uploader.py",
    "s5-urlupdater.py",
]

# State file to track progress
STATE_FILE = LOG_DIR / "pipeline_state.json"

@dataclass
class StepState:
    name: str
    status: str = "pending"  # pending, running, completed, failed
    start_time: str = ""
    end_time: str = ""
    exit_code: int = 0
    pid: int = 0

class PipelineState:
    def __init__(self):
        self.steps: list = [StepState(name=s) for s in STEPS]
        self.overall_status: str = "idle"
        self.message: str = ""

    def to_dict(self):
        return {
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
    with open(LOG_DIR / "pipeline.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def resolve_step_python_cmd(script_path: Path) -> list[str]:
    from_env = os.getenv("LEARNEXT_PYTHON")
    if from_env:
        return [from_env, str(script_path)]

    candidates = []
    active_venv = os.getenv("VIRTUAL_ENV")
    if active_venv:
        venv_path = Path(active_venv)
        if sys.platform == "win32":
            candidates.append(venv_path / "Scripts" / "python.exe")
        candidates.append(venv_path / "bin" / "python")

    for venv_name in ("venv", ".venv"):
        base = PROJECT_ROOT / venv_name
        if sys.platform == "win32":
            candidates.append(base / "Scripts" / "python.exe")
        candidates.append(base / "bin" / "python")

    if sys.executable:
        candidates.append(Path(sys.executable))

    for candidate in candidates:
        if candidate.exists():
            return [str(candidate), str(script_path)]

    python_in_path = shutil.which("python")
    if python_in_path:
        return [python_in_path, str(script_path)]

    if sys.platform == "win32":
        py_launcher = shutil.which("py")
        if py_launcher:
            return [py_launcher, "-3", str(script_path)]

    raise FileNotFoundError(
        "No Python interpreter found for pipeline steps. Set LEARNEXT_PYTHON."
    )

# ---------------------------------------------------------------------------
# STEP RUNNER
# ---------------------------------------------------------------------------
def run_step(script: str, state, index: int) -> bool:
    step = state.steps[index]
    step.status = "running"
    step.start_time = datetime.now().isoformat()
    step.end_time = ""
    step.exit_code = 0
    state.save()

    cmd = resolve_step_python_cmd(PROJECT_ROOT / script)
    log(f"Running step {index+1}/{len(STEPS)}: {script}")

    # Open per-step log files
    out = open(LOG_DIR / f"{script}.stdout.log", "a", encoding="utf-8")
    err = open(LOG_DIR / f"{script}.stderr.log", "a", encoding="utf-8")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=out,
            stderr=err,
        )
    except FileNotFoundError as exc:
        step.exit_code = 127
        step.end_time = datetime.now().isoformat()
        step.status = "failed"
        state.save()
        log(f"Failed to start {script}: {exc}")
        return False

    step.pid = proc.pid
    state.save()

    try:
        exit_code = proc.wait()
    except KeyboardInterrupt:
        log("KeyboardInterrupt received, terminating current step...")
        proc.terminate()
        proc.wait()
        raise

    step.exit_code = exit_code
    step.end_time = datetime.now().isoformat()

    if exit_code == 0:
        step.status = "completed"
        log(f"Step {script} completed successfully.")
        state.save()
        return True
    else:
        step.status = "failed"
        log(f"Step {script} failed with exit code {exit_code}.")
        state.save()
        return False

# ---------------------------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------------------------
def main():
    log("=" * 60)
    log("Pipeline Started")
    log("Running s1 -> s2 -> s3 -> s4 -> s5 sequentially")
    log("Press Ctrl+C to stop")
    log("=" * 60)

    state = PipelineState()
    state.overall_status = "running"
    state.message = "Starting pipeline..."
    state.save()

    def on_signal(signum, frame):
        log(f"Received signal {signum}, shutting down gracefully...")
        state.overall_status = "cancelled"
        state.message = "Pipeline cancelled by user."
        state.save()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

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
            log("All steps completed successfully!")
    except KeyboardInterrupt:
        log("Pipeline interrupted by user.")
        state.overall_status = "cancelled"
        state.message = "Pipeline cancelled by user."
        state.save()
    finally:
        log("Pipeline finished. Check logs/ and pipeline_state.json for details.")

if __name__ == "__main__":
    main()
