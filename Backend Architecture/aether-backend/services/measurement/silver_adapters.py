"""Silver-to-canonical-activity adapters.

Each adapter converts a silver fact table row (or a projector output dict) into
a CanonicalActivity dict suitable for ActivityRepository.upsert().

Adapters are pure functions — they do NOT write to the database. The caller
(typically the silver projector or a backfill script) handles persistence.

Idempotency key convention:
    "{source_table}:{fact_id or source_event_id}:{tenant_id}"

This ensures the same silver row always maps to the same canonical_activity row
regardless of how many times the adapter is called.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID


# ── Adapter registry ──────────────────────────────────────────────────────────

def adapt_from_silver(
    silver_table: str,
    row: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Route a silver row to the correct adapter. Returns None if not mappable."""
    _adapters = {
        "silver_campaign_touchpoint_facts": adapt_campaign_touchpoint,
        "silver_web3_transaction_facts": adapt_web3_transaction,
        "silver_x402_flow_facts": adapt_x402_flow,
        "silver_agent_execution_facts": adapt_agent_execution,
        "silver_identity_evidence_facts": adapt_identity_evidence,
        "silver_outcome_facts": adapt_outcome,
        "silver_revenue_facts": adapt_revenue,
        "silver_exposure_facts": adapt_exposure,
        "silver_account_activity_facts": adapt_account_activity,
        "silver_comms_facts": adapt_comms,
        "canonical_conversions": adapt_canonical_conversion,
    }
    fn = _adapters.get(silver_table)
    if fn is None:
        return None
    return fn(row)


# ── Individual adapters ───────────────────────────────────────────────────────

def adapt_campaign_touchpoint(row: dict[str, Any]) -> dict[str, Any]:
    """silver_campaign_touchpoint_facts → canonical_activity (family=campaign or web2)."""
    tp_type = row.get("touchpoint_type", "page_view")
    is_campaign = bool(row.get("campaign_id"))
    family = "campaign" if is_campaign else "web2"

    return _base(row, silver_table="silver_campaign_touchpoint_facts") | {
        "activity_family": family,
        "activity_type": tp_type,
        "actor_type": row.get("actor_type") or "human",
        "channel": row.get("channel"),
        "source": row.get("source"),
        "medium": row.get("medium"),
        "platform": row.get("platform"),
        "source_class": row.get("source_class"),
        "traffic_origin": row.get("traffic_origin"),
        "economic_class": row.get("economic_class"),
        "channel_family": row.get("channel_family"),
        "entry_method": row.get("entry_method"),
        "proof_level": row.get("proof_level"),
        "evidence_conflicts": row.get("evidence_conflicts") or [],
        "referral_mediation_type": row.get("referral_mediation_type"),
        "ai_provider": row.get("ai_provider"),
        "ai_product": row.get("ai_product"),
        "journey_role": row.get("journey_role"),
        "evidence_confidence": row.get("evidence_confidence"),
        "verification_level": row.get("verification_level"),
        "source_classifier_version": row.get("source_classifier_version"),
        "normalized_referrer_domain": row.get("normalized_referrer_domain"),
        "source_classification_id": row.get("source_classification_id"),
        "attribution_eligible": row.get("attribution_eligible", True),
        "verified_referral_link_id": row.get("verified_referral_link_id"),
        "domain": row.get("normalized_referrer_domain"),
        "landing_url": row.get("landing_url"),
        "referrer": row.get("referrer"),
        "campaign_id": row.get("campaign_id"),
        "wallet_id": row.get("wallet_id"),
        "agent_id": row.get("agent_id"),
        "device_id": row.get("device_id"),
        "session_id": row.get("session_id"),
        "profile_id": row.get("profile_id"),
        "cluster_id": row.get("cluster_id"),
        "anonymous_id": row.get("anonymous_id"),
        "account_id": row.get("account_id"),
        "organization_id": row.get("organization_id"),
        "identity_method": row.get("identity_resolution_method"),
        "identity_confidence": row.get("identity_confidence"),
        "identity_version": row.get("identity_version"),
        "consent_snapshot_id": row.get("consent_snapshot_id"),
        "privacy_class": row.get("privacy_class", "behavioral"),
        "silver_fact_id": _uuid(row.get("touchpoint_id")),
        "silver_table": "silver_campaign_touchpoint_facts",
        "idempotency_key": f"sctf:{row.get('touchpoint_id') or row.get('idempotency_key')}:{row.get('tenant_id')}",
    }


