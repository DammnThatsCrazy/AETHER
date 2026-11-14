"""Gold anomaly alerts retain only verified canonical signal/event pointers."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from ingestion.lake.anomaly_alerts import verified_anomaly_alert_dimensions  # noqa: E402
from ingestion.lake.routes import MaterializeRequest, materialize_gold  # noqa: E402
from intelligence.risk360.contracts import RiskSignal  # noqa: E402
from intelligence.risk360.provider import RepositoryRiskSourceReader  # noqa: E402
from intelligence.risk360.store import RiskSignalRepository  # noqa: E402
from shared.common.common import BadRequestError  # noqa: E402
from shared.intelligence_projections.contracts import ProjectionSubject  # noqa: E402


class _Tenant:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    def require_permission(self, permission: str) -> None:
        assert permission == "write"


async def _signal(
    tenant_id: str,
    signal_id: str,
    *,
    subject_id: str = "agent-1",
    event_refs: tuple[tuple[str, str], ...] = (("event-1", "bronze.observation"),),
) -> None:
    signal = RiskSignal(
        signal_id=signal_id,
        tenant_id=tenant_id,
        subject_kind="agent",
        subject_id=subject_id,
        risk_dimension="fraud",
        source="fraud.detector",
        evidence_refs=[
            EvidenceRef(id=event_id, type="event", source=source)
            for event_id, source in event_refs
        ],
    )
    await RiskSignalRepository().upsert_scoped(
        tenant_id, signal_id, signal.model_dump(mode="json")
    )


@pytest.mark.asyncio
async def test_materialize_alert_binds_one_persisted_signal_event() -> None:
    tenant_id = f"alert-binding-{uuid4().hex}"
    await _signal(tenant_id, "signal-1")

    result = await materialize_gold(
        MaterializeRequest(
            domain="identity",
            metric_name="anomaly_alert",
            entity_id="agent-1",
            entity_type="agent",
            value={"source_reported_alert": True},
            dimensions={"risk_signal_id": "signal-1"},
            source_tag="risk-review-1",
        ),
        SimpleNamespace(state=SimpleNamespace(tenant=_Tenant(tenant_id))),
    )

    dimensions = result["data"]["dimensions"]
    assert dimensions["risk_signal_id"] == "signal-1"
    assert dimensions["source_event_id"] == "event-1"
    assert dimensions["source_event_source"] == "bronze.observation"

    read = await RepositoryRiskSourceReader().anomaly_events(
        tenant_id=tenant_id,
        subject=ProjectionSubject(kind="agent", id="agent-1"),
    )
    assert read.complete is True
    assert len(read.records) == 1
    assert read.records[0]["source_event_join"]["state"] == (
        "verified_signal_evidence_reference"
    )
    assert read.records[0]["source_event_join"]["risk_signal_id"] == "signal-1"


@pytest.mark.asyncio
async def test_alert_write_rejects_cross_tenant_and_subject_signal() -> None:
    tenant_id = f"alert-binding-{uuid4().hex}"
    await _signal(tenant_id, "signal-1")
    body = MaterializeRequest(
        domain="identity",
        metric_name="anomaly_alert",
        entity_id="agent-1",
        entity_type="agent",
        value={},
        dimensions={"risk_signal_id": "signal-1"},
    )
    with pytest.raises(BadRequestError):
        await materialize_gold(
            body,
            SimpleNamespace(state=SimpleNamespace(tenant=_Tenant(f"other-{tenant_id}"))),
        )
    with pytest.raises(BadRequestError):
        await materialize_gold(
            body.model_copy(update={"entity_id": "agent-2"}),
            SimpleNamespace(state=SimpleNamespace(tenant=_Tenant(tenant_id))),
        )


@pytest.mark.asyncio
async def test_alert_write_requires_exact_selection_for_multiple_events() -> None:
    tenant_id = f"alert-binding-{uuid4().hex}"
    await _signal(
        tenant_id,
        "signal-1",
        event_refs=(("event-1", "bronze.observation"), ("event-2", "bronze.observation")),
    )
    scope = {
        "tenant_id": tenant_id,
        "subject_kind": "agent",
        "subject_id": "agent-1",
    }
    with pytest.raises(BadRequestError):
        await verified_anomaly_alert_dimensions(
            **scope, dimensions={"risk_signal_id": "signal-1"}
        )
    with pytest.raises(BadRequestError):
        await verified_anomaly_alert_dimensions(
            **scope,
            dimensions={
                "risk_signal_id": "signal-1",
                "source_event_id": "event-3",
                "source_event_source": "bronze.observation",
            },
        )
    selected = await verified_anomaly_alert_dimensions(
        **scope,
        dimensions={
            "risk_signal_id": "signal-1",
            "source_event_id": "event-2",
            "source_event_source": "bronze.observation",
        },
    )
    assert selected["source_event_id"] == "event-2"
