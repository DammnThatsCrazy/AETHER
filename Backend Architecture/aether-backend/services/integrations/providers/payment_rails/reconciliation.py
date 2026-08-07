"""Payment rail reconciliation — SDK-side signals vs provider truth.

Reconciles what the tenant's SDK observed (payment_* signals captured on the
client/backend) against provider truth (verified webhooks / status polling)
into the six canonical states:

- ``sdk_only``          SDK saw the flow; no provider confirmation yet.
- ``provider_only``     provider truth exists; no SDK signal was captured.
- ``matched``           both sides agree on the compared fields.
- ``stale``             no provider confirmation within the staleness window.
- ``conflict``          both sides disagree — field-level discrepancies listed.
- ``ignored_duplicate`` the triggering delivery was an exact duplicate.

Discrepancies are (field, sdk_value, provider_value) triples over a fixed
compare-field list; values pass the sensitive-field sanitizer so raw payment
instruments can never surface through a reconciliation record.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from services.integrations.providers.payment_rails.base import is_sensitive_key
from services.integrations.providers.payment_rails.models import (
    ReconciliationRecord,
    utc_now_iso,
)

# A session with an SDK-side signal but no provider confirmation within this
# window is considered stale. Environment-tunable (alerting + reconciliation use
# the same window), defaulting to 24h.
STALE_AFTER_SECONDS: int = int(
    os.getenv("AETHER_PAYMENT_RECON_STALE_AFTER_SECONDS", str(24 * 60 * 60))
)

# Fields compared between the SDK view and provider truth.
RECONCILIATION_COMPARE_FIELDS: tuple[str, ...] = (
    "status",
    "provider",
    "flow_type",
    "source_amount",
    "fiat_currency",
    "destination_amount",
    "destination_asset",
    "destination_chain",
    "destination_address",
    "provider_transaction_id",
    "tx_hash",
)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _safe_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def compare_views(
    sdk_view: dict[str, Any], provider_view: dict[str, Any]
) -> list[dict[str, Optional[str]]]:
    """Field-level discrepancies between the two views, sanitized.

    Only fields present (non-null) on BOTH sides are compared — a missing
    field is absence of signal, not disagreement.
    """
    discrepancies: list[dict[str, Optional[str]]] = []
    for field in RECONCILIATION_COMPARE_FIELDS:
        if is_sensitive_key(field):  # defense-in-depth; compare list is safe
            continue
        sdk_value = sdk_view.get(field)
        provider_value = provider_view.get(field)
        if sdk_value is None or provider_value is None:
            continue
        if _safe_str(sdk_value) != _safe_str(provider_value):
            discrepancies.append({
                "field": field,
                "sdk_value": _safe_str(sdk_value),
                "provider_value": _safe_str(provider_value),
            })
    return discrepancies


def evaluate_state(
    *,
    sdk_view: Optional[dict[str, Any]],
    provider_view: Optional[dict[str, Any]],
    is_duplicate: bool = False,
    now: Optional[datetime] = None,
    stale_after_seconds: int = STALE_AFTER_SECONDS,
) -> tuple[str, list[dict[str, Optional[str]]]]:
    """Map (sdk_view, provider_view) into one of the six canonical states."""
    if is_duplicate:
        return "ignored_duplicate", []
    if sdk_view and not provider_view:
        observed = _parse_ts(sdk_view.get("observed_at") or sdk_view.get("occurred_at"))
        moment = now or datetime.now(timezone.utc)
        if observed is not None and (moment - observed).total_seconds() > stale_after_seconds:
            return "stale", []
        return "sdk_only", []
    if provider_view and not sdk_view:
        return "provider_only", []
    if not sdk_view and not provider_view:
        return "sdk_only", []  # nothing to reconcile against — treat as unconfirmed
    discrepancies = compare_views(sdk_view or {}, provider_view or {})
    if discrepancies:
        return "conflict", discrepancies
    return "matched", []


def reconcile_session(
    session: dict[str, Any],
    *,
    sdk_view: Optional[dict[str, Any]] = None,
    provider_view: Optional[dict[str, Any]] = None,
    is_duplicate: bool = False,
    last_source: str = "webhook",
    sdk_event_id: Optional[str] = None,
    provider_event_id: Optional[str] = None,
    now: Optional[datetime] = None,
    stale_after_seconds: int = STALE_AFTER_SECONDS,
) -> ReconciliationRecord:
    """Build the ReconciliationRecord for a funding session.

    ``sdk_view`` defaults to the sanitized SDK signal the service stashed in
    ``session.metadata.sdk_signal``; ``provider_view`` defaults to the session
    itself when it was advanced by provider truth (webhook/polling).
    """
    metadata = session.get("metadata") or {}
    if sdk_view is None:
        sdk_view = metadata.get("sdk_signal")
    if provider_view is None and last_source in ("webhook", "polling"):
        provider_view = session

    state, discrepancies = evaluate_state(
        sdk_view=sdk_view,
        provider_view=provider_view,
        is_duplicate=is_duplicate,
        now=now,
        stale_after_seconds=stale_after_seconds,
    )
    resolved_at = utc_now_iso() if state == "matched" else None
    return ReconciliationRecord(
        tenant_id=session["tenant_id"],
        funding_session_id=session["id"],
        provider=session["provider"],
        state=state,  # type: ignore[arg-type]
        last_source=last_source,
        sdk_event_id=sdk_event_id or (sdk_view or {}).get("event_id"),
        provider_event_id=provider_event_id,
        discrepancies=discrepancies,  # type: ignore[arg-type]
        first_observed_at=session.get("created_at") or utc_now_iso(),
        last_checked_at=utc_now_iso(),
        resolved_at=resolved_at,
    )
