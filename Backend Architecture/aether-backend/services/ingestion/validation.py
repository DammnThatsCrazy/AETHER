"""Canonical asynchronous validation for every SDK ingestion path.

This module owns policy decisions only. V1 and V2 keep their distinct
persistence/idempotency mechanics, but both must consume EventValidationResult
before any durable write or publish.

Consent-class model shared by the WS-B3 ingress paths (``evaluate_ingress_decision``):
  - **S** = per-subject server receipt (``services.consent.authority.evaluate_consent``).
  - **C** = credential/connection-class (install/config is the grant; no per-subject
    lookup unless a purpose resolves AND the authoritative flag is on).
  - **T** = tenant-server/back-office (tenant attests rights; data-policy + scrub only).
    API feeds and imports are T.
Batch = S (``validate_event``). Feeds/imports = T. Connector/comm/payment/provider = C.

WS-B3 rule applied by every seam (see ``evaluate_ingress_decision``):
  * the MANDATORY minimization layer -- scrub of sensitive values, strip of
    client-asserted canonical entity ids, and T-class tenant data-policy removal
    of fingerprinting -- runs UNCONDITIONALLY on every path (default ON; never
    behind a per-path flag). Scrub never rejects and data-policy is
    default-allow, so this layer closes the Invariant #9 gap without new denials;
  * the per-subject (S) SERVER-receipt rejection is the ONLY per-path toggle. It
    applies when a purpose is present under the authoritative flag; it is
    fail-closed like ``validate_event`` -- ``evaluate_consent`` returns
    ``consent_receipt_missing`` for an event with no resolvable subject/anonymous
    identifier, so an authoritative-ON, purposed, subject-less request is never
    silently fail-opened to allowed. A caller that wants NO per-subject gate
    supplies no purpose (C/T minimization), never a subject-less purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from config.settings import settings
from services.consent.authority import (
    evaluate_consent,
    evaluate_data_policy,
    evaluate_request_privacy_signals,
)
from services.ingestion.acquisition_privacy import sanitize_acquisition_payload
from services.ingestion.generated_registry import (
    CANONICAL_EVENT_TYPES,
    EVENT_CONSENT_PURPOSE,
    EVENT_FAMILY,
)
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.ingestion.validation")

VALIDATION_VERSION = "2"
SCHEMA_VERSION = "1.0.0"

REJECT_UNKNOWN_TYPE = "unknown_event_type"
REJECT_CONSENT_DENIED = "consent_denied"
REJECT_CONSENT_REQUIRED = "consent_required"
REJECT_EXECUTION_CLAIM = "execution_by_aether_must_be_false"
REJECT_DEPLOYMENT_CONTEXT = "deployment_context_invalid"
REJECT_ENVELOPE_MISSING = "envelope_missing"

# Canonical envelope v1 fields (packages/shared/events.ts) that release-critical
# events must carry when enforcement is on. Order matters: the wire rejection
# reason names the FIRST missing field in this order
# (`envelope_missing:<field>`); the full list lands in audit_metadata.
ENVELOPE_REQUIRED_FIELDS = ("sequence", "schemaVersion", "surface")

# Event families the founding release train actually projects — the families
# consumed by config/founding_tenant_release.yaml's release_surface.consumers
# (stream-ingestion-projection, identity-signal-emission,
# graph-profile-projection, measurement-identity-restatement,
# semantic-classification). Families in the release's excluded domains
# (payments/derivatives/stablecoin/rewards/agent-execution/...) keep today's
# metrics-only posture until their domain enters a release surface.
RELEASE_CRITICAL_EVENT_FAMILIES = frozenset({"core", "journey", "identity", "consent"})

_CANONICAL_ENTITY_KEYS = frozenset({"canonical_entity_id", "canonicalentityid"})
_FINGERPRINT_KEYS = frozenset({
    "fingerprint",
    "fingerprinting",
    "fingerprintsignals",
    "devicefingerprint",
    "crossdevicefingerprint",
    "browserfingerprint",
    "canvasfingerprint",
    "audiofingerprint",
    "webglfingerprint",
})
_SENSITIVE_KEY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"private[_\s]?key", r"seed[_\s]?phrase", r"mnemonic",
        r"password", r"passwd", r"passphrase", r"secret[_\s]?key?",
        r"\bsecret\b", r"\bpin\b", r"card[_\s]?number", r"\bpan\b",
        r"\bcvv\b", r"\bcvc\b", r"cvv2", r"payment[_\s]?token",
        r"auth[_\s]?code", r"api[_\s\-]?key", r"access[_\s]?token",
        r"refresh[_\s]?token", r"bearer[_\s]?token", r"ssh[_\s]?key",
        r"\bauthorization\b", r"authorization[_\s\-]?token", r"auth[_\s\-]?token",
        r"\bbearer\b", r"\bcookie\b", r"session[_\s]?token", r"\btoken\b",
        r"\bcredential", r"\bjwt\b", r"oauth[_\s\-]?token", r"\bdob\b",
        r"credit[_\s\-]?card",
        r"id[_\s]?token", r"social[_\s]?security", r"\bssn\b",
        r"\bein\b", r"\btin\b", r"bank[_\s]?account",
        r"routing[_\s]?number", r"iban", r"totp[_\s]?secret",
        r"otp[_\s]?secret", r"recovery[_\s]?code", r"client[_\s]?secret",
        r"webhook[_\s]?secret", r"form[_\s]?value", r"field[_\s]?value",
        r"input[_\s]?value", r"entered[_\s]?text", r"clipboard",
        r"keystroke", r"raw[_\s]?message", r"message[_\s]?body",
        r"email[_\s]?body",
    )
)


@dataclass(frozen=True)
class RequestPrivacySignals:
    """Sanitized request-time privacy signals; raw header values are never kept."""

    gpc: bool = False
    dnt: bool = False
    malformed: tuple[str, ...] = ()

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> "RequestPrivacySignals":
        gpc_raw = headers.get("sec-gpc")
        dnt_raw = headers.get("dnt")
        malformed: list[str] = []
        if gpc_raw is not None and str(gpc_raw).strip() not in {"0", "1"}:
            malformed.append("sec-gpc")
        if dnt_raw is not None and str(dnt_raw).strip() not in {"0", "1"}:
            malformed.append("dnt")
        return cls(
            gpc=str(gpc_raw or "").strip() == "1",
            dnt=str(dnt_raw or "").strip() == "1",
            malformed=tuple(malformed),
        )


@dataclass(frozen=True)
class EventValidationResult:
    """Typed, side-effect-bounded decision consumed by V1 and V2 ingestion."""

    allowed: bool
    reason_code: Optional[str]
    required_purpose: Optional[str]
    normalized_event: Optional[dict[str, Any]]
    deployment_id: Optional[str]
    privacy_decisions: tuple[dict[str, Any], ...] = ()
    audit_metadata: dict[str, Any] = field(default_factory=dict)


def scrub_sensitive_fields(obj: Any) -> tuple[Any, bool]:
    """Recursively redact sensitive values without logging payload contents."""
    found = False
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if any(pattern.search(str(key)) for pattern in _SENSITIVE_KEY_PATTERNS):
                out[key] = "[REDACTED]"
                found = True
            else:
                out[key], nested = scrub_sensitive_fields(value)
                found = found or nested
        return out, found
    if isinstance(obj, list):
        out_list: list[Any] = []
        for value in obj:
            scrubbed, nested = scrub_sensitive_fields(value)
            out_list.append(scrubbed)
            found = found or nested
        return out_list, found
    return obj, False


def strip_canonical_entity_id(obj: Any) -> Any:
    """Drop all client-asserted canonical entity identifiers recursively."""
    if isinstance(obj, dict):
        return {
            key: strip_canonical_entity_id(value)
            for key, value in obj.items()
            if re.sub(r"[^a-z0-9_]", "", str(key).lower()) not in _CANONICAL_ENTITY_KEYS
        }
    if isinstance(obj, list):
        return [strip_canonical_entity_id(value) for value in obj]
    return obj


def classify_fingerprints(obj: Any, path: tuple[str, ...] = ()) -> list[str]:
    """Public: classify fingerprint-bearing fields by key only; values are never
    retained. Shared by ``validate_event`` and the WS-B3 ingress facade so every
    path (batch, feed, comms, provider, imports) speaks one fingerprint language."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            next_path = (*path, str(key))
            if normalized in _FINGERPRINT_KEYS or normalized.endswith("fingerprint"):
                found.append(".".join(next_path))
            found.extend(classify_fingerprints(value, next_path))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(classify_fingerprints(value, (*path, "[]")))
    return found[:16]