def adapt_web3_transaction(row: dict[str, Any]) -> dict[str, Any]:
    """silver_web3_transaction_facts → canonical_activity (family=web3)."""
    event_type = row.get("source_event_type", "transaction_submitted")
    status = _web3_status_from_event_type(event_type, row.get("status"))

    return _base(row, silver_table="silver_web3_transaction_facts") | {
        "activity_family": "web3",
        "activity_type": event_type,
        "actor_type": "human",
        "profile_id": row.get("user_id") or row.get("actor_id"),
        "anonymous_id": row.get("anonymous_id"),
        "wallet_address": row.get("from_address"),
        "chain_id": str(row.get("chain_id")) if row.get("chain_id") else None,
        "contract_address": row.get("contract_address"),
        "tx_hash": row.get("tx_hash"),
        "activity_status": status,
        "token_address": row.get("token_address"),
        "value_wei": row.get("value_wei"),
        "privacy_class": row.get("privacy_class", "financial"),
        "silver_fact_id": _uuid(row.get("fact_id")),
        "silver_table": "silver_web3_transaction_facts",
        "idempotency_key": f"web3:{row.get('fact_id') or row.get('idempotency_key')}:{row.get('tenant_id')}",
    }


def adapt_x402_flow(row: dict[str, Any]) -> dict[str, Any]:
    """silver_x402_flow_facts → canonical_activity (family=x402)."""
    flow_type = row.get("flow_type", "x402_resource_requested")

    amount = row.get("amount")
    currency = row.get("currency")
    settled = row.get("settled", False)
    status = "confirmed" if settled else "pending"

    return _base(row, silver_table="silver_x402_flow_facts") | {
        "activity_family": "x402",
        "activity_type": flow_type,
        "actor_type": "agent",
        "profile_id": row.get("user_id") or row.get("actor_id"),
        "anonymous_id": row.get("anonymous_id"),
        "activity_status": status,
        "gross_amount": amount,
        "currency": currency,
        "privacy_class": row.get("privacy_class", "financial"),
        "silver_fact_id": _uuid(row.get("fact_id")),
        "silver_table": "silver_x402_flow_facts",
        "idempotency_key": f"x402:{row.get('fact_id') or row.get('idempotency_key')}:{row.get('tenant_id')}",
    }


def adapt_agent_execution(row: dict[str, Any]) -> dict[str, Any]:
    """silver_agent_execution_facts → canonical_activity (family=agent)."""
    outcome = row.get("outcome", "unknown")
    status = "confirmed" if outcome == "success" else ("failed" if outcome == "failure" else "observed")

    return _base(row, silver_table="silver_agent_execution_facts") | {
        "activity_family": "agent",
        "activity_type": "agent_task_executed",
        "actor_type": "agent",
        "agent_id": row.get("agent_id") or row.get("actor_id"),
        "profile_id": row.get("user_id"),
        "anonymous_id": row.get("anonymous_id"),
        "activity_status": status,
        "privacy_class": row.get("privacy_class", "behavioral"),
        "silver_fact_id": _uuid(row.get("fact_id")),
        "silver_table": "silver_agent_execution_facts",
        "idempotency_key": f"agent:{row.get('fact_id') or row.get('idempotency_key')}:{row.get('tenant_id')}",
    }


def adapt_identity_evidence(row: dict[str, Any]) -> dict[str, Any]:
    """silver_identity_evidence_facts → canonical_activity (family=web2)."""
    event_kind = row.get("event_kind", "identify")
    activity_type = _identity_event_kind_to_type(event_kind)

    return _base(row, silver_table="silver_identity_evidence_facts") | {
        "activity_family": "web2",
        "activity_type": activity_type,
        "actor_type": "human",
        "profile_id": row.get("user_id") or row.get("actor_id"),
        "anonymous_id": row.get("anonymous_id"),
        "device_id": row.get("device_id"),
        "identity_method": row.get("identity_method"),
        "identity_confidence": float(row.get("confidence")) if row.get("confidence") else None,
        "privacy_class": row.get("privacy_class", "behavioral"),
        "silver_fact_id": _uuid(row.get("fact_id")),
        "silver_table": "silver_identity_evidence_facts",
        "idempotency_key": f"idev:{row.get('fact_id') or row.get('idempotency_key')}:{row.get('tenant_id')}",
    }


