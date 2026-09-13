"""Universal Ingestion Gateway — the one validated gateway (WS-B1).

Adapters build Envelope-B observations; the gateway is the single choke point
between "built by an adapter" and "durable + published". It owns the invariant
gates that are cheap and path-independent to enforce on the envelope itself:

- **schema validation** — Envelope-B required blocks/fields + curated
  vocabularies are re-validated here by rebuilding the pydantic runtime model,
  so the gateway never trusts an envelope that did not come from the model;
- **schema authority** — ``observation_type`` must be a canonical Contract-Spine
  event type (Invariant #2) and, when the adapter declared one, ``family`` must
  match the spine;
- **tenant provenance** (Invariant #6) — ``tenancy.tenant_id`` must equal the
  authenticated tenant;
- **source-trust classification** — the adapter's ``credential_class`` is the
  effective trust basis of an unsigned observation; the gateway stamps it as
  ``provenance.source_trust`` when the adapter did not assert one, and records
  the adapter identity/version;
- **typed rejection** — a failing envelope is returned as a typed
  ``rejected`` (never silently accepted, never confused with the A-side event,
  which its caller may still accept on the flat path — Invariant #10).

Consent/privacy policy, idempotency ordering, sequencing/gap detection, and
durable-Bronze-before-publish are the gateway's *sequence* gates; they need
per-path context and are adopted as each family converges
(WS-B2..WS-B5 — see the EXECUTION_STATE ledger). This module is the Envelope-B
validation + trust core every family routes through; the durable/idempotency/
publish spine it precedes unifies in WS-B5.

Adoption (flag-gated, default OFF): ``/v1/batch`` runs every accepted SDK
envelope through :func:`validate_and_stamp` when
``settings.ingress_gateway.enabled`` is ON (degrade-safe — a rejected envelope
is simply not persisted; the A-side event is already accepted).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Optional

from pydantic import ValidationError

from shared.logger.logger import get_logger
from shared.observation.envelope import (
    ProvenanceBlock,
    QualityBlock,
    UniversalObservationEnvelope,
)

from services.ingestion.adapters.base import UniversalIngressAdapter
from services.ingestion.generated_registry import CANONICAL_EVENT_TYPES, EVENT_FAMILY

logger = get_logger("aether.service.ingestion.gateway")

# Typed gateway dispositions. ``rejected`` means "this envelope must not be
# persisted/published" — the caller still owns the A-side decision (on the SDK
# path an accepted event degrades to the flat dict rather than being dropped).
GatewayStatus = Literal["accepted", "rejected"]


@dataclass(frozen=True)
class GatewayResult:
    """Outcome of :func:`validate_and_stamp` for one observation."""

    observation_id: str
    status: GatewayStatus
    reasons: tuple[str, ...] = ()
    envelope: Optional[dict[str, Any]] = field(default=None, repr=False)

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"


def _reject(observation_id: str, reason: str) -> GatewayResult:
    return GatewayResult(observation_id=observation_id, status="rejected", reasons=(reason,))


def validate_and_stamp(
    envelope_dict: Mapping[str, Any],
    *,
    adapter: UniversalIngressAdapter,
    tenant_id: str,
) -> GatewayResult:
    """Validate an adapter-built Envelope-B observation and stamp its provenance.

    Rebuilds the runtime model (schema + vocabulary enforcement), checks the
    canonical event type / family against the Contract Spine and the tenant
    against ``tenancy.tenant_id``, then stamps ``provenance.credential_class`` /
    ``adapter`` / ``adapter_version`` / ``source_trust`` (defaulting to the
    adapter's credential class) and ``quality.validation_state``.

    Returns a :class:`GatewayResult`: ``accepted`` with the stamped additive
    envelope dict, or ``rejected`` with reason codes
    (``envelope_schema_invalid`` / ``unknown_observation_type`` /
    ``family_mismatch`` / ``tenant_mismatch``).
    """
    observation_id = str(
        (envelope_dict.get("observation") or {}).get("observation_id") or ""
    )

    try:
        envelope = UniversalObservationEnvelope(**dict(envelope_dict))
    except ValidationError as exc:
        logger.warning(
            "ingress gateway: envelope_schema_invalid (%d error(s)), "
            "observation_id=%s",
            exc.error_count(),
            observation_id,
        )
        return _reject(observation_id, "envelope_schema_invalid")

    event_type = envelope.observation.observation_type
    if event_type not in CANONICAL_EVENT_TYPES:
        return _reject(observation_id, "unknown_observation_type")

    family = envelope.observation.family
    if family is not None:
        expected_family = EVENT_FAMILY.get(event_type)
        if expected_family is not None and family != expected_family:
            return _reject(observation_id, "family_mismatch")

    if envelope.tenancy.tenant_id != tenant_id:
        return _reject(observation_id, "tenant_mismatch")

    # ── Provenance stamping (gateway-owned; never trusted from the adapter) ──
    provenance = envelope.provenance
    stamped_provenance = ProvenanceBlock(
        credential_class=adapter.credential_class,
        signature_status=provenance.signature_status if provenance else None,
        adapter=adapter.adapter_id,
        adapter_version=adapter.adapter_version,
        source_trust=(
            provenance.source_trust
            if provenance and provenance.source_trust
            else adapter.credential_class
        ),
    )

    quality = envelope.quality
    stamped_quality = QualityBlock(
        completeness=quality.completeness if quality else None,
        freshness=quality.freshness if quality else None,
        sequencing_state=quality.sequencing_state if quality else None,
        validation_state="gateway:accepted",
    )

    stamped = envelope.model_copy(
        update={"provenance": stamped_provenance, "quality": stamped_quality}
    )
    return GatewayResult(
        observation_id=observation_id,
        status="accepted",
        envelope=stamped.to_bronze_additive(),
    )