def get_event_family(event_type: str) -> str:
    return EVENT_FAMILY.get(event_type, "core")


def build_normalized_payload(
    sdk_event: Any,
    tenant_id: str,
    batch_id: str,
    received_at: str,
) -> dict[str, Any]:
    """Build the only payload eligible for Bronze/outbox persistence."""
    return sanitize_acquisition_payload({
        "event_id": sdk_event.id,
        "tenant_id": tenant_id,
        "event_type": sdk_event.type,
        "event_family": get_event_family(sdk_event.type),
        "session_id": sdk_event.sessionId,
        "anonymous_id": sdk_event.anonymousId,
        "user_id": sdk_event.userId,
        "properties": strip_canonical_entity_id(sdk_event.properties or {}),
        "context": strip_canonical_entity_id(
            sdk_event.context.model_dump(exclude_none=True)
        ),
        "timestamp": sdk_event.timestamp,
        "received_at": received_at,
        "ingested_at": utc_now().isoformat(),
        "batch_id": batch_id,
        "schema_version": SCHEMA_VERSION,
        "source": "sdk",
    })


def format_rejection(result: EventValidationResult, sdk_event: Any) -> str:
    """Render the stable wire reason while keeping result fields structured."""
    code = result.reason_code or "validation_failed"
    # Class-specific details must win over the generic purpose suffix: a
    # deployment rejection also carries the event's required_purpose, and
    # rendering that first told operators "deployment_context_invalid:analytics"
    # instead of the actual cause (deployment_not_found, deployment_not_active,
    # event_family_not_allowed).
    if code == REJECT_UNKNOWN_TYPE:
        return f"{code}:{sdk_event.type}"
    if code == REJECT_DEPLOYMENT_CONTEXT:
        detail = result.audit_metadata.get("deployment_reason")
        return f"{code}:{detail}" if detail else code
    if code == REJECT_ENVELOPE_MISSING:
        # Per-field reason: name the first missing envelope field (canonical
        # ENVELOPE_REQUIRED_FIELDS order) rather than the generic purpose
        # suffix; audit_metadata carries the complete missing list.
        missing = result.audit_metadata.get("envelope_missing_fields") or []
        return f"{code}:{missing[0]}" if missing else code
    if result.required_purpose:
        return f"{code}:{result.required_purpose}"
    return code


