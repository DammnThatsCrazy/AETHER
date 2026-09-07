"""Reconcile classification (§32 steps 1–11) — pure function tests.

The reconciler never writes and never classifies ``actionable`` from missing
evidence: absent or stale observations yield ``unknown``; a fail-closed
provider credential yields ``blocked``; only real, fresh evidence can produce
``match`` / ``acceptable_drift`` / ``actionable_drift``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.managed_integrations.desired_policy import build_desired_state
from services.managed_integrations.reconciler import (
    DEFAULT_FRESHNESS_WINDOW_SECONDS,
    reconcile,
)
from services.managed_integrations.contracts import (
    DesiredStateSpec,
    ObservedStateSnapshot,
)

NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
TENANT = "tenant-a"
ENV = "env-1"


def _now(**kw) -> datetime:
    return NOW + timedelta(**kw)


def _desired(
    *,
    mi: str = "mi-sdk-1",
    release_channel: str = "managed_stable",
    schema_fingerprint: str | None = None,
    minimum_capabilities: list[tuple[str, str]] | None = None,
) -> DesiredStateSpec:
    return build_desired_state(
        managed_integration_id=mi,
        tenant_id=TENANT,
        environment_id=ENV,
        release_channel=release_channel,
        schema_fingerprint=schema_fingerprint,
        minimum_capabilities=minimum_capabilities,
    )


def _observed(
    *,
    mi: str = "mi-sdk-1",
    availability: str = "available",
    runtime_version: str | None = None,
    schema_fingerprint: str | None = None,
    health_status: str | None = None,
    provider_state: str | None = None,
    reported_source_identity: str | None = None,
    observed_at: datetime | None = None,
) -> ObservedStateSnapshot:
    return ObservedStateSnapshot(
        observed_state_id=f"rcobs_{mi[:12]}",
        managed_integration_ref=mi,
        tenant_id=TENANT,
        environment_id=ENV,
        observed_at=observed_at or _now(seconds=-5),
        received_at=NOW,
        availability=availability,  # type: ignore[arg-type]
        runtime_version=runtime_version,
        schema_fingerprint=schema_fingerprint,
        health_status=health_status,
        provider_state=provider_state,
        reported_source_identity=reported_source_identity,
    )


def _run(**kwargs):
    return reconcile(
        managed_integration_id=kwargs.pop("mi", "mi-sdk-1"),
        tenant_id=TENANT,
        environment_id=ENV,
        integration_kind=kwargs.pop("integration_kind", "sdk_web"),
        expected_identity=kwargs.pop("expected_identity", "mi-sdk-1"),
        desired=kwargs.pop("desired"),
        observed=kwargs.pop("observed"),
        observed_capabilities=kwargs.pop("observed_capabilities", None),
        freshness_window_seconds=kwargs.pop(
            "freshness_window_seconds", DEFAULT_FRESHNESS_WINDOW_SECONDS
        ),
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


# ── match ───────────────────────────────────────────────────────────────────


def test_identical_desired_and_observed_is_match() -> None:
    desired = _desired()
    observed = _observed(
        runtime_version="8.1.3",
        reported_source_identity="mi-sdk-1",
    )
    view = _run(desired=desired, observed=observed)
    assert view.result == "match"
    assert view.freshness_ok is True
    assert view.drift == []
    assert view.desired_state_ref == desired.desired_state_id
    assert view.observed_state_ref == observed.observed_state_id


def test_match_can_tolerate_a_capability_met_at_requirement() -> None:
    desired = _desired(minimum_capabilities=[("batch_ingestion", "available")])
    observed = _observed(runtime_version="8.1.3")
    view = _run(
        desired=desired,
        observed=observed,
        observed_capabilities={"batch_ingestion": "available"},
    )
    assert view.result == "match"


# ── acceptable_drift ────────────────────────────────────────────────────────


def test_deprecated_but_at_floor_runtime_is_acceptable_drift() -> None:
    # 7.9.0 is deprecated-but-served at the managed_stable floor: tracked, not
    # actionable -> acceptable_drift with a release_support_drift record only.
    desired = _desired()
    observed = _observed(runtime_version="7.9.0")
    view = _run(desired=desired, observed=observed)
    assert view.result == "acceptable_drift"
    assert [d.drift_type for d in view.drift] == ["release_support_drift"]


# ── actionable_drift ────────────────────────────────────────────────────────


def test_runtime_below_floor_is_actionable_version_drift() -> None:
    desired = _desired()  # managed_stable floor = 7.0.0 (deprecated band)
    observed = _observed(runtime_version="6.4.2")  # read_compatible band
    view = _run(desired=desired, observed=observed)
    assert view.result == "actionable_drift"
    assert [d.drift_type for d in view.drift] == ["version_drift"]
    assert "below the managed_stable floor" in view.drift[0].detail


def test_capability_mismatch_is_actionable_capability_drift() -> None:
    desired = _desired(minimum_capabilities=[("batch_ingestion", "available")])
    observed = _observed(runtime_version="8.1.3")
    view = _run(
        desired=desired,
        observed=observed,
        observed_capabilities={"batch_ingestion": "missing"},
    )
    assert view.result == "actionable_drift"
    assert [d.drift_type for d in view.drift] == ["capability_drift"]


def test_degraded_capability_is_actionable_when_available_required() -> None:
    desired = _desired(minimum_capabilities=[("replay", "available")])
    observed = _observed(runtime_version="8.1.3")
    view = _run(
        desired=desired,
        observed=observed,
        observed_capabilities={"replay": "degraded"},
    )
    assert view.result == "actionable_drift"
    assert view.drift[0].drift_type == "capability_drift"
    assert "observed degraded, required available" in view.drift[0].detail


def test_schema_fingerprint_mismatch_is_actionable_schema_drift() -> None:
    desired = _desired(schema_fingerprint="fp-desired")
    observed = _observed(runtime_version="8.1.3", schema_fingerprint="fp-observed")
    view = _run(desired=desired, observed=observed)
    assert view.result == "actionable_drift"
    assert [d.drift_type for d in view.drift] == ["schema_drift"]


def test_degraded_health_is_actionable_health_drift() -> None:
    observed = _observed(runtime_version="8.1.3", health_status="degraded")
    view = _run(desired=_desired(), observed=observed)
    assert view.result == "actionable_drift"
    assert [d.drift_type for d in view.drift] == ["health_drift"]


def test_unhealthy_health_is_actionable_health_drift() -> None:
    observed = _observed(runtime_version="8.1.3", health_status="unhealthy")
    view = _run(desired=_desired(), observed=observed)
    assert view.result == "actionable_drift"
    assert [d.drift_type for d in view.drift] == ["health_drift"]


def test_mismatched_source_identity_is_actionable_fleet_identity_drift() -> None:
    observed = _observed(
        runtime_version="8.1.3",
        reported_source_identity="mi-sdk-999",
    )
    view = _run(
        desired=_desired(),
        observed=observed,
        expected_identity="mi-sdk-1",
    )
    assert view.result == "actionable_drift"
    assert [d.drift_type for d in view.drift] == ["fleet_identity_drift"]


def test_combined_drift_records_all_actionable_types() -> None:
    desired = _desired(
        schema_fingerprint="fp-desired",
        minimum_capabilities=[("batch_ingestion", "available")],
    )
    observed = _observed(
        runtime_version="6.4.2",
        schema_fingerprint="fp-observed",
        health_status="degraded",
        reported_source_identity="mi-sdk-999",
    )
    view = _run(
        desired=desired,
        observed=observed,
        expected_identity="mi-sdk-1",
        observed_capabilities={"batch_ingestion": "missing"},
    )
    assert view.result == "actionable_drift"
    assert sorted(d.drift_type for d in view.drift) == [
        "capability_drift",
        "fleet_identity_drift",
        "health_drift",
        "schema_drift",
        "version_drift",
    ]


# ── blocked ─────────────────────────────────────────────────────────────────


def test_provider_connection_missing_credential_is_blocked() -> None:
    observed = _observed(provider_state="credential_missing")
    view = _run(
        mi="mi-provider-1",
        integration_kind="provider_runtime_connection",
        desired=_desired(mi="mi-provider-1"),
        observed=observed,
    )
    assert view.result == "blocked"
    assert view.drift == []
    assert "credential" in (view.note or "")


def test_connector_missing_credential_is_blocked() -> None:
    observed = _observed(provider_state="credential_missing")
    view = _run(
        mi="mi-connector-1",
        integration_kind="connector_aether_hosted",
        desired=_desired(mi="mi-connector-1"),
        observed=observed,
    )
    assert view.result == "blocked"


def test_credential_waiting_is_also_fail_closed_blocked() -> None:
    observed = _observed(provider_state="credential_waiting")
    view = _run(
        mi="mi-provider-1",
        integration_kind="provider_runtime_connection",
        desired=_desired(mi="mi-provider-1"),
        observed=observed,
    )
    assert view.result == "blocked"


def test_provider_state_sentinel_is_ignored_for_sdk_kind() -> None:
    # A provider_state is only meaningful for provider/connector integrations;
    # an SDK row with a stray provider_state does not get classified blocked.
    observed = _observed(runtime_version="8.1.3", provider_state="credential_missing")
    view = _run(desired=_desired(), observed=observed)
    assert view.result == "match"


# ── unknown (never classified from missing/stale evidence) ──────────────────


def test_missing_observation_is_unknown() -> None:
    observed = _observed(availability="missing")
    view = _run(desired=_desired(), observed=observed)
    assert view.result == "unknown"
    assert view.drift == []
    assert "missing" in (view.note or "")


def test_missing_observation_beats_fail_closed_provider_branch() -> None:
    # Branch order: absent evidence -> unknown even for a provider connection
    # that would otherwise be blocked. Nothing is classified from missing bytes.
    observed = _observed(availability="missing", provider_state="credential_missing")
    view = _run(
        mi="mi-provider-1",
        integration_kind="provider_runtime_connection",
        desired=_desired(mi="mi-provider-1"),
        observed=observed,
    )
    assert view.result == "unknown"


def test_stale_observation_is_unknown() -> None:
    observed = _observed(
        runtime_version="6.4.2",
        observed_at=_now(seconds=-(DEFAULT_FRESHNESS_WINDOW_SECONDS + 60)),
    )
    view = _run(desired=_desired(), observed=observed)
    assert view.result == "unknown"
    assert view.freshness_ok is False
    assert view.drift == []
    assert "stale" in (view.note or "")


def test_future_observation_is_unknown() -> None:
    observed = _observed(runtime_version="8.1.3", observed_at=_now(seconds=120))
    view = _run(desired=_desired(), observed=observed)
    assert view.result == "unknown"
    assert view.freshness_ok is False
    assert "future" in (view.note or "")


def test_fresh_boundary_observation_is_fresh() -> None:
    observed = _observed(
        runtime_version="8.1.3",
        observed_at=_now(seconds=-DEFAULT_FRESHNESS_WINDOW_SECONDS),
    )
    view = _run(desired=_desired(), observed=observed)
    assert view.freshness_ok is True
    assert view.result == "match"


# ── pinned channel reconciles no version dimension ──────────────────────────


def test_pinned_channel_reconciles_no_version_dimension() -> None:
    desired = _desired(release_channel="pinned")  # minimum_runtime_version None
    observed = _observed(runtime_version="6.4.2")
    view = _run(desired=desired, observed=observed)
    # No floor -> no version drift; nothing else differs -> match.
    assert view.result == "match"


# ── provenance / metadata ───────────────────────────────────────────────────


def test_run_view_carries_drift_evidence_and_no_mutation() -> None:
    observed = _observed(runtime_version="6.4.2")
    view = _run(desired=_desired(), observed=observed)
    assert view.reconcile_id.startswith("rcr_")
    assert all(d.drift_id.startswith("rcdr_") for d in view.drift)
    assert view.created_at == NOW
    assert view.desired_revision == "1"
    assert view.observed_revision == observed.observed_state_id
    for record in view.drift:
        assert record.drift_type in {
            "version_drift", "capability_drift", "schema_drift",
            "health_drift", "release_support_drift", "fleet_identity_drift",
        }
