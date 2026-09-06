"""Autouse registry hygiene for M7 fidelity tests.

Fidelity definitions self-register additively on the Canonical Computation
Substrate (``shared.computation.registry.COMPUTATION_REGISTRY``). The
governance parity suite (``tests/computation/test_registry_parity.py``)
asserts the live registry exactly equals the generated twin, so any worker
that runs fidelity tests must leave the registry exactly as it found it. This
autouse fixture snapshots the pre-test registry and removes any key a fidelity
test adds, so fidelity definitions never leak into sibling parity assertions —
regardless of xdist scheduling order.
"""

from __future__ import annotations

import pytest

from shared.computation.registry import COMPUTATION_REGISTRY


@pytest.fixture(autouse=True)
def _restore_computation_registry():
    baseline = set(COMPUTATION_REGISTRY)
    yield
    for key in [k for k in COMPUTATION_REGISTRY if k not in baseline]:
        del COMPUTATION_REGISTRY[key]