async def validate_event(
    *,
    sdk_event: Any,
    tenant_id: str,
    batch_id: str,
    received_at: str,
    granted_consents: frozenset[str] = frozenset(),
    request_privacy: RequestPrivacySignals = RequestPrivacySignals(),
) -> EventValidationResult:
    """Run the canonical policy pipeline without persistence or publication."""

    required_purpose = EVENT_CONSENT_PURPOSE.get(sdk_event.type)
    decisions: list[dict[str, Any]] = []
    audit: dict[str, Any] = {
        "validation_version": VALIDATION_VERSION,
        "request_signals": {"gpc": request_privacy.gpc, "dnt": request_privacy.dnt},
        "malformed_request_signals": list(request_privacy.malformed),
        "sensitive_fields_scrubbed": False,
        "fingerprint_paths": [],
    }

    def reject(code: str, *, purpose: Optional[str] = required_purpose) -> EventValidationResult:
        return EventValidationResult(
            allowed=False,
            reason_code=code,
            required_purpose=purpose,
            normalized_event=None,
            deployment_id=None,
            privacy_decisions=tuple(decisions),
            audit_metadata=dict(audit),
        )

    if sdk_event.type not in CANONICAL_EVENT_TYPES:
        metrics.increment("ingestion_validation_failed_total", labels={"reason": "unknown_type"})
        return reject(REJECT_UNKNOWN_TYPE, purpose=None)

    if sdk_event.properties and sdk_event.properties.get("execution_by_aether") is True:
        metrics.increment(
            "ingestion_validation_failed_total", labels={"reason": "execution_by_aether"}
        )
        return reject(REJECT_EXECUTION_CLAIM, purpose=None)

    # ── Envelope required-field enforcement (staged, release-profile-driven) ──
    # Default OFF in local/dev/integration (older SDK payloads stay accepted
    # exactly as today), ON in staging/production via
    # settings.ingestion_v2.envelope_required_fields_enforced. Applies only to
    # release-critical event families; rejection reason is
    # `envelope_missing:<field>` via format_rejection.
    if (
        settings.ingestion_v2.envelope_required_fields_enforced
        and get_event_family(sdk_event.type) in RELEASE_CRITICAL_EVENT_FAMILIES
    ):
        missing_fields = [
            field_name
            for field_name in ENVELOPE_REQUIRED_FIELDS
            if getattr(sdk_event.context, field_name, None) is None
        ]
        if missing_fields:
            audit["envelope_missing_fields"] = missing_fields
            metrics.increment(
                "ingestion_validation_failed_total",
                labels={"reason": "envelope_missing"},
            )
            # required_purpose stays on the result for audit; format_rejection
            # renders the per-field reason before any purpose suffix.
            return reject(REJECT_ENVELOPE_MISSING)

    properties, props_sensitive = scrub_sensitive_fields(sdk_event.properties or {})
    context_dict, context_sensitive = scrub_sensitive_fields(
        sdk_event.context.model_dump(exclude_none=False)
    )
    sdk_event.properties = properties
    sdk_event.context = sdk_event.context.__class__.model_validate(context_dict)
    audit["sensitive_fields_scrubbed"] = props_sensitive or context_sensitive
    if audit["sensitive_fields_scrubbed"]:
        metrics.increment("ingestion_sensitive_scrub_total")
        logger.warning(
            "Sensitive fields scrubbed event_id=%s tenant=%s type=%s",
            sdk_event.id,
            tenant_id,
            sdk_event.type,
        )

    if sdk_event.type != "consent" and required_purpose:
        consent_snapshot = sdk_event.context.consent
        if isinstance(consent_snapshot, dict) and consent_snapshot.get(required_purpose) is False:
            metrics.increment(
                "ingestion_consent_blocked_total", labels={"purpose": required_purpose}
            )
            return reject(REJECT_CONSENT_DENIED)
        if granted_consents and required_purpose not in granted_consents:
            metrics.increment(
                "ingestion_validation_failed_total", labels={"reason": "consent_missing"}
            )
            return reject(REJECT_CONSENT_REQUIRED)

        signal_allowed, signal_reason = evaluate_request_privacy_signals(
            required_purpose,
            gpc_observed=request_privacy.gpc,
            dnt_observed=request_privacy.dnt,
        )
        decisions.append({
            "control": "request_privacy_signals",
            "outcome": "allowed" if signal_allowed else "suppressed",
            "reason_code": signal_reason,
            "purpose": required_purpose,
        })
        if not signal_allowed:
            metrics.increment(
                "ingestion_request_privacy_blocked_total",
                labels={"purpose": required_purpose, "reason": signal_reason or "unknown"},
            )
            return reject(signal_reason or REJECT_CONSENT_DENIED)

        if settings.consent_authority.authoritative_consent_enforcement_enabled:
            allowed, reason_code = await evaluate_consent(
                tenant_id=tenant_id,
                subject_id=sdk_event.userId,
                anonymous_id=sdk_event.anonymousId,
                purpose=required_purpose,
            )
            if not allowed:
                metrics.increment(
                    "ingestion_consent_authority_blocked_total",
                    labels={"purpose": required_purpose, "reason": reason_code or "unknown"},
                )
                return reject(reason_code or REJECT_CONSENT_DENIED)

    fingerprint_paths = classify_fingerprints({
        "properties": sdk_event.properties or {},
        "context": sdk_event.context.model_dump(exclude_none=True),
    })
    audit["fingerprint_paths"] = fingerprint_paths
    if fingerprint_paths:
        allowed, reason_code = await evaluate_data_policy(tenant_id, "fingerprint")
        decisions.append({
            "control": "fingerprint_policy",
            "outcome": "allowed" if allowed else "denied",
            "reason_code": reason_code,
            "classified_paths": len(fingerprint_paths),
        })
        if not allowed:
            metrics.increment(
                "ingestion_data_policy_blocked_total",
                labels={"data_class": "fingerprint", "reason": reason_code or "unknown"},
            )
            return reject(reason_code or "fingerprinting_not_authorized")

    deployment_id: Optional[str] = None
    if settings.external_agent_telemetry.enabled:
        deployment_ctx = (
            sdk_event.context.agentDeployment or sdk_event.context.agent_deployment
        )
        if isinstance(deployment_ctx, dict):
            deployment_id = (
                deployment_ctx.get("deploymentId") or deployment_ctx.get("deployment_id")
            )
        if deployment_id:
            from services.agent.deployments import (
                record_event_outcome,
                validate_deployment_context,
            )

            valid, reason = await validate_deployment_context(
                tenant_id,
                deployment_ctx,
                event_family=get_event_family(sdk_event.type),
            )
            if not valid:
                await record_event_outcome(
                    tenant_id, str(deployment_id), "rejected"
                )
                audit["deployment_reason"] = reason
                metrics.increment(
                    "ingestion_validation_failed_total",
                    labels={"reason": "deployment_context"},
                )
                return EventValidationResult(
                    allowed=False,
                    reason_code=REJECT_DEPLOYMENT_CONTEXT,
                    required_purpose=required_purpose,
                    normalized_event=None,
                    deployment_id=str(deployment_id),
                    privacy_decisions=tuple(decisions),
                    audit_metadata=dict(audit),
                )

    normalized = build_normalized_payload(
        sdk_event=sdk_event,
        tenant_id=tenant_id,
        batch_id=batch_id,
        received_at=received_at,
    )
    return EventValidationResult(
        allowed=True,
        reason_code=None,
        required_purpose=required_purpose,
        normalized_event=normalized,
        deployment_id=str(deployment_id) if deployment_id else None,
        privacy_decisions=tuple(decisions),
        audit_metadata=dict(audit),
    )


