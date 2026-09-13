"""Observed-state adapters (Phase 0) — read-only + best-effort.

Each adapter turns an *existing authority's* record into an
``ObservedStateSnapshot``. Phase-0 invariants:

* No adapter ever fabricates ``available`` from nothing; a missing record yields
  availability ``missing`` and an unreachable/unknown authority yields
  ``unknown``.
* ``missing`` is never reported as ``empty`` (CP-12).
* Adapters never mutate the authority they observe.

The adapters are pure functions over already-fetched records so unit tests can
drive them with fixtures and no live store. (Thin live fetch helpers that read
the real authorities under ``AETHER_ENV!=local`` are added in the phase that
plumbs a scheduler; Phase 0 reconciles what a caller hands it.)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Optional

from services.managed_integrations.availability import availability_from_readiness
from services.managed_integrations.contracts import ObservedStateSnapshot
from shared.temporal.instant import coerce_utc_lenient


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[object]) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        # The temporal kernel owns "assume UTC on a naive instant"; sensor
        # snapshots must never fabricate a zone on their own.
        return coerce_utc_lenient(value) or None  # type: ignore[return-value]
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return coerce_utc_lenient(parsed) or parsed


def _pick(*values: Optional[object]) -> Optional[object]:
    for value in values:
        if value not in (None, "", False):
            return value
    return None


def observed_from_sdk_health(
    *,
    managed_integration_ref: str,
    tenant_id: str,
    environment_id: str,
    installation: Optional[Mapping[str, object]] = None,
    health_score: Optional[Mapping[str, object]] = None,
    heartbeat: Optional[Mapping[str, object]] = None,
    observed_at: Optional[datetime] = None,
) -> ObservedStateSnapshot:
    """Assemble an observed snapshot from the SDK health authority.

    ``installation`` is the durable ``sdk_installations`` row
    (``SDKInstallationRepository``); ``health_score`` is the latest
    ``SDKHealthScore``; ``heartbeat`` is an optional recent heartbeat carrying
    the event ``schema_hash`` and auth/consent/queue facts (not durable beyond
    the Redis cache). Missing record -> ``missing``; nothing is ever inferred
    from the absence of bytes.
    """
    observed_at = observed_at or _utc_now()
    if installation is None and heartbeat is None and health_score is None:
        return ObservedStateSnapshot(
            observed_state_id=f"rcobs_{managed_integration_ref[:12]}",
            managed_integration_ref=managed_integration_ref,
            tenant_id=tenant_id,
            environment_id=environment_id,
            observed_at=observed_at,
            received_at=_utc_now(),
            provenance="unknown",
            availability="missing",
        )

    if installation is not None and installation.get("uninstalled"):
        availability = "missing"
    elif installation is not None and installation.get("disabled"):
        availability = "not_applicable"
    else:
        availability = "available"

    score = health_score or {}
    raw_status = _pick(
        score.get("status"),
        installation.get("status") if installation is not None else None,
    )
    health_status = str(raw_status) if raw_status else None
    if health_status == "silent":
        availability = "degraded"

    hb = heartbeat or {}
    runtime_version = _pick(hb.get("sdk_version"), installation.get("sdk_version"))
    platform = _pick(hb.get("platform"), installation.get("platform"))
    installation_id = _pick(
        hb.get("sdk_id"), installation.get("installation_id"), managed_integration_ref
    )
    auth_state = None
    consent_state = None
    queue_state = None
    ingestion_state = None
    if hb:
        auth_valid = hb.get("auth_valid")
        consent_valid = hb.get("consent_valid")
        auth_state = "valid" if auth_valid is True else ("invalid" if auth_valid is False else None)
        consent_state = (
            "valid" if consent_valid is True else ("invalid" if consent_valid is False else None)
        )
        if hb.get("queue_depth") is not None:
            queue_state = {"queue_depth": int(hb["queue_depth"] or 0)}
        if hb.get("ingestion_success_rate") is not None:
            ingestion_state = "healthy" if float(hb["ingestion_success_rate"] or 0) >= 0.95 else "degraded"

    provenance = "runtime_reported" if hb else "backend_verified"
    return ObservedStateSnapshot(
        observed_state_id=f"rcobs_{managed_integration_ref[:12]}",
        managed_integration_ref=managed_integration_ref,
        tenant_id=tenant_id,
        environment_id=environment_id,
        observed_at=observed_at,
        received_at=_utc_now(),
        provenance=provenance,
        availability=availability,  # type: ignore[arg-type]
        runtime_version=str(runtime_version) if runtime_version else None,
        platform=str(platform) if platform else None,
        schema_fingerprint=str(hb.get("schema_hash")) if hb.get("schema_hash") else None,
        queue_state=queue_state,
        ingestion_state=ingestion_state,
        auth_state=auth_state,
        consent_state=consent_state,
        health_ref=(
            f"sdk_health:{installation_id}" if health_status is not None else None
        ),
        health_status=health_status,
        reported_source_identity=str(installation_id) if installation_id else None,
        last_successful_observation_at=(
            _iso(_pick(score.get("last_heartbeat_at"), hb.get("reported_at")))
        ),
    )


def observed_from_provider_connection(
    *,
    managed_integration_ref: str,
    tenant_id: str,
    environment_id: str,
    connection_state: Optional[str] = None,
    provider_identity: Optional[str] = None,
    credential_ref: Optional[str] = None,
    last_successful_sync_at: Optional[datetime] = None,
    last_verified_at: Optional[datetime] = None,
    observed_at: Optional[datetime] = None,
) -> ObservedStateSnapshot:
    """Assemble an observed snapshot from the provider-runtime authority.

    ``connection_state`` is the ``ConnectionState`` value string. A connection
    record exists (state observed) -> ``available`` evidence; a state that the
    provider reports as degraded (``degraded``/``rate_limited``/``token_expiring``)
    lowers the snapshot to ``degraded``. Credential material is never read —
    only whether a ``credential_ref`` exists (its absence surfaces as the
    ``provider_state`` sentinel the reconciler treats as fail-closed).
    """
    observed_at = observed_at or _utc_now()
    if connection_state is None and provider_identity is None and credential_ref is None:
        return ObservedStateSnapshot(
            observed_state_id=f"rcobs_{managed_integration_ref[:12]}",
            managed_integration_ref=managed_integration_ref,
            tenant_id=tenant_id,
            environment_id=environment_id,
            observed_at=observed_at,
            received_at=_utc_now(),
            provenance="unknown",
            availability="missing",
        )

    state = str(connection_state) if connection_state else ""
    if state in ("degraded", "rate_limited", "token_expiring"):
        availability = "degraded"
    else:
        availability = "available"

    provider_state = state or "unknown"
    # Fail-closed sentinel: a connection that needs a credential has none.
    if state == "credential_waiting" and not credential_ref:
        provider_state = "credential_missing"
    return ObservedStateSnapshot(
        observed_state_id=f"rcobs_{managed_integration_ref[:12]}",
        managed_integration_ref=managed_integration_ref,
        tenant_id=tenant_id,
        environment_id=environment_id,
        observed_at=observed_at,
        received_at=_utc_now(),
        provenance="backend_verified",
        availability=availability,  # type: ignore[arg-type]
        provider_state=provider_state,
        health_ref=f"provider_runtime:{managed_integration_ref}" if state else None,
        last_successful_observation_at=last_successful_sync_at or last_verified_at,
    )


def observed_capability_availability(
    activation_rows: list[Mapping[str, object]],
) -> dict[str, str]:
    """Map capability activation rows -> per-capability CP-12 availability.

    Each row is a ``capability_activation_states`` record carrying at least
    ``capability`` and ``readiness_state``. The newest non-superseded row per
    capability wins (Phase 0 callers hand in the already-current rows).
    """
    resolved: dict[str, str] = {}
    for row in activation_rows:
        capability = row.get("capability")
        if not capability:
            continue
        resolved[str(capability)] = availability_from_readiness(
            str(row["readiness_state"]) if row.get("readiness_state") else None
        )
    return resolved
