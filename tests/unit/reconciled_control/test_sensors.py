"""Observed-state adapters (sensors) — evidence-backed, never fabricated.

Each adapter is pure over already-fetched authority records. A missing record
yields availability ``missing`` (never ``empty``, never ``available``); an
unreachable/absent authority yields provenance ``unknown``. ``missing`` is never
reported as ``empty`` (CP-12), and nothing is inferred from absent bytes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.managed_integrations.contracts import (
    INTEGRATION_AVAILABILITY_VALUES,
)
from services.managed_integrations.sensors import (
    observed_capability_availability,
    observed_from_provider_connection,
    observed_from_sdk_health,
    observed_from_site_install,
)

MI = "sdk-abc123"
TENANT = "tenant-a"
ENV = "env-1"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


# ── observed_from_sdk_health ────────────────────────────────────────────────


def test_sdk_health_no_records_is_missing_with_unknown_provenance() -> None:
    snap = observed_from_sdk_health(
        managed_integration_ref=MI,
        tenant_id=TENANT,
        environment_id=ENV,
        observed_at=NOW,
    )
    assert snap.availability == "missing"
    assert snap.provenance == "unknown"
    assert snap.health_status is None
    assert snap.runtime_version is None


def test_sdk_health_installation_only_is_available_backend_verified() -> None:
    snap = observed_from_sdk_health(
        managed_integration_ref=MI,
        tenant_id=TENANT,
        environment_id=ENV,
        installation={"installation_id": MI, "sdk_version": "8.1.0", "platform": "ios"},
        observed_at=NOW,
    )
    assert snap.availability == "available"
    assert snap.provenance == "backend_verified"
    assert snap.runtime_version == "8.1.0"
    assert snap.platform == "ios"
    assert snap.reported_source_identity == MI


def test_sdk_health_uninstalled_is_missing_not_empty() -> None:
    snap = observed_from_sdk_health(
        managed_integration_ref=MI,
        tenant_id=TENANT,
        environment_id=ENV,
        installation={"installation_id": MI, "uninstalled": True},
        observed_at=NOW,
    )
    assert snap.availability == "missing"


def test_sdk_health_disabled_is_not_applicable() -> None:
    snap = observed_from_sdk_health(
        managed_integration_ref=MI,
        tenant_id=TENANT,
        environment_id=ENV,
        installation={"installation_id": MI, "disabled": True},
        observed_at=NOW,
    )
    assert snap.availability == "not_applicable"


def test_sdk_health_heartbeat_enriches_runtime_reported_evidence() -> None:
    snap = observed_from_sdk_health(
        managed_integration_ref=MI,
        tenant_id=TENANT,
        environment_id=ENV,
        installation={"installation_id": MI, "sdk_version": "8.1.0"},
        heartbeat={
            "sdk_version": "8.2.1",
            "schema_hash": "schema-v9",
            "auth_valid": True,
            "consent_valid": True,
            "queue_depth": 3,
            "ingestion_success_rate": 0.99,
            "platform": "web",
        },
        observed_at=NOW,
    )
    assert snap.provenance == "runtime_reported"
    assert snap.runtime_version == "8.2.1"  # heartbeat is newer evidence
    assert snap.schema_fingerprint == "schema-v9"
    assert snap.platform == "web"
    assert snap.auth_state == "valid"
    assert snap.consent_state == "valid"
    assert snap.queue_state == {"queue_depth": 3}
    assert snap.ingestion_state == "healthy"


def test_sdk_health_invalid_auth_and_slow_ingestion_degrade_snapshot() -> None:
    snap = observed_from_sdk_health(
        managed_integration_ref=MI,
        tenant_id=TENANT,
        environment_id=ENV,
        installation={"installation_id": MI},
        heartbeat={
            "auth_valid": False,
            "consent_valid": False,
            "ingestion_success_rate": 0.80,
        },
        observed_at=NOW,
    )
    assert snap.auth_state == "invalid"
    assert snap.consent_state == "invalid"
    assert snap.ingestion_state == "degraded"


def test_sdk_health_silent_health_status_is_degraded() -> None:
    snap = observed_from_sdk_health(
        managed_integration_ref=MI,
        tenant_id=TENANT,
        environment_id=ENV,
        installation={"installation_id": MI},
        health_score={"status": "silent"},
        observed_at=NOW,
    )
    assert snap.health_status == "silent"
    assert snap.availability == "degraded"
    assert snap.health_ref == f"sdk_health:{MI}"


def test_sdk_health_never_reports_empty() -> None:
    for kwargs in (
        {"installation": None, "health_score": None, "heartbeat": None},
        {"installation": {"uninstalled": True}},
    ):
        snap = observed_from_sdk_health(
            managed_integration_ref=MI,
            tenant_id=TENANT,
            environment_id=ENV,
            observed_at=NOW,
            **kwargs,
        )
        assert snap.availability != "empty"
        assert snap.availability in INTEGRATION_AVAILABILITY_VALUES


# ── observed_from_provider_connection ───────────────────────────────────────


def test_provider_connection_no_records_is_missing() -> None:
    snap = observed_from_provider_connection(
        managed_integration_ref="mi-provider-1",
        tenant_id=TENANT,
        environment_id=ENV,
        observed_at=NOW,
    )
    assert snap.availability == "missing"
    assert snap.provenance == "unknown"


def test_provider_connection_connected_is_available() -> None:
    snap = observed_from_provider_connection(
        managed_integration_ref="mi-provider-1",
        tenant_id=TENANT,
        environment_id=ENV,
        connection_state="connected",
        provider_identity="stripe",
        credential_ref="cred-1",
        observed_at=NOW,
    )
    assert snap.availability == "available"
    assert snap.provider_state == "connected"
    assert snap.health_ref == "provider_runtime:mi-provider-1"


def test_provider_connection_credential_waiting_without_ref_is_fail_closed() -> None:
    # A connection that needs a credential but has none surfaces the
    # credential_missing sentinel the reconciler treats as `blocked`.
    snap = observed_from_provider_connection(
        managed_integration_ref="mi-provider-1",
        tenant_id=TENANT,
        environment_id=ENV,
        connection_state="credential_waiting",
        provider_identity="stripe",
        credential_ref=None,
        observed_at=NOW,
    )
    assert snap.provider_state == "credential_missing"


def test_provider_connection_degraded_state_is_degraded() -> None:
    for state in ("degraded", "rate_limited", "token_expiring"):
        snap = observed_from_provider_connection(
            managed_integration_ref="mi-provider-1",
            tenant_id=TENANT,
            environment_id=ENV,
            connection_state=state,
            provider_identity="stripe",
            credential_ref="cred-1",
            observed_at=NOW,
        )
        assert snap.availability == "degraded", state


def test_provider_connection_never_reads_credential_material() -> None:
    # Only the *presence* of a credential_ref is observed — never the material.
    snap = observed_from_provider_connection(
        managed_integration_ref="mi-provider-1",
        tenant_id=TENANT,
        environment_id=ENV,
        connection_state="connected",
        credential_ref="cred-1",
        observed_at=NOW,
    )
    assert snap.provider_state == "connected"
    assert snap.last_successful_observation_at is None


# ── observed_capability_availability ────────────────────────────────────────


def test_capability_availability_maps_readiness_to_cp12() -> None:
    rows = [
        {"capability": "batch_ingestion", "readiness_state": "connection_validated"},
        {"capability": "server_side", "readiness_state": "credential_supplied"},
        {"capability": "replay", "readiness_state": "credential_waiting"},
        {"capability": "normalization", "readiness_state": None},
    ]
    resolved = observed_capability_availability(rows)
    assert resolved == {
        "batch_ingestion": "available",
        "server_side": "degraded",
        "replay": "missing",
        "normalization": "missing",
    }


def test_capability_availability_empty_rows_is_empty_map() -> None:
    assert observed_capability_availability([]) == {}


def test_capability_availability_skips_rows_without_capability() -> None:
    resolved = observed_capability_availability(
        [
            {"capability": "batch_ingestion", "readiness_state": "partner_live"},
            {"readiness_state": "partner_live"},  # no capability key -> skipped
        ]
    )
    assert resolved == {"batch_ingestion": "available"}


def _recent() -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=5)


def test_sensor_snapshots_carry_aware_utc_timestamps() -> None:
    snap = observed_from_sdk_health(
        managed_integration_ref=MI,
        tenant_id=TENANT,
        environment_id=ENV,
        installation={"installation_id": MI},
        observed_at=_recent(),
    )
    for field in ("observed_at", "received_at"):
        value = getattr(snap, field)
        assert value.tzinfo is not None, field


# ── observed_from_site_install ──────────────────────────────────────────────
#
# A site install is the SDK distribution layer's evidence that a one-tag
# install came up. It has no health agent and no heartbeat, so the install
# record is the whole observation — and the CP-12 distinctions below are the
# ones the plane's verdict turns on.

SITE = "site_abc123"


def _site_install(**overrides) -> dict:
    return {
        "state": "live",
        "status": "live",
        "signals": {"sdk_loaded": {"count": 1}, "sdk_initialized": {"count": 1}},
        "signals_observed": ["sdk_loaded", "sdk_initialized"],
        "signals_missing": ["sdk_init_failed"],
        "last_signal": "sdk_initialized",
        "last_signal_at": "2026-09-06T11:00:00+00:00",
        "first_signal_at": "2026-09-06T11:00:00+00:00",
        "age_seconds": 3600.0,
        "install_mode": "snippet",
        "loader_version": "0.1.0-alpha.0",
        "sdk_version": "0.1.0-alpha.0",
        "compatibility_tier": "supported",
        "desired_version": "0.1.0-alpha.0",
        "drift_status": "current",
        "reason": None,
        "warnings": [],
        **overrides,
    }


def _site_snap(install, *, site_id: str = SITE, observed_at: datetime = NOW):
    return observed_from_site_install(
        managed_integration_ref=SITE,
        tenant_id=TENANT,
        environment_id=ENV,
        site_install=install,
        site_id=site_id,
        observed_at=observed_at,
    )


def test_site_install_with_no_record_is_missing_and_never_available() -> None:
    snap = _site_snap(None)
    assert snap.availability == "missing"
    assert snap.provenance == "unknown"
    assert snap.health_status is None
    assert snap.runtime_version is None


def test_awaiting_first_signal_reads_as_the_absence_it_is() -> None:
    """The described view of a site with no record is not a state it is *in*."""
    described = _site_install(
        state="awaiting_first_signal",
        status=None,
        signals={},
        signals_observed=[],
        signals_missing=["sdk_loaded", "sdk_initialized", "sdk_init_failed"],
        last_signal=None,
        last_signal_at=None,
        first_signal_at=None,
        age_seconds=None,
        install_mode=None,
        loader_version=None,
        sdk_version=None,
        compatibility_tier=None,
        desired_version=None,
        drift_status=None,
    )
    snap = _site_snap(described)
    assert snap.availability == "missing"
    assert snap.provenance == "unknown"
    # The identity still travels: which site is silent is the operator's question.
    assert snap.reported_source_identity == SITE


def test_failed_install_is_degraded_evidence_and_not_missing() -> None:
    """A failed install is the record that exists and says broken.

    Reported as ``missing`` it would hand the reconciler "nothing to reconcile"
    for the one install that most needs a ChangeSet — the exact ambiguity the
    install verifier exists to remove.
    """
    snap = _site_snap(
        _site_install(
            state="failed",
            status="failed",
            last_signal="sdk_init_failed",
            reason="csp_blocked",
            warnings=["blocked by Content-Security-Policy"],
        )
    )
    assert snap.availability == "degraded"
    assert snap.availability != "missing"
    assert snap.health_status == "failed"
    assert snap.provenance == "runtime_reported"


def test_a_live_install_is_available_and_carries_the_loader_version() -> None:
    snap = _site_snap(_site_install())
    assert snap.availability == "available"
    assert snap.provenance == "runtime_reported"
    assert snap.health_status == "live"
    # The loader version, not sdk_version: it is the field the distribution
    # layer derives drift_status from, so the plane's version diff reads the
    # same field and the two cannot disagree about a site's drift.
    assert snap.runtime_version == "0.1.0-alpha.0"
    assert snap.reported_source_identity == SITE
    assert snap.health_ref == f"sdk_site_install:{SITE}"


def test_an_unknown_install_state_resolves_to_unknown_not_to_healthy() -> None:
    """CP-12: ambiguity resolves to ``unknown``, never to the nearest label."""
    snap = _site_snap(_site_install(state="something_new", status="something_new"))
    assert snap.availability == "unknown"
    assert snap.provenance == "unknown"
    assert snap.health_status is None


def test_install_age_is_reported_not_thresholded_into_a_state() -> None:
    """A site installed last year is still correctly installed.

    ``observed_at`` is when the snapshot was assembled; the handshake's own age
    is carried separately, so a working install is never reported as stale.
    """
    snap = _site_snap(_site_install(), observed_at=NOW)
    assert snap.observed_at == NOW
    assert snap.last_successful_observation_at == datetime(
        2026, 9, 6, 11, 0, 0, tzinfo=timezone.utc
    )


def test_site_install_health_status_is_one_the_reconciler_treats_as_drift() -> None:
    """The seam that matters: a broken install must not reconcile as ``match``."""
    from services.managed_integrations.reconciler import _UNHEALTHY_STATUSES

    failed = _site_snap(_site_install(state="failed", status="failed"))
    assert failed.health_status in _UNHEALTHY_STATUSES
    # And the healthy states must not be, or every working site would drift.
    for healthy in ("loaded", "live"):
        assert healthy not in _UNHEALTHY_STATUSES
