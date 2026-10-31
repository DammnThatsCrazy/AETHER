"""Authority grants and boundaries for observed agent actions (WO-020).

The delegation engine answers "may this grantee do this now?" before an
action. This module answers the after-the-fact question for an *observed*
action: was it inside the boundary of an authority grant that existed when it
happened? The answer is ``inside``, ``outside`` or ``unknown`` with reasons and
evidence. It is an explanation, never an authorization decision and never
proof of intent.

Scope shape extends the engine's (``actions``, ``resources``, ``max_amount``)
with the economic constraints the work orders require. Every key is optional;
an absent constraint is "not constrained", not "violated":

    {
      "actions": ["purchase", "invoke_tool"],
      "resources": ["merchant:*"],
      "max_amount": "100.00",             # per transaction
      "daily_limit": "250.00",
      "merchant_allowlist": ["shop-1"],
      "protocol_allowlist": ["uniswap"],
      "asset_allowlist": ["USDC"],
      "human_approval_threshold": "50.00"
    }
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

AUTHORITY_SCOPES = (
    "read_email", "send_email", "purchase", "trade_asset", "transfer_asset",
    "post_social", "invoke_tool", "create_agent", "terminate_agent", "access_resource",
)
INSIDE = "inside"
OUTSIDE = "outside"
UNKNOWN = "unknown"


def _dec(value: Any) -> Optional[Decimal]:
    if value in (None, "", "*") or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _resource_matches(pattern: str, resource: str) -> bool:
    if pattern in ("*", resource):
        return True
    return pattern.endswith(":*") and resource.startswith(pattern[:-1])


def _ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class ObservedAction:
    """An action reported by an agent, with the context needed to check it."""

    event_id: str
    actor_ref: str
    action: str
    occurred_at: str
    resource: Optional[str] = None
    amount: Optional[str] = None
    merchant: Optional[str] = None
    protocol: Optional[str] = None
    asset: Optional[str] = None
    human_approval_ref: Optional[str] = None


@dataclass
class BoundaryResult:
    status: str
    grant_id: Optional[str]
    reasons: list[str] = field(default_factory=list)
    requires_human_approval: bool = False
    human_approval_observed: bool = False
    evidence: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "grant_id": self.grant_id,
            "reasons": self.reasons,
            "requires_human_approval": self.requires_human_approval,
            "human_approval_observed": self.human_approval_observed,
            "evidence": self.evidence,
            "notes": self.notes,
            "claim": "authority_boundary_check",
            "note": "Observed against recorded grants; not an authorization decision.",
        }


def grant_active_at(grant: dict[str, Any], at: str) -> Optional[bool]:
    """True/False when the grant window is known, None when it cannot be told."""
    moment = _ts(at)
    if moment is None:
        return None
    start, end, revoked = _ts(grant.get("starts_at")), _ts(grant.get("ends_at")), _ts(grant.get("revoked_at"))
    if start and moment < start:
        return False
    if end and moment >= end:
        return False
    if revoked and moment >= revoked:
        return False
    return True


def _scope_violations(scope: dict[str, Any], act: ObservedAction, spent_today: Decimal) -> list[str]:
    reasons: list[str] = []
    actions = scope.get("actions") or []
    if actions and act.action not in actions and "*" not in actions:
        reasons.append("action_not_in_scope")
    resources = scope.get("resources") or []
    if resources and act.resource and not any(_resource_matches(p, act.resource) for p in resources):
        reasons.append("resource_not_in_scope")
    amount = _dec(act.amount)
    per_tx = _dec(scope.get("max_amount"))
    if amount is not None and per_tx is not None and amount > per_tx:
        reasons.append("max_transaction_exceeded")
    daily = _dec(scope.get("daily_limit"))
    if amount is not None and daily is not None and spent_today + amount > daily:
        reasons.append("daily_limit_exceeded")
    for key, value in (("merchant_allowlist", act.merchant), ("protocol_allowlist", act.protocol),
                       ("asset_allowlist", act.asset)):
        allow = scope.get(key)
        if allow and value and value not in allow:
            reasons.append(f"{key.replace('_allowlist', '')}_not_allowlisted")
    return reasons


def check_action(
    act: ObservedAction,
    grants: Iterable[dict[str, Any]],
    prior_actions: Iterable[ObservedAction] = (),
) -> BoundaryResult:
    """Classify one observed action against the actor's recorded grants.

    ``prior_actions`` are the actor's earlier observed spends, used only for
    the daily limit; spends Aether did not observe make the daily check a
    lower bound, which the result says.
    """
    grants = [g for g in grants if g.get("grantee_entity_id") in (act.actor_ref, None)]
    if not grants:
        return BoundaryResult(UNKNOWN, None, ["no_recorded_grant"], evidence=[act.event_id])
    day = (act.occurred_at or "")[:10]
    spent = sum(
        (_dec(p.amount) or Decimal(0) for p in prior_actions
         if p.actor_ref == act.actor_ref and (p.occurred_at or "")[:10] == day
         and (p.occurred_at or "") < (act.occurred_at or "") and p.event_id != act.event_id),
        Decimal(0),
    )
    best: Optional[BoundaryResult] = None
    for grant in sorted(grants, key=lambda g: str(g.get("delegation_id") or "")):
        active = grant_active_at(grant, act.occurred_at)
        scope = grant.get("scope") or {}
        reasons = _scope_violations(scope, act, spent)
        if active is False:
            reasons.insert(0, "grant_not_active_at_action_time")
        threshold = _dec(scope.get("human_approval_threshold"))
        amount = _dec(act.amount)
        needs_human = bool(threshold is not None and amount is not None and amount >= threshold)
        if needs_human and not act.human_approval_ref:
            reasons.append("human_approval_required_not_observed")
        status = OUTSIDE if reasons else (UNKNOWN if active is None else INSIDE)
        result = BoundaryResult(
            status, grant.get("delegation_id"), reasons or (["action_time_unknown"] if active is None else []),
            requires_human_approval=needs_human,
            human_approval_observed=bool(act.human_approval_ref),
            evidence=[act.event_id],
        )
        if _dec(scope.get("daily_limit")) is not None and "daily_limit_exceeded" not in reasons:
            # Spend Aether did not observe could still breach the limit.
            result.notes.append("daily_limit_checked_against_observed_spend_only")
        if status == INSIDE:
            return result
        if best is None or len(result.reasons) < len(best.reasons):
            best = result
    assert best is not None
    return best
