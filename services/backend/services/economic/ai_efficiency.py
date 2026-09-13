"""Deterministic AI efficiency detectors (governed proposals only).

Five evidence-backed detectors over ``ai_execution_facts``. Every finding is
a proposal — nothing here changes models, prompts, routing, or spend. All
thresholds are module constants. Monetary estimates are per-currency maps
and are extrapolated to a 30-day month from the observed window (minimum
window of one day) — they are estimates, never billed truth.

Finding shape::

    {
        "detector": str,                # one of AI_EFFICIENCY_DETECTORS
        "tenant_id": str,
        "severity": "low"|"medium"|"high",
        "title": str,
        "description": str,
        "evidence_refs": [invocation_id, ...],
        "estimated_monthly_waste": {currency: amount} | None,
        "candidate_action": str,        # proposal text only — never executed
    }
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

from services.economic import ai_aggregation
from services.economic.ai_costs import USAGE_RATE_MAP
from services.economic.ai_models import AIPriceCard
from services.economic.ai_pricing import AIPriceCardRegistry, get_price_card_registry

logger = get_logger("aether.economic.ai_efficiency")

# ── Detector thresholds (module constants) ─────────────────────────────────

RETRY_WASTE_SHARE_THRESHOLD = 0.15      # retry waste ≥ 15% of a group's known cost
RETRY_WASTE_MIN_RETRIED_INVOCATIONS = 2

OVERQUALIFICATION_MIN_QUALITY = 0.95    # every scored invocation at or above this
OVERQUALIFICATION_MIN_SAMPLES = 5       # quality-scored invocations required

DETERMINISTIC_MIN_REPEATS = 5           # identical prompt_hash repetitions required
DETERMINISTIC_REQUIRED_QUALITY = 1.0

CACHE_MIN_REPEATED_INPUT_TOKENS = 50_000
CACHE_LOW_UTILIZATION_THRESHOLD = 0.20

FAILURE_RATE_THRESHOLD = 0.50           # strictly greater-than
FAILURE_MIN_INVOCATIONS = 2

SEVERITY_HIGH_MONTHLY_WASTE = 100.0
SEVERITY_MEDIUM_MONTHLY_WASTE = 10.0

EXTRAPOLATION_MIN_WINDOW_DAYS = 1.0
EXTRAPOLATION_MONTH_DAYS = 30.0

MAX_EVIDENCE_REFS = 50


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_ts(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _window_days(facts: list[dict[str, Any]]) -> float:
    stamps = [ts for ts in (_parse_ts(f.get("observed_at") or "") for f in facts) if ts]
    if len(stamps) < 2:
        return EXTRAPOLATION_MIN_WINDOW_DAYS
    delta_days = (max(stamps) - min(stamps)).total_seconds() / 86400.0
    return max(delta_days, EXTRAPOLATION_MIN_WINDOW_DAYS)


def _extrapolate_monthly(
    observed_waste: dict[str, float], facts: list[dict[str, Any]]
) -> Optional[dict[str, float]]:
    waste = {c: amount for c, amount in observed_waste.items() if amount > 0}
    if not waste:
        return None
    factor = EXTRAPOLATION_MONTH_DAYS / _window_days(facts)
    return {c: round(amount * factor, 6) for c, amount in waste.items()}


def _severity(monthly_waste: Optional[dict[str, float]]) -> str:
    if not monthly_waste:
        return "low"
    peak = max(monthly_waste.values())
    if peak >= SEVERITY_HIGH_MONTHLY_WASTE:
        return "high"
    if peak >= SEVERITY_MEDIUM_MONTHLY_WASTE:
        return "medium"
    return "low"


def _finding(
    detector: str,
    tenant_id: str,
    title: str,
    description: str,
    evidence_refs: list[str],
    monthly_waste: Optional[dict[str, float]],
    candidate_action: str,
) -> dict[str, Any]:
    return {
        "detector": detector,
        "tenant_id": tenant_id,
        "severity": _severity(monthly_waste),
        "title": title,
        "description": description,
        "evidence_refs": evidence_refs[:MAX_EVIDENCE_REFS],
        "estimated_monthly_waste": monthly_waste,
        "candidate_action": candidate_action,
    }


def _card_cost_for_fact(fact: dict[str, Any], card: AIPriceCard) -> Optional[float]:
    """Price a fact's usage dims against a card. None when nothing priceable."""
    total = 0.0
    priced_any = False
    for usage_field, rate_field, divisor in USAGE_RATE_MAP:
        usage = fact.get(usage_field)
        rate = getattr(card.rates, rate_field)
        if usage is None or rate is None:
            continue
        total += (usage / divisor) * rate
        priced_any = True
    return round(total, 10) if priced_any else None