# ── Shared ingress facade (WS-B3: consent-on-every-path) ─────────────────────
# One decision function for every non-batch ingress seam. The ordering mirrors
# ``validate_event``'s S-class pipeline (request-privacy signals → server
# authority → fingerprint/data-policy) while letting each path state its class:
# a caller supplies ``purpose`` (+ subject) to opt into the per-subject S gate,
# or omits it for a T/C-class purpose-less decision (data-policy + scrub only).
# Never raises; scrub always proceeds regardless of the decision.

def format_ingress_rejection(reason_code: Optional[str], decisions: tuple[dict, ...]) -> str:
    """Stable wire reason mirroring ``format_rejection`` (code[:purpose])."""
    if not reason_code:
        return "validation_failed"
    purpose = next(
        (d.get("purpose") for d in decisions if d.get("purpose")), None
    )
    return f"{reason_code}:{purpose}" if purpose else reason_code


async def evaluate_ingress_decision(
    *,
    tenant_id: str,
    subject_id: Optional[str] = None,
    anonymous_id: Optional[str] = None,
    purpose: Optional[str] = None,
    request_privacy: RequestPrivacySignals = RequestPrivacySignals(),
    fingerprint_obj: Any = None,
) -> tuple[bool, Optional[str], tuple[dict, ...]]:
    """Consent/data-policy decision for an ingress path (never raises).

    Returns ``(allowed, reason_code_or_None, decisions)`` where ``decisions`` is
    the tuple of policy decisions (same dict vocabulary as ``validate_event``'s
    privacy_decisions).

    Order mirrors ``validate_event`` EXACTLY (so no ingress seam can diverge
    from the /v1/batch path):
      1. request-privacy signals (GPC/DNT) suppress a supplied purpose;
      2. when a purpose is supplied and
         ``authoritative_consent_enforcement_enabled`` is ON → server consent
         receipt via ``evaluate_consent`` UNCONDITIONALLY. ``evaluate_consent``
         itself is fail-closed on an unresolvable subject: no subject/anonymous
         identifier → ``consent_receipt_missing`` (absence of a server receipt
         is NOT permission). A caller that wants to skip the per-subject (S)
         gate entirely supplies NO purpose (T/C class), never a subject-less
         purpose under the authoritative flag;
      3. when ``fingerprint_obj`` is supplied → classify + tenant data-policy
         (``evaluate_data_policy(tenant_id, "fingerprint")``).
    Reject reason codes reuse this module's ``REJECT_*`` constants and the
    authority's stable codes (``consent_receipt_missing``, ...).
    """
    decisions: list[dict[str, Any]] = []

    if purpose:
        signal_allowed, signal_reason = evaluate_request_privacy_signals(
            purpose,
            gpc_observed=request_privacy.gpc,
            dnt_observed=request_privacy.dnt,
        )
        decisions.append({
            "control": "request_privacy_signals",
            "outcome": "allowed" if signal_allowed else "suppressed",
            "reason_code": signal_reason,
            "purpose": purpose,
        })
        if not signal_allowed:
            metrics.increment(
                "ingestion_request_privacy_blocked_total",
                labels={"purpose": purpose, "reason": signal_reason or "unknown"},
            )
            return False, signal_reason or REJECT_CONSENT_DENIED, tuple(decisions)

        subject = (subject_id or "").strip() or None
        anon = (anonymous_id or "").strip() or None
        # Mirror validate_event: under the authoritative flag the server receipt
        # is consulted for EVERY purposed event. evaluate_consent denies
        # (CONSENT_RECEIPT_MISSING) when no subject/anonymous identifier is
        # resolvable, so an authoritative-ON, purposed, subject-less request is
        # REJECTED — never silently fail-opened to allowed.
        if settings.consent_authority.authoritative_consent_enforcement_enabled:
            allowed, reason_code = await evaluate_consent(
                tenant_id=tenant_id,
                subject_id=subject,
                anonymous_id=anon,
                purpose=purpose,
            )
            decisions.append({
                "control": "consent_authority",
                "outcome": "allowed" if allowed else "denied",
                "reason_code": reason_code,
                "purpose": purpose,
                "subject_resolvable": bool(subject or anon),
            })
            if not allowed:
                metrics.increment(
                    "ingestion_consent_authority_blocked_total",
                    labels={"purpose": purpose, "reason": reason_code or "unknown"},
                )
                return False, reason_code or REJECT_CONSENT_DENIED, tuple(decisions)

    if fingerprint_obj is not None:
        fingerprint_paths = classify_fingerprints(fingerprint_obj)
        if fingerprint_paths:
            allowed, reason_code = await evaluate_data_policy(tenant_id, "fingerprint")
            decisions.append({
                "control": "fingerprint_policy",
                "outcome": "allowed" if allowed else "denied",
                "reason_code": reason_code,
                "classified_paths": len(fingerprint_paths),
            })
            if not allowed:
                metrics.increment(
                    "ingestion_data_policy_blocked_total",
                    labels={"data_class": "fingerprint", "reason": reason_code or "unknown"},
                )
                return False, reason_code or "fingerprinting_not_authorized", tuple(decisions)

    return True, None, tuple(decisions)


__all__ = [
    "ENVELOPE_REQUIRED_FIELDS",
    "EventValidationResult",
    "REJECT_ENVELOPE_MISSING",
    "RELEASE_CRITICAL_EVENT_FAMILIES",
    "RequestPrivacySignals",
    "build_normalized_payload",
    "classify_fingerprints",
    "evaluate_ingress_decision",
    "format_ingress_rejection",
    "format_rejection",
    "get_event_family",
    "scrub_sensitive_fields",
    "strip_canonical_entity_id",
    "validate_event",
]
