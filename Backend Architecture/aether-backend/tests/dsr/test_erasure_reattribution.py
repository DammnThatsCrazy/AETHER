"""Program 3 M1: re-attribution wired into measurement privacy erasure.

See docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md §3 ("Deletion / replay /
re-attribution") for the full, multi-milestone program this increment starts.
This test file covers ONLY M1: ``MeasurementPrivacyHandler.handle_erasure``
now supersedes the stale attribution run of every conversion whose ACTIVE
run was built from a touchpoint this same erasure just tombstoned, using the
same ``AttributionRunRepository`` run-creation primitives (``create_run`` /
``deactivate_prior_runs``) that ``attribution_engine.py`` and
``subscription_ltv.py`` already call in production. M2 (DSR propagation
evidence), M3 (generalized invalidation service), and M4 (replay) are
explicitly out of scope and are not exercised here.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

import services.measurement.privacy as privacy_mod
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
    # Attribution runs/credits live in their own module-level dicts, separate
    # from reset_in_memory_stores() (see attribution_run_repo.py's own
    # _reset_local_attribution docstring) — must be cleared explicitly.
    _reset_local_attribution()
    yield
    _reset_local_attribution()


async def _seed_touchpoint_and_conversion(
    tenant_id: str, profile_id: str, *, gross_value: str = "100.00"
) -> tuple[str, str]:
    """Seed one profile-owned touchpoint and one profile-owned conversion.

    Uses fresh uuid4 ids so this is safe to call repeatedly across tests
    sharing the same (session-lifetime, unreset) touchpoint/conversion local
    stores — matches the isolation approach already used by
    tests/e2e/test_privacy_consent_flow.py for the same repositories.
    """
    touchpoint_id = str(uuid4())
    conversion_id = str(uuid4())

    await TouchpointRepository().upsert({
        "touchpoint_id": touchpoint_id,
        "tenant_id": tenant_id,
        "profile_id": profile_id,
        "channel": "paid_social",
        "source": "meta",
        "touchpoint_type": "click",
        "occurred_at": _now_iso(),
        "idempotency_key": f"reattr-tp-{touchpoint_id}",
    })
    await ConversionRepository().upsert({
        "conversion_id": conversion_id,
        "tenant_id": tenant_id,
        "conversion_type": "purchase",
        "profile_id": profile_id,
        "gross_value": gross_value,
        "net_value": gross_value,
        "occurred_at": _now_iso(),
        "conversion_status": "confirmed",
        "attribution_eligible": True,
        "deduplication_key": f"reattr-order-{conversion_id}",
    })
    return touchpoint_id, conversion_id


async def _seed_active_run(
    tenant_id: str, conversion_id: str, touchpoint_id: str
) -> str:
    """Seed a completed, ACTIVE attribution run crediting touchpoint_id as the
    conversion's sole (winning) touchpoint — the pre-erasure state M1 must
    correct."""
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


async def test_erasure_deactivates_stale_run_and_creates_active_replacement():
    """Erasing a profile whose conversion had a winning touchpoint must
    deactivate the stale, now-wrong run and leave a fresh run active."""
    tenant_id = f"tenant-reattr-{uuid4().hex[:8]}"
    profile_id = f"profile-{uuid4().hex[:8]}"

    touchpoint_id, conversion_id = await _seed_touchpoint_and_conversion(tenant_id, profile_id)
    prior_run_id = await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    run_repo = AttributionRunRepository()
    assert (await run_repo.get_active_run(tenant_id, conversion_id))["attribution_run_id"] == prior_run_id

    result = await MeasurementPrivacyHandler().handle_erasure(tenant_id, profile_id)

    assert result["errors"] == []
    assert result["partial_failure"] is False
    assert result["touchpoints_tombstoned"] == 1
    assert result["conversions_tombstoned"] == 1
    assert result["conversions_reattributed"] == 1

    # The prior (winning-touchpoint-erased) run is deactivated ...
    prior_after = await run_repo.get_run(prior_run_id, tenant_id=tenant_id)
    assert prior_after is not None
    assert prior_after["is_active"] is False

    # ... and a NEW run is active, superseding it, with no stale credit.
    active_after = await run_repo.get_active_run(tenant_id, conversion_id)
    assert active_after is not None
    assert active_after["attribution_run_id"] != prior_run_id
    assert active_after["credit_total"] == "0"
    assert active_after["prior_attribution_run_id"] == prior_run_id
    assert active_after["trigger_reason"] == "privacy_erasure"


async def test_erasure_leaves_unaffected_conversions_active_run_untouched():
    """A conversion whose active run does NOT reference an erased touchpoint
    (i.e. its touchpoint set did not change) must be left exactly as is —
    M1 only corrects runs whose credited touchpoints were actually erased."""
    tenant_id = f"tenant-reattr-{uuid4().hex[:8]}"
    profile_id = f"profile-{uuid4().hex[:8]}"
    other_profile_id = f"profile-other-{uuid4().hex[:8]}"

    # This profile's own touchpoint/conversion/run — WILL be corrected.
    touchpoint_id, conversion_id = await _seed_touchpoint_and_conversion(tenant_id, profile_id)
    await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    # A different profile's touchpoint/conversion/run — must NOT be touched by
    # this erasure.
    other_touchpoint_id, other_conversion_id = await _seed_touchpoint_and_conversion(
        tenant_id, other_profile_id
    )
    other_run_id = await _seed_active_run(tenant_id, other_conversion_id, other_touchpoint_id)

    result = await MeasurementPrivacyHandler().handle_erasure(tenant_id, profile_id)
    assert result["partial_failure"] is False
    assert result["conversions_reattributed"] == 1

    run_repo = AttributionRunRepository()
    untouched = await run_repo.get_active_run(tenant_id, other_conversion_id)
    assert untouched is not None
    assert untouched["attribution_run_id"] == other_run_id
    assert untouched["credit_total"] == "1.0"


async def test_partial_failure_when_one_conversion_reattribution_fails(monkeypatch):
    """If re-attribution succeeds for one conversion and fails for another,
    handle_erasure must report partial_failure explicitly — never a blanket
    success — matching its existing per-store partial_failure pattern."""
    tenant_id = f"tenant-reattr-{uuid4().hex[:8]}"
    profile_id = f"profile-{uuid4().hex[:8]}"

    ok_touchpoint_id, ok_conversion_id = await _seed_touchpoint_and_conversion(tenant_id, profile_id)
    ok_prior_run_id = await _seed_active_run(tenant_id, ok_conversion_id, ok_touchpoint_id)

    bad_touchpoint_id, bad_conversion_id = await _seed_touchpoint_and_conversion(tenant_id, profile_id)
    bad_prior_run_id = await _seed_active_run(tenant_id, bad_conversion_id, bad_touchpoint_id)

    run_repo = AttributionRunRepository()
    real_create_run = run_repo.create_run

    async def _flaky_create_run(payload):
        if payload.get("conversion_id") == bad_conversion_id:
            raise RuntimeError("simulated re-attribution failure")
        return await real_create_run(payload)

    monkeypatch.setattr(privacy_mod._attribution_run_repo, "create_run", _flaky_create_run)

    result = await MeasurementPrivacyHandler().handle_erasure(tenant_id, profile_id)

    assert result["partial_failure"] is True
    assert result["conversions_reattributed"] == 1
    assert any(
        e.startswith(f"reattribution:{bad_conversion_id}") and "simulated re-attribution failure" in e
        for e in result["errors"]
    ), result["errors"]

    # The tombstone steps (privacy-critical) still fully succeeded despite the
    # re-attribution failure — erasure itself is never blocked by this step.
    assert result["touchpoints_tombstoned"] == 2
    assert result["conversions_tombstoned"] == 2

    # The succeeding conversion really was corrected ...
    ok_active = await run_repo.get_active_run(tenant_id, ok_conversion_id)
    assert ok_active is not None
    assert ok_active["attribution_run_id"] != ok_prior_run_id
    assert ok_active["credit_total"] == "0"

    # ... while the failing conversion's stale run is left exactly as it was:
    # still active, still crediting the now-erased touchpoint. Worse would be
    # silently reporting success; better-but-unimplemented would be retrying
    # it — but it must never be left with NO active run at all (that would be
    # a correctness regression, not a fix).
    bad_active = await run_repo.get_active_run(tenant_id, bad_conversion_id)
    assert bad_active is not None
    assert bad_active["attribution_run_id"] == bad_prior_run_id
    assert bad_active["credit_total"] == "1.0"


async def test_erasure_with_no_prior_attribution_is_a_clean_success():
    """A profile with no touchpoints/conversions at all must not be affected
    by the new re-attribution step (no spurious errors, count stays 0)."""
    tenant_id = f"tenant-reattr-{uuid4().hex[:8]}"
    profile_id = f"profile-empty-{uuid4().hex[:8]}"

    result = await MeasurementPrivacyHandler().handle_erasure(tenant_id, profile_id)

    assert result["errors"] == []
    assert result["partial_failure"] is False
    assert result["conversions_reattributed"] == 0
    assert result["touchpoints_tombstoned"] == 0
    assert result["conversions_tombstoned"] == 0


async def test_erasure_deactivates_stale_run_for_conversion_identified_only_by_account_id():
    """Regression test — verifier HIGH finding (account_id snapshot mismatch).

    ``ConversionRepository.tombstone_for_profile`` matches ``profile_id = X OR
    cluster_id = X OR account_id = X``, so a conversion reachable ONLY through
    account_id genuinely gets tombstoned by this erasure. Before the fix, the
    re-attribution snapshot was read via ``list_by_profile`` (profile_id OR
    cluster_id only), which never sees such a conversion — the tombstone
    still happens, but the stale, now-wrong active attribution run crediting
    an erased touchpoint is never deactivated: the exact stale-credit bug
    this whole re-attribution step exists to close. The fix reads the
    snapshot via ``list_by_erasure_identity`` instead, matching the same
    three identity columns ``tombstone_for_profile`` does.
    """
    tenant_id = f"tenant-reattr-{uuid4().hex[:8]}"
    account_id = f"account-{uuid4().hex[:8]}"

    touchpoint_id = str(uuid4())
    conversion_id = str(uuid4())

    # Touchpoint identity resolution (profile_id/anonymous_id) is untouched by
    # this bug — seed it reachable the ordinary way (profile_id = account_id)
    # so it is discovered and tombstoned exactly as in the other tests here.
    await TouchpointRepository().upsert({
        "touchpoint_id": touchpoint_id,
        "tenant_id": tenant_id,
        "profile_id": account_id,
        "channel": "paid_social",
        "source": "meta",
        "touchpoint_type": "click",
        "occurred_at": _now_iso(),
        "idempotency_key": f"reattr-tp-acct-{touchpoint_id}",
    })
    # The conversion is reachable ONLY through account_id — no profile_id or
    # cluster_id set. This is precisely the identity shape
    # tombstone_for_profile's WHERE clause matches but list_by_profile's
    # default identity match (profile_id OR cluster_id) does not.
    await ConversionRepository().upsert({
        "conversion_id": conversion_id,
        "tenant_id": tenant_id,
        "conversion_type": "purchase",
        "account_id": account_id,
        "gross_value": "250.00",
        "net_value": "250.00",
        "occurred_at": _now_iso(),
        "conversion_status": "confirmed",
        "attribution_eligible": True,
        "deduplication_key": f"reattr-order-acct-{conversion_id}",
    })

    prior_run_id = await _seed_active_run(tenant_id, conversion_id, touchpoint_id)

    result = await MeasurementPrivacyHandler().handle_erasure(tenant_id, account_id)

    assert result["errors"] == []
    assert result["partial_failure"] is False
    assert result["conversions_tombstoned"] == 1
    assert result["conversions_reattributed"] == 1, (
        "a conversion identified only by account_id must still be "
        f"re-attributed by this erasure; result={result}"
    )

    run_repo = AttributionRunRepository()
    prior_after = await run_repo.get_run(prior_run_id, tenant_id=tenant_id)
    assert prior_after is not None
    assert prior_after["is_active"] is False

    active_after = await run_repo.get_active_run(tenant_id, conversion_id)
    assert active_after is not None
    assert active_after["attribution_run_id"] != prior_run_id
    assert active_after["credit_total"] == "0"
    assert active_after["prior_attribution_run_id"] == prior_run_id
    assert active_after["trigger_reason"] == "privacy_erasure"


async def test_erasure_surfaces_reattribution_scope_truncation(monkeypatch):
    """Regression test — verifier MED finding (silent truncation).

    When a profile has more touchpoints/conversions than
    ``_REATTRIBUTION_SCOPE_LIMIT``, handle_erasure must never silently drop
    the overage: it must report ``reattribution_truncated=True`` with scanned
    counts, log a warning, and participate in the existing
    ``errors``/``partial_failure`` reporting pattern — while the privacy
    tombstone itself (which has no such limit) still affects every row.
    """
    tenant_id = f"tenant-reattr-{uuid4().hex[:8]}"
    profile_id = f"profile-{uuid4().hex[:8]}"

    monkeypatch.setattr(privacy_mod, "_REATTRIBUTION_SCOPE_LIMIT", 1)

    # Two touchpoint+conversion pairs — one more than the patched limit of 1.
    await _seed_touchpoint_and_conversion(tenant_id, profile_id)
    await _seed_touchpoint_and_conversion(tenant_id, profile_id)

    result = await MeasurementPrivacyHandler().handle_erasure(tenant_id, profile_id)

    assert result["reattribution_truncated"] is True
    assert result["reattribution_scope_limit"] == 1
    assert result["reattribution_touchpoints_scanned"] == 1
    assert result["reattribution_conversions_scanned"] == 1
    assert result["partial_failure"] is True
    assert any(
        "reattribution_scope_truncated" in e for e in result["errors"]
    ), result["errors"]

    # Truncation only bounds re-attribution SCOPE DISCOVERY — the tombstone
    # steps themselves carry no such limit and must still affect every row
    # regardless of how many exceed the re-attribution scope bound.
    assert result["touchpoints_tombstoned"] == 2
    assert result["conversions_tombstoned"] == 2
