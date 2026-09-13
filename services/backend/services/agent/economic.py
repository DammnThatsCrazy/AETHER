"""
Aether Service — Agent Economic Views

Per-agent budget usage, delegation policy views, and treasury runway.
Consumed by Profile360 and the commerce analytics surface.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from repositories.repos import (
    AgentEconomicIdentityRepository,
    DelegationRepository,
    PaymentIntentRepository,
    SettlementEventRepository,
)
from services.value.models import to_decimal
from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.service.agent.economic")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except InvalidOperation:
        return Decimal("0")


# ═══════════════════════════════════════════════════════════════════════════
# Outcome classification — claimed vs observed vs verified vs estimated vs
# counterfactual. A claimed success (HTTP 200, a "success" flag) is NEVER a
# verified business outcome.
# ═══════════════════════════════════════════════════════════════════════════

# Provenance classes, ordered loosely by strength of evidence.
OUTCOME_CLASSES = frozenset({
    "claimed",        # self-reported by the executor (HTTP 2xx, success flag) — unverified
    "observed",       # a record exists in a system of record, not yet reconciled
    "verified",       # independently reconciled/confirmed against an authority
    "estimated",      # modeled/projected value — not a realized outcome
    "counterfactual",  # baseline "what would have happened" — not a realized outcome
    "unknown",        # no signal
})

# Reconciliation states (mirrors services.value.models.RECONCILIATION_STATES).
_VERIFIED_RECONCILIATION = "matched"
_OBSERVED_RECONCILIATION = frozenset(
    {"provider_only", "sdk_only", "unreconciled", "stale", "conflict"}
)
# Terminal settlement statuses treated as authoritative *spend* by budget_view.
# Their mere presence is an observed record, NOT an independently verified one.
_TERMINAL_SETTLED_STATUSES = frozenset({"settled", "paid", "success", "access_granted"})


def classify_outcome(
    *,
    http_status: int | None = None,
    self_reported_success: bool | None = None,
    settlement_status: str | None = None,
    reconciliation_state: str | None = None,
    verified_by: str | None = None,
    is_estimate: bool = False,
    is_counterfactual: bool = False,
) -> dict[str, Any]:
    """Classify an outcome by the *strength of its evidence*.

    A claimed success is never silently promoted to a verified business outcome.

    Precedence:

    * ``counterfactual`` — a baseline/"what-if"; never a realized outcome.
    * ``estimated``      — modeled/projected; not a realized outcome.
    * ``verified``       — independently reconciled/confirmed (reconciliation
                           ``matched`` or an explicit ``verified_by`` authority).
    * ``observed``       — a record exists in a system of record but is not yet
                           reconciled.
    * ``claimed``        — self-reported only (HTTP 2xx, a success flag). This is
                           the ceiling for an HTTP 200: it is NOT verified.
    * ``unknown``        — no signal.

    ``is_verified_business_outcome`` is True only for ``verified``.
    """
    signals = {
        "http_status": http_status,
        "self_reported_success": self_reported_success,
        "settlement_status": settlement_status,
        "reconciliation_state": reconciliation_state,
        "verified_by": verified_by,
        "is_estimate": is_estimate,
        "is_counterfactual": is_counterfactual,
    }

    def _result(classification: str, rationale: str) -> dict[str, Any]:
        return {
            "classification": classification,
            "is_verified_business_outcome": classification == "verified",
            "rationale": rationale,
            "signals": signals,
        }

    if is_counterfactual:
        return _result("counterfactual", "baseline/what-if scenario; not a realized outcome")
    if is_estimate:
        return _result("estimated", "modeled/projected value; not a realized outcome")

    if reconciliation_state == _VERIFIED_RECONCILIATION or verified_by:
        return _result(
            "verified",
            "independently reconciled/confirmed against an authoritative source",
        )

    observed = (
        settlement_status in _TERMINAL_SETTLED_STATUSES
        or reconciliation_state in _OBSERVED_RECONCILIATION
    )
    claimed = (
        (http_status is not None and 200 <= http_status < 300)
        or self_reported_success is True
    )

    if observed:
        return _result(
            "observed",
            "a record exists in a system of record but is not reconciled/verified",
        )
    if claimed:
        return _result(
            "claimed",
            "self-reported success (e.g. HTTP 2xx) — unverified, not a business outcome",
        )
    return _result("unknown", "no outcome signal available")


# ═══════════════════════════════════════════════════════════════════════════
# Expected-utility — components kept SEPARATELY VISIBLE, money as Decimal.
# ═══════════════════════════════════════════════════════════════════════════

def _clamp_probability(value: object) -> Decimal | None:
    """Parse a probability into a Decimal in [0, 1], or None if invalid/absent.

    Unknown probability is None (never coerced to 0), matching the value model's
    "unknown != 0" rule.
    """
    d = to_decimal(value)
    if d is None or d < 0 or d > 1:
        return None
    return d


def compute_expected_utility(
    *,
    value_of_success: object,
    probability_of_success: object,
    execution_cost: object = None,
    failure_cost: object = None,
    review_cost: object = None,
    risk_penalty: object = None,
    currency: str = "USD",
    outcome_class: str | None = None,
) -> dict[str, Any]:
    """Expected-utility of an agent action, every component SEPARATELY visible.

    ::

        expected_utility = expected_value_of_success
                           - execution_cost
                           - expected_failure_cost
                           - review_cost
                           - risk_penalty

    where::

        expected_value_of_success = value_of_success * probability_of_success
        expected_failure_cost     = failure_cost * (1 - probability_of_success)

    Every term is returned individually — the result is never collapsed into one
    opaque number. Money is Decimal end-to-end (via ``to_decimal``); it is never
    float-summed, and an unknown input is never coerced to 0 — a missing input
    makes ``expected_utility`` ``None`` and is listed under ``missing_inputs``.
    """
    p_success = _clamp_probability(probability_of_success)
    value = to_decimal(value_of_success)
    exec_cost = to_decimal(execution_cost)
    fail_cost = to_decimal(failure_cost)
    rev_cost = to_decimal(review_cost)
    risk = to_decimal(risk_penalty)

    missing: list[str] = []
    if value is None:
        missing.append("value_of_success")
    if p_success is None:
        missing.append("probability_of_success")
    if exec_cost is None:
        missing.append("execution_cost")
    if fail_cost is None:
        missing.append("failure_cost")
    if rev_cost is None:
        missing.append("review_cost")
    if risk is None:
        missing.append("risk_penalty")

    p_failure = (Decimal(1) - p_success) if p_success is not None else None
    expected_value_of_success = (
        value * p_success if value is not None and p_success is not None else None
    )
    expected_failure_cost = (
        fail_cost * p_failure if fail_cost is not None and p_failure is not None else None
    )

    expected_utility: Decimal | None = None
    if not missing:
        # Pure Decimal arithmetic — no float ever enters the sum.
        expected_utility = (
            expected_value_of_success
            - exec_cost
            - expected_failure_cost
            - rev_cost
            - risk
        )

    def _s(d: Decimal | None) -> str | None:
        return str(d) if d is not None else None

    return {
        "currency": currency,
        "components_visible": True,
        # Each component surfaced individually — NOT collapsed into one number:
        "value_of_success": _s(value),
        "probability_of_success": _s(p_success),
        "probability_of_failure": _s(p_failure),
        "expected_value_of_success": _s(expected_value_of_success),
        "execution_cost": _s(exec_cost),
        "expected_failure_cost": _s(expected_failure_cost),
        "review_cost": _s(rev_cost),
        "risk_penalty": _s(risk),
        "expected_utility": _s(expected_utility),
        "computable": not missing,
        "missing_inputs": missing,
        # Provenance of the value input — a claimed/observed outcome is not
        # bankable; only a verified one is.
        "outcome_class": outcome_class,
        "is_verified_business_outcome": (
            outcome_class == "verified" if outcome_class is not None else None
        ),
        "computed_at": utc_now().isoformat(),
    }


class AgentEconomicViews:
    """Aggregates per-agent economic data from repositories.

    All queries are tenant-scoped; no cross-tenant data is ever returned.
    """

    def __init__(
        self,
        payment_intents: Optional[PaymentIntentRepository] = None,
        settlements: Optional[SettlementEventRepository] = None,
        delegations: Optional[DelegationRepository] = None,
        identities: Optional[AgentEconomicIdentityRepository] = None,
    ) -> None:
        self._intents = payment_intents or PaymentIntentRepository()
        self._settlements = settlements or SettlementEventRepository()
        self._delegations = delegations or DelegationRepository()
        self._identities = identities or AgentEconomicIdentityRepository()

    async def budget_view(
        self,
        agent_id: str,
        tenant_id: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Return current budget usage and burn rate for an agent.

        Derives spend from settlement records (authoritative) rather than
        intent status to avoid double-counting pending intents.
        """
        intents = await self._intents.list_for_agent(agent_id, tenant_id, limit=limit)
        settlements = await self._settlements.list_for_agent(agent_id, tenant_id, limit=limit)

        # Terminal settled statuses — all represent completed spend
        settled_statuses = {"settled", "paid", "success", "access_granted"}

        spend_by_currency: dict[str, Decimal] = {}
        for s in settlements:
            if s.get("status") in settled_statuses:
                currency = s.get("currency") or "UNKNOWN"
                spend_by_currency[currency] = (
                    spend_by_currency.get(currency, Decimal("0"))
                    + _decimal(s.get("amount"))
                )

        pending_count = sum(
            1 for i in intents
            if i.get("settlement_status") in {"pending", "submitted", "authorized"}
        )
        failed_count = sum(
            1 for s in settlements
            if s.get("status") in {"failed", "timeout"}
        )
        total_settled = sum(
            1 for s in settlements
            if s.get("status") in settled_statuses
        )

        # Economic identity holds pre-computed recurring spend and preferences
        identity = await self._identities.find_for_agent(agent_id, tenant_id)
        recurring_spend = (identity or {}).get("recurring_spend", {})

        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "spend_by_currency": {k: str(v) for k, v in spend_by_currency.items()},
            "recurring_spend": recurring_spend,
            "intent_count": len(intents),
            "pending_intent_count": pending_count,
            "settled_count": total_settled,
            "failed_count": failed_count,
            "settlement_success_rate": (
                round(total_settled / len(settlements), 4) if settlements else None
            ),
            "computed_at": utc_now().isoformat(),
        }

    async def delegation_policy_view(
        self,
        agent_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Return active delegations granted to and by this agent.

        Combines explicit delegation grants (from DelegationRepository) with
        subagent spawns (recorded by AgentLifecycleMapper as delegation rows).
        """
        # Delegations where this agent is the grantee (it acts on behalf of someone)
        received = await self._delegations.active_for(agent_id, tenant_id)

        # Delegations where this agent is the grantor (it delegated to others)
        granted = await self._delegations.find_many(
            filters={"grantor_entity_id": agent_id, "tenant_id": tenant_id},
            limit=200,
        )
        now_iso = utc_now().isoformat()
        active_granted = [
            d for d in granted
            if not d.get("revoked_at")
            and (not d.get("ends_at") or d["ends_at"] > now_iso)
        ]

        # Subagents: delegations granted to others with source=agent_subagent_spawned
        subagents = [
            d for d in active_granted
            if (d.get("metadata") or {}).get("source") == "agent_subagent_spawned"
        ]

        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "received_delegation_count": len(received),
            "received_delegations": received,
            "granted_delegation_count": len(active_granted),
            "subagent_count": len(subagents),
            "subagents": [
                {
                    "agent_id": d.get("grantee_entity_id"),
                    "delegation_id": d.get("delegation_id"),
                    "scope": d.get("scope", {}),
                    "starts_at": d.get("starts_at"),
                }
                for d in subagents
            ],
            "computed_at": utc_now().isoformat(),
        }

    async def full_economic_profile(
        self,
        agent_id: str,
        tenant_id: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Merge budget + delegation views into a single economic profile response."""
        budget = await self.budget_view(agent_id, tenant_id, limit=limit)
        delegation = await self.delegation_policy_view(agent_id, tenant_id)
        identity = await self._identities.find_for_agent(agent_id, tenant_id)

        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "budget": budget,
            "delegation_policy": delegation,
            "economic_identity": identity,
            "computed_at": utc_now().isoformat(),
        }

    # Pure decision helpers exposed on the aggregator for discoverability.
    # They take no repository state, so they are safe as static methods.
    classify_outcome = staticmethod(classify_outcome)
    compute_expected_utility = staticmethod(compute_expected_utility)
