"""Path setup for WS-D backend-interpretation unit tests.

The WS-D primitives (shared/backend_interpretation/*), the episode engine
(services/measurement/episodes), the outcome-truth recorder and the Silver
projectors all live under the backend root, so it must sit on sys.path while
these tests run (same pattern as tests/unit/observation/conftest.py).
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


@pytest.fixture
def wsd_flags():
    """Toggle the seven WS-D flags on Settings.backend_interpretation.

    Returns a setter ``_set(**flags)`` that first resets every WS-D flag to
    False (the default), applies the requested overrides, and restores the
    original block on teardown.
    """
    import config.settings as config_settings

    original = getattr(config_settings.settings, "backend_interpretation", None)
    flags = (
        "relationship_fact_enabled",
        "episode_engine_enabled",
        "outcome_truth_store_enabled",
        "evidence_dedupe_enabled",
        "silver_temporal_envelope_enabled",
        "correlation_first_class_enabled",
        "silver_exact_money_enabled",
    )

    def _set(**overrides) -> SimpleNamespace:
        state = {flag: False for flag in flags}
        state.update(overrides)
        config_settings.settings.backend_interpretation = SimpleNamespace(**state)
        return config_settings.settings.backend_interpretation

    yield _set
    config_settings.settings.backend_interpretation = original


@pytest.fixture
def mutation_mode():
    """Read/restore the derived-truth mutation-gateway mode (item 8)."""
    import config.settings as config_settings

    original = getattr(config_settings.settings, "mutation_gateway_mode", "off")

    def _set(mode: str) -> None:
        config_settings.settings.mutation_gateway_mode = mode

    yield _set
    config_settings.settings.mutation_gateway_mode = original
