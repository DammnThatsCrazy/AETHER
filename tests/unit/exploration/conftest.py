"""Path setup + shared fixtures for exploration-fabric unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── Module-generation pinning ────────────────────────────────────────────────
# ``tests/contracts/test_comparison_contract_parity.py`` verifies the lazy-import
# invariant by deleting every ``services.*`` module from ``sys.modules``. That
# global purge makes a later in-body import mint a new class generation that no
# longer matches classes captured at collection time (Pydantic then rejects a
# valid instance with a ``model_type`` error). We snapshot the consistent
# generation present right after collection and re-pin it before each test.
_COLLECTION_MODULE_SNAPSHOT: dict[str, object] = {}


def pytest_collection_finish(session) -> None:  # noqa: ANN001
    if _COLLECTION_MODULE_SNAPSHOT:
        return
    for name, module in list(sys.modules.items()):
        if name == "services" or name.startswith("services."):
            _COLLECTION_MODULE_SNAPSHOT[name] = module


@pytest.fixture(autouse=True)
def _pin_module_generation():
    for name, module in _COLLECTION_MODULE_SNAPSHOT.items():
        sys.modules[name] = module
    yield


@pytest.fixture(autouse=True)
def _clean_stores():
    from repositories.repos import reset_in_memory_stores

    reset_in_memory_stores()
    yield
    reset_in_memory_stores()
