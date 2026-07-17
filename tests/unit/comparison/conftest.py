"""Path setup + shared fixtures for comparison-engine unit tests."""
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

from comparison_fakes import FakeAnalytics  # noqa: E402

# ── Module-generation pinning ────────────────────────────────────────────────
# ``tests/contracts/test_comparison_contract_parity.py`` verifies the lazy-import
# invariant by deleting *every* ``services.*`` module from ``sys.modules`` and
# re-importing ``services.intelligence`` fresh. That purge is a global side
# effect: any test that later imports a comparison submodule fresh (e.g. inside
# a test body) gets a NEW class generation, which no longer matches the classes
# these test modules captured at collection time — Pydantic then rejects a
# perfectly valid instance with a ``model_type`` error.
#
# We snapshot the one consistent generation present right after collection (all
# test-module top-level imports have run, no test has purged anything yet) and
# re-pin it before each test. This makes in-body fresh imports resolve to the
# same class objects the test module holds, without weakening the invariant
# guard (which completes entirely within its own test, before this runs).
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


@pytest.fixture()
def fake_analytics() -> FakeAnalytics:
    return FakeAnalytics()


@pytest.fixture(autouse=True)
def _clean_stores():
    from repositories.repos import reset_in_memory_stores

    reset_in_memory_stores()
    yield
    reset_in_memory_stores()
