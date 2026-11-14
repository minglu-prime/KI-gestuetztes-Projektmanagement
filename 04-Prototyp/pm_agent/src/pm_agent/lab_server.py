"""Starts, checks and stops the KI-Lab study server (04-Prototyp/ki_lab) for the KI-Lab page.

The lab is a separate program with its own tests. This module only runs it as a child process
and asks its health endpoint. No Streamlit in here.
"""

import atexit
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

KI_LAB_DIR = Path(__file__).resolve().parents[3] / "ki_lab"
PORT = 8874  # the lab's default port

_process: subprocess.Popen[str] | None = None


class LabError(RuntimeError):
    """The lab cannot be started or reached. The message is German and meant for the user."""


def health(port: int = PORT) -> dict[str, Any] | None:
    """The lab's status, or None if nothing listens on the port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            status = json.load(response)
    except urllib.error.HTTPError as err:
        raise LabError(
            f"Auf Port {port} antwortet ein anderes Programm (HTTP {err.code})."
        ) from err
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None  # nothing listens: the lab is not running
    except ValueError as err:
        raise LabError(f"Auf Port {port} antwortet ein anderes Programm.") from err
    if not isinstance(status, dict) or status.get("ok") is not True:
        raise LabError(f"Auf Port {port} antwortet ein anderes Programm.")
    return status


def allows_frame(origin: str, port: int = PORT) -> bool:
    """Whether the running lab lets the page at `origin` show it in a frame. A lab that was
    started on its own forbids framing."""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
        policy = response.headers.get("Content-Security-Policy", "")
    ancestors = next(
        (
            part.split()[1:]
            for part in policy.split(";")
            if part.strip().startswith("frame-ancestors")
        ),
        [],
    )
    return origin in ancestors


def start(
    frame_origins: list[str], port: int = PORT, db: Path | None = None, wait: float = 15
) -> None:
    """Run the lab as a child process and return once it answers. `frame_origins` are the
    pages that may show it in a frame; the lab accepts only pages on this computer."""
    global _process
    command = [sys.executable, "server.py", "--port", str(port)]
    for origin in frame_origins:
        command += ["--allow-frame", origin]
    if db is not None:
        command += ["--db", str(db)]
    process = subprocess.Popen(
        command,
        cwd=KI_LAB_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if process.poll() is not None:
            said = (process.stderr.read() if process.stderr else "").strip().splitlines()
            reason = said[-1] if said else f"Exit-Code {process.returncode}"
            raise LabError(f"Das KI-Lab hat sich beim Start beendet: {reason}")
        if health(port) is not None:
            _process = process
            return
        time.sleep(0.2)
    process.kill()
    raise LabError(f"Das KI-Lab antwortet nach {wait:g} Sekunden nicht auf Port {port}.")


def started_here() -> bool:
    """True while the lab that this program started is running."""
    return _process is not None and _process.poll() is None


def stop() -> None:
    """End the lab this program started. A lab started elsewhere is left alone."""
    global _process
    if _process is None:
        return
    _process.terminate()
    try:
        _process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _process.kill()
        _process.wait()
    _process = None


atexit.register(stop)  # do not leave the child running when the app ends normally
