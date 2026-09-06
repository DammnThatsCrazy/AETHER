"""Phase-0 reconciliation skeleton (blueprint §32, steps 1-11 only).

``reconcile`` loads an explicit desired state, an observed snapshot, resolves
capability availability, validates freshness, diffs each Phase-0 dimension, and
classifies the result:

* ``match``            — desired == observed on every reconciled dimension.
* ``acceptable_drift`` — only tracked-but-tolerated drift (e.g. a deprecated-but-
  served runtime under ``managed_stable``).
* ``actionable_drift`` — drift a later phase would turn into a ChangeSet
  (version, capability, schema, health, fleet-identity, or below-served release
  support). Phase 0 only *summarises* this drift — it never applies anything.
* ``blocked``          — an upstream authority is fail-closed (e.g. a required
  provider credential is absent): reconciliation cannot proceed safely.
* ``unknown``          — evidence is stale or entirely absent (never classified
  as actionable from missing evidence).

Steps 12+ of §32 (ChangeSet generation, blast radius, risk, automation
authority, simulate/shadow, approval, execution, verify/rollback, LKG, evidence,
action-required) are OUT of Phase 0 scope. This module never writes — the
caller persists the returned :class:`ReconcileRunView`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from services.managed_integrations.contracts import (
    DesiredStateSpec,
    DriftRecord,
    ObservedStateSnapshot,
    ReconcileRunView,
)
from services.managed_integrations.desired_policy import (
    classify_observed_runtime,
    floor_band_for_channel,
    is_below_channel_floor,
)
from shared.temporal.instant import coerce_utc_lenient

# Drift types the Phase-0 reconciler can emit (subset of blueprint §33).
_ACTIONABLE_DRIFT_TYPES = frozenset(
    {
        "version_drift",
        "capability_drift",
        "schema_drift",
        "health_drift",
        "fleet_identity_drift",
    }
)
# Provider connection state strings that mean an upstream credential authority
# is fail-closed — reconciliation must stop, not guess.
_FAIL_CLOSED_PROVIDER_STATES = frozenset({"credential_missing", "credential_waiting"})

DEFAULT_FRESHNESS_WINDOW_SECONDS = 300  # mirrors the SDK-health silent threshold


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _drift_id() -> str:
    return f"rcdr_{uuid.uuid4().hex[:16]}"


def _reconcile_id() -> str:
    return f"rcr_{uuid.uuid4().hex[:16]}"


def _freshness(
    observed: ObservedStateSnapshot,
    now: datetime,
    window_seconds: int,
) -> tuple[bool, Optional[str]]:
    observed_at = observed.observed_at
    if observed_at is None:
        return False, "observed state carries no observed_at — freshness cannot be established"
    # The temporal kernel owns the "assume UTC on a naive instant" policy; the
    # reconciler only ever compares against an aware clock.
    observed_at = coerce_utc_lenient(observed_at) or observed_at
    if observed_at > now + timedelta(seconds=60):
        return False, "observed_at is in the future — evidence is not trustworthy"
    age = (now - observed_at).total_seconds()
    if age > window_seconds:
        return False, (
            f"observed state is stale ({int(age)}s old; freshness window "
            f"{window_seconds}s) — not reconciled on stale evidence"
        )
    return True, None


def _version_and_release_drift(
    desired: DesiredStateSpec,
    observed: ObservedStateSnapshot,
    ref: str,
    now: datetime,
) -> list[DriftRecord]:
    """Version + release-support drift for the SDK version dimensions.

    Only when the desired channel pins a floor AND the runtime reports a
    classifiable version. A runtime below the channel floor is actionable
    version drift; a deprecated-but-at-floor runtime is acceptable
    (release-support) drift; `pinned` channels reconcile no version dimension.
    """
    if not desired.minimum_runtime_version or not observed.runtime_version:
        return []
    band_id = classify_observed_runtime(observed.runtime_version)
    if band_id is None:
        return []
    drift: list[DriftRecord] = []
    if is_below_channel_floor(desired.release_channel, band_id):
        drift.append(
            DriftRecord(
                drift_id=_drift_id(),
                managed_integration_ref=ref,
                desired_state_ref=desired.desired_state_id,
                observed_state_ref=observed.observed_state_id,
                drift_type="version_drift",
                detail=(
                    f"runtime {observed.runtime_version} is below the "
                    f"{desired.release_channel} floor "
                    f"{desired.minimum_runtime_version} (band {band_id})"
                ),
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    elif floor_band_for_channel(desired.release_channel) == band_id:
        drift.append(
            DriftRecord(
                drift_id=_drift_id(),
                managed_integration_ref=ref,
                desired_state_ref=desired.desired_state_id,
                observed_state_ref=observed.observed_state_id,
                drift_type="release_support_drift",
                detail=(
                    f"runtime {observed.runtime_version} is deprecated-but-served "
                    f"under {desired.release_channel} — tracked, not actionable"
                ),
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    return drift


def _capability_drift(
    desired: DesiredStateSpec,
    observed: ObservedStateSnapshot,
    observed_capabilities: dict[str, str],
    ref: str,
    now: datetime,
) -> list[DriftRecord]:
    drift: list[DriftRecord] = []
    for requirement in desired.minimum_capabilities:
        capability = requirement.capability
        required = requirement.required_availability or "available"
        actual = observed_capabilities.get(capability, "missing")
        if required == "available" and actual == "available":
            continue
        if actual == required:
            continue
        drift.append(
            DriftRecord(
                drift_id=_drift_id(),
                managed_integration_ref=ref,
                desired_state_ref=desired.desired_state_id,
                observed_state_ref=observed.observed_state_id,
                drift_type="capability_drift",
                detail=(
                    f"capability {capability!r} observed {actual}, "
                    f"required {required}"
                ),
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    return drift


def _remaining_drift(
    desired: DesiredStateSpec,
    observed: ObservedStateSnapshot,
    expected_identity: str,
    ref: str,
    now: datetime,
) -> list[DriftRecord]:
    """Schema, health and fleet-identity drift (never fabricated from silence)."""
    drift: list[DriftRecord] = []
    if (
        desired.schema_fingerprint
        and observed.schema_fingerprint
        and observed.schema_fingerprint != desired.schema_fingerprint
    ):
        drift.append(
            DriftRecord(
                drift_id=_drift_id(),
                managed_integration_ref=ref,
                desired_state_ref=desired.desired_state_id,
                observed_state_ref=observed.observed_state_id,
                drift_type="schema_drift",
                detail=(
                    f"schema fingerprint {observed.schema_fingerprint} differs from "
                    f"desired {desired.schema_fingerprint}"
                ),
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    if observed.health_status in ("degraded", "unhealthy", "silent"):
        drift.append(
            DriftRecord(
                drift_id=_drift_id(),
                managed_integration_ref=ref,
                desired_state_ref=desired.desired_state_id,
                observed_state_ref=observed.observed_state_id,
                drift_type="health_drift",
                detail=f"observed health is {observed.health_status}",
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    if (
        observed.reported_source_identity
        and expected_identity
        and observed.reported_source_identity != expected_identity
    ):
        drift.append(
            DriftRecord(
                drift_id=_drift_id(),
                managed_integration_ref=ref,
                desired_state_ref=desired.desired_state_id,
                observed_state_ref=observed.observed_state_id,
                drift_type="fleet_identity_drift",
                detail=(
                    f"reported source identity {observed.reported_source_identity!r} "
                    f"does not match registered identity {expected_identity!r}"
                ),
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    return drift


def reconcile(
    *,
    managed_integration_id: str,
    tenant_id: str,
    environment_id: str,
    integration_kind: str,
    expected_identity: str,
    desired: DesiredStateSpec,
    observed: ObservedStateSnapshot,
    observed_capabilities: Optional[dict[str, str]] = None,
    freshness_window_seconds: int = DEFAULT_FRESHNESS_WINDOW_SECONDS,
    now: Optional[datetime] = None,
) -> ReconcileRunView:
    """Classify desired-vs-observed drift for one managed integration.

    Pure and side-effect free: no authority is read or written here. The caller
    supplies the desired spec, an observed snapshot (from ``sensors``) and the
    observed per-capability availability map; the returned
    :class:`ReconcileRunView` is what a caller persists to ``reconcile_runs``.
    """
    now = now or _utc_now()
    observed_capabilities = observed_capabilities or {}
    ref = managed_integration_id

    freshness_ok, freshness_note = _freshness(observed, now, freshness_window_seconds)
    result: str
    note: Optional[str] = None
    drift: list[DriftRecord] = []

    if not freshness_ok:
        result = "unknown"
        note = freshness_note or "observed state is stale"
    elif observed.availability == "missing":
        result = "unknown"
        note = (
            "no observation recorded for this integration (availability missing) — "
            "nothing to reconcile"
        )
    elif (
        integration_kind in ("provider_runtime_connection",)
        or integration_kind.startswith("connector_")
    ) and observed.provider_state in _FAIL_CLOSED_PROVIDER_STATES:
        result = "blocked"
        note = (
            f"provider credential is absent/fail-closed "
            f"(provider_state={observed.provider_state}) — supply credentials "
            f"before this integration can be reconciled"
        )
    else:
        drift = _version_and_release_drift(desired, observed, ref, now)
        drift += _capability_drift(
            desired, observed, observed_capabilities, ref, now
        )
        drift += _remaining_drift(desired, observed, expected_identity, ref, now)
        actionable = [d for d in drift if d.drift_type in _ACTIONABLE_DRIFT_TYPES]
        acceptable_only = drift and not actionable
        if actionable:
            result = "actionable_drift"
        elif acceptable_only:
            result = "acceptable_drift"
        else:
            result = "match"

    return ReconcileRunView(
        reconcile_id=_reconcile_id(),
        managed_integration_ref=ref,
        desired_state_ref=desired.desired_state_id,
        observed_state_ref=observed.observed_state_id,
        desired_revision=desired.revision,
        observed_revision=(
            observed.observed_state_id if observed.observed_state_id else "no_observation"
        ),
        freshness_ok=freshness_ok,
        result=result,  # type: ignore[arg-type]
        note=note,
        drift=drift,
        created_at=now,
    )
