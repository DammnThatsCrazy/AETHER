"""Unit tests — aggregated comms graph projection (Phase 17, ADR-C6)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _fact(event_type: str, **extra) -> dict:
    return {
        "tenant_id": "tenant-g",
        "source_event_type": event_type,
        "source_event_id": extra.pop("source_event_id", f"src-{event_type}"),
        "occurred_at": "2026-07-01T00:00:00+00:00",
        "channel": "email",
        "message_category": "marketing",
        "organization_id": "org-1",
        "recipient_entity_id": "ent-1",
        "provider": "klaviyo",
        "provider_account_id": "acct-1",
        **extra,
    }


@pytest.fixture(autouse=True)
def _clean():
    from services.comms.graph_projection import reset_local_relationships
    reset_local_relationships()
    yield
    reset_local_relationships()


class TestSenderResolution:
    def test_never_uses_global_system_sender(self):
        from services.comms.graph_projection import resolve_sender_ref
        assert resolve_sender_ref(_fact("email_delivered")) == "org:org-1"
        assert resolve_sender_ref(_fact("email_delivered", organization_id=None,
                                        agent_id="ag-1")) == "agent:ag-1"
        assert resolve_sender_ref(_fact("email_delivered", organization_id=None,
                                        sender_entity_id="ent-9")) == "entity:ent-9"
        assert resolve_sender_ref(_fact("email_delivered", organization_id=None)) == \
            "provider_account:klaviyo:acct-1"
        bare = _fact("email_delivered", organization_id=None,
                     provider=None, provider_account_id=None)
        assert resolve_sender_ref(bare) is None  # unresolvable → no edge, never "system"


class TestAggregation:
    @pytest.mark.asyncio
    async def test_events_aggregate_into_one_relationship(self):
        from services.comms.graph_projection import CommsGraphProjector
        projector = CommsGraphProjector()
        agg = None
        for i in range(5):
            agg = await projector.project_fact(
                _fact("email_delivered", source_event_id=f"e-{i}")
            )
        assert agg["message_count"] == 5
        assert agg["delivered_count"] == 5
        assert agg["reply_count"] == 0

    @pytest.mark.asyncio
    async def test_no_event_node_explosion(self):
        """100 events → exactly one relationship aggregate (ADR-C6)."""
        from services.comms.graph_projection import (
            CommsGraphProjector, _local_relationships,
        )
        projector = CommsGraphProjector()
        for i in range(100):
            await projector.project_fact(
                _fact("email_delivered", source_event_id=f"e-{i}")
            )
        assert len(_local_relationships) == 1

    @pytest.mark.asyncio
    async def test_lifecycle_noise_and_machine_events_excluded(self):
        from services.comms.graph_projection import (
            CommsGraphProjector, _local_relationships,
        )
        projector = CommsGraphProjector()
        assert await projector.project_fact(_fact("email_queued")) is None
        assert await projector.project_fact(_fact("email_bounced")) is None
        assert await projector.project_fact(
            _fact("email_clicked", suspected_machine_activity=True)
        ) is None
        assert len(_local_relationships) == 0

    @pytest.mark.asyncio
    async def test_evidence_refs_bounded(self):
        from services.comms.graph_projection import CommsGraphProjector
        projector = CommsGraphProjector()
        agg = None
        for i in range(30):
            agg = await projector.project_fact(
                _fact("email_delivered", source_event_id=f"e-{i}")
            )
        assert len(agg["evidence_refs"]) <= 20


class TestEdgeTypes:
    @pytest.mark.asyncio
    async def test_marketing_send_is_contacted(self):
        from services.comms.graph_projection import CommsGraphProjector
        agg = await CommsGraphProjector().project_fact(_fact("email_delivered"))
        assert agg["edge_type"] == "CONTACTED"

    @pytest.mark.asyncio
    async def test_reply_upgrades_to_communicates_with(self):
        from services.comms.graph_projection import CommsGraphProjector
        agg = await CommsGraphProjector().project_fact(_fact("email_replied"))
        assert agg["edge_type"] == "COMMUNICATES_WITH"
        # inbound reply flows recipient → sender context
        assert agg["sender_ref"] == "entity:ent-1"

    @pytest.mark.asyncio
    async def test_agent_notification_layer(self):
        from services.comms.graph_projection import CommsGraphProjector
        agg = await CommsGraphProjector().project_fact(_fact(
            "notification_delivered", organization_id=None, agent_id="ag-7",
            message_category="operational", channel="push",
        ))
        assert agg["edge_type"] == "NOTIFIES"
        assert agg["sender_ref"] == "agent:ag-7"

    @pytest.mark.asyncio
    async def test_tenant_isolation_in_aggregate_key(self):
        from services.comms.graph_projection import (
            CommsGraphProjector, _local_relationships,
        )
        projector = CommsGraphProjector()
        await projector.project_fact(_fact("email_delivered"))
        await projector.project_fact({**_fact("email_delivered"), "tenant_id": "tenant-h"})
        assert len(_local_relationships) == 2
