"""Path setup for deploy/kafka tests.

The provisioner under test lives one level up (deploy/kafka/topic_provisioner.py)
and imports kafka-python lazily, but the module itself must be importable.
pytest inserts this tests/ directory on sys.path, not its parent, so we add the
deploy/kafka directory explicitly. Also put the backend package root on
sys.path for the registry-sync test, which imports shared.events.events.
"""

from __future__ import annotations

import sys
from pathlib import Path

_KAFKA_DIR = Path(__file__).resolve().parent.parent  # deploy/kafka
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # repo root
_BACKEND_DIR = _REPO_ROOT / "Backend Architecture" / "aether-backend"

for _path in (_KAFKA_DIR, _BACKEND_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