def adapt_outcome(row: dict[str, Any]) -> dict[str, Any]:
    """silver_outcome_facts → canonical_activity (family=outcome)."""
    outcome_type = row.get("outcome_type", "custom")
    succeeded = row.get("succeeded", True)
    status = "confirmed" if succeeded else "failed"

    return _base(row, silver_table="silver_outcome_facts") | {
        "activity_family": "outcome",
        "activity_type": outcome_type,
        "actor_type": "human",
        "profile_id": row.get("user_id") or row.get("actor_id"),
        "anonymous_id": row.get("anonymous_id"),
        "activity_status": status,
        "gross_amount": row.get("value_amount"),
        "currency": row.get("value_currency"),
        "privacy_class": row.get("privacy_class", "financial"),
        "silver_fact_id": _uuid(row.get("fact_id")),
        "silver_table": "silver_outcome_facts",
        "idempotency_key": f"out:{row.get('fact_id') or row.get('idempotency_key')}:{row.get('tenant_id')}",
    }


def adapt_revenue(row: dict[str, Any]) -> dict[str, Any]:
    """silver_revenue_facts → canonical_activity (family=commerce)."""
    revenue_type = row.get("revenue_type", "payment")

    return _base(row, silver_table="silver_revenue_facts") | {
        "activity_family": "commerce",
        "activity_type": revenue_type,
        "actor_type": "human",
        "profile_id": row.get("user_id") or row.get("actor_id"),
        "anonymous_id": row.get("anonymous_id"),
        "activity_status": "confirmed",
        "gross_amount": row.get("gross_amount") or row.get("amount"),
        "currency": row.get("currency", "USD"),
        "privacy_class": row.get("privacy_class", "financial"),
        "silver_fact_id": _uuid(row.get("fact_id")),
        "silver_table": "silver_revenue_facts",
        "idempotency_key": f"rev:{row.get('fact_id') or row.get('idempotency_key')}:{row.get('tenant_id')}",
    }


def adapt_exposure(row: dict[str, Any]) -> dict[str, Any]:
    """silver_exposure_facts → canonical_activity (family=campaign)."""
    return _base(row, silver_table="silver_exposure_facts") | {
        "activity_family": "campaign",
        "activity_type": "recommendation_exposure",
        "actor_type": "human",
        "profile_id": row.get("user_id") or row.get("actor_id"),
        "anonymous_id": row.get("anonymous_id"),
        "campaign_id": row.get("campaign_id"),
        "privacy_class": row.get("privacy_class", "behavioral"),
        "silver_fact_id": _uuid(row.get("fact_id")),
        "silver_table": "silver_exposure_facts",
        "idempotency_key": f"exp:{row.get('fact_id') or row.get('idempotency_key')}:{row.get('tenant_id')}",
    }


def adapt_account_activity(row: dict[str, Any]) -> dict[str, Any]:
    """silver_account_activity_facts → canonical_activity (family=web2)."""
    activity_type = row.get("activity_type", "account_action")

    return _base(row, silver_table="silver_account_activity_facts") | {
        "activity_family": "web2",
        "activity_type": activity_type,
        "actor_type": "human",
        "profile_id": row.get("user_id") or row.get("actor_id"),
        "anonymous_id": row.get("anonymous_id"),
        "account_id": row.get("workspace_id"),
        "privacy_class": row.get("privacy_class", "behavioral"),
        "silver_fact_id": _uuid(row.get("fact_id")),
        "silver_table": "silver_account_activity_facts",
        "idempotency_key": f"acct:{row.get('fact_id') or row.get('idempotency_key')}:{row.get('tenant_id')}",
    }


