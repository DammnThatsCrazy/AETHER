"""Agent Access Intelligence — capability alerting + bounded dataset export (PR 4).

Two read-only derivations layered on top of ``risk_service``. Nothing here writes a
tenant row, registers an event type, or creates a table: ``evaluate`` re-reads findings
the risk lane already computes, and ``export`` re-reads findings / blast radius / catalog
through the same services. **No new store and no migration.**

Rules are a *default*, not a policy
-----------------------------------
``services/security/policy_engine.py`` deliberately does not block ``capability.invoke``
on risk level, and records why in-code: no policy source in this repo defines a blocking
threshold, and inventing one produces a fabricated control operators would believe is
enforced. The same reasoning binds this module. So:

* every rule is a declarative record (:class:`AlertRule`), not a constant buried in a
  comparison;
* the **whole rule set travels in every response**, including the rules that did not
  fire, with ``is_default: true`` and a disclaimer naming it as an Aether starting point;
* a fired alert carries its threshold *and* the observed value side by side, so an
  operator can see the arithmetic rather than trust the verdict;
* nothing here blocks, denies, revokes or notifies. ``evaluate`` produces a report.

Unknown is never zero
---------------------
The single rule this package exists to protect, inherited verbatim from ``risk_service``.
A threshold is a two-sided claim: "observed 3, threshold 5, no alert" is only true if we
saw everything. When an input was truncated or unavailable we can still *fire* a rule —
a count over a partial window is a valid lower bound, and ``observed >= threshold`` stays
true when more rows exist — but we can never *clear* one. A rule that did not fire over a
partial window lands in ``undecidable_rules``, ``alerts_known`` goes ``false``, and every
count in ``counts`` becomes ``null``. "0 alerts" reads as all-clear, and we are not
entitled to say it.

Alerts that did fire are still reported when the answer is incomplete: withholding a real
alert because some *other* input truncated would hide the thing the surface exists to
show. Incompleteness suppresses the totals, not the evidence.

``observed_only`` never alerts
------------------------------
``risk_service`` deliberately does not emit a finding for an undeclared capability — this
platform's premise is inventorying capabilities nobody declared, so "undeclared" is the
normal state of a healthy tenant. Alerting on it would bury the real findings on day one.
:data:`NON_ALERTABLE_FINDING_CODES` makes that structural: a rule naming one of those
codes fails at import.

Reuse, not a parallel pipeline
------------------------------
* Severity vocabulary is ``agentic_observability.models.RiskLevel``. No second enum.
* Agentic corroboration is read through the Noesis
  ``AgenticIntelligenceAdapter`` — the repo's read-only, evidence-classified query
  surface over the observability stores — rather than by reaching into
  ``obs_agent_risk_signals`` directly. Going through the adapter means every statement
  arrives already tagged with an evidence classification and its source tables, which is
  exactly what an alert payload needs so a reader can tell an observed fact from an
  inference. The adapter is a *rule input*: ``observed_agent_risk_signals`` cannot be
  evaluated without it.
* Durable exports go through the canonical export service
  (``services/export/service.py``) by registering an exporter in its ``EXPORTERS``
  registry, so ``POST /v1/exports`` can produce a checksum-verified artifact of these
  datasets. The inline ``export()`` below is the bounded read-now path that the export
  service's own docstring keeps available on originating routes; it is not a second
  export pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from shared.common.common import BadRequestError
from shared.logger.logger import get_logger

from services.agent_access_intelligence.catalog_service import capability_catalog_service
from services.agent_access_intelligence.risk_service import (
    IDENTITY_DRIFT_CODE,
    capability_risk_service,
)
from services.agentic_observability.models import RiskLevel
from services.noesis.adapters.agentic_intelligence_adapter import (
    AgenticIntelligenceAdapter,
)

logger = get_logger("aether.service.agent_access_intelligence.alerts")

__all__ = [
    "AGENTIC_RISK_SIGNAL_CODE",
    "AGENTIC_RISK_SIGNAL_INTENT",
    "DEFAULT_RULES",
    "EXPORT_DATASETS",
    "NON_ALERTABLE_FINDING_CODES",
    "RULE_SET_ID",
    "SOURCE_AGENTIC_SIGNALS",
    "SOURCE_FINDINGS",
    "AlertRule",
    "CapabilityAlertService",
    "capability_alert_service",
]


# ── vocabulary ────────────────────────────────────────────────────────────────

SOURCE_FINDINGS = "capability_findings"
SOURCE_AGENTIC_SIGNALS = "agentic_risk_signals"
_SOURCES = (SOURCE_FINDINGS, SOURCE_AGENTIC_SIGNALS)

# The Noesis intent that answers "what permission risk has been observed for this
# tenant?". Named here so the rule set states which query produced its input.
AGENTIC_RISK_SIGNAL_INTENT = "permission_risk_lookup"
# The signal kind that intent returns. Not a `scanning.FindingCode` — it comes from the
# observability plane, not from inspecting a capability record, and the two vocabularies
# must stay separable in a response.
AGENTIC_RISK_SIGNAL_CODE = "agent_risk_signal"

# Codes a rule may never name. `observed_only` is a *state*, reported as a count by
# ``risk_service`` and deliberately never as a finding — see module docstring.
NON_ALERTABLE_FINDING_CODES = frozenset({"observed_only"})

RULE_SET_ID = "aether_default_v1"

# Severity ranks derived from RiskLevel — the platform's one severity vocabulary.
# Lower rank = more severe. An unrecognized level ranks below everything and therefore
# never satisfies a `min_risk_level` threshold; its presence is disclosed instead.
_RISK_ORDER = {
    RiskLevel.CRITICAL.value: 0,
    RiskLevel.HIGH.value: 1,
    RiskLevel.MEDIUM.value: 2,
    RiskLevel.LOW.value: 3,
}
_UNRANKED = 99

# Evidence attached to one alert is capped; the cap is disclosed per alert.
_EVIDENCE_LIMIT = 25

EXPORT_DATASETS = ("findings", "blast_radius", "catalog")
# Blast radius is computed per subject, so an export of it is bounded by subject count as
# well as by `limit`. Both bounds are disclosed when hit.
_BLAST_RADIUS_SUBJECT_LIMIT = 50

# Export type registered with the canonical export service for the durable,
# checksum-verified artifact path.
DURABLE_EXPORT_TYPE = "capability_access_intelligence"


def _risk_rank(level: Any) -> int:
    return _RISK_ORDER.get(str(getattr(level, "value", level) or "").strip().lower(), _UNRANKED)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── rules ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AlertRule:
    """A declarative threshold over (source, finding code, risk level, count).

    Every field appears in the API response. There is no hidden constant: an operator
    reading a fired alert can see the code it matched, the severity floor it applied, the
    count it required, and the count actually observed.
    """

    rule_id: str
    source: str
    # None = any code from this source.
    code: Optional[str]
    # Matches findings at this severity **or above**, using RiskLevel's ordering.
    min_risk_level: str
    # Fires at this many matches or more. Always >= 1: a rule that fires on zero matches
    # would fire on an empty tenant, which is noise, not a signal.
    min_count: int
    # Severity of the alert itself. Also a RiskLevel value — no second enum.
    severity: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "source": self.source,
            "code": self.code,
            "min_risk_level": self.min_risk_level,
            "min_count": self.min_count,
            "severity": self.severity,
            "description": self.description,
        }

    def matches(self, code: Any, risk_level: Any) -> bool:
        if self.code is not None and str(code or "").strip().lower() != self.code:
            return False
        return _risk_rank(risk_level) <= _risk_rank(self.min_risk_level)


DEFAULT_RULES: tuple[AlertRule, ...] = (
    AlertRule(
        rule_id="identity_drift_observed",
        source=SOURCE_FINDINGS,
        code=IDENTITY_DRIFT_CODE,
        min_risk_level=RiskLevel.HIGH.value,
        min_count=1,
        severity=RiskLevel.HIGH.value,
        description=(
            "A capability the tenant declared no longer matches what was observed. A "
            "declaration is the one place the tenant stated an expectation, so a single "
            "divergence is worth surfacing."
        ),
    ),
    AlertRule(
        rule_id="credential_in_server_url",
        source=SOURCE_FINDINGS,
        code="credential_in_url",
        min_risk_level=RiskLevel.HIGH.value,
        min_count=1,
        severity=RiskLevel.CRITICAL.value,
        description=(
            "A credential was observed embedded in a capability server URL. One is "
            "enough — the secret is already in whatever logs recorded the URL."
        ),
    ),
    AlertRule(
        rule_id="high_risk_finding_volume",
        source=SOURCE_FINDINGS,
        code=None,
        min_risk_level=RiskLevel.HIGH.value,
        min_count=5,
        severity=RiskLevel.MEDIUM.value,
        description=(
            "A volume threshold over high-and-above findings of any code. Five is an "
            "Aether default chosen to be visibly arbitrary, not a policy: no source in "
            "this repo defines a blocking count. Tune it to your inventory."
        ),
    ),
    AlertRule(
        rule_id="observed_agent_risk_signals",
        source=SOURCE_AGENTIC_SIGNALS,
        code=AGENTIC_RISK_SIGNAL_CODE,
        min_risk_level=RiskLevel.HIGH.value,
        min_count=1,
        severity=RiskLevel.HIGH.value,
        description=(
            "The agentic observability plane recorded a high-or-above permission risk "
            "signal. Read through the Noesis agentic intelligence adapter "
            f"(intent {AGENTIC_RISK_SIGNAL_INTENT!r}) so each corroborating statement "
            "carries its evidence classification and source tables."
        ),
    ),
)

_RULE_SET_DISCLAIMER = (
    "These are Aether DEFAULT alert rules, not a policy this platform enforces. No "
    "policy source in this repo defines a blocking risk threshold, so nothing here "
    "blocks, denies or revokes anything — evaluate() produces a report. Every rule, "
    "fired or not, travels in this response with its threshold so the arithmetic is "
    "visible and the numbers can be argued with."
)


def _validate_rules(rules: tuple[AlertRule, ...]) -> None:
    """Reject a malformed or non-alertable rule at import, not at request time."""
    seen: set[str] = set()
    for rule in rules:
        if rule.rule_id in seen:
            raise ValueError(f"duplicate alert rule_id {rule.rule_id!r}")
        seen.add(rule.rule_id)
        if rule.source not in _SOURCES:
            raise ValueError(f"rule {rule.rule_id!r}: unknown source {rule.source!r}")
        if rule.code is not None and rule.code in NON_ALERTABLE_FINDING_CODES:
            raise ValueError(
                f"rule {rule.rule_id!r}: {rule.code!r} is not alertable. An undeclared "
                "capability is the normal state of a tenant this platform is built to "
                "inventory; alerting on it buries every real finding."
            )
        if _risk_rank(rule.min_risk_level) == _UNRANKED:
            raise ValueError(
                f"rule {rule.rule_id!r}: min_risk_level {rule.min_risk_level!r} is not a "
                f"RiskLevel value"
            )
        if _risk_rank(rule.severity) == _UNRANKED:
            raise ValueError(
                f"rule {rule.rule_id!r}: severity {rule.severity!r} is not a RiskLevel value"
            )
        if rule.min_count < 1:
            raise ValueError(f"rule {rule.rule_id!r}: min_count must be >= 1")


_validate_rules(DEFAULT_RULES)


# ── service ───────────────────────────────────────────────────────────────────


class CapabilityAlertService:
    """Rule evaluation over access-intelligence findings, and bounded dataset export."""

    def __init__(self, rules: tuple[AlertRule, ...] = DEFAULT_RULES) -> None:
        _validate_rules(rules)
        self._rules = rules
        # One adapter instance, like every other module-level service singleton here.
        # Its repositories bind their in-memory table dicts at construction, and
        # ``reset_in_memory_stores`` clears those dicts in place, so the singleton stays
        # correct across test resets.
        self._agentic = AgenticIntelligenceAdapter()

    # ------------------------------------------------------------------
    # Evaluate
    # ------------------------------------------------------------------

    async def evaluate(self, tenant_id: str, *, limit: int = 500) -> dict[str, Any]:
        """Apply the rule set to the tenant's current access-intelligence state.

        ``limit`` bounds every read this makes. Hitting it does not fail the request: a
        rule that fires over a partial window is still true (its count is a lower bound),
        while a rule that does *not* fire becomes undecidable and is reported as such.
        """
        if limit < 1:
            raise BadRequestError("limit must be >= 1")

        findings_ctx = await self._findings_input(tenant_id, limit=limit)
        agentic_ctx = await self._agentic_input(tenant_id, limit=limit)
        contexts = {
            SOURCE_FINDINGS: findings_ctx,
            SOURCE_AGENTIC_SIGNALS: agentic_ctx,
        }

        alerts: list[dict[str, Any]] = []
        undecidable: list[dict[str, Any]] = []
        for rule in self._rules:
            ctx = contexts[rule.source]
            if not ctx["available"]:
                undecidable.append({
                    "rule_id": rule.rule_id,
                    "source": rule.source,
                    "reason": ctx["reason"],
                })
                continue
            matched = [
                item for item in ctx["items"]
                if rule.matches(ctx["code_of"](item), ctx["risk_of"](item))
            ]
            observed = len(matched)
            if observed >= rule.min_count:
                alerts.append(self._alert(rule, matched, ctx))
            elif not ctx["complete"]:
                # Cannot clear a threshold over a window we know was cut short.
                undecidable.append({
                    "rule_id": rule.rule_id,
                    "source": rule.source,
                    "reason": (
                        f"threshold not met over an incomplete window ({ctx['reason']}); "
                        "a count that could not be completed cannot clear a rule"
                    ),
                })

        missing_inputs: list[str] = []
        for ctx in contexts.values():
            for entry in ctx["missing_inputs"]:
                if entry not in missing_inputs:
                    missing_inputs.append(entry)

        alerts.sort(key=lambda a: (_risk_rank(a["severity"]), a["rule_id"]))
        known = not undecidable

        if known:
            counts: dict[str, Optional[int]] = {
                "rules_evaluated": len(self._rules),
                "alerts_triggered": len(alerts),
                "findings_examined": len(findings_ctx["items"]),
                "agentic_signals_examined": len(agentic_ctx["items"]),
            }
            summary = (
                f"{len(alerts)} alert(s) triggered from {len(self._rules)} default rule(s) "
                f"for tenant {tenant_id}. Every rule was decidable over a complete window. "
                "These thresholds are Aether defaults, not an enforced control."
            )
        else:
            # Every count null, exactly as risk_service does: a partial total is still a
            # number a reader treats as complete.
            counts = {
                "rules_evaluated": None,
                "alerts_triggered": None,
                "findings_examined": None,
                "agentic_signals_examined": None,
            }
            undecided = ", ".join(entry["rule_id"] for entry in undecidable)
            summary = (
                f"Alerting for tenant {tenant_id} is UNKNOWN, not zero. Rule(s) that "
                f"could not be decided: {undecided}. Every count is null because it "
                "could not be computed — do not read this as no alerts. Any alert listed "
                "below did fire and is real; the response simply cannot claim it is the "
                "complete set."
            )

        return {
            "alerts_known": known,
            "missing_inputs": missing_inputs,
            "undecidable_rules": undecidable,
            "rule_set": {
                "rule_set_id": RULE_SET_ID,
                "is_default": True,
                "disclaimer": _RULE_SET_DISCLAIMER,
                "rules": [rule.to_dict() for rule in self._rules],
            },
            "alerts": alerts,
            "counts": counts,
            "inputs": [findings_ctx["descriptor"], agentic_ctx["descriptor"]],
            "coverage": {
                "findings_available": findings_ctx["available"],
                "findings_complete": findings_ctx["complete"],
                "agentic_signals_available": agentic_ctx["available"],
                "agentic_signals_complete": agentic_ctx["complete"],
                "all_rules_decidable": known,
            },
            "limit": limit,
            "generated_at": _now(),
            "summary": summary,
        }

    def _alert(
        self, rule: AlertRule, matched: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> dict[str, Any]:
        observed = len(matched)
        evidence = matched[:_EVIDENCE_LIMIT]
        lower_bound = not ctx["complete"]
        return {
            "rule_id": rule.rule_id,
            "severity": rule.severity,
            "source": rule.source,
            # The threshold that fired, verbatim — not a restatement.
            "rule": rule.to_dict(),
            "observed": {
                "count": observed,
                "count_is_lower_bound": lower_bound,
                "matched_code": rule.code,
                "matched_at_or_above_risk_level": rule.min_risk_level,
            },
            "threshold": {
                "min_count": rule.min_count,
                "min_risk_level": rule.min_risk_level,
                "code": rule.code,
            },
            "evidence": evidence,
            "evidence_truncated": observed > len(evidence),
            "evidence_limit": _EVIDENCE_LIMIT,
            "evidence_source": ctx["evidence_source"],
            "summary": (
                f"Rule {rule.rule_id!r} fired: observed {observed} "
                f"{'or more ' if lower_bound else ''}"
                f"{rule.source} item(s) matching code="
                f"{rule.code or 'any'} at risk_level {rule.min_risk_level} or above; the "
                f"rule's threshold is {rule.min_count}. This is a reported default "
                "threshold, not an enforced control."
            ),
        }

    # ------------------------------------------------------------------
    # Rule inputs
    # ------------------------------------------------------------------

    async def _findings_input(self, tenant_id: str, *, limit: int) -> dict[str, Any]:
        """Findings from ``risk_service``, plus whether that view was complete."""
        descriptor: dict[str, Any] = {
            "input": SOURCE_FINDINGS,
            "service": "services.agent_access_intelligence.risk_service",
        }
        try:
            data = await capability_risk_service.findings(tenant_id, limit=limit)
        except Exception as exc:  # pragma: no cover — defensive; surfaced, never swallowed
            logger.warning(
                "capability findings unavailable for alerting: tenant=%s error=%s",
                tenant_id, exc,
            )
            reason = f"capability_risk_findings:unavailable:{type(exc).__name__}"
            descriptor.update({"available": False, "complete": False, "reason": reason})
            return {
                "available": False,
                "complete": False,
                "reason": reason,
                "missing_inputs": [reason],
                "items": [],
                "code_of": lambda i: None,
                "risk_of": lambda i: None,
                "evidence_source": descriptor,
                "descriptor": descriptor,
            }

        items = data.get("items") or []
        coverage = data.get("coverage") or {}
        counts = data.get("counts") or {}

        reasons: list[str] = []
        if coverage.get("catalog_truncated"):
            reasons.append("capability_catalog:scan_truncated")
        if coverage.get("declarations_truncated"):
            reasons.append("capability_declarations:scan_truncated")
        total = counts.get("total")
        if isinstance(total, int) and total > len(items):
            reasons.append("capability_risk_findings:page_truncated")
        if any(_risk_rank(item.get("risk_level")) == _UNRANKED for item in items):
            # A finding whose risk level we cannot rank cannot be compared to a floor.
            reasons.append("capability_risk_findings:unrecognized_risk_level")

        complete = not reasons
        descriptor.update({
            "available": True,
            "complete": complete,
            "reason": "; ".join(reasons) if reasons else None,
            "identity_states_are_counts_not_findings": True,
        })
        return {
            "available": True,
            "complete": complete,
            "reason": "; ".join(reasons) if reasons else None,
            "missing_inputs": reasons,
            "items": items,
            "code_of": lambda i: i.get("code"),
            "risk_of": lambda i: i.get("risk_level"),
            "evidence_source": descriptor,
            "descriptor": descriptor,
        }

    async def _agentic_input(self, tenant_id: str, *, limit: int) -> dict[str, Any]:
        """Observed permission-risk signals, read through the Noesis adapter.

        The adapter — not ``AgentRiskSignalRepository`` — is the input on purpose: it
        returns an evidence classification and the source tables alongside the rows, and
        an alert payload that cannot say how it knows something is not worth sending.
        """
        descriptor: dict[str, Any] = {
            "input": SOURCE_AGENTIC_SIGNALS,
            "adapter": "services.noesis.adapters.agentic_intelligence_adapter",
            "intent": AGENTIC_RISK_SIGNAL_INTENT,
        }
        try:
            answer = await self._agentic.answer(
                AGENTIC_RISK_SIGNAL_INTENT, tenant_id, limit=limit
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "agentic intelligence adapter unavailable for alerting: tenant=%s error=%s",
                tenant_id, exc,
            )
            reason = f"noesis_agentic_intelligence:unavailable:{type(exc).__name__}"
            descriptor.update({"available": False, "complete": False, "reason": reason})
            return {
                "available": False,
                "complete": False,
                "reason": reason,
                "missing_inputs": [reason],
                "items": [],
                "code_of": lambda i: None,
                "risk_of": lambda i: None,
                "evidence_source": descriptor,
                "descriptor": descriptor,
            }

        rows = list(answer.results or [])
        reasons: list[str] = []
        # The adapter passes `limit` straight to `find_many` and does not itself disclose
        # truncation, so the disclosure is made here.
        if len(rows) >= limit:
            reasons.append("obs_agent_risk_signals:scan_truncated")
        if answer.warnings:
            reasons.extend(f"noesis_agentic_intelligence:{w}" for w in answer.warnings)

        complete = not reasons
        descriptor.update({
            "available": True,
            "complete": complete,
            "reason": "; ".join(reasons) if reasons else None,
            # Proof-of-provenance carried through verbatim from the adapter.
            "sources": list(answer.sources or []),
            "claim_classifications": [
                claim.get("classification") for claim in (answer.claims or [])
            ],
            "warnings": list(answer.warnings or []),
        })
        evidence_source = dict(descriptor)
        # The adapter's own claims travel with a fired alert (they name counts in prose,
        # so they stay out of the always-present descriptor, where a "0 ... observed"
        # sentence would read as an all-clear in an UNKNOWN response).
        evidence_source["answer"] = answer.answer
        evidence_source["claims"] = list(answer.claims or [])
        return {
            "available": True,
            "complete": complete,
            "reason": "; ".join(reasons) if reasons else None,
            "missing_inputs": reasons,
            "items": rows,
            # Every row this intent returns is a permission risk signal; the rule's `code`
            # names that kind, and the row's own `risk_level` is the severity compared.
            "code_of": lambda i: AGENTIC_RISK_SIGNAL_CODE,
            "risk_of": lambda i: i.get("risk_level"),
            "evidence_source": evidence_source,
            "descriptor": descriptor,
        }

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    async def export(
        self, tenant_id: str, *, dataset: str, limit: int = 1000
    ) -> dict[str, Any]:
        """A bounded export of one access-intelligence dataset.

        A bounded export that hit its limit and said nothing is worse than no export: a
        consumer will treat a truncated file as the full inventory. Every response
        carries ``truncated``, the ``limit`` applied, the ``row_count`` actually
        returned, and a plain-language ``statement`` of what the file is and is not.
        """
        if limit < 1:
            raise BadRequestError("limit must be >= 1")
        key = (dataset or "").strip().lower()
        if key not in EXPORT_DATASETS:
            raise BadRequestError(
                f"Unknown dataset {dataset!r}. Valid: {list(EXPORT_DATASETS)}"
            )

        if key == "findings":
            rows, reasons = await self._export_findings(tenant_id, limit)
        elif key == "catalog":
            rows, reasons = await self._export_catalog(tenant_id, limit)
        else:
            rows, reasons = await self._export_blast_radius(tenant_id, limit)

        truncated = bool(reasons)
        if truncated:
            statement = (
                f"INCOMPLETE EXPORT. This file holds {len(rows)} {key} row(s) and stopped "
                f"short of the full dataset (limit={limit}; {', '.join(reasons)}). Do not "
                f"treat it as tenant {tenant_id}'s complete {key} inventory."
            )
        else:
            statement = (
                f"Complete within its bound: every {key} row available to tenant "
                f"{tenant_id} fitted inside the limit of {limit}; {len(rows)} row(s) "
                "returned."
            )
        return {
            "dataset": key,
            "rows": rows,
            "row_count": len(rows),
            "limit": limit,
            "truncated": truncated,
            "completeness": {
                "complete": not truncated,
                "truncated": truncated,
                "limit": limit,
                "rows_returned": len(rows),
                "reasons": reasons,
                "statement": statement,
            },
            "generated_at": _now(),
        }

    async def _export_findings(
        self, tenant_id: str, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        data = await capability_risk_service.findings(tenant_id, limit=limit)
        rows = data.get("items") or []
        coverage = data.get("coverage") or {}
        counts = data.get("counts") or {}
        reasons: list[str] = []
        total = counts.get("total")
        if isinstance(total, int) and total > len(rows):
            reasons.append(f"export_limit_reached:{len(rows)}_of_{total}_matching_findings")
        if coverage.get("catalog_truncated"):
            reasons.append("capability_catalog:scan_truncated")
        if coverage.get("declarations_truncated"):
            reasons.append("capability_declarations:scan_truncated")
        return rows, reasons

    async def _export_catalog(
        self, tenant_id: str, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        rows = await capability_catalog_service.list_capabilities(tenant_id, limit=limit)
        reasons: list[str] = []
        # A full page cannot be distinguished from a truncated one without a count query,
        # so a full page is disclosed as truncated. Over-disclosing incompleteness is the
        # safe direction; under-disclosing it hands a consumer a partial inventory that
        # claims to be whole.
        if len(rows) >= limit:
            reasons.append("export_limit_reached:page_full_at_limit")
        return rows, reasons

    async def _export_blast_radius(
        self, tenant_id: str, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        installations = await capability_catalog_service.list_installations(
            tenant_id, limit=limit
        )
        reasons: list[str] = []
        if len(installations) >= limit:
            reasons.append("capability_installations:scan_truncated")

        agent_ids = sorted({
            str(i["agent_id"]) for i in installations if i.get("agent_id")
        })
        subject_cap = min(limit, _BLAST_RADIUS_SUBJECT_LIMIT)
        subjects = agent_ids[:subject_cap]
        if len(agent_ids) > len(subjects):
            reasons.append(
                f"blast_radius_subject_limit_reached:{len(subjects)}_of_{len(agent_ids)}_agents"
            )
        # Each row is `risk_service.blast_radius` verbatim, so its own unknown-not-zero
        # disclosure (exposure_known / missing_inputs / null counts) survives the export.
        rows = [
            await capability_risk_service.blast_radius(tenant_id, agent_id=agent_id)
            for agent_id in subjects
        ]
        return rows, reasons


capability_alert_service = CapabilityAlertService()


# ── durable export path (canonical export service) ───────────────────────────


def _register_durable_exporter() -> None:
    """Register these datasets with ``services/export/service.py``.

    Registered on import (the module is imported by ``alert_routes``, which main mounts)
    so the durable path is reachable rather than dead. Guarded rather than decorated:
    ``@register_exporter`` raises on a repeat registration, and this suite churns module
    identities, so the idempotent-membership-check form used by
    ``register_export_handlers`` is the safe one.

    Completeness survives into the artifact manifest: ``params`` (dataset + limit) is
    echoed, ``row_count`` is recorded, and ``per_source`` carries an explicit
    ``truncated_at_limit`` entry that is present only when the export was cut short.
    """
    try:
        from services.export.service import EXPORTERS, ExportPayload
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(f"durable capability export registration skipped: {exc}")
        return
    if DURABLE_EXPORT_TYPE in EXPORTERS:
        return

    async def _exporter(tenant_id: str, params: dict) -> Any:
        dataset = (params or {}).get("dataset", "findings")
        limit = int((params or {}).get("limit", 1000))
        result = await capability_alert_service.export(
            tenant_id, dataset=dataset, limit=limit
        )
        per_source: dict[str, int] = {f"capability_{result['dataset']}": result["row_count"]}
        if result["truncated"]:
            per_source["truncated_at_limit"] = result["limit"]
        return ExportPayload(rows=result["rows"], per_source=per_source)

    EXPORTERS[DURABLE_EXPORT_TYPE] = _exporter


_register_durable_exporter()
