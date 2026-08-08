"""Reliability Phase-2, Program 3 M3: generalized re-attribution invalidation.

See docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md §3. M3 extracts the
per-conversion "supersede the stale attribution run" core that M1 inlined into
``services/measurement/privacy.py`` into the standalone, callable
``services.measurement.reattribution.reattribute_affected`` service, and wires
a fraud-network takedown flow to it with ``reason="fraud_takedown"``.

Coverage here:
  (a) the service works standalone — deactivates + recreates runs, returns
      correct structured counts, filters on voided-touchpoint overlap, resolves
      identity selectors, surfaces scope truncation, and never blanket-succeeds
      on a per-conversion failure;
  (b) the fraud takedown route path triggers invalidation with
      reason="fraud_takedown" (retaining evidence — no tombstone);
  (c) a parity guard that ``handle_erasure`` still returns the exact same dict
      keys/shape it did before the extraction (the behavioral parity is proven
      in full by tests/dsr/test_erasure_reattribution.py, run alongside this).
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

import services.measurement.reattribution as reattr_mod
from services.measurement.reattribution import ReattributionResult, reattribute_affected
from services.measurement.privacy import MeasurementPrivacyHandler
from services.measurement.repositories.attribution_run_repo import (
    AttributionRunRepository,
    _reset_local_attribution,
)
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.touchpoint_repo import TouchpointRepository

pytestmark = pytest.mark.asyncio


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _isolate_attribution_stores():
    _reset_local_attribution()
    yield
    _reset_local_attribution()


async def _seed_touchpoint(tenant_id: str, identity: str) -> str:
    touchpoint_id = str(uuid4())
    await TouchpointRepository().upsert({
        "touchpoint_id": touchpoint_id,
        "tenant_id": tenant_id,
        "profile_id": identity,
        "channel": "paid_social",
        "source": "meta",
        "touchpoint_type": "click",
        "occurred_at": _now_iso(),
        "idempotency_key": f"reattr-tp-{touchpoint_id}",
    })
    return touchpoint_id


async def _seed_conversion(tenant_id: str, identity: str, *, gross_value: str = "100.00") -> str:
    conversion_id = str(uuid4())
    await ConversionRepository().upsert({
        "conversion_id": conversion_id,
        "tenant_id": tenant_id,
        "conversion_type": "purchase",
        "profile_id": identity,
        "gross_value": gross_value,
        "net_value": gross_value,
        "occurred_at": _now_iso(),
        "conversion_status": "confirmed",
        "attribution_eligible": True,
        "deduplication_key": f"reattr-order-{conversion_id}",
    })
    return conversion_id


async def _seed_active_run(tenant_id: str, conversion_id: str, touchpoint_id: str) -> str:
    """Seed a completed, ACTIVE run crediting ``touchpoint_id`` — the state an
    invalidation must supersede."""
    run_repo = AttributionRunRepository()
    run = await run_repo.create_run({
        "tenant_id": tenant_id,
        "conversion_id": conversion_id,
        "model_type": "last_touch",
        "status": "running",
        "input_touchpoint_ids": [touchpoint_id],
        "started_at": _now_iso(),
    })
    completed = await run_repo.update_run(
        run["attribution_run_id"],
        {
            "status": "complete",
            "is_active": True,
            "completed_at": _now_iso(),
            "credit_total": "1.0",
            "unattributed_credit": "0.0",
            "input_touchpoint_ids": [touchpoint_id],
        },
        tenant_id=tenant_id,
    )
    assert completed is not None and completed["is_active"] is True
    return run["attribution_run_id"]


# ── (a) service standalone ───────────────────────────────────────────────────


async def test_reattribute_affected_supersedes_run_and_returns_counts():
    """Given a pre-resolved conversion whose active run credits a voided
    touchpoint, the service deactivates the stale run, creates a fresh active
    zero-credit run stamped with the trigger reason, and returns exact counts."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    identity = f"profile-{uuid4().hex[:8]}"

    touchpoint_id = await _seed_touchpoint(tenant_id, identity)
    conversion_id = await _seed_conversion(tenant_id, identity)
    prior_run_id = await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    result = await reattribute_affected(
        tenant_id,
        reason="fraud_takedown",
        conversions=[conversion_id],
        voided_touchpoint_ids={touchpoint_id},
    )

    assert isinstance(result, ReattributionResult)
    assert result.reason == "fraud_takedown"
    assert result.conversions_scanned == 1
    assert result.conversions_reattributed == 1
    assert result.runs_deactivated == 1
    assert result.runs_created == 1
    assert result.truncated is False
    assert result.partial_failure is False
    assert result.errors == []

    run_repo = AttributionRunRepository()
    prior_after = await run_repo.get_run(prior_run_id, tenant_id=tenant_id)
    assert prior_after is not None and prior_after["is_active"] is False

    active_after = await run_repo.get_active_run(tenant_id, conversion_id)
    assert active_after is not None
    assert active_after["attribution_run_id"] != prior_run_id
    assert active_after["credit_total"] == "0"
    assert active_after["prior_attribution_run_id"] == prior_run_id
    assert active_after["trigger_reason"] == "fraud_takedown"
    assert active_after["excluded_touchpoint_ids"] == [touchpoint_id]
    assert active_after["exclusion_reasons"] == {touchpoint_id: "fraud_takedown"}


