"""Ensure the backend package root is importable for repo-root graph tests.

The backend lives under ``Backend Architecture/aether-backend`` (note the
space). Repo-root graph tests import ``shared.graph`` / ``services`` /
``config`` / ``repositories`` directly, so this conftest inserts that root on
``sys.path`` — self-contained, rather than depending on a sibling test
directory's conftest having loaded first.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
