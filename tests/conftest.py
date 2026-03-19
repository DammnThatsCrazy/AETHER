"""Root test conftest — force imports to use the local repository packages."""

import importlib
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
_project_root_str = str(_project_root)
if _project_root_str not in sys.path:
    sys.path.insert(0, _project_root_str)

existing = sys.modules.get("security")
if existing is not None:
    module_file = getattr(existing, "__file__", "") or ""
    if not module_file.startswith(_project_root_str):
        del sys.modules["security"]

importlib.import_module("security")
