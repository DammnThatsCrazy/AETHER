"""CI-gated tests for OODA/outcome usage dimensions (Scope 11).

Verifies the 6 new metering dimensions are registered in the contract and that
the metering service records them through the same path as the existing 16.
Uses the standard ``backend_module_path`` import-isolation pattern.
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def revops(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("AETHER_USAGE_METERING_ENABLED", "true")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        mod = importlib.import_module("services.billing.revops")
        yield mod


NEW_DIMENSIONS = [
    "recommendation_previewed", "confidence_updated", "investigation_opened",
    "connector_sync", "webhook_ingested", "sdk_event_ingested",
]


def test_new_dimensions_have_labels(revops):
    for dim in NEW_DIMENSIONS:
        assert dim in revops.DIMENSION_LABELS, f"missing DIMENSION_LABELS entry for {dim}"


async def test_metering_records_new_dimension(revops):
    svc = revops.MeteringService(revops.UsageMeteringEventRepository())
    event = revops.UsageMeteringEvent(
        tenant_id="tenant-a",
        event_type="recommendation_previewed",
        source_id="rec-1",
        source_type="recommendation",
        occurred_at=revops.now_iso(),
    )
    stored = await svc.record_event(event)
    assert stored is not None
    assert stored["event_type"] == "recommendation_previewed"
    assert stored["tenant_id"] == "tenant-a"


async def test_metering_is_idempotent_for_new_dimension(revops):
    svc = revops.MeteringService(revops.UsageMeteringEventRepository())
    kwargs = dict(
        tenant_id="tenant-a", event_type="sdk_event_ingested",
        source_id="evt-1", source_type="ingestion", occurred_at=revops.now_iso(),
    )
    first = await svc.record_event(revops.UsageMeteringEvent(**kwargs))
    second = await svc.record_event(revops.UsageMeteringEvent(**kwargs))
    # Same source identity → idempotent (returns the existing record, not a dup).
    assert first["metering_event_id"] == second["metering_event_id"]


def test_invalid_dimension_rejected(revops):
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        revops.UsageMeteringEvent(
            tenant_id="tenant-a", event_type="not_a_real_dimension",
            occurred_at=revops.now_iso(),
        )
