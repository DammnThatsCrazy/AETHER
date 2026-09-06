"""Path setup + shared fixtures for Reconciled Control Plane unit tests.

The whole ``services/managed_integrations`` package (contracts, availability,
desired_policy, sensors, reconciler, repository, routes) lives under the backend
root, so it must sit on sys.path while these tests run (same pattern as
``tests/unit/observation/conftest.py`` and ``tests/unit/interop/conftest.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_RCP_FLAG_NAMES = ("enabled", "reconciler_enabled", "kyber_route_enabled")


@pytest.fixture(autouse=True)
def _reset_rcp_stores():
    """Empty the module-local managed-integration / reconcile-run / change-set
    stores (managed_integrations.repository + change_sets_repository)."""
    from services.managed_integrations.change_sets_repository import (
        reset_change_set_in_memory_store,
    )
    from services.managed_integrations.repository import (
        reset_managed_integration_in_memory_store,
    )

    reset_managed_integration_in_memory_store()
    reset_change_set_in_memory_store()
    yield
    reset_managed_integration_in_memory_store()
    reset_change_set_in_memory_store()


@pytest.fixture
def rcp_flags():
    """Toggle the three Reconciled Control Plane flags on the settings block.

    Returns a setter ``_set(**flags)`` that first resets every RCP flag to False
    (the default), applies the requested overrides, and restores the original
    block on teardown. Mirrors ``tests/unit/backend_interpretation/conftest.py``
    (``wsd_flags``): the nested block is swapped in place, never mutated.
    """
    import config.settings as config_settings

    original = getattr(config_settings.settings, "reconciled_control", None)

    def _set(**overrides) -> SimpleNamespace:
        state = {name: False for name in _RCP_FLAG_NAMES}
        state.update(overrides)
        config_settings.settings.reconciled_control = SimpleNamespace(**state)
        return config_settings.settings.reconciled_control

    yield _set
    config_settings.settings.reconciled_control = original


@pytest.fixture
def db_free(monkeypatch):
    """Pin ``get_pool`` to None so repository tests always hit in-memory stores.

    ``AETHER_ENV`` already defaults to ``local`` (in-memory), but pinning the
    module-level import makes the tests robust to an ambient non-local env.
    Mirrors the data-exchange ``_db_free`` fixture.
    """

    async def _no_pool():
        return None

    monkeypatch.setattr(
        "services.managed_integrations.repository.get_pool", _no_pool
    )
