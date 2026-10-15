"""Policy evaluation and response redaction for Suggestion Intelligence.

Enforces tenant isolation, high-risk class approval requirements, execution
eligibility, consent-purpose checks, and scrubs sensitive fields from
tenant-facing responses.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from .models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionPolicyDecision,
    SuggestionSource,
)

logger = get_logger("aether.suggestions.policy")

# ---------------------------------------------------------------------------
# Approval gate rules
# ---------------------------------------------------------------------------

HIGH_RISK_CLASSES: frozenset[SuggestionClass] = frozenset({
    SuggestionClass.SECURITY,
    SuggestionClass.GOVERNANCE,
    SuggestionClass.IDENTITY,
    SuggestionClass.GRAPH_HEALTH,
    SuggestionClass.RELIABILITY,
})

CONSENT_SENSITIVE_CLASSES: frozenset[SuggestionClass] = frozenset({
    SuggestionClass.IDENTITY,
    SuggestionClass.CAMPAIGN,
    SuggestionClass.RETARGETING,
    SuggestionClass.NOTIFICATION,
})

# ---------------------------------------------------------------------------
# Sensitive keys to strip from tenant-facing responses (deep redact)
# ---------------------------------------------------------------------------

SENSITIVE_KEYS: frozenset[str] = frozenset({
    "api_key", "key_hash", "secret", "token", "password",
    "credentials", "authorization", "session_token", "refresh_token",
    "private_key", "connection_string", "oauth_token", "webhook_secret",
    "x_api_key", "client_secret", "access_token", "bearer",
    "cookie", "set_cookie", "operator_context",
})

# Fields never returned to tenant-facing surfaces
OPERATOR_ONLY_FIELDS: frozenset[str] = frozenset({
    "operator_notes",
    "operator_context",
    "source_ref",
    "lineage_event_ids",
    "graph_refs",
    "profile_refs",
    "journey_refs",
    "audit_trail",
    "policy_decision",
})


def requires_approval(
    suggestion_class: SuggestionClass,
    risk_score: Optional[float],
    reversible: Optional[bool],
) -> bool:
    """Return True if this suggestion must enter review before execution."""
    if suggestion_class in HIGH_RISK_CLASSES:
        return True
    if risk_score is not None and risk_score >= 0.7:
        return True
    if reversible is False:
        return True
    return False


def execution_eligible(
    suggestion_class: SuggestionClass,
    source: SuggestionSource,
    risk_score: Optional[float],
) -> bool:
    """Return True only for classes/sources that support automated execution."""
    automated_sources: frozenset[SuggestionSource] = frozenset({
        SuggestionSource.RECOMMENDATION_ENGINE,
        SuggestionSource.NOTIFICATION_INTELLIGENCE,
        SuggestionSource.SYSTEM,
        SuggestionSource.RULE,
    })
    if source not in automated_sources:
        return False
    if suggestion_class in HIGH_RISK_CLASSES:
        return False
    if risk_score is not None and risk_score >= 0.7:
        return False
    return True


async def evaluate_suggestion_policy(
    create: SuggestionCreate,
    tenant_context: Any,
) -> SuggestionPolicyDecision:
    """Evaluate policy for a SuggestionCreate.

    Checks:
    1. Tenant isolation — create.tenant_id must match tenant_context.tenant_id
    2. Sensitivity — high-risk classes → requires_approval=True
    3. Execution eligibility
    4. Consent-purpose check for marketing/identity subjects
    """
    policies: list[str] = []
    obligations: list[str] = []
    explanation_parts: list[str] = []

    ctx_tid = getattr(tenant_context, "tenant_id", None)
    if ctx_tid and create.tenant_id != ctx_tid:
        return SuggestionPolicyDecision(
            decision_id=str(uuid.uuid4()),
            allowed=False,
            requires_approval=True,
            policies=["tenant_isolation"],
            obligations=[],
            explanation="Suggestion tenant_id does not match the authenticated tenant.",
            evaluated_at=utc_now().isoformat(),
        )

    _requires_approval = requires_approval(
        create.suggestion_class,
        create.risk_score,
        create.reversible,
    )
    _execution_eligible = execution_eligible(
        create.suggestion_class,
        create.source,
        create.risk_score,
    )

    if create.suggestion_class in HIGH_RISK_CLASSES:
        policies.append("high_risk_class_approval")
        explanation_parts.append(
            f"Class {create.suggestion_class.value!r} requires human approval."
        )

    if create.risk_score is not None and create.risk_score >= 0.7:
        policies.append("high_risk_score_approval")
        explanation_parts.append(
            f"Risk score {create.risk_score:.2f} exceeds the 0.70 threshold."
        )

    if create.reversible is False:
        policies.append("irreversible_action_approval")
        explanation_parts.append("Irreversible suggestions require approval.")

    if create.suggestion_class in CONSENT_SENSITIVE_CLASSES:
        policies.append("consent_purpose_check")
        obligations.append("verify_consent_before_delivery")
        explanation_parts.append(
            "Marketing/identity class requires consent verification before delivery."
        )

    if not policies:
        policies.append("default_suggestion_policy")

    return SuggestionPolicyDecision(
        decision_id=str(uuid.uuid4()),
        allowed=True,
        requires_approval=_requires_approval,
        policies=policies,
        obligations=obligations,
        explanation=" ".join(explanation_parts) or None,
        evaluated_at=utc_now().isoformat(),
    )


def _deep_redact(obj: Any, sensitive_keys: frozenset[str]) -> Any:
    """Recursively scrub sensitive keys from dicts/lists."""
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if k in sensitive_keys else _deep_redact(v, sensitive_keys)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_deep_redact(item, sensitive_keys) for item in obj]
    return obj


def redact_for_tenant(suggestion: dict) -> dict:
    """Remove or scrub fields not safe for tenant-facing API responses.

    Strips operator-only keys entirely, then deep-redacts remaining values
    containing sensitive credential-like keys.
    """
    cleaned = {k: v for k, v in suggestion.items() if k not in OPERATOR_ONLY_FIELDS}
    return _deep_redact(cleaned, SENSITIVE_KEYS)
