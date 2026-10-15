"""Fault-injection fixtures for the adversarial suite (program sec9/sec23).

Every adversarial test gets:

  * ``reset_stores`` (autouse) — deterministic isolation of the in-memory
    repositories, typed tables, shared.store registries, and credential
    backends between tests.
  * ``fault`` — a factory returning an armed :class:`FaultInjector` for any
    classification in the shared vocabulary.
  * ``transport`` — the httpx fault-handler factory.
  * ``plan_source`` — the deterministic stream-plan factory.
  * ``faulty_store`` — wraps a shared.store object with per-method injectors.

The suite runs with NO live network, NO live credentials, NO broker: the
in-memory backends are the authoritative store under test, and ``reset_stores``
makes every scenario deterministic.
"""

from __future__ import annotations

import os
import sys

import pytest

# Make the sibling faultkit importable as a top-level module regardless of how
# pytest collects this tree (the root conftest already puts BACKEND_ROOT and
# REPO_ROOT on sys.path; this additionally covers direct sub-tree runs).
sys.path.insert(0, os.path.dirname(__file__))

import faultkit  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from repositories.typed_repo import reset_typed_in_memory_stores  # noqa: E402
from shared.credentials.in_memory import InMemoryCredentialBackend  # noqa: E402
from shared.store import reset_in_memory_stores as reset_shared_stores  # noqa: E402


@pytest.fixture(autouse=True)
def reset_stores():
    """Isolate every in-memory backing store + credential backend per test.

    ``shared.store`` owns its own named-store registry (``payment_provider_receipts``
    and friends) separate from ``repositories.repos`` / ``repositories.typed_repo``,
    so all must be cleared together or a durable-store-backed repository
    (e.g. ProviderReceiptRepository) leaks rows across tests. Same convention
    as ``tests/faults/conftest.py``.
    """
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    reset_shared_stores()
    InMemoryCredentialBackend.reset()
    yield
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    reset_shared_stores()
    InMemoryCredentialBackend.reset()


@pytest.fixture
def fault():
    """Factory: ``injector = fault(classification, mode=..., nth=...)``."""
    def _factory(classification: str, *, mode: str = "once", nth: int = 1):
        return faultkit.FaultInjector(
            faultkit.make_fault(classification), mode=mode, nth=nth,
        )
    return _factory


@pytest.fixture
def transport():
    """The httpx fault-handler factory (timeout/rate-limit/auth/malformed)."""
    return faultkit.transport_handler


@pytest.fixture
def mock_transport():
    """An ``httpx.MockTransport`` armed with a fault handler."""
    return faultkit.mock_transport


@pytest.fixture
def plan_source():
    """The deterministic stream-plan factory (duplicate/replay/out-of-order)."""
    return faultkit.PlanSource


@pytest.fixture
def faulty_store():
    """Wrap a store object with per-method FaultInjectors."""
    return faultkit.FaultyStore


@pytest.fixture
def expect_fault():
    """The 'failure is distinguishable from empty' assertion helper."""
    return faultkit.expect_fault
