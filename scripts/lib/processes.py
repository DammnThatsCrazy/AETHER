"""Bounded subprocess execution for the repository control plane.

CI commands commonly launch another Python runner which then launches pytest
workers. A timeout on only the outer wrapper leaves those descendants alive,
so a later check can be starved or contaminated by the previous run. Every
bounded control-plane command therefore gets its own process group and the
whole group is terminated before the timeout is reported to the caller.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def timeout_output(error: subprocess.TimeoutExpired) -> str:
    """Return captured timeout output without leaking bytes into evidence."""
    return _text(error.stdout) + _text(error.stderr)


def _signal_group(process: subprocess.Popen[str], sig: signal.Signals) -> None:
    """Signal the process group, falling back to the direct process."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, sig)
            return
        except ProcessLookupError:
            return
    if sig == signal.SIGTERM:
        process.terminate()
    else:
        process.kill()


def _terminate_group(process: subprocess.Popen[str], *, grace_seconds: float) -> None:
    """Terminate a timed-out command and all descendants in its process group."""
    _signal_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        process.wait()


def run_with_timeout(
    command: Sequence[str],
    *,
    cwd: str | Path,
    env: Mapping[str, str],
    timeout: float,
    grace_seconds: float = 5.0,
) -> subprocess.CompletedProcess[str]:
    """Run a command and terminate its complete process group on timeout."""
    popen_kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "posix":
        # The PID is also the process-group ID, allowing descendants such as
        # pytest workers to be terminated together with the wrapper.
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(list(command), **popen_kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        _terminate_group(process, grace_seconds=grace_seconds)
        try:
            stdout, stderr = process.communicate(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            # A descendant that escaped the group can keep a pipe open. Do
            # not let evidence collection hang forever in that case: close
            # our read ends after the group kill and reap the wrapper.
            stdout = _text(error.stdout)
            stderr = _text(error.stderr)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            process.kill()
            process.wait()
        raise subprocess.TimeoutExpired(
            list(command),
            timeout,
            output=_text(stdout),
            stderr=_text(stderr),
        ) from error
    return subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr)