def _card_unit_rate(card: AIPriceCard) -> float:
    """Comparable per-1k text rate for cheaper-model ranking."""
    return (card.rates.input_tokens_per_1k or 0.0) + (card.rates.output_tokens_per_1k or 0.0)


# ── Detector 1: retry waste ────────────────────────────────────────────────

async def detect_retry_waste(
    tenant_id: str,
    facts: list[dict[str, Any]],
    registry: AIPriceCardRegistry,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        groups[(fact.get("provider", ""), fact.get("model", ""))].append(fact)

    for (provider, model), group in sorted(groups.items()):
        retried = [f for f in group if (f.get("retry_count") or 0) > 0]
        if len(retried) < RETRY_WASTE_MIN_RETRIED_INVOCATIONS:
            continue
        waste = ai_aggregation.retry_waste_cost(group)
        totals = ai_aggregation.total_cost_by_currency(group)
        breaching = {
            c: amount for c, amount in waste.items()
            if totals.get(c, 0) > 0 and amount / totals[c] >= RETRY_WASTE_SHARE_THRESHOLD
        }
        if not breaching:
            continue
        monthly = _extrapolate_monthly(breaching, group)
        findings.append(_finding(
            "retry_waste", tenant_id,
            f"Retry waste on {provider}/{model}",
            f"{len(retried)} of {len(group)} invocations of {provider}/{model} were retried; "
            f"retry cost exceeds {RETRY_WASTE_SHARE_THRESHOLD:.0%} of the group's known cost.",
            [f.get("invocation_id", "") for f in retried],
            monthly,
            f"Investigate the failure/retry causes for {provider}/{model} "
            "(timeouts, rate limits, malformed requests) and fix the root cause "
            "before retrying; consider capped exponential backoff.",
        ))
    return findings


# ── Detector 2: model overqualification ────────────────────────────────────

async def detect_model_overqualification(
    tenant_id: str,
    facts: list[dict[str, Any]],
    registry: AIPriceCardRegistry,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        groups[(fact.get("task_type", ""), fact.get("provider", ""), fact.get("model", ""))].append(fact)

    for (task_type, provider, model), group in sorted(groups.items()):
        scored = [f for f in group if f.get("quality_score") is not None]
        if len(scored) < OVERQUALIFICATION_MIN_SAMPLES:
            continue
        if min(f["quality_score"] for f in scored) < OVERQUALIFICATION_MIN_QUALITY:
            continue

        current_card = await registry.get_active_card(
            provider, model, tenant_id=tenant_id
        )
        if current_card is None:
            continue
        cheaper_card: Optional[AIPriceCard] = None
        for record in await registry.list_cards(tenant_id=tenant_id, provider=provider):
            if record.get("model") == model:
                continue
            candidate = await registry.get_active_card(
                provider, record.get("model", ""), tenant_id=tenant_id
            )
            if candidate is None or candidate.currency != current_card.currency:
                continue
            if _card_unit_rate(candidate) >= _card_unit_rate(current_card):
                continue
            if cheaper_card is None or _card_unit_rate(candidate) < _card_unit_rate(cheaper_card):
                cheaper_card = candidate
        if cheaper_card is None:
            continue

        savings = 0.0
        for fact in group:
            current_cost = _card_cost_for_fact(fact, current_card)
            cheaper_cost = _card_cost_for_fact(fact, cheaper_card)
            if current_cost is not None and cheaper_cost is not None:
                savings += max(current_cost - cheaper_cost, 0.0)
        monthly = _extrapolate_monthly({current_card.currency: savings}, group)

        findings.append(_finding(
            "model_overqualification", tenant_id,
            f"Task '{task_type}' may be over-served by {provider}/{model}",
            f"All {len(scored)} quality-scored invocations of task '{task_type}' on "
            f"{provider}/{model} scored ≥ {OVERQUALIFICATION_MIN_QUALITY}; a cheaper card "
            f"exists for {provider}/{cheaper_card.model}.",
            [f.get("invocation_id", "") for f in group],
            monthly,
            f"Propose an offline evaluation of task '{task_type}' on "
            f"{provider}/{cheaper_card.model}; only migrate after quality parity is "
            "demonstrated. No routing change is made by this finding.",
        ))
    return findings


# ── Detector 3: deterministic replacement candidate ────────────────────────

async def detect_deterministic_replacement(
    tenant_id: str,
    facts: list[dict[str, Any]],
    registry: AIPriceCardRegistry,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        prompt_hash = fact.get("prompt_hash")
        if prompt_hash:
            groups[(fact.get("task_type", ""), prompt_hash)].append(fact)

    for (task_type, prompt_hash), group in sorted(groups.items()):
        if len(group) < DETERMINISTIC_MIN_REPEATS:
            continue
        qualities = [f.get("quality_score") for f in group]
        if any(q is None or q < DETERMINISTIC_REQUIRED_QUALITY for q in qualities):
            continue
        totals = ai_aggregation.total_cost_by_currency(group)
        repeat_share = (len(group) - 1) / len(group)
        waste = {c: amount * repeat_share for c, amount in totals.items()}
        monthly = _extrapolate_monthly(waste, group)
        findings.append(_finding(
            "deterministic_replacement_candidate", tenant_id,
            f"Task '{task_type}' repeats an identical prompt with perfect quality",
            f"Prompt hash {prompt_hash[:16]}… for task '{task_type}' ran {len(group)} times "
            "with quality 1.0 every time — the output appears deterministic.",
            [f.get("invocation_id", "") for f in group],
            monthly,
            f"Propose replacing the repeated invocation of task '{task_type}' with a "
            "cached result or deterministic code path; keep the model call as fallback.",
        ))
    return findings


# ── Detector 4: cache opportunity ──────────────────────────────────────────

async def detect_cache_opportunity(
    tenant_id: str,
    facts: list[dict[str, Any]],
    registry: AIPriceCardRegistry,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        groups[(fact.get("provider", ""), fact.get("model", ""))].append(fact)

    for (provider, model), group in sorted(groups.items()):
        utilization = ai_aggregation.cache_utilization_rate(group)
        if utilization is None or utilization >= CACHE_LOW_UTILIZATION_THRESHOLD:
            continue

        # Repeated input volume: input tokens on facts whose prompt_hash was
        # already seen in the window (occurrences beyond the first).
        seen: set[str] = set()
        repeated_facts: list[dict[str, Any]] = []
        repeated_tokens = 0.0
        for fact in sorted(group, key=lambda f: f.get("observed_at") or ""):
            prompt_hash = fact.get("prompt_hash")
            if not prompt_hash:
                continue
            if prompt_hash in seen:
                repeated_facts.append(fact)
                repeated_tokens += fact.get("input_tokens") or 0
            else:
                seen.add(prompt_hash)
        if repeated_tokens < CACHE_MIN_REPEATED_INPUT_TOKENS:
            continue

        monthly: Optional[dict[str, float]] = None
        card = await registry.get_active_card(provider, model, tenant_id=tenant_id)
        if card is not None:
            input_rate = card.rates.input_tokens_per_1k
            cached_rate = card.rates.cached_input_tokens_per_1k
            if input_rate is not None and cached_rate is not None and input_rate > cached_rate:
                saving = (repeated_tokens / 1000.0) * (input_rate - cached_rate)
                monthly = _extrapolate_monthly({card.currency: saving}, group)

        findings.append(_finding(
            "cache_opportunity", tenant_id,
            f"Low cache utilization on {provider}/{model}",
            f"{provider}/{model} re-sent ~{int(repeated_tokens)} input tokens for previously "
            f"seen prompts while cache utilization is {utilization:.0%} "
            f"(threshold {CACHE_LOW_UTILIZATION_THRESHOLD:.0%}).",
            [f.get("invocation_id", "") for f in repeated_facts],
            monthly,
            f"Propose enabling prompt caching for repeated prefixes on {provider}/{model} "
            "and restructuring prompts to keep the static prefix stable.",
        ))
    return findings


# ── Detector 5: failed workflow concentration ──────────────────────────────

async def detect_failed_workflow_concentration(
    tenant_id: str,
    facts: list[dict[str, Any]],
    registry: AIPriceCardRegistry,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def _check_group(kind: str, key: str, group: list[dict[str, Any]]) -> None:
        if len(group) < FAILURE_MIN_INVOCATIONS:
            return
        failed = [f for f in group if f.get("status") != "succeeded"]
        failure_rate = len(failed) / len(group)
        if failure_rate <= FAILURE_RATE_THRESHOLD:
            return
        failed_cost = ai_aggregation.total_cost_by_currency(failed)
        if not any(amount > 0 for amount in failed_cost.values()):
            return
        monthly = _extrapolate_monthly(failed_cost, group)
        findings.append(_finding(
            "failed_workflow_concentration", tenant_id,
            f"High failure concentration in {kind} '{key}'",
            f"{len(failed)} of {len(group)} invocations in {kind} '{key}' failed "
            f"({failure_rate:.0%} > {FAILURE_RATE_THRESHOLD:.0%}) while still incurring cost.",
            [f.get("invocation_id", "") for f in failed],
            monthly,
            f"Propose investigating the failing {kind} '{key}' (inputs, guardrails, "
            "provider errors) and gating further spend until the failure cause is fixed.",
        ))

    by_workflow: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        run_id = fact.get("workflow_run_id")
        if run_id:  # never fabricate workflow ids
            by_workflow[run_id].append(fact)
    for run_id, group in sorted(by_workflow.items()):
        _check_group("workflow", run_id, group)

    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        by_task[fact.get("task_type", "")].append(fact)
    for task_type, group in sorted(by_task.items()):
        _check_group("task_type", task_type, group)

    return findings


# ── Entry point ────────────────────────────────────────────────────────────

_DETECTORS = (
    detect_retry_waste,
    detect_model_overqualification,
    detect_deterministic_replacement,
    detect_cache_opportunity,
    detect_failed_workflow_concentration,
)


async def run_detectors(
    tenant_id: str,
    facts: Optional[list[dict[str, Any]]] = None,
    registry: Optional[AIPriceCardRegistry] = None,
) -> list[dict[str, Any]]:
    """Run all five deterministic detectors for one tenant. Proposals only."""
    if facts is None:
        facts = await ai_aggregation.list_facts(tenant_id)
    registry = registry or get_price_card_registry()
    findings: list[dict[str, Any]] = []
    for detector in _DETECTORS:
        try:
            findings.extend(await detector(tenant_id, facts, registry))
        except Exception as exc:  # detector isolation — one failure never hides the rest
            logger.error(
                "ai_efficiency detector %s failed tenant=%s: %s",
                getattr(detector, "__name__", "unknown"), tenant_id, exc,
            )
    return findings
