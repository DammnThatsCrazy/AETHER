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
