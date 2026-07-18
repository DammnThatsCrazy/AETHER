"""Path setup + module-generation pinning for graph-mutation-gateway tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Backend package trees whose *object identity* the gateway tests depend on.
# ``tests/graph`` purges and re-imports ``shared.graph.*`` (and its
# dependencies) mid-worker, creating a second generation of those modules. A
# projector that resolves ``get_mutation_gateway`` via a lazy in-method import
# then binds to the reloaded module — whose process-wide ``_shared_gateway`` is
# unset — and projects the edge to the *global* GraphClient instead of the
# test's wired client, while the ledger record still lands in the shared
# in-memory store. The result is a live-vs-replay digest mismatch that only
# appears when pytest-xdist co-locates the two suites on one worker. Pinning
# these packages to the single collection-time generation keeps the test's
# wired gateway, the projectors, and the digest reader all on one instance.
_PINNED_PREFIXES = ("shared.graph", "services", "repositories", "config")


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


@pytest.fixture(autouse=True)
def _pin_module_generation():
    for name, module in _COLLECTION_MODULE_SNAPSHOT.items():
        sys.modules[name] = module
    yield
