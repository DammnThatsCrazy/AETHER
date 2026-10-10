"""
Aether CI/CD -- Shared Command Runner
Single source of truth for subprocess execution, logging, and timing.
Every stage delegates to these functions instead of reimplementing them.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# CommandResult
# --------------------------------------------------------------------------- #

@dataclass
class CommandResult:
    """Structured result of a shell command."""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


# --------------------------------------------------------------------------- #
# run_cmd  --  the ONE place that calls subprocess
# --------------------------------------------------------------------------- #

def run_cmd(
    cmd: str,
    cwd: str = ".",
    timeout: int = 600,
    env: dict | None = None,
    capture: bool = True,
) -> CommandResult:
    """
    Execute a shell command and return a structured result.

    Args:
        cmd:     Shell command string.
        cwd:     Working directory.
        timeout: Max seconds before TimeoutExpired.
        env:     Optional extra environment variables (merged with os.environ).
        capture: Whether to capture stdout/stderr (disable for streaming output).

    Returns:
        CommandResult with exit_code, stdout, stderr, duration.
    """
    import os

    merged_env = None
    if env:
        merged_env = {**os.environ, **env}

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=timeout,
            env=merged_env,
        )
        elapsed = time.time() - start
        return CommandResult(
            command=cmd,
            exit_code=result.returncode,
            stdout=result.stdout if capture else "",
            stderr=result.stderr if capture else "",
            duration_seconds=elapsed,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return CommandResult(
            command=cmd,
            exit_code=124,
            stdout="",
            stderr=f"Command timed out after {timeout}s: {cmd}",
            duration_seconds=elapsed,
        )
    except Exception as exc:
        elapsed = time.time() - start
        return CommandResult(
            command=cmd,
            exit_code=1,
            stdout="",
            stderr=f"Command failed: {exc}",
            duration_seconds=elapsed,
        )


# --------------------------------------------------------------------------- #
# log  --  consistent pipeline logging
# --------------------------------------------------------------------------- #

def log(msg: str, stage: str = "PIPELINE") -> None:
    """Print a pipeline log line with stage prefix."""
    print(f"  [{stage}] {msg}")


# --------------------------------------------------------------------------- #
# timed  --  wrap a callable with timing
# --------------------------------------------------------------------------- #

def timed(label: str, fn: Callable[[], T]) -> tuple:
    """Execute *fn*, print duration, return (result, elapsed_seconds)."""
    start = time.time()
    result = fn()
    elapsed = time.time() - start
    log(f"{label} completed in {elapsed:.1f}s")
    return result, elapsed
