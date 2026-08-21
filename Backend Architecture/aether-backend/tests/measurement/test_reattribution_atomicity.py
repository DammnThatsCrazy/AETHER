"""Re-attribution invalidation: atomic run switch (N8) + cluster selectors (N11).

* N8  — ``_supersede_runs_for_conversions`` previously called
        ``deactivate_prior_runs()`` and then a separate ``update_run()``; in
        production those commit on independent connections, so a transient
        failure of the second after the first succeeded strands the conversion
        with NO active run (prior left inactive, replacement stuck
        inactive/running). The repo exposes ``complete_run_atomically()`` — the
        only success path that should activate a run — which deactivates the
        prior and activates the replacement in ONE transaction and rolls back on
        failure. The service must use it. Regression: a switch failure leaves the
        PRIOR run active (never no active run), and no standalone deactivation is
        issued.
* N11 — the voided-touchpoint resolver called ``list_by_profile`` untyped, which
        matches only profile_id OR anonymous_id. A fraud-network member that is a
        CLUSTER identity had its conversions discovered (the conversion side
        matches cluster_id) but an EMPTY voided touchpoint set, so its fraudulent
        active attribution was silently left in place. The resolver must also
        query the cluster_id dimension.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from services.measurement.reattribution import reattribute_affected
from services.measurement.repositories.attribution_run_repo import (
    AttributionRunRepository,
    _reset_local_attribution,
)
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.touchpoint_repo import (
    TouchpointRepository,
    _reset_local_touchpoints,
)

pytestmark = pytest.mark.asyncio


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _isolate_stores():
    _reset_local_attribution()
    _reset_local_touchpoints()
    yield
    _reset_local_attribution()
    _reset_local_touchpoints()


async def _seed_cluster_touchpoint(tenant_id: str, cluster_id: str) -> str:
    touchpoint_id = str(uuid4())
    await TouchpointRepository().upsert({
        "touchpoint_id": touchpoint_id,
        "tenant_id": tenant_id,
        "cluster_id": cluster_id,          # cluster identity — NOT profile/anonymous
        "channel": "paid_social",
        "source": "meta",
        "touchpoint_type": "click",
        "occurred_at": _now_iso(),
        "idempotency_key": f"reattr-cluster-tp-{touchpoint_id}",
    })
    return touchpoint_id


async def _seed_cluster_conversion(tenant_id: str, cluster_id: str) -> str:
    conversion_id = str(uuid4())
    await ConversionRepository().upsert({
        "conversion_id": conversion_id,
        "tenant_id": tenant_id,
        "conversion_type": "purchase",
        "cluster_id": cluster_id,          # cluster identity
        "gross_value": "100.00",
        "net_value": "100.00",
        "occurred_at": _now_iso(),
        "conversion_status": "confirmed",
        "attribution_eligible": True,
        "deduplication_key": f"reattr-cluster-order-{conversion_id}",
    })
    return conversion_id


async def _seed_active_run(tenant_id: str, conversion_id: str, touchpoint_id: str) -> str:
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


# ── N8: a failed switch never leaves the conversion with no active run ───────


class _AtomicFailRunRepo(AttributionRunRepository):
    """Models a transient failure DURING the active-run switch.

    ``complete_run_atomically`` raising models the production transaction
    aborting: because the deactivate+activate happen inside that one call, the
    prior run is never left inactive. The old two-call shape
    (deactivate_prior_runs then update_run) would instead have already committed
    the deactivation before failing.
    """

    def __init__(self) -> None:
        super().__init__()
        self.deactivate_calls = 0

    async def deactivate_prior_runs(self, tenant_id: str, conversion_id: str) -> int:
        self.deactivate_calls += 1
        return await super().deactivate_prior_runs(tenant_id, conversion_id)

    async def complete_run_atomically(self, *args, **kwargs):
        raise RuntimeError("simulated switch failure")


async def test_switch_failure_leaves_prior_run_active():
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    cluster_id = f"cluster-{uuid4().hex[:8]}"

    touchpoint_id = await _seed_cluster_touchpoint(tenant_id, cluster_id)
    conversion_id = await _seed_cluster_conversion(tenant_id, cluster_id)
    prior_run_id = await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    failing_repo = _AtomicFailRunRepo()
    result = await reattribute_affected(
        tenant_id,
        reason="fraud_takedown",
        conversions=[conversion_id],
        voided_touchpoint_ids={touchpoint_id},
        run_repo=failing_repo,
    )

    # The switch failed and is surfaced — never a blanket success.
    assert result.partial_failure is True
    assert result.conversions_reattributed == 0
    assert result.runs_deactivated == 0
    assert any(f"reattribution:{conversion_id}" in e for e in result.errors), result.errors

    # No standalone deactivate was issued — the switch goes through the atomic
    # method, so a failure cannot leave the prior run stranded inactive.
    assert failing_repo.deactivate_calls == 0

    # The conversion still has its ORIGINAL active run — not zero active runs.
    active_after = await AttributionRunRepository().get_active_run(tenant_id, conversion_id)
    assert active_after is not None
    assert active_after["attribution_run_id"] == prior_run_id
    assert active_after["is_active"] is True
    assert active_after["credit_total"] == "1.0"


# ── N11: cluster-identity members resolve their voided touchpoints ───────────


async def test_cluster_identity_voided_touchpoints_are_resolved():
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    cluster_id = f"cluster-{uuid4().hex[:8]}"

    touchpoint_id = await _seed_cluster_touchpoint(tenant_id, cluster_id)
    conversion_id = await _seed_cluster_conversion(tenant_id, cluster_id)
    prior_run_id = await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    # The member id is a cluster identity: the takedown passes it as both the
    # conversion selector AND the voided-touchpoint selector.
    result = await reattribute_affected(
        tenant_id,
        reason="fraud_takedown",
        identity_selectors=[cluster_id],
        voided_touchpoint_selectors=[cluster_id],
    )

    # The cluster's touchpoint is resolved into the voided set (was empty before
    # the fix), so its fraudulent attribution is actually superseded.
    assert result.touchpoints_scanned == 1
    assert result.conversions_scanned == 1
    assert result.conversions_reattributed == 1
    assert result.partial_failure is False

    active_after = await AttributionRunRepository().get_active_run(tenant_id, conversion_id)
    assert active_after is not None
    assert active_after["attribution_run_id"] != prior_run_id
    assert active_after["trigger_reason"] == "fraud_takedown"
    assert active_after["credit_total"] == "0"
    assert active_after["excluded_touchpoint_ids"] == [touchpoint_id]
