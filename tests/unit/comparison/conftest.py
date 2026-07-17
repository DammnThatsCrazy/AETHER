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


# Backend package trees whose *class identity* the comparison test modules
# capture at collection time and later assert against — ``services.*`` for the
# engine/routes/contracts, ``shared.common``/``shared.auth`` for the exception
# and permission classes used with ``pytest.raises`` (``BadRequestError`` /
# ``NotFoundError`` / ``ForbiddenError``), ``config`` for the settings the
# route flag-gate reads, and ``repositories`` for the in-memory stores. Sibling
# suites (e.g. ``tests/graph``) purge and re-import ``shared.*`` mid-worker,
# which would otherwise give the raised exceptions a different class generation
# than the one ``pytest.raises`` holds, so a correctly-raised error would
# escape uncaught. Pinning all of these to the single collection-time
# generation keeps every party on the same classes.
_PINNED_PREFIXES = ("services", "shared.common", "shared.auth", "config", "repositories")


def _is_pinned(name: str) -> bool:
    return name in _PINNED_PREFIXES or any(
        name.startswith(f"{prefix}.") for prefix in _PINNED_PREFIXES
    )


def pytest_collection_finish(session) -> None:  # noqa: ANN001
    if _COLLECTION_MODULE_SNAPSHOT:
        return
    for name, module in list(sys.modules.items()):
        if _is_pinned(name):
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
