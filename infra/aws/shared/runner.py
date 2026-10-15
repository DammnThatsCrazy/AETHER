"""
Shared command runner and logging — single source of truth.
Eliminates duplicated _run() / _log() across all operational scripts.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CommandResult:
    """Standardised result from any shell command."""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float = 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        return (self.stdout + self.stderr).strip()


def run_cmd(
    cmd: str,
    timeout: int = 300,
    capture: bool = True,
    env: Optional[dict] = None,
) -> CommandResult:
    """Execute a shell command with timeout and structured result.

    Single implementation replaces _run() duplicated in
    disaster_recovery.py and monitoring_ops.py.
    """
    start = time.monotonic()
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=capture,
            text=True,
            timeout=timeout,
            env=env,
        )
        elapsed = (time.monotonic() - start) * 1000
        return CommandResult(
            exit_code=r.returncode,
            stdout=r.stdout or "",
            stderr=r.stderr or "",
            duration_ms=round(elapsed, 1),
        )
    except subprocess.TimeoutExpired:
        elapsed = (time.monotonic() - start) * 1000
        return CommandResult(1, "", f"Timeout after {timeout}s", round(elapsed, 1))
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CommandResult(1, "", str(e), round(elapsed, 1))


def log(msg: str, tag: str = "AWS", timestamp: bool = True) -> None:
    """Unified logger with configurable tag.

    Single implementation replaces:
      [NET] in network_ops.py
      [MON] in monitoring_ops.py
      [COST] in cost_ops.py
      [DR] in disaster_recovery.py
    """
    if timestamp:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"  [{ts}] [{tag}] {msg}")
    else:
        print(f"  [{tag}] {msg}")


class timed:
    """Context manager for timing operations.

    Usage:
        with timed("Rebuilding infrastructure", tag="DR"):
            ...  # work here
    """

    def __init__(self, label: str, tag: str = "AWS"):
        self.label = label
        self.tag = tag
        self.start: float = 0
        self.elapsed_ms: float = 0

    def __enter__(self) -> "timed":
        log(f"{self.label}...", tag=self.tag)
        self.start = time.monotonic()
        return self

    def __exit__(self, *_exc) -> None:
        self.elapsed_ms = round((time.monotonic() - self.start) * 1000, 1)
        log(f"{self.label} completed ({self.elapsed_ms:.0f}ms)", tag=self.tag)


# ── Convenience partials per domain ────────────────────────────────────
# Scripts import these instead of calling log() with tag= every time.

def net_log(msg: str) -> None:
    log(msg, tag="NET")

def mon_log(msg: str) -> None:
    log(msg, tag="MON")

def cost_log(msg: str) -> None:
    log(msg, tag="COST")

def dr_log(msg: str) -> None:
    log(msg, tag="DR")

def sec_log(msg: str) -> None:
    log(msg, tag="SEC")

def cap_log(msg: str) -> None:
    log(msg, tag="CAP")
