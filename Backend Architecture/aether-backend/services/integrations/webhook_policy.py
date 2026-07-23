"""Consent and signature policy boundary for inbound connector webhooks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from config.settings import settings


POLICY_RUNTIME_UNAVAILABLE = "consent_policy_runtime_unavailable"
SIGNATURE_INVALID = "invalid_signature"


@dataclass(frozen=True)
class WebhookPolicyOutcome:
    allowed: bool
    reason_code: Optional[str] = None
    quarantine_required: bool = False
    policy_decision_id: Optional[str] = None


def _explicit_bool(config: Mapping[str, Any], key: str) -> Optional[bool]:
    """Preserve absent governance configuration as unknown, not false."""

    if key not in config:
        return None
    value = config[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        return None
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    return None


def verify_provider_webhook_signature(
    connector: Any,
    *,
    raw_body: bytes,
    headers: Mapping[str, Any],
    secret: Optional[str],
    signature: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> bool:
    """Verify using the connector's native scheme or Aether generic HMAC."""

    if not secret:
        return False
    native_verifier = getattr(connector, "verify_webhook_signature", None)
    if callable(native_verifier):
        try:
            return bool(native_verifier(raw_body, dict(headers), secret))
        except Exception:
            return False

    from services.security.integration_security import verify_signature

    return bool(
        signature
        and timestamp
        and verify_signature(secret, raw_body, timestamp, signature)
    )


async def evaluate_consent_control_plane(
    *,
    tenant_id: str,
    connector_type: str,
    connector_config: Optional[Mapping[str, Any]],
    payload_fields: Optional[list[str]] = None,
    subject_id: Optional[str] = None,
    anonymous_id: Optional[str] = None,
) -> WebhookPolicyOutcome:
    """Evaluate webhook processing when the integration gate is active.

    Rollout-off behavior preserves the existing connector path. When active,
    an unavailable consent runtime is a denial so imports can never silently
    bypass the control plane.
    """

    rollout = settings.integration_consent
    if not (
        rollout.control_plane_v2_enabled
        and rollout.connector_policy_gate_enabled
    ):
        return WebhookPolicyOutcome(allowed=True)

    config = dict(connector_config or {})
    try:
        from services.integrations.consent_policy import (
            evaluate_connector_processing,
        )
    except ImportError:
        return WebhookPolicyOutcome(
            allowed=False,
            reason_code=POLICY_RUNTIME_UNAVAILABLE,
            quarantine_required=True,
        )

    decision = await evaluate_connector_processing(
        tenant_id,
        connector_type,
        source_kind="webhook",
        payload_fields=payload_fields,
        subject_id=subject_id,
        anonymous_id=anonymous_id,
        purpose=config.get("purpose") or config.get("processing_purpose"),
        processing_basis=config.get("processing_basis"),
        tenant_admin_approved=_explicit_bool(
            config, "tenant_admin_approved"
        ),
        provider_admin_installed=_explicit_bool(
            config, "provider_admin_installed"
        ),
        action="process",
    )
    return WebhookPolicyOutcome(
        allowed=decision.allowed,
        reason_code=decision.reasonCode,
        quarantine_required=decision.quarantineRequired,
        policy_decision_id=decision.decisionId,
    )
