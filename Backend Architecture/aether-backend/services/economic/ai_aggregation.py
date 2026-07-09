"""AI economics aggregation over ``ai_execution_facts``.

Aggregation rules:

- Workflow IDs are NEVER fabricated — facts without a ``workflow_run_id`` are
  excluded from workflow aggregation.
- Costs are NEVER summed across currencies — every monetary aggregate is a
  ``{currency: amount}`` map over facts whose cost is known.
- Unknown costs stay unknown: facts with ``cost_basis == "unknown"`` count
  toward coverage denominators but never contribute zero to a total.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger
from shared.store import get_store

from services.economic.ai_models import AIWorkflowEconomics

logger = get_logger("aether.economic.ai_aggregation")

AI_EXECUTION_FACTS_STORE = "ai_execution_facts"
AI_WORKFLOW_ECONOMICS_STORE = "ai_workflow_economics"

_FILTERABLE_FIELDS = (
    "workflow_run_id", "provider", "model", "task_type", "status",
    "cost_basis", "agent_id", "campaign_id",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round(value: float) -> float:
    return round(value, 10)


def _known_cost(fact: dict[str, Any]) -> Optional[float]:
    """Selected cost when known; None otherwise (never coerced to zero)."""
    if fact.get("cost_basis") == "unknown":
        return None
    cost = fact.get("selected_cost")
    return float(cost) if cost is not None else None


async def list_facts(
    tenant_id: str,
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: Optional[int] = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    """Tenant-scoped fact listing with optional field/time filters."""
    store = get_store(AI_EXECUTION_FACTS_STORE)
    facts = await store.find(tenant_id=tenant_id)
    for field in _FILTERABLE_FIELDS:
        value = filters.get(field)
        if value is not None:
            facts = [f for f in facts if f.get(field) == value]
    if since is not None:
        facts = [f for f in facts if (f.get("observed_at") or "") >= since]
    if until is not None:
        facts = [f for f in facts if (f.get("observed_at") or "") < until]
    facts.sort(key=lambda f: f.get("observed_at") or "")
    if limit is not None:
        facts = facts[: max(limit, 0)]
    return facts


# ── Monetary aggregates (always per-currency; never mixed) ─────────────────

def total_cost_by_currency(facts: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        cost = _known_cost(fact)
        if cost is None:
            continue
        totals[fact.get("currency", "")] += cost
    return {currency: _round(total) for currency, total in totals.items()}


def cost_per_invocation(facts: list[dict[str, Any]]) -> dict[str, float]:
    """Average known cost per invocation, per currency."""
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for fact in facts:
        cost = _known_cost(fact)
        if cost is None:
            continue
        currency = fact.get("currency", "")
        totals[currency] += cost
        counts[currency] += 1
    return {c: _round(totals[c] / counts[c]) for c in totals if counts[c]}


def failed_execution_cost(facts: list[dict[str, Any]]) -> dict[str, float]:
    """Known cost of invocations that did not succeed, per currency."""
    return total_cost_by_currency(
        [f for f in facts if f.get("status") != "succeeded"]
    )


def retry_waste_cost(facts: list[dict[str, Any]]) -> dict[str, float]:
    """Approximate cost of retries beyond the first attempt, per currency.

    For a fact with ``retry_count`` retries the waste approximation is
    ``selected_cost * retry_count / (retry_count + 1)``.
    """
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        retries = fact.get("retry_count") or 0
        if retries <= 0:
            continue
        cost = _known_cost(fact)
        if cost is None:
            continue
        totals[fact.get("currency", "")] += cost * retries / (retries + 1)
    return {currency: _round(total) for currency, total in totals.items()}


def quality_adjusted_cost(facts: list[dict[str, Any]]) -> dict[str, float]:
    """Sum of cost / quality_score over quality-scored facts, per currency."""
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        quality = fact.get("quality_score")
        cost = _known_cost(fact)
        if cost is None or quality is None or quality <= 0:
            continue
        totals[fact.get("currency", "")] += cost / quality
    return {currency: _round(total) for currency, total in totals.items()}


def cost_per_completed_workflow(facts: list[dict[str, Any]]) -> dict[str, float]:
    """Average known cost per fully-succeeded workflow, per currency.

    Facts without a workflow_run_id are excluded (never fabricated).
    """
    by_workflow: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        run_id = fact.get("workflow_run_id")
        if run_id:
            by_workflow[run_id].append(fact)

    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for wf_facts in by_workflow.values():
        if any(f.get("status") != "succeeded" for f in wf_facts):
            continue
        wf_totals = total_cost_by_currency(wf_facts)
        for currency, amount in wf_totals.items():
            totals[currency] += amount
            counts[currency] += 1
    return {c: _round(totals[c] / counts[c]) for c in totals if counts[c]}


# ── Ratio aggregates ────────────────────────────────────────────────────────

def cost_coverage(facts: list[dict[str, Any]]) -> Optional[float]:
    """Share of facts whose cost_basis is not 'unknown' (None when no facts)."""
    if not facts:
        return None
    known = sum(1 for f in facts if f.get("cost_basis") != "unknown")
    return known / len(facts)


def cache_utilization_rate(facts: list[dict[str, Any]]) -> Optional[float]:
    """cached_input_tokens / (input_tokens + cached_input_tokens)."""
    cached = sum(f.get("cached_input_tokens") or 0 for f in facts)
    fresh = sum(f.get("input_tokens") or 0 for f in facts)
    denominator = cached + fresh
    if denominator <= 0:
        return None
    return cached / denominator


def human_correction_rate(facts: list[dict[str, Any]]) -> Optional[float]:
    if not facts:
        return None
    corrected = sum(1 for f in facts if f.get("human_corrected"))
    return corrected / len(facts)


def outcome_attribution_coverage(facts: list[dict[str, Any]]) -> Optional[float]:
    if not facts:
        return None
    attributed = sum(1 for f in facts if f.get("outcome_id"))
    return attributed / len(facts)


# ── Workflow economics ─────────────────────────────────────────────────────

def _workflow_key(tenant_id: str, workflow_run_id: str) -> str:
    return f"{tenant_id}:{workflow_run_id}"


async def recompute_workflow(
    tenant_id: str, workflow_run_id: str
) -> Optional[AIWorkflowEconomics]:
    """Recompute and persist workflow economics from execution facts.

    Returns None when no facts carry this workflow_run_id (never fabricated).
    """
    if not workflow_run_id:
        return None
    facts = await list_facts(tenant_id, workflow_run_id=workflow_run_id)
    if not facts:
        return None

    totals = total_cost_by_currency(facts)
    known_currencies = sorted(totals)
    if len(known_currencies) == 1:
        currency = known_currencies[0]
        total_model_cost: Optional[float] = totals[currency]
    else:
        # Zero or several currencies: never mix — leave the total unknown.
        currency = known_currencies[0] if known_currencies else facts[0].get("currency", "")
        total_model_cost = None

    quality_scores = [f["quality_score"] for f in facts if f.get("quality_score") is not None]
    observed = sorted(f.get("observed_at") or "" for f in facts)
    failed = sum(1 for f in facts if f.get("status") != "succeeded")

    economics = AIWorkflowEconomics(
        tenant_id=tenant_id,
        workflow_run_id=workflow_run_id,
        total_invocations=len(facts),
        successful_invocations=sum(1 for f in facts if f.get("status") == "succeeded"),
        failed_invocations=failed,
        total_retries=int(sum(f.get("retry_count") or 0 for f in facts)),
        total_latency_ms=_round(sum(f.get("latency_ms") or 0 for f in facts)),
        total_model_cost=total_model_cost,
        tool_cost=None,
        retrieval_cost=None,
        fully_loaded_cost=total_model_cost,
        currency=currency,
        cost_coverage=cost_coverage(facts) or 0.0,
        quality_score=(sum(quality_scores) / len(quality_scores)) if quality_scores else None,
        human_reviewed=any(f.get("human_reviewed") for f in facts),
        human_corrected=any(f.get("human_corrected") for f in facts),
        technical_success=failed == 0,
        qualified_outcome_count=sum(1 for f in facts if f.get("outcome_id")),
        attributed_value=None,
        first_observed_at=observed[0],
        last_observed_at=observed[-1],
        computed_at=_utc_now_iso(),
    )
    store = get_store(AI_WORKFLOW_ECONOMICS_STORE)
    await store.set(_workflow_key(tenant_id, workflow_run_id), economics.model_dump(mode="json"))
    return economics


async def list_workflow_economics(tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
    store = get_store(AI_WORKFLOW_ECONOMICS_STORE)
    records = await store.find(tenant_id=tenant_id)
    records.sort(key=lambda r: r.get("last_observed_at") or "", reverse=True)
    return records[: max(limit, 0)]


# ── Rollups for the API surface ────────────────────────────────────────────

def model_rollup(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per provider+model rollup: invocations, cost per currency, latency,
    success rate, average quality."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        groups[(fact.get("provider", ""), fact.get("model", ""))].append(fact)

    rollups: list[dict[str, Any]] = []
    for (provider, model), group in sorted(groups.items()):
        latencies = [f["latency_ms"] for f in group if f.get("latency_ms") is not None]
        qualities = [f["quality_score"] for f in group if f.get("quality_score") is not None]
        rollups.append({
            "provider": provider,
            "model": model,
            "invocations": len(group),
            "cost_by_currency": total_cost_by_currency(group),
            "cost_coverage": cost_coverage(group),
            "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
            "success_rate": sum(1 for f in group if f.get("status") == "succeeded") / len(group),
            "avg_quality_score": (sum(qualities) / len(qualities)) if qualities else None,
        })
    return rollups


async def tenant_summary(tenant_id: str) -> dict[str, Any]:
    """Aggregate metric summary for one tenant."""
    facts = await list_facts(tenant_id)
    return {
        "tenant_id": tenant_id,
        "fact_count": len(facts),
        "total_cost_by_currency": total_cost_by_currency(facts),
        "cost_per_invocation": cost_per_invocation(facts),
        "cost_per_completed_workflow": cost_per_completed_workflow(facts),
        "failed_execution_cost": failed_execution_cost(facts),
        "retry_waste_cost": retry_waste_cost(facts),
        "quality_adjusted_cost": quality_adjusted_cost(facts),
        "cost_coverage": cost_coverage(facts),
        "cache_utilization_rate": cache_utilization_rate(facts),
        "human_correction_rate": human_correction_rate(facts),
        "outcome_attribution_coverage": outcome_attribution_coverage(facts),
        "computed_at": _utc_now_iso(),
    }
