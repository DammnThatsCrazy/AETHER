"""Path setup for observation-envelope (Envelope B) unit tests.

The model (shared/observation/envelope.py), the SDK mapping
(services/ingestion/observation_envelope.py) and the generated field-trust
registry they read live under the backend root, so it must sit on sys.path
while these tests run (same pattern as tests/unit/temporal/conftest.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
