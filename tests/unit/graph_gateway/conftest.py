"""Path setup for graph-mutation-gateway unit tests (backend root on sys.path)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