def adapt_comms(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """silver_comms_facts → canonical_activity.

    Family and actor kind are routed by business meaning (message category /
    provenance), never hard-coded (ADR-C4/Phase 6). The idempotency key is the
    source-derived canonical activity key so one real-world event maps to one
    activity regardless of Silver row identity or replay.

    Events whose journey role is ``excluded`` (machine engagement, automated
    replies) produce no canonical activity at all.
    """
    from services.comms.contracts import (
        activity_family_for,
        actor_kind_from_provenance,
        canonical_activity_key,
    )

    journey_role = row.get("journey_role")
    if journey_role == "excluded":
        return None

    comms_type = row.get("source_event_type") or row.get("comms_type", "message")
    category = row.get("message_category")
    actor_kind = row.get("actor_kind") or actor_kind_from_provenance(
        direction=row.get("direction"),
        agent_id=row.get("agent_id"),
        sender_is_organization=bool(row.get("organization_id") or row.get("org_id")),
        category=category,
    ).value
    family = activity_family_for(category, actor_kind=actor_kind)

    idem = row.get("canonical_activity_key") or canonical_activity_key(
        str(row.get("tenant_id") or ""),
        str(row.get("provider") or "sdk"),
        row.get("provider_account_id"),
        str(row.get("provider_event_id") or row.get("source_event_id") or ""),
        str(comms_type),
    )

    return _base(row, silver_table="silver_comms_facts") | {
        "activity_family": family,
        "activity_type": comms_type,
        "actor_type": actor_kind,
        "profile_id": row.get("profile_id") or row.get("user_id") or row.get("actor_id"),
        "anonymous_id": row.get("anonymous_id"),
        "cluster_id": row.get("cluster_id"),
        "organization_id": row.get("organization_id"),
        "agent_id": row.get("agent_id"),
        "channel": row.get("channel"),
        "campaign_id": row.get("campaign_id"),
        "identity_confidence": _float_or_none(row.get("identity_confidence")),
        "privacy_class": row.get("privacy_class", "behavioral"),
        "silver_fact_id": _uuid(row.get("fact_id")),
        "silver_table": "silver_comms_facts",
        "idempotency_key": f"comms:{idem}",
    }


def adapt_canonical_conversion(row: dict[str, Any]) -> dict[str, Any]:
    """canonical_conversions → canonical_activity (family=commerce, type=conversion)."""
    occurred_at = row.get("occurred_at")

    return {
        "activity_family": "commerce",
        "activity_type": f"conversion_{row.get('conversion_type', 'custom')}",
        "actor_type": "human",
        "tenant_id": row.get("tenant_id"),
        "profile_id": row.get("profile_id"),
        "cluster_id": row.get("cluster_id"),
        "account_id": row.get("account_id"),
        "organization_id": row.get("organization_id"),
        "wallet_id": row.get("wallet_id"),
        "agent_id": row.get("agent_id"),
        "occurred_at": occurred_at,
        "server_received_at": row.get("observed_at") or datetime.now(timezone.utc).isoformat(),
        "activity_status": _conversion_status(row.get("conversion_status", "confirmed")),
        "source_event_id": str(row.get("source_event_id") or row.get("conversion_id")),
        "source_connector_id": row.get("source_connector_id"),
        "conversion_id": str(row.get("conversion_id")),
        "gross_amount": row.get("gross_value"),
        "net_amount": row.get("net_value"),
        "currency": row.get("currency", "USD"),
        "consent_snapshot_id": row.get("consent_snapshot_id"),
        "identity_version": row.get("identity_version"),
        "privacy_class": "financial",
        "silver_table": "canonical_conversions",
        "silver_fact_id": _uuid(row.get("conversion_id")),
        "idempotency_key": f"conv:{row.get('conversion_id')}:{row.get('tenant_id')}",
        "schema_version": 1,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base(row: dict[str, Any], *, silver_table: str) -> dict[str, Any]:
    """Build common canonical activity fields from a silver row."""
    return {
        "tenant_id": row.get("tenant_id"),
        "source_event_id": str(row.get("source_event_id") or row.get("fact_id") or ""),
        "consent_snapshot_id": row.get("consent_snapshot_id"),
        "occurred_at": row.get("occurred_at"),
        "server_received_at": row.get("received_at") or datetime.now(timezone.utc).isoformat(),
        "surface": row.get("surface"),
        "sequence_key": row.get("sequence_key"),
        "privacy_class": row.get("privacy_class", "behavioral"),
        "schema_version": 1,
        "activity_status": "observed",
    }


def _web3_status_from_event_type(event_type: str, raw_status: Optional[str]) -> str:
    if event_type in ("transaction_confirmed", "transaction_confirmed_observed", "settlement_finality_observed"):
        return "confirmed"
    if event_type in ("transaction_failed", "transaction_reverted_observed"):
        return "failed"
    if event_type in ("transaction_reorged_observed",):
        return "reorged"
    if event_type in ("transaction_submitted", "transaction_initiated"):
        return "pending"
    if raw_status:
        _map = {"success": "confirmed", "failed": "failed", "pending": "pending", "reverted": "reverted"}
        return _map.get(raw_status, "observed")
    return "observed"


def _identity_event_kind_to_type(event_kind: str) -> str:
    _map = {
        "login": "login",
        "logout": "logout",
        "identify": "identify",
        "register": "account_creation",
        "signup": "account_creation",
        "mfa": "mfa_verified",
        "password_reset": "password_reset",
        "wallet_bind": "wallet_connection",
        "siwx": "wallet_proof",
    }
    return _map.get(event_kind, event_kind)


def _conversion_status(status: str) -> str:
    _map = {
        "confirmed": "confirmed",
        "pending": "pending",
        "reversed": "reverted",
        "adjusted": "adjusted",
        "ineligible": "observed",
    }
    return _map.get(status, "observed")


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None
