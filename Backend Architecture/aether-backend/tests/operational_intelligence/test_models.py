from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.operational_intelligence.models import (
    EventPipelineEnvelope,
    GraphEdge,
    GraphFilterRequest,
    GraphTraversalRequest,
    RealtimeSubscribeMessage,
    ShortestPathRequest,
    TemporalGraphRequest,
)


def test_graph_traversal_accepts_frontend_contract_shape() -> None:
    request = GraphTraversalRequest.model_validate(
        {
            "tenantId": "tenant_a",
            "start": {"kind": "user", "id": "user_1", "label": "Ada"},
            "depth": 2,
            "direction": "both",
            "filter": {
                "kinds": ["wallet", "agent"],
                "scoreRanges": {"risk": {"min": 0.2, "max": 0.8}},
                "time": {"from": "2026-05-01T00:00:00Z", "to": "2026-05-17T00:00:00Z"},
            },
            "overlays": ["risk", "attribution"],
            "limit": 25,
        }
    )

    assert request.tenantId == "tenant_a"
    assert request.start.kind == "user"
    assert request.filter is not None
    assert request.filter.time is not None
    assert request.filter.time.from_ == "2026-05-01T00:00:00Z"


def test_graph_contracts_reject_invalid_bounds() -> None:
    with pytest.raises(ValidationError):
        GraphTraversalRequest.model_validate(
            {"tenantId": "tenant_a", "start": {"kind": "user", "id": "user_1"}, "depth": 0}
        )

    with pytest.raises(ValidationError):
        GraphFilterRequest.model_validate(
            {"tenantId": "tenant_a", "filter": {"scoreRanges": {"risk": {"min": -0.1}}}}
        )


def test_aliases_round_trip_for_reserved_graph_fields() -> None:
    edge = GraphEdge.model_validate(
        {"id": "edge_1", "type": "OWNS_WALLET", "from": "user_1", "to": "wallet_1", "directed": True}
    )
    path = ShortestPathRequest.model_validate(
        {
            "tenantId": "tenant_a",
            "from": {"kind": "user", "id": "user_1"},
            "to": {"kind": "wallet", "id": "wallet_1"},
        }
    )
    temporal = TemporalGraphRequest.model_validate(
        {"tenantId": "tenant_a", "anchor": {"kind": "user", "id": "user_1"}, "asOf": "2026-05-17T00:00:00Z"}
    )

    assert edge.from_ == "user_1"
    assert edge.model_dump(by_alias=True)["from"] == "user_1"
    assert path.from_.id == "user_1"
    assert path.model_dump(by_alias=True)["from"]["id"] == "user_1"
    assert temporal.asOf == "2026-05-17T00:00:00Z"


def test_event_pipeline_and_realtime_contracts_accept_intelligence_events() -> None:
    envelope = EventPipelineEnvelope.model_validate(
        {
            "id": "evt_1",
            "type": "graph.mutated",
            "tenantId": "tenant_a",
            "occurredAt": "2026-05-17T00:00:00Z",
            "ingestedAt": "2026-05-17T00:00:01Z",
            "schemaVersion": "1.0.0",
            "source": "graph-engine",
            "subject": {"kind": "user", "id": "user_1"},
            "replayable": True,
            "payload": {"nodes": 1},
        }
    )
    subscription = RealtimeSubscribeMessage.model_validate(
        {
            "action": "subscribe",
            "requestId": "req_1",
            "tenantId": "tenant_a",
            "channels": ["tenant.graph", "entity.relationships"],
            "cursor": "cursor_1",
        }
    )

    assert envelope.type == "graph.mutated"
    assert envelope.subject is not None
    assert subscription.channels == ["tenant.graph", "entity.relationships"]
