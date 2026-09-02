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

# ── Force-load the S5 service tree BEFORE collection-finish ─────────────────
# The exploration SESSION tests import ``services.exploration.service`` (and its
# closure: ``session``/``operations``, ``shared.projection_engine.runtime``,
# ``shared.intelligence_projections.registry``, ``repositories.repos``) only
# INSIDE test bodies, so those modules are absent from the collection-time
# snapshot below. A sibling suite that evicts the whole backend tree then makes
# the next in-body import mint a SECOND generation of ``service``/``session``/
# ``runtime``/the in-memory repos store — splitting identity from the pinned
# generation the test module's top-level models still hold (Pydantic
# ``model_type`` errors, provider registrations landing on a registry the
# service's ``runtime`` does not see, and store resets that miss the repo the
# service actually reads). Loading the tree here, at conftest import (which
# precedes ``pytest_collection_finish`` in every worker that collects this
# directory), guarantees the full service closure lands in the snapshot as ONE
# generation and is re-pinned before every test.
# Imports below: exploration service facade (service/session/operations/planner/
# adapters/facets), projection-engine runtime + registry singletons they bind,
# and the BaseRepository store. Import side effects are limited to constructing
# the in-memory repos (safe: the module imports cleanly with no AETHER_ENV).
import services.exploration.service as _exploration_service  # noqa: E402,F401
import services.exploration.session  # noqa: E402,F401

# ── Module-generation pinning ────────────────────────────────────────────────
# Sibling suites (``tests/unit/`` ``test_ingestion_roundtrip.py``,
# ``test_admin_billing_subscription_routes.py``, and ~40 others) verify module
# boundaries by evicting the ENTIRE backend tree — every module whose top-level
# package is in the ``_BACKEND_PREFIXES`` set below — from ``sys.modules`` and
# never restoring it. Any later in-body import then mints a NEW class
# generation that no longer matches classes the service layer captured at
# import time (Pydantic ``model_type`` errors, and — worse — two live copies of
# module-level singletons like ``runtime``, ``projection_registry`` and the
# in-memory ``repositories`` store dict). We snapshot the one consistent
# generation present right after collection (all test-module imports have run,
# no test has purged anything yet) and re-pin it before each test.
#
# The exploration fabric binds identity across every one of these trees:
# ``services.exploration.*`` (service/session/operations singletons),
# ``shared.exploration`` (context/session models), ``shared.projection_engine``
# (``runtime``, ``lens_registry``, ``LensConflict``/``LensNotFound``),
# ``shared.intelligence_projections`` (``ProjectionRequest``,
# ``projection_registry``), ``shared.contracts_models`` (``FilterGroup``),
# ``shared.common``/``shared.auth`` (exception + permission classes used with
# ``pytest.raises``), ``config`` (route flag-gate), ``dependencies`` and
# ``repositories`` (session store the service binds at import). Pin all of them
# to the single collection-time generation so every party stays on one copy.
_PINNED_PREFIXES = (
    "config",
    "services",
    "shared",
    "middleware",
    "dependencies",
    "repositories",
)


def _is_pinned(name: str) -> bool:
    return name in _PINNED_PREFIXES or any(
        name.startswith(f"{prefix}.") for prefix in _PINNED_PREFIXES
    )


_COLLECTION_MODULE_SNAPSHOT: dict[str, object] = {}


def pytest_collection_finish(session) -> None:  # noqa: ANN001
    if _COLLECTION_MODULE_SNAPSHOT:
        return
    for name, module in list(sys.modules.items()):
        if _is_pinned(name):
            _COLLECTION_MODULE_SNAPSHOT[name] = module


# S5 stateful modules whose module-level singletons bind the in-memory repos
# store at import time (``service._sessions``) or are imported only inside test
# bodies (``routes``/``service``). If a mid-worker eviction regenerates
# ``repositories.repos`` while a snapshot-pinned ``service`` survives, the
# pinned ``_sessions`` repo keeps reading/writing the OLD store dict, and a
# reset of the CURRENT repos generation silently misses it — sessions accumulate
# across tests. The fixture below therefore runs pin → pop → reset in ONE body
# (order enforced by construction, not by pytest's cross-fixture ordering) so
# the test body's fresh imports always bind the SAME repos generation whose
# store the reset just cleared. Pure modules (``operations``/``planner``/
# adapters/models) stay pinned — they hold no store and their classes are
# captured by the test files' top-level imports.
_STATEFUL_S5_MODULES = (
    "services.exploration.routes",
    "services.exploration.service",
    "services.exploration.session",
)


@pytest.fixture(autouse=True)
def _isolated_exploration_state():
    # 1) Restore the single collection-time generation (undoes any mid-worker
    #    eviction of the backend tree by sibling suites).
    for name, module in _COLLECTION_MODULE_SNAPSHOT.items():
        sys.modules[name] = module
    # 2) Drop the stateful S5 modules so this test re-imports them fresh; their
    #    repo singletons then bind the repos generation pinned in (1) — the same
    #    one (3) resets.
    for name in _STATEFUL_S5_MODULES:
        sys.modules.pop(name, None)
    # 3) Clear the in-memory stores of the pinned repos generation.
    from repositories.repos import reset_in_memory_stores

    reset_in_memory_stores()
    yield
    reset_in_memory_stores()
