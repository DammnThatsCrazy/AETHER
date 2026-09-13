"""Capability reconciliation — observed inventory vs provider-reported state (PR 3).

A read-only derivation over stores that already exist (``capability_catalog``,
``capability_installations``, and the provider-evidence rows produced by
``provider_evidence.py``). Nothing here writes a row, registers an event type, or creates
a table.

Two independent surfaces live in this module:

**1. The capability reconciliation report** compares the *observed* side (what AETHER saw
an agent actually reach) against the *provider-reported* side (what the provider says
exists), producing three finding kinds:

``missing``
    The provider reports a capability/account that this tenant's catalog has never
    observed. A gap in **our** coverage, not proof of misuse.

``orphan``
    The catalog observed a capability with no corresponding provider evidence.

``mismatch``
    Both sides exist and disagree on an attribute **they both assert** — the agent
    attributed to the capability, or a provider verification that predates our newest
    observation of it.

**2. The pipeline reconciliation passthrough** (``pipeline_health`` / ``lineage``) wraps
``services.agentic_observability.reconciliation.AgenticReconciliationService``, which is
correct, tested, and — until this module — had no live caller anywhere in the product. It
is reused verbatim, never reimplemented; the only thing added at this boundary is a
disclosure of what its verdict is (and is not) derived from.

Three rules this module exists to obey, each of which this package has been bitten by:

1. **``orphan`` is not automatically alarming.** This platform's entire premise is
   inventorying capabilities nobody declared or registered, so "observed, with no provider
   evidence" is the *normal* state for most tenants. An orphan is emitted as an item only
   when the tenant actually has provider evidence *for that capability's provider* — i.e.
   when the comparison is meaningful at all. Everything else is reported as a **count**.
   Emitting a finding per unmatched observation would bury the real findings on day one,
   which is exactly the mistake ``risk_service``'s ``observed_only`` avoided.

2. **Unknown is never zero.** If provider evidence is absent entirely — no integration, a
   provider that reports nothing, or another tenant's id — the answer is UNKNOWN: every
   count is ``None`` (serialized ``null``), ``reconciliation_known`` is ``False``,
   ``missing_inputs`` names each absent input, and the summary says so. "0 mismatches"
   reads as "everything reconciles", and we are not entitled to that claim. As in
   ``risk_service``, the rule is applied strictly: if *any* required input is missing,
   *every* count is ``None``, because a partial total is still a number a reader will
   treat as complete.

3. **Every bounded read discloses truncation.** Each of the three windows below reports
   when it was hit, and a hit window makes the comparison unknown rather than letting a
   partial view be read as a complete one. The returned ``items`` list carries its own
   ``items_truncated`` flag so a page is never mistaken for the whole report.

The observed↔reported join is **exact**, on ``capability_id``: both sides derive it with
``models.capability_id_for`` over the same ``(tenant, provider, server_key, tool_name)``
tuple, so no fuzzy name matching can silently pair a provider's row with the wrong
observed capability. Evidence rows that carry no ``capability_id`` cannot be joined at
all; they are counted and disclosed in ``coverage``, never guessed into a finding.

Deliberately **not** compared: the provider's ``evidence_digest`` against the catalog's
``artifact_digest``. They are digests of different tuples computed by different parties —
comparing them would report permanent mismatch for every capability in the tenant, which
is the same fabricated-drift failure ``declarations.declared_fields`` was introduced to
fix.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

from services.agent_access_intelligence.catalog_service import (
    _clean,
    capability_catalog_service,
)
from services.agent_access_intelligence.provider_evidence import provider_evidence_service
# One ordering for both read-only risk surfaces, so `capability-risk` and
# `capability-reconciliation` can never disagree about which level is worse.
from services.agent_access_intelligence.risk_service import _risk_rank
from services.agentic_observability.models import RiskLevel
from services.agentic_observability.reconciliation import AgenticReconciliationService

logger = get_logger("aether.service.agent_access_intelligence.reconciliation")

__all__ = [
    "FINDING_KINDS",
    "MISSING",
    "MISMATCH",
    "ORPHAN",
    "CapabilityReconciliationService",
    "capability_reconciliation_service",
]

# Finding kinds. No new severity enum is introduced anywhere in this module —
# ``RiskLevel`` from the observability models is reused for every level below.
MISSING = "missing"
ORPHAN = "orphan"
MISMATCH = "mismatch"
FINDING_KINDS = (MISSING, ORPHAN, MISMATCH)

# The attributes a ``mismatch`` can be raised on. Both sides must assert the attribute
# before it is compared — you cannot diverge from an assertion nobody made.
ATTR_AGENT_ATTRIBUTION = "agent_attribution"
ATTR_VERIFICATION_STALE = "verification_status"

# Bounded read windows. Every one of them, when hit, is named in ``missing_inputs`` and
# makes the comparison unknown, rather than silently answering from a partial view.
_CATALOG_SCAN_LIMIT = 1000
_INSTALLATION_SCAN_LIMIT = 1000
_EVIDENCE_SCAN_LIMIT = 1000

_COUNT_KEYS = (
    "missing",
    "orphan",
    "mismatch",
    "total",
    "observed_without_evidence",
    "orphan_not_comparable",
)

_COVERAGE_COUNT_KEYS = (
    "capabilities_examined",
    "evidence_examined",
    "capabilities_matched",
    "evidence_unjoinable",
)


class CapabilityReconciliationService:
    """Observed-vs-reported reconciliation, plus the pipeline reconciliation passthrough."""

    def __init__(self, pipeline: Optional[AgenticReconciliationService] = None) -> None:
        # Reused, not reimplemented. This service is the first live caller it has ever had.
        self._pipeline = pipeline or AgenticReconciliationService()

    # ------------------------------------------------------------------
    # The missing / orphan / mismatch report
    # ------------------------------------------------------------------

    async def report(
        self,
        tenant_id: str,
        *,
        provider_id: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        provider_id = _clean(provider_id)
        wanted_kind = (kind or "").strip().lower() or None
        filters = {"provider_id": provider_id, "kind": wanted_kind}
        missing_inputs: list[str] = []

        evidence = list(
            await provider_evidence_service.list(
                tenant_id=tenant_id, provider_id=provider_id, limit=_EVIDENCE_SCAN_LIMIT
            )
            or []
        )
        if not evidence:
            # THE case this surface exists for. With nothing reported, there is nothing to
            # reconcile *against* — the answer is unknown, not "everything reconciles".
            # A cross-tenant id lands here too, identically to an absent one, so the report
            # is not an existence oracle for another tenant's evidence.
            scope = f"provider_id={provider_id}" if provider_id else f"tenant_id={tenant_id}"
            return self._unknown(
                missing=[f"provider_evidence:none_for_{scope}"],
                limit=limit,
                filters=filters,
            )
        if len(evidence) >= _EVIDENCE_SCAN_LIMIT:
            missing_inputs.append("provider_evidence:scan_truncated")

        catalog = await capability_catalog_service.list_capabilities(
            tenant_id, provider=provider_id, limit=_CATALOG_SCAN_LIMIT
        )
        if len(catalog) >= _CATALOG_SCAN_LIMIT:
            missing_inputs.append("capability_catalog:scan_truncated")

        installations = await capability_catalog_service.list_installations(
            tenant_id, limit=_INSTALLATION_SCAN_LIMIT
        )
        if len(installations) >= _INSTALLATION_SCAN_LIMIT:
            # Attribution is compared against the agents these rows record. A truncated
            # window would make an agent we *did* observe look like one we never saw, and
            # every such capability would report a fabricated attribution mismatch.
            missing_inputs.append("capability_installations:scan_truncated")

        observed_by_id: dict[str, dict[str, Any]] = {
            str(row["capability_id"]): row for row in catalog if row.get("capability_id")
        }
        observed_agents: dict[str, set[str]] = {}
        for installation in installations:
            agent_id = _clean(installation.get("agent_id"))
            if not agent_id:
                continue
            for cid in installation.get("capability_ids") or []:
                observed_agents.setdefault(str(cid), set()).add(agent_id)

        reported_by_id: dict[str, list[dict[str, Any]]] = {}
        providers_with_evidence: set[str] = set()
        unjoinable = 0
        for row in evidence:
            reported_provider = _clean(row.get("provider_id"))
            if reported_provider:
                providers_with_evidence.add(reported_provider)
            cid = _clean(row.get("capability_id"))
            if not cid:
                # Not joinable on the one key both sides derive identically. Counted and
                # disclosed; never guessed onto a capability by name.
                unjoinable += 1
                continue
            reported_by_id.setdefault(cid, []).append(row)

        items: list[dict[str, Any]] = []
        matched = 0
        for cid, rows in reported_by_id.items():
            observed = observed_by_id.get(cid)
            if observed is None:
                items.append(self._missing_item(cid, rows[0]))
                continue
            matched += 1
            for row in rows:
                items.extend(
                    self._mismatch_items(cid, observed, row, observed_agents.get(cid) or set())
                )

        observed_without_evidence = 0
        orphan_not_comparable = 0
        for cid, observed in observed_by_id.items():
            if cid in reported_by_id:
                continue
            observed_without_evidence += 1
            provider = _clean(observed.get("provider"))
            if provider and provider in providers_with_evidence:
                # The provider does report to us, and did not report this one — the
                # comparison is meaningful, so this is a finding.
                items.append(self._orphan_item(cid, observed, provider))
            else:
                # Nothing to compare against. Counted, never emitted: see rule 1 in the
                # module docstring.
                orphan_not_comparable += 1

        items.sort(
            key=lambda i: (
                _risk_rank(i.get("risk_level")),
                str(i.get("kind") or ""),
                str(i.get("capability_id") or ""),
                str(i.get("attribute") or ""),
            )
        )

        # Counts describe the WHOLE comparison, never the filtered page: filtering to one
        # kind must not make the other two read as zero.
        counts = {
            "missing": sum(1 for i in items if i["kind"] == MISSING),
            "orphan": sum(1 for i in items if i["kind"] == ORPHAN),
            "mismatch": sum(1 for i in items if i["kind"] == MISMATCH),
            "total": len(items),
            "observed_without_evidence": observed_without_evidence,
            "orphan_not_comparable": orphan_not_comparable,
        }

        shown = [i for i in items if not wanted_kind or i["kind"] == wanted_kind]
        page = shown[:limit]
        items_truncated = len(shown) > limit

        coverage = {
            "capabilities_examined": len(observed_by_id),
            "evidence_examined": len(evidence),
            "capabilities_matched": matched,
            "evidence_unjoinable": unjoinable,
            "providers_with_evidence": sorted(providers_with_evidence),
            "catalog_scan_limit": _CATALOG_SCAN_LIMIT,
            "installation_scan_limit": _INSTALLATION_SCAN_LIMIT,
            "evidence_scan_limit": _EVIDENCE_SCAN_LIMIT,
            "complete": not (missing_inputs or unjoinable or items_truncated),
        }

        if missing_inputs:
            return self._unknown(
                missing=missing_inputs,
                limit=limit,
                filters=filters,
                items=page,
                items_truncated=items_truncated,
                providers_with_evidence=sorted(providers_with_evidence),
            )

        return {
            "reconciliation_known": True,
            "missing_inputs": [],
            "basis": "observed_vs_provider_reported",
            "counts": counts,
            "items": page,
            # Rule 3: a page is never presented as the whole report.
            "items_truncated": items_truncated,
            "limit": limit,
            "filter": filters,
            "coverage": coverage,
            "summary": self._summary(counts, coverage),
        }

    # ------------------------------------------------------------------
    # Finding constructors
    # ------------------------------------------------------------------

    @staticmethod
    def _missing_item(capability_id: str, row: dict[str, Any]) -> dict[str, Any]:
        provider = _clean(row.get("provider_id"))
        account = _clean(row.get("external_account_id"))
        return {
            "kind": MISSING,
            # A coverage gap on OUR side, not evidence of misuse: the provider says this
            # exists and we have never seen it. Worth investigating, not worth paging.
            "risk_level": RiskLevel.MEDIUM.value,
            "capability_id": capability_id,
            "provider_id": provider,
            "external_account_id": account,
            "agent_id": _clean(row.get("agent_id")),
            "source": "provider_evidence",
            "summary": (
                f"Provider {provider or 'unknown'} reports capability {capability_id}"
                + (f" (account {account})" if account else "")
                + ", which this tenant's catalog has never observed."
            ),
            "evidence": (
                f"verification_status={_clean(row.get('verification_status')) or 'none'} "
                f"verified_at={_clean(row.get('verified_at')) or 'none'} "
                f"evidence_digest={_clean(row.get('evidence_digest')) or 'none'}"
            ),
        }

    @staticmethod
    def _orphan_item(
        capability_id: str, observed: dict[str, Any], provider: str
    ) -> dict[str, Any]:
        return {
            "kind": ORPHAN,
            # LOW on purpose. Observing a capability nobody registered is this platform's
            # normal output; it is only reported at all because this provider does report
            # to us and did not report this one.
            "risk_level": RiskLevel.LOW.value,
            "capability_id": capability_id,
            "provider_id": provider,
            "external_account_id": None,
            "agent_id": None,
            "source": "capability_catalog",
            "summary": (
                f"Capability {capability_id} was observed, but provider {provider} — which "
                "does report evidence for this tenant — reports nothing for it."
            ),
            "evidence": (
                f"tool_name={observed.get('tool_name') or 'none'} "
                f"server={observed.get('server_name') or observed.get('server_url') or 'none'} "
                f"last_seen_at={observed.get('last_seen_at') or 'none'}"
            ),
        }

    @staticmethod
    def _mismatch_items(
        capability_id: str,
        observed: dict[str, Any],
        row: dict[str, Any],
        observed_agent_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Disagreements on attributes **both** sides assert.

        Every comparison below is guarded on both values being present. An absent value is
        not a disagreement: comparing against a side that asserted nothing is how
        ``declarations`` came to report permanent drift for capabilities that had never
        changed, and it is not repeated here."""
        provider = _clean(row.get("provider_id")) or _clean(observed.get("provider"))
        out: list[dict[str, Any]] = []

        reported_agent = _clean(row.get("agent_id"))
        if reported_agent and observed_agent_ids and reported_agent not in observed_agent_ids:
            out.append({
                "kind": MISMATCH,
                "attribute": ATTR_AGENT_ATTRIBUTION,
                # Two sources of truth disagree about WHO holds this access. That is the
                # strongest signal this surface can produce.
                "risk_level": RiskLevel.HIGH.value,
                "capability_id": capability_id,
                "provider_id": provider,
                "external_account_id": _clean(row.get("external_account_id")),
                "agent_id": reported_agent,
                "source": "both",
                "reported": reported_agent,
                "observed": sorted(observed_agent_ids),
                "summary": (
                    f"Provider {provider or 'unknown'} attributes capability "
                    f"{capability_id} to agent {reported_agent}, which was never observed "
                    f"reaching it (observed: {', '.join(sorted(observed_agent_ids))})."
                ),
                "evidence": (
                    f"reported_agent_id={reported_agent} "
                    f"observed_agent_ids={','.join(sorted(observed_agent_ids))}"
                ),
            })

        verified_at = _clean(row.get("verified_at"))
        last_seen_at = _clean(observed.get("last_seen_at"))
        # Lexicographic ISO-8601 comparison, exactly as `catalog_service._max_ts` orders
        # the timestamps this reads.
        if verified_at and last_seen_at and verified_at < last_seen_at:
            status = _clean(row.get("verification_status")) or "unknown"
            out.append({
                "kind": MISMATCH,
                "attribute": ATTR_VERIFICATION_STALE,
                "risk_level": RiskLevel.MEDIUM.value,
                "capability_id": capability_id,
                "provider_id": provider,
                "external_account_id": _clean(row.get("external_account_id")),
                "agent_id": reported_agent,
                "source": "both",
                "reported": f"{status}@{verified_at}",
                "observed": last_seen_at,
                "summary": (
                    f"Provider verification of capability {capability_id} "
                    f"({status}) is dated {verified_at}, before it was last observed in "
                    f"use at {last_seen_at} — the provider's state predates our newest "
                    "observation."
                ),
                "evidence": f"verified_at={verified_at} last_seen_at={last_seen_at}",
            })
        return out

    # ------------------------------------------------------------------
    # Summaries + the unknown response
    # ------------------------------------------------------------------

    @staticmethod
    def _summary(counts: dict[str, Any], coverage: dict[str, Any]) -> str:
        text = (
            f"Reconciled {coverage['capabilities_examined']} observed capability(ies) "
            f"against {coverage['evidence_examined']} provider evidence row(s): "
            f"{counts['missing']} missing, {counts['orphan']} orphan, "
            f"{counts['mismatch']} mismatch. "
            f"{counts['orphan_not_comparable']} observed capability(ies) have no provider "
            "evidence for their provider at all; those are counted, not reported as "
            "findings — observing capabilities nobody registered is this platform's normal "
            "output, not a defect."
        )
        if coverage["evidence_unjoinable"]:
            text += (
                f" {coverage['evidence_unjoinable']} evidence row(s) carried no "
                "capability_id and could not be compared."
            )
        if not coverage["capabilities_matched"] and coverage["capabilities_examined"]:
            text += (
                " No observed capability matched any evidence row; if that is unexpected, "
                "the two sides may not be deriving capability_id over the same tuple."
            )
        return text + (
            " This compares what was observed against what the provider reported; it is a "
            "proof of neither side's completeness."
        )

    @staticmethod
    def _unknown(
        *,
        missing: list[str],
        limit: int,
        filters: dict[str, Any],
        items: Optional[list[dict[str, Any]]] = None,
        items_truncated: bool = False,
        providers_with_evidence: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Every count ``None``; whatever we did observe kept as a labelled list.

        The lists are evidence, not totals — nothing in this response claims they are
        complete. Emitting ``0`` for any count here would assert that the two sides agree,
        which is precisely the claim no input supports."""
        deduped: list[str] = []
        for entry in missing:
            if entry not in deduped:
                deduped.append(entry)
        return {
            "reconciliation_known": False,
            "missing_inputs": deduped,
            "basis": "observed_vs_provider_reported",
            "counts": {key: None for key in _COUNT_KEYS},
            "items": list(items or []),
            "items_truncated": items_truncated,
            "limit": limit,
            "filter": dict(filters),
            "coverage": {
                # Null, not zero: "we examined 0" and "we could not complete the
                # comparison" are different statements, and only the second is true.
                **{key: None for key in _COVERAGE_COUNT_KEYS},
                "providers_with_evidence": list(providers_with_evidence or []),
                "catalog_scan_limit": _CATALOG_SCAN_LIMIT,
                "installation_scan_limit": _INSTALLATION_SCAN_LIMIT,
                "evidence_scan_limit": _EVIDENCE_SCAN_LIMIT,
                "complete": False,
            },
            "summary": (
                "Reconciliation for this tenant is UNKNOWN, not zero. Required input(s) "
                f"absent or truncated: {', '.join(deduped)}. Every count is null because "
                "it could not be computed — do not read this as everything reconciling."
            ),
        }

    # ------------------------------------------------------------------
    # Pipeline reconciliation passthrough (AgenticReconciliationService)
    # ------------------------------------------------------------------

    async def pipeline_health(self, tenant_id: str) -> dict[str, Any]:
        """The agentic pipeline's own health counters, wrapped verbatim.

        The wrapped payload is passed through untouched under ``pipeline``; the disclosure
        is added at THIS boundary rather than by editing a peer module. It matters:
        ``health`` is derived from counts alone, so a tenant with no rows in those tables
        reads ``healthy`` — which is a statement about the absence of failures, not about
        the presence of a working pipeline."""
        health = await self._pipeline.pipeline_health(tenant_id)
        return {
            "pipeline": dict(health),
            "verdict_basis": (
                "health is derived from failure counters only (dead-lettered and failed "
                "outbox rows). Zero counts across the board mean nothing has been recorded "
                "in these tables for this tenant — that is not the same as a healthy "
                "pipeline, and this endpoint does not claim it is."
            ),
        }

    async def lineage(self, tenant_id: str, source_event_id: str) -> dict[str, Any]:
        """End-to-end lineage for one source event, wrapped verbatim.

        ``AgenticLineageResult.as_dict()`` is returned untouched under ``lineage``. Its
        record counts come from bounded reads inside that service, so they describe what
        was read, not necessarily everything that exists."""
        result = await self._pipeline.lineage(tenant_id, source_event_id)
        return {
            "lineage": result.as_dict(),
            "verdict_basis": (
                "counts are of records read through bounded per-tier windows; a gap means "
                "nothing was found in that tier within the window, not that nothing exists."
            ),
        }


capability_reconciliation_service = CapabilityReconciliationService()
