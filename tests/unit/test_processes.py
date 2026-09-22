from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.lib.processes import run_with_timeout


def test_timeout_terminates_descendant_processes(tmp_path: Path) -> None:
    marker = tmp_path / "descendant-survived"
    child_code = (
        "import pathlib, time; time.sleep(0.6); "
        f"pathlib.Path({str(marker)!r}).write_text('leaked')"
    )
    parent_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(30)"
    )

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_with_timeout(
            [sys.executable, "-c", parent_code],
            cwd=tmp_path,
            env={},
            timeout=0.1,
        )

    assert time.monotonic() - started < 5
    time.sleep(0.9)
    assert not marker.exists()
