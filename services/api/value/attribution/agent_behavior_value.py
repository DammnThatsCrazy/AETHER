"""Value attribution for agent-mediated economic activity (WO-092).

Value distinguishes activity an agent *selected*, *executed* or only
*influenced* from activity a human selected. It consumes DecisionEnvelopes and
responsibility roles; it never writes value into a DecisionEnvelope
(anti-pattern) and never treats an agent-reported settlement as settled money:
reported amounts stay ``reported`` until the owning rail confirms them.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

CLASSES = ("agent_selected_and_executed", "agent_executed_human_selected", "agent_selected_human_executed",
           "agent_influenced", "human_only", "unattributed")


def _dec(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


def classify(roles: dict[str, dict[str, Any]], agent_refs: set[str]) -> str:
    decision = roles.get("decision_actor", {}).get("value")
    execution = roles.get("execution_actor", {}).get("value")
    influence = roles.get("influencing_actor", {}).get("value")
    by_agent_decided = decision in agent_refs
    by_agent_executed = execution in agent_refs
    if by_agent_decided and by_agent_executed:
        return "agent_selected_and_executed"
    if by_agent_executed and decision is not None:
        return "agent_executed_human_selected"
    if by_agent_decided:
        return "agent_selected_human_executed"
    if influence in agent_refs:
        return "agent_influenced"
    if decision is not None or execution is not None:
        return "human_only"
    return "unattributed"


def attribute(actions: Iterable[dict[str, Any]], agent_refs: Iterable[str],
              confirmed_settlements: Iterable[str] = ()) -> dict[str, Any]:
    """``actions``: ``{"event_id", "amount", "currency", "roles"}`` per economic
    action. Totals are exact decimals per (class, currency, finality)."""
    agents = set(agent_refs)
    confirmed = set(confirmed_settlements)
    totals: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    rows = []
    for a in actions:
        amount = _dec(a.get("amount"))
        cls = classify(a.get("roles") or {}, agents)
        finality = "confirmed" if a["event_id"] in confirmed else "reported"
        rows.append({"event_id": a["event_id"], "class": cls, "amount": str(amount) if amount is not None else None,
                     "currency": a.get("currency"), "finality": finality})
        if amount is not None and a.get("currency"):
            totals[(cls, a["currency"], finality)] += amount
    return {
        "actions": rows,
        "totals": [{"class": k[0], "currency": k[1], "finality": k[2], "amount": str(v)}
                   for k, v in sorted(totals.items())],
        "note": "Reported amounts are agent claims; only confirmed rows are settled value. "
                "Currencies are never summed together.",
    }
