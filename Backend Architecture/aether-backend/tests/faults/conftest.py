"""Fixtures for the stage-boundary fault suite.

Adds the sibling ``tests/adversarial/`` directory to ``sys.path`` so ``faultkit``
imports identically to the adversarial suite, and isolates every in-memory
backing store between tests (same contract as the adversarial conftest).
"""

from __future__ import annotations

import os
import sys

import pytest

_ADV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "adversarial")
if _ADV not in sys.path:
    sys.path.insert(0, _ADV)
_FAULTS = os.path.dirname(os.path.abspath(__file__))
if _FAULTS not in sys.path:
    sys.path.insert(0, _FAULTS)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from repositories.typed_repo import reset_typed_in_memory_stores  # noqa: E402
from shared.credentials.in_memory import InMemoryCredentialBackend  # noqa: E402
from shared.store import reset_in_memory_stores as reset_shared_stores  # noqa: E402


@pytest.fixture(autouse=True)
def reset_stores():
    """Isolate every in-memory backing store + credential backend per test.

    ``shared.store`` owns its own named-store registry (``payment_provider_receipts``
    and friends) separate from ``repositories.repos`` / ``repositories.typed_repo``,
    so all three must be cleared together or a durable-store-backed repository
    (e.g. ProviderReceiptRepository) leaks rows across tests.
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
