"""Fraud-network takedown must cover the WHOLE member set (N12).

``FraudNetworkMemberRepository.list_by_network`` returns a single 500-row page
and silently drops the rest. The takedown treated that page as the complete
network, so for a network expanded beyond 500 entities every member outside the
first page kept active fraudulent attribution while the takedown still reported
``partial_failure=False``.

The fix pages the full member set (``_list_all_network_members``) and, if even
the hard safety ceiling is exceeded, surfaces the truncation through the same
``partial_failure`` channel a per-conversion failure uses — never a clean
takedown over a network that could not be fully loaded.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

import services.fraud_networks.routes as fn_routes
from repositories.repos import FraudNetworkMemberRepository, FraudNetworkRepository
from services.fraud_networks.models import NetworkStatusUpdateRequest
from services.fraud_networks.routes import takedown_network

pytestmark = pytest.mark.asyncio


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _admin_request(tenant_id: str):
    from shared.auth.auth import Role, TenantContext

    return SimpleNamespace(
        state=SimpleNamespace(
            tenant=TenantContext(tenant_id=tenant_id, role=Role.ADMIN, permissions=[]),
        )
    )


class _RecordingProducer:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)


async def _seed_network(tenant_id: str, network_id: str) -> None:
    await FraudNetworkRepository().create({
        "id": network_id,
        "tenant_id": tenant_id,
        "label": "ring",
        "network_type": "layering_network",
        "status": "active",
        "anchor_entity_ids": [],
        "evidence_refs": [],
        "detected_signals": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "metadata": {},
    })


async def _seed_members(tenant_id: str, network_id: str, count: int) -> list[str]:
    repo = FraudNetworkMemberRepository()
    entity_ids: list[str] = []
    for _ in range(count):
        entity_id = f"entity-{uuid4().hex[:12]}"
        entity_ids.append(entity_id)
        await repo.create({
            "id": str(uuid4()),
            "network_id": network_id,
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "entity_type": "user",
            "role": "member",
            "joined_at": _now_iso(),
            "metadata": {},
        })
    return entity_ids


async def test_list_all_members_pages_past_the_500_cap():
    """The pager loads all 501 members; the single-page repo call returns 500."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    network_id = str(uuid4())
    await _seed_network(tenant_id, network_id)
    await _seed_members(tenant_id, network_id, 501)

    members, complete = await fn_routes._list_all_network_members(network_id)
    assert complete is True
    assert len(members) == 501

    # Documents the silent cap the takedown bug relied on.
    capped = await FraudNetworkMemberRepository().list_by_network(network_id)
    assert len(capped) == 500


async def test_takedown_surfaces_truncation_when_members_exceed_ceiling(monkeypatch):
    """When the member set cannot be fully loaded, the takedown reports it via
    partial_failure instead of a clean success — and still closes the network."""
    monkeypatch.setattr(fn_routes, "_require_feature", lambda: None)
    # Shrink the paging ceiling so a tiny seeded network trips it cheaply.
    monkeypatch.setattr(fn_routes, "_MEMBER_PAGE_SIZE", 2)
    monkeypatch.setattr(fn_routes, "_MAX_MEMBER_PAGES", 1)  # ceiling = 2 members

    tenant_id = f"tenant-{uuid4().hex[:8]}"
    network_id = str(uuid4())
    await _seed_network(tenant_id, network_id)
    await _seed_members(tenant_id, network_id, 3)  # one past the ceiling

    producer = _RecordingProducer()
    response = await takedown_network(
        network_id,
        NetworkStatusUpdateRequest(tenant_id=tenant_id, reason="confirmed fraud ring"),
        _admin_request(tenant_id),
        producer=producer,
    )

    # Network still marked down, but the truncation is surfaced honestly.
    assert response["status"] == "closed"
    reattr = response["reattribution"]
    assert reattr["partial_failure"] is True
    assert any("fraud_takedown_members_truncated" in e for e in reattr["errors"]), reattr["errors"]
    # The event carries the partial_failure marker too.
    assert producer.events[0].payload["partial_failure"] is True


async def test_takedown_clean_when_members_fit(monkeypatch):
    """A network whose members fit in one page loads completely — no truncation."""
    monkeypatch.setattr(fn_routes, "_require_feature", lambda: None)

    tenant_id = f"tenant-{uuid4().hex[:8]}"
    network_id = str(uuid4())
    await _seed_network(tenant_id, network_id)
    await _seed_members(tenant_id, network_id, 3)

    producer = _RecordingProducer()
    response = await takedown_network(
        network_id,
        NetworkStatusUpdateRequest(tenant_id=tenant_id, reason=None),
        _admin_request(tenant_id),
        producer=producer,
    )

    assert response["status"] == "closed"
    reattr = response["reattribution"]
    assert reattr["partial_failure"] is False
    assert not any("members_truncated" in e for e in reattr["errors"])
