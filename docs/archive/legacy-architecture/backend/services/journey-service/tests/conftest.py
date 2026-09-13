"""Pytest bootstrap.

The journey-service directory contains a hyphen, so it cannot be imported
directly as a Python package. We register a synthetic package alias
`_journey_pkg` whose `__path__` points at the service dir, allowing the
modules' relative imports (`from .policies import …`) to resolve, then
expose stable aliases in sys.modules so tests can `import policies` etc.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


_PKG_DIR = Path(__file__).resolve().parents[1]
_PKG_NAME = "_journey_pkg"


def _install_pkg() -> None:
    if _PKG_NAME not in sys.modules:
        pkg = types.ModuleType(_PKG_NAME)
        pkg.__path__ = [str(_PKG_DIR)]   # type: ignore[attr-defined]
        sys.modules[_PKG_NAME] = pkg
    for short in ("policies", "journey_fsm", "causality", "snapshot_writer"):
        full = f"{_PKG_NAME}.{short}"
        mod = importlib.import_module(full)
        sys.modules[short] = mod        # let tests `import policies`


_install_pkg()