async def test_reattribute_affected_skips_runs_without_voided_overlap():
    """A conversion whose active run does NOT credit any voided touchpoint is
    left exactly as it was — the same "its touchpoint set actually changed"
    filter M1 uses."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    identity = f"profile-{uuid4().hex[:8]}"

    touchpoint_id = await _seed_touchpoint(tenant_id, identity)
    conversion_id = await _seed_conversion(tenant_id, identity)
    prior_run_id = await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    # Void an UNRELATED touchpoint — no overlap with this run's credited set.
    result = await reattribute_affected(
        tenant_id,
        reason="fraud_takedown",
        conversions=[conversion_id],
        voided_touchpoint_ids={str(uuid4())},
    )

    assert result.conversions_scanned == 1
    assert result.conversions_reattributed == 0
    assert result.runs_created == 0
    assert result.partial_failure is False

    active_after = await AttributionRunRepository().get_active_run(tenant_id, conversion_id)
    assert active_after is not None
    assert active_after["attribution_run_id"] == prior_run_id
    assert active_after["credit_total"] == "1.0"


async def test_reattribute_affected_empty_voided_set_is_a_noop():
    """No voided touchpoints -> nothing is superseded (identical short-circuit
    to M1's ``if tombstoned_touchpoint_ids and candidate_conversion_ids``)."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    identity = f"profile-{uuid4().hex[:8]}"
    touchpoint_id = await _seed_touchpoint(tenant_id, identity)
    conversion_id = await _seed_conversion(tenant_id, identity)
    await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    result = await reattribute_affected(
        tenant_id, reason="fraud_takedown", conversions=[conversion_id],
    )
    assert result.conversions_reattributed == 0
    assert result.partial_failure is False


async def test_reattribute_affected_resolves_identity_selectors():
    """Passing identity_selectors (not pre-resolved conversions) resolves both
    the candidate conversions and the voided touchpoints from the identity, then
    invalidates — the path the fraud takedown uses."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    identity = f"entity-{uuid4().hex[:8]}"

    touchpoint_id = await _seed_touchpoint(tenant_id, identity)
    conversion_id = await _seed_conversion(tenant_id, identity)
    prior_run_id = await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    result = await reattribute_affected(
        tenant_id,
        reason="fraud_takedown",
        identity_selectors=[identity],
        voided_touchpoint_selectors=[identity],
    )

    assert result.conversions_scanned == 1
    assert result.touchpoints_scanned == 1
    assert result.conversions_reattributed == 1
    assert result.truncated is False
    assert result.partial_failure is False

    active_after = await AttributionRunRepository().get_active_run(tenant_id, conversion_id)
    assert active_after is not None
    assert active_after["attribution_run_id"] != prior_run_id
    assert active_after["trigger_reason"] == "fraud_takedown"
    assert active_after["credit_total"] == "0"


async def test_reattribute_affected_surfaces_scope_truncation():
    """When an identity has more touchpoints/conversions than scope_limit, the
    overage is surfaced (truncated=True + errors + partial_failure), never
    silently dropped."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    identity = f"entity-{uuid4().hex[:8]}"

    # Two of each — one past the scope_limit of 1.
    tp1 = await _seed_touchpoint(tenant_id, identity)
    c1 = await _seed_conversion(tenant_id, identity)
    await _seed_active_run(tenant_id, c1, tp1)
    tp2 = await _seed_touchpoint(tenant_id, identity)
    c2 = await _seed_conversion(tenant_id, identity)
    await _seed_active_run(tenant_id, c2, tp2)

    result = await reattribute_affected(
        tenant_id,
        reason="fraud_takedown",
        identity_selectors=[identity],
        voided_touchpoint_selectors=[identity],
        scope_limit=1,
    )

    assert result.truncated is True
    assert result.scope_limit == 1
    assert result.partial_failure is True
    assert any("reattribution_scope_truncated" in e for e in result.errors), result.errors
    # Bounded scope discovery trims to the limit — never scans unbounded.
    assert result.touchpoints_scanned == 1
    assert result.conversions_scanned == 1


async def test_reattribute_affected_partial_failure_never_blanket_success(monkeypatch):
    """If invalidation fails for one conversion and succeeds for another, the
    service reports partial_failure explicitly (never a blanket success) and
    still corrects the healthy one."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    identity = f"profile-{uuid4().hex[:8]}"

    ok_tp = await _seed_touchpoint(tenant_id, identity)
    ok_cid = await _seed_conversion(tenant_id, identity)
    ok_prior = await _seed_active_run(tenant_id, ok_cid, ok_tp)

    bad_tp = await _seed_touchpoint(tenant_id, identity)
    bad_cid = await _seed_conversion(tenant_id, identity)
    bad_prior = await _seed_active_run(tenant_id, bad_cid, bad_tp)

    real_create_run = reattr_mod._attribution_run_repo.create_run

    async def _flaky_create_run(payload):
        if payload.get("conversion_id") == bad_cid:
            raise RuntimeError("simulated invalidation failure")
        return await real_create_run(payload)

    monkeypatch.setattr(reattr_mod._attribution_run_repo, "create_run", _flaky_create_run)

    result = await reattribute_affected(
        tenant_id,
        reason="fraud_takedown",
        conversions=[ok_cid, bad_cid],
        voided_touchpoint_ids={ok_tp, bad_tp},
    )

    assert result.partial_failure is True
    assert result.conversions_reattributed == 1
    assert any(
        e.startswith(f"reattribution:{bad_cid}") and "simulated invalidation failure" in e
        for e in result.errors
    ), result.errors

    run_repo = AttributionRunRepository()
    ok_active = await run_repo.get_active_run(tenant_id, ok_cid)
    assert ok_active["attribution_run_id"] != ok_prior
    assert ok_active["credit_total"] == "0"
    # The failing conversion keeps its prior run — never left with NO active run.
    bad_active = await run_repo.get_active_run(tenant_id, bad_cid)
    assert bad_active["attribution_run_id"] == bad_prior
    assert bad_active["credit_total"] == "1.0"


# ── (b) fraud takedown route path ────────────────────────────────────────────


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


async def test_fraud_takedown_invalidates_attribution_with_reason(monkeypatch):
    """The takedown route resolves the network's member identities, invalidates
    their fraudulent attribution via the service with reason='fraud_takedown',
    marks the network closed, and does NOT delete the underlying evidence."""
    import services.fraud_networks.routes as fn_routes
    from repositories.repos import FraudNetworkMemberRepository, FraudNetworkRepository
    from services.fraud_networks.models import NetworkStatusUpdateRequest
    from services.fraud_networks.routes import takedown_network

    # The feature flag lives on a frozen settings dataclass; bypass just the
    # feature gate (the permission + tenant-match checks in _require still run).
    monkeypatch.setattr(fn_routes, "_require_feature", lambda: None)

    tenant_id = f"tenant-{uuid4().hex[:8]}"
    entity_id = f"entity-{uuid4().hex[:8]}"
    network_id = str(uuid4())

    # Seed the fraudulent identity's touchpoint + conversion + winning run.
    touchpoint_id = await _seed_touchpoint(tenant_id, entity_id)
    conversion_id = await _seed_conversion(tenant_id, entity_id)
    prior_run_id = await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    # Seed a fraud network + one member pointing at that identity.
    await FraudNetworkRepository().create({
        "id": network_id,
        "tenant_id": tenant_id,
        "label": "ring",
        "network_type": "layering_network",
        "status": "active",
        "anchor_entity_ids": [entity_id],
        "evidence_refs": [],
        "detected_signals": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "metadata": {},
    })
    await FraudNetworkMemberRepository().create({
        "id": str(uuid4()),
        "network_id": network_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "entity_type": "user",
        "role": "anchor",
        "joined_at": _now_iso(),
        "metadata": {},
    })

    producer = _RecordingProducer()
    response = await takedown_network(
        network_id,
        NetworkStatusUpdateRequest(tenant_id=tenant_id, reason="confirmed fraud ring"),
        _admin_request(tenant_id),
        producer=producer,
    )

    # Route response carries the structured invalidation summary.
    assert response["status"] == "closed"
    assert response["reattribution"]["reason"] == "fraud_takedown"
    assert response["reattribution"]["conversions_reattributed"] == 1
    assert response["reattribution"]["partial_failure"] is False

    # The fraudulent attribution really was superseded, reason recorded.
    run_repo = AttributionRunRepository()
    prior_after = await run_repo.get_run(prior_run_id, tenant_id=tenant_id)
    assert prior_after["is_active"] is False
    active_after = await run_repo.get_active_run(tenant_id, conversion_id)
    assert active_after["attribution_run_id"] != prior_run_id
    assert active_after["trigger_reason"] == "fraud_takedown"
    assert active_after["credit_total"] == "0"

    # Evidence is RETAINED — a takedown voids attribution but does not tombstone
    # the touchpoint/conversion (unlike privacy erasure).
    conv = await ConversionRepository().get(tenant_id, conversion_id)
    assert conv is not None
    tps = await TouchpointRepository().list_by_profile(tenant_id, entity_id)
    assert any(str(t.get("touchpoint_id")) == touchpoint_id for t in tps)

    # A takedown event was published with the takedown marker + counts.
    assert len(producer.events) == 1
    payload = producer.events[0].payload
    assert payload["update"] == "takedown"
    assert payload["network_id"] == network_id
    assert payload["conversions_reattributed"] == 1


async def test_fraud_takedown_clean_when_network_has_no_attribution(monkeypatch):
    """A network whose entities produced no attribution is a clean takedown:
    zero reattributed, no errors, still marked closed."""
    import services.fraud_networks.routes as fn_routes
    from repositories.repos import FraudNetworkRepository
    from services.fraud_networks.models import NetworkStatusUpdateRequest
    from services.fraud_networks.routes import takedown_network

    monkeypatch.setattr(fn_routes, "_require_feature", lambda: None)

    tenant_id = f"tenant-{uuid4().hex[:8]}"
    entity_id = f"entity-{uuid4().hex[:8]}"
    network_id = str(uuid4())

    await FraudNetworkRepository().create({
        "id": network_id,
        "tenant_id": tenant_id,
        "network_type": "unknown",
        "status": "active",
        "anchor_entity_ids": [entity_id],
        "evidence_refs": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "metadata": {},
    })

    producer = _RecordingProducer()
    response = await takedown_network(
        network_id,
        NetworkStatusUpdateRequest(tenant_id=tenant_id, reason=None),
        _admin_request(tenant_id),
        producer=producer,
    )

    assert response["status"] == "closed"
    assert response["reattribution"]["conversions_reattributed"] == 0
    assert response["reattribution"]["partial_failure"] is False
    assert response["reattribution"]["truncated"] is False


# ── (c) privacy parity guard ─────────────────────────────────────────────────


async def test_privacy_erasure_dict_shape_unchanged_after_extraction():
    """handle_erasure must still return the exact evidence-dict keys it did
    before the M3 extraction — the delegation to reattribute_affected is a pure
    parity refactor. (Full behavioral parity: tests/dsr/test_erasure_reattribution.py.)"""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    identity = f"profile-{uuid4().hex[:8]}"

    touchpoint_id = await _seed_touchpoint(tenant_id, identity)
    conversion_id = await _seed_conversion(tenant_id, identity)
    prior_run_id = await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    result = await MeasurementPrivacyHandler().handle_erasure(tenant_id, identity)

    assert set(result.keys()) == {
        "tenant_id",
        "user_id",
        "touchpoints_tombstoned",
        "conversions_tombstoned",
        "journey_rebuild_triggered",
        "conversions_reattributed",
        "reattribution_truncated",
        "reattribution_scope_limit",
        "reattribution_touchpoints_scanned",
        "reattribution_conversions_scanned",
        "errors",
        "partial_failure",
    }
    # And the erasure still stamps reason="privacy_erasure" (not fraud_takedown).
    assert result["conversions_reattributed"] == 1
    assert result["errors"] == []
    active_after = await AttributionRunRepository().get_active_run(tenant_id, conversion_id)
    assert active_after["attribution_run_id"] != prior_run_id
    assert active_after["trigger_reason"] == "privacy_erasure"
