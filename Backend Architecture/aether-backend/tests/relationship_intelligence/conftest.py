"""Autouse registry + environment hygiene for Relationship Intelligence tests.

Fidelity definitions self-register additively on the Canonical Computation
Substrate (``shared.computation.registry.COMPUTATION_REGISTRY``) and the
governance parity suite asserts the live registry exactly equals the generated
twin — so any worker that persists a fidelity vector must leave the registry as
it found it (mirroring ``tests/relationship_fidelity/conftest.py``).

``AETHER_ENV`` defaults to ``local`` (the repo's ``repositories.repos`` in-memory
fallback requires no database), and the module-level D-05 consent provider is
cleared before/after every test so consent is never leaked between tests
(fail-closed default).

The Computation Substrate's repository is a module-global in-memory store when
no pool is configured; run/result rows persist across tests within one worker
unless reset. A test that seeds a persisted fidelity run for a tenant/pair would
otherwise be visible to a later test asserting no run for that tenant/pair (the
run-id is deterministic per relationship). Each test therefore gets a FRESH
store so the read-surface honesty assertions ("no run => unknown, never 0") are
deterministic regardless of xdist scheduling — never dependent on cross-test
store emptiness.
"""

from __future__ import annotations

import os

import pytest

import services.computation.repositories as _computation_repositories
from shared.computation.registry import COMPUTATION_REGISTRY
from services.relationship_intelligence import consent as _consent

os.environ.setdefault("AETHER_ENV", "local")
os.environ.pop("AETHER_RELATIONSHIP_FIDELITY_MODE", None)
os.environ.pop("AETHER_SOCIAL360_ENABLED", None)


@pytest.fixture(autouse=True)
def _restore_computation_registry():
    """Snapshot the registry and remove any key a fidelity test adds."""
    baseline = set(COMPUTATION_REGISTRY)
    yield
    for key in [k for k in COMPUTATION_REGISTRY if k not in baseline]:
        del COMPUTATION_REGISTRY[key]


@pytest.fixture(autouse=True)
def _clear_consent_provider():
    """Fail-closed consent between tests: no default provider ever leaks."""
    _consent.clear_default_consent_provider()
    yield
    _consent.clear_default_consent_provider()


@pytest.fixture(autouse=True)
def _fresh_computation_store():
    """Deterministic store isolation: a fresh repository per test.

    Replaces the module-global computation-repository singleton so persisted
    runs/results never leak across tests within a worker. All tests in this
    directory persist and read back within a single test, so a fresh store per
    test is behaviour-preserving and removes the xdist-scheduling dependence.
    """
    _computation_repositories._repo_singleton = None
    yield
    _computation_repositories._repo_singleton = None
