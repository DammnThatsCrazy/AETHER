"""Economic360 intelligence-projection provider (vertical slice S3).

Economic360 is an intelligence projection over canonical Aether truth — never a
competing system of record (ADR-010). This provider projects the *economic*
domain for a subject (campaign / episode / source) from canonical economic
facts: AI execution economics (``services/api/value/economic/ai_*``), computed campaign
economics (``services/api/value/economic/computed_results`` +
``services/api/intelligence/computation/campaign``), value normalization / safe rollups
(``services/api/value/value``) and value diagnostics (``services/api/value/economic/value_diagnostics``).

The provider is a read-only, fail-isolated, tenant-scoped projection:

* It raises ONLY :class:`ProjectionError` subclasses on failure; the registry
  fail-isolates any other exception.
* It degrades sections (typed ``degraded`` / ``missing`` / ``empty`` states)
  instead of crashing or fabricating when a canonical source is unavailable.
* Every claim carries a reused canonical :class:`EvidenceRef`.
* Mixed-currency / missing-price / double-count situations produce the typed
  :class:`EconomicWarning` codes — never an invented USD figure.
* ``profile360`` / ``relationship360`` / ``outcome360`` are still ``in_flight``:
  the registry's ``build_context`` records them in ``dependencyState`` and this
  provider degrades the ``outcomes`` section honestly instead of raising.

Imports stay lazy/defensive: importing this module must never require a
database, a store backend, or any heavy canonical service. All canonical reads
happen inside :meth:`Economic360Provider.project` (and the injected source
reader), each wrapped so an unavailable backing source degrades its section.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Protocol

# Lightweight plane imports — always importable.
from shared.intelligence_projections.contracts import (
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ClaimEnvelope,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import ProjectionError
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry

# Reused canonical primitives (never redefined here).
from graph.operational_intelligence.models import EvidenceRef

# Economic domain contracts for this slice.
from value.economic.economic360_contracts import (
    EconomicWarning,
    EconomicWarningCode,
    MonetaryAmount,
    detect_double_count,
    economic_warnings_for_amounts,
    safe_usd_total,
)

# Sections the registry declares for economic360 (must match outputSections).
OUTPUT_SECTIONS: tuple[str, ...] = ("summary", "state", "evidence", "outcomes", "findings")

# Registry projection dependencies we degrade for honestly while they are
# still in_flight (profile360 / relationship360 / outcome360). Each entry maps
# the section whose enrichment depends on that sibling projection.
SECTION_DEPENDENCIES: dict[str, str] = {
    "summary": "profile360",
    "state": "relationship360",
    "outcomes": "outcome360",
}

AI_EXECUTION_FACTS_SUBJECT_SCOPE_UNAVAILABLE = (
    "ai_execution_facts_subject_scope_unavailable"
)
AI_EXECUTION_FACTS_SCOPE_READ_FAILED = "ai_execution_facts_scope_read_failed"
EPISODE_COMMERCE_ORDER_SCOPE_UNAVAILABLE = (
    "episode_commerce_order_reference_scope_unavailable"
)


def _dependency_missing(dep_state: list[Any], projection_id: str) -> bool:
    """True when a sibling projection is missing or not yet available."""
    dep = next((d for d in dep_state if d.projectionId == projection_id), None)
    return dep is None or dep.state != "available"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EconomicSourceReader(Protocol):
    """Canonical economic read seam for the provider.

    Implementations MUST be tenant-scoped: the provider trusts nothing and
    re-filters every returned record by the requesting tenant. A reader that
    cannot reach its backing store returns ``[]`` (the provider degrades the
    affected sections) — never raises, never fabricates.
    """

    async def records(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        """Canonical economic value records for the tenant + subject.

        Each record is a raw value-record shape consumed by
        ``services/api/value/value``'s ``value_of`` / ``safe_rollup`` (native ``amount`` /
        ``currency``, optional ``value_usd``, optional ``metric_kind``) plus
        ``tenant_id`` and ``_source`` / ``_evidence_*`` bookkeeping.
        """
        ...


class AgentIdentityReader(Protocol):
    """Tenant-scoped authority for validating an Agent 360 subject."""

    async def is_canonical_agent(self, tenant_id: str, agent_id: str) -> Optional[bool]:
        """True for a canonical tenant Agent, False for mismatch, None on outage."""
        ...


class CampaignIdentityReader(Protocol):
    """Tenant-scoped authority for validating a Campaign 360 subject."""

    async def is_canonical_campaign(self, tenant_id: str, campaign_id: str) -> Optional[bool]:
        """True for a canonical tenant Campaign, False for mismatch, None on outage."""
        ...


class ProfileIdentityReader(Protocol):
    """Tenant-scoped authority for validating an entity's canonical profile."""

    async def is_canonical_profile(self, tenant_id: str, entity_id: str) -> Optional[bool]:
        """True for a canonical tenant profile, False for mismatch, None on outage."""
        ...


class RepositoryAgentIdentityReader:
    """Validate Agent subjects against the canonical tenant Entity authority."""

    async def is_canonical_agent(self, tenant_id: str, agent_id: str) -> Optional[bool]:
        try:
            from repositories.repos import EntityRepository

            row = await EntityRepository().find_by_id(agent_id)
        except Exception:  # noqa: BLE001 - identity authority failure stays unknown
            return None
        return bool(
            isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and row.get("entity_type") == "agent"
            and row.get("entity_id") == agent_id
        )


class RepositoryCampaignIdentityReader:
    """Validate Campaign subjects against the canonical campaign registry."""

    async def is_canonical_campaign(self, tenant_id: str, campaign_id: str) -> Optional[bool]:
        try:
            from uuid import UUID

            from journeys.campaign.repository import CampaignRegistryRepository

            canonical_id = UUID(campaign_id)
            row = await CampaignRegistryRepository().get_by_id(tenant_id, canonical_id)
        except ValueError:
            return False
        except Exception:  # noqa: BLE001 - registry outage stays unknown
            return None
        return bool(
            isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and str(row.get("campaign_id")) == str(canonical_id)
        )


class RepositoryProfileIdentityReader:
    """Validate an entity subject against the canonical Profile authority."""

    async def is_canonical_profile(self, tenant_id: str, entity_id: str) -> Optional[bool]:
        try:
            from dependencies.providers import get_cache, get_graph
            from repositories.repos import IdentityRepository

            row = await IdentityRepository(get_graph(), get_cache()).get_profile(
                tenant_id, entity_id
            )
        except Exception:  # noqa: BLE001 - identity authority failure stays unknown
            return None
        return bool(
            isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and str(row.get("user_id", "")) == entity_id
        )


class RepositoryEconomicSourceReader:
    """Default canonical reader over the existing ``services/api/value/economic`` stores.

    Reads AI execution facts (``ai_aggregation.list_facts``) and exact
    subject-scoped computed economics (``ComputedResultsRepository``), mapping
    each to a raw value-record. A computed-results scope-read failure is
    surfaced as incomplete so it cannot look like complete absence.
    """

    async def records(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        # Tenant scope alone is not enough for a subject 360. Include AI costs
        # only when the canonical fact carries an exact key for this subject.
        records.extend(await self._ai_cost_records(tenant_id, subject))
        records.extend(await self._computed_metric_records(tenant_id, subject))
        return records

    async def _ai_cost_records(
        self, tenant_id: str, subject: ProjectionSubject
    ) -> list[dict[str, Any]]:
        """Map only exactly subject-bound AI execution costs.

        The fact schema has direct ``agent_id``, ``campaign_id`` and
        ``entity_id`` keys. It has no canonical episode, journey or source key;
        workflow IDs are not treated as those subject IDs without a resolver.
        """
        try:
            from value.economic import ai_aggregation

            subject_field = {
                "agent": "agent_id",
                "campaign": "campaign_id",
                "entity": "entity_id",
            }.get(subject.kind)
            if subject_field is None:
                # AI execution facts have no canonical episode or journey key.
                # Preserve the unsupported scope as unknown instead of making
                # the cost metric look like a complete empty read.
                return [
                    {
                        "tenant_id": tenant_id,
                        "_source_incomplete_reason": (
                            AI_EXECUTION_FACTS_SUBJECT_SCOPE_UNAVAILABLE
                        ),
                    }
                ]
            facts = await ai_aggregation.list_facts(
                tenant_id,
                limit=501,
                **{subject_field: subject.id},
            )
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return [
                {
                    "tenant_id": tenant_id,
                    "_source_incomplete_reason": AI_EXECUTION_FACTS_SCOPE_READ_FAILED,
                }
            ]
        scoped = [
            fact
            for fact in facts
            if str(fact.get("tenant_id", "")) == tenant_id
            and str(fact.get(subject_field, "")) == subject.id
        ]
        truncated = len(scoped) > 500
        metric_name = {
            "agent": "agent_execution_cost",
            "campaign": "ai_execution_cost",
            "entity": "entity_execution_cost",
        }[subject.kind]
        records: list[dict[str, Any]] = []
        for fact in scoped[:500]:
            cost_basis = str(fact.get("cost_basis") or "unknown")
            selected = _to_decimal(fact.get("selected_cost"))
            if (
                selected is not None and (not selected.is_finite() or selected < 0)
            ) or cost_basis == "unknown":
                selected = None
            invocation_id = str(fact.get("invocation_id") or fact.get("_key") or "")
            if not invocation_id:
                # An amount without a stable evidence key cannot be surfaced.
                continue
            currency = str(fact.get("currency") or "").strip()
            explicit_usd = _to_decimal(
                fact.get("value_usd") or fact.get("usd_value") or fact.get("amount_usd")
            )
            if explicit_usd is not None and (not explicit_usd.is_finite() or explicit_usd < 0):
                explicit_usd = None
            if selected is None:
                explicit_usd = None
            # A USD-denominated canonical cost is already in the reporting
            # currency. Other native currencies need an explicit normalized
            # value; this provider never performs an implicit FX conversion.
            normalized_usd = (
                explicit_usd
                if explicit_usd is not None
                else selected
                if currency.upper() == "USD"
                else None
            )
            provenance = fact.get("provenance")
            provenance_source = (
                provenance.get("source")
                if isinstance(provenance, dict) and isinstance(provenance.get("source"), str)
                else None
            )
            provenance_schema = (
                provenance.get("schema_version")
                if isinstance(provenance, dict)
                and isinstance(provenance.get("schema_version"), str)
                else None
            )
            records.append(
                {
                    "tenant_id": tenant_id,
                    "amount": None if selected is None else format(selected, "f"),
                    "currency": currency or None,
                    "value_usd": (None if normalized_usd is None else format(normalized_usd, "f")),
                    "metric_kind": "flow",
                    "_source": "ai_execution_facts",
                    "_evidence_id": invocation_id,
                    "_evidence_type": "event",
                    "_evidence_source": "services/api/value/economic/ai_aggregation",
                    "_evidence_uri": f"store://ai_execution_facts/{invocation_id}",
                    "_provenance_source": provenance_source,
                    "_provenance_schema_version": provenance_schema,
                    "_metric_name": metric_name,
                    "_cost_basis": cost_basis,
                    "_observed_at": fact.get("observed_at"),
                    "_source_truncated": truncated,
                }
            )
        return records

    async def _computed_metric_records(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        """Canonical computed economics for the exact subject scope."""
        try:
            from intelligence.computation.repositories import get_computation_repository
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return [
                {
                    "tenant_id": tenant_id,
                    "_source_incomplete_reason": "economic_computed_result_subject_scope_read_failed",
                }
            ]

        try:
            repo = get_computation_repository()
        except Exception:  # noqa: BLE001 - repository construction failure stays incomplete
            return [
                {
                    "tenant_id": tenant_id,
                    "_source_incomplete_reason": "economic_computed_result_subject_scope_read_failed",
                }
            ]
        list_for_subject = getattr(repo, "list_for_subject", None)
        if not callable(list_for_subject):
            # Never fall back to a tenant-wide bounded read: unrelated rows can
            # consume its limit and conceal exact journey economics.
            return [
                {
                    "tenant_id": tenant_id,
                    "_source_incomplete_reason": "economic_computed_result_subject_scope_query_unavailable",
                }
            ]
        try:
            rows = await list_for_subject(
                tenant_id,
                subject.kind,
                subject.id,
                limit=201,
            )
        except Exception:  # noqa: BLE001 - scoped storage read failure stays incomplete
            return [
                {
                    "tenant_id": tenant_id,
                    "_source_incomplete_reason": "economic_computed_result_subject_scope_read_failed",
                }
            ]
        if not isinstance(rows, list):
            return [
                {
                    "tenant_id": tenant_id,
                    "_source_incomplete_reason": "economic_computed_result_subject_scope_read_invalid",
                }
            ]

        # CanonicalResult dimensions are the persisted scope authority. Rows
        # without an exact subject type/id are not joined by amount, timestamp,
        # or correlation identifier. Recheck the repository contract defensively.
        scoped_rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("tenant_id", "")) == tenant_id
            and isinstance(row.get("dimensions"), dict)
            and row["dimensions"].get("subject_type") == subject.kind
            and str(row["dimensions"].get("subject_id", "")) == subject.id
        ]
        scope_query_violated = len(scoped_rows) != len(rows)
        if scope_query_violated:
            return [
                {
                    "tenant_id": tenant_id,
                    "_source_incomplete_reason": "economic_computed_result_subject_scope_returned_unscoped_rows",
                }
            ]
        if not scoped_rows:
            return []

        # ComputedResults retains immutable scopes side by side. Select the
        # latest scope group for this exact subject instead of summing every
        # historical materialization together.
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in scoped_rows:
            context_hash = row.get("context_hash")
            if isinstance(context_hash, str) and context_hash:
                groups.setdefault(context_hash, []).append(row)
        if not groups:
            return []
        latest_group = max(
            groups.values(),
            key=lambda group: max(
                str(row.get("computed_at") or row.get("created_at") or "") for row in group
            ),
        )
        truncated = len(scoped_rows) > 200

        records: list[dict[str, Any]] = []
        for row in latest_group:
            value = row.get("value")
            if value is None:
                continue  # honest absence — never a fabricated zero record
            definition_id = str(row.get("definition_id") or "")
            result_id = str(row.get("result_id") or row.get("context_hash") or "")
            metric_name = "campaign_spend" if subject.kind == "campaign" else "economic_value"
            if "gross_revenue" in definition_id or "revenue" in definition_id:
                metric_name = "gross_value"
            currency = str(row.get("currency") or "").strip()
            explicit_usd_raw = next(
                (
                    row[key]
                    for key in ("value_usd", "usd_value", "amount_usd")
                    if row.get(key) is not None and row.get(key) != ""
                ),
                None,
            )
            explicit_usd = _to_decimal(explicit_usd_raw)
            if explicit_usd is not None and not explicit_usd.is_finite():
                explicit_usd = None
            # ComputedResults carries a native amount and currency. USD has an
            # identity normalization; every other currency needs an explicit
            # canonical USD value. Economic360 does not invent an FX rate.
            normalized_usd = (
                explicit_usd
                if explicit_usd is not None
                else _to_decimal(value)
                if currency.upper() == "USD"
                else None
            )
            records.append(
                {
                    "tenant_id": tenant_id,
                    "amount": value,
                    "currency": currency or None,
                    "value_usd": (None if normalized_usd is None else format(normalized_usd, "f")),
                    "metric_kind": "flow",
                    "_source": f"computed_results:{definition_id}",
                    "_evidence_id": result_id,
                    "_evidence_type": "model_output",
                    "_evidence_source": "services/api/value/economic/computed_results",
                    "_evidence_uri": f"store://computed_results/{definition_id}",
                    "_metric_name": metric_name,
                    "_result_status": row.get("status"),
                    "_computed_at": row.get("computed_at"),
                    "_source_truncated": truncated,
                }
            )
        if truncated and not any(record.get("_source_truncated") is True for record in records):
            records.append({"tenant_id": tenant_id, "_source_truncated": True})
        return records


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Parse a value into a Decimal, or None when unparseable (never 0)."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return None


def _is_ai_execution_cost(record: dict[str, Any]) -> bool:
    """Whether a record is operating cost that must not count as business value."""
    return record.get("_source") == "ai_execution_facts" or record.get("_metric_name") in {
        "agent_execution_cost",
        "ai_execution_cost",
        "entity_execution_cost",
    }


def _known_native_cost_totals(records: list[dict[str, Any]]) -> dict[str, str]:
    """Known AI costs grouped by their native currency, with no implicit FX."""
    totals: dict[str, Decimal] = {}
    for record in records:
        if str(record.get("_cost_basis") or "unknown") == "unknown":
            continue
        amount = _to_decimal(record.get("amount"))
        currency = str(record.get("currency") or "").strip()
        if amount is None or not currency:
            continue
        totals[currency] = totals.get(currency, Decimal(0)) + amount
    return {currency: format(total, "f") for currency, total in sorted(totals.items())}


def _timestamp_range(
    records: list[dict[str, Any]], *, source_field: str, field_name: str
) -> dict[str, Any]:
    """Preserve the range and coverage of valid source timestamps."""
    observed: list[tuple[datetime, str]] = []
    for record in records:
        raw = record.get(source_field)
        if not isinstance(raw, str) or not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        observed.append((parsed.astimezone(timezone.utc), raw))
    observed.sort(key=lambda item: item[0])
    return {
        "field": field_name,
        "timestampCount": len(observed),
        "timestampCoverage": (round(len(observed) / len(records), 4) if records else None),
        "oldest": observed[0][1] if observed else None,
        "latest": observed[-1][1] if observed else None,
    }


def _observed_at_range(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Preserve the range and coverage of valid source observation timestamps."""
    return _timestamp_range(records, source_field="_observed_at", field_name="observed_at")


def _computed_result_observability(records: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Expose canonical computation quality and timestamp coverage for a metric.

    A stale result is marked stale only when the canonical computation status
    says so. Timestamp age alone cannot establish freshness because this
    projection has no configured freshness threshold.
    """
    computed = [
        record
        for record in records
        if str(record.get("_source") or "").startswith("computed_results:")
    ]
    if not computed:
        return None

    status_counts: dict[str, int] = {}
    for record in computed:
        status = record.get("_result_status")
        status_name = status if isinstance(status, str) and status else "unknown"
        status_counts[status_name] = status_counts.get(status_name, 0) + 1
    is_stale = status_counts.get("stale", 0) > 0
    return {
        "resultStatusCounts": dict(sorted(status_counts.items())),
        "computedAt": _timestamp_range(
            computed, source_field="_computed_at", field_name="computed_at"
        ),
        "freshness": {
            "state": "stale" if is_stale else "unknown",
            "reason": (
                "canonical_result_status_stale"
                if is_stale
                else "freshness_threshold_not_configured"
            ),
        },
    }


def _source_provenance(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Expose safe source/schema provenance while omitting hashes and request IDs."""
    items: dict[tuple[str, str, str], dict[str, str]] = {}
    for record in records:
        evidence_id = record.get("_evidence_id")
        source = record.get("_provenance_source")
        schema_version = record.get("_provenance_schema_version")
        if not all(isinstance(value, str) and value for value in (evidence_id, source)):
            continue
        key = (evidence_id, source, schema_version if isinstance(schema_version, str) else "")
        item = {"evidenceId": evidence_id, "source": source}
        if isinstance(schema_version, str) and schema_version:
            item["schemaVersion"] = schema_version
        items[key] = item
    return [items[key] for key in sorted(items)]


def _monetary_from_record(record: dict[str, Any]) -> MonetaryAmount:
    """A MonetaryAmount for a raw value record — absent USD stays None."""
    amount = _to_decimal(record.get("amount"))
    currency = record.get("currency")
    explicit_usd = next(
        (
            record[key]
            for key in ("value_usd", "usd_value", "amount_usd")
            if record.get(key) is not None and record.get(key) != ""
        ),
        None,
    )
    usd_value = _to_decimal(explicit_usd)
    if usd_value is None and amount is not None and str(currency or "").strip().upper() == "USD":
        # USD native amounts have an identity normalization; no FX inference is
        # involved and zero remains a real, explicitly denominated amount.
        usd_value = amount
    return MonetaryAmount(
        amount=amount,
        currency=str(currency) if currency is not None else None,
        usd_value=usd_value,
    )


def _normalization_state(amounts: list[MonetaryAmount]) -> str:
    """Describe USD normalization coverage without treating absence as zero."""
    native_amounts = [amount for amount in amounts if amount.amount is not None]
    if not native_amounts:
        return "missing"
    priced = sum(amount.usd_value is not None for amount in native_amounts)
    if priced == len(native_amounts):
        return "normalized"
    if priced:
        return "partial"
    return "unknown"


def _native_totals_by_currency(amounts: list[MonetaryAmount]) -> dict[str, str]:
    """Retain native values per currency when a USD normalization is unknown."""
    totals: dict[str, Decimal] = {}
    for amount in amounts:
        if amount.amount is None or not amount.amount.is_finite():
            continue
        currency = amount.currency or "unknown"
        totals[currency] = totals.get(currency, Decimal(0)) + amount.amount
    return {currency: format(value, "f") for currency, value in sorted(totals.items())}


def _evidence_ids_for_records(
    records: list[dict[str, Any]], *, normalized_only: bool = False
) -> list[str]:
    """Link a displayed metric to the canonical evidence rows that support it.

    The complete typed refs remain in the evidence section. Summary metrics
    carry their IDs so consumers can trace each aggregate without duplicating
    the full evidence payload. Normalized-only lists identify the rows that
    contribute to a reported USD amount.
    """
    evidence_ids: list[str] = []
    for record in records:
        evidence_id = record.get("_evidence_id")
        if not evidence_id:
            continue
        if normalized_only and _monetary_from_record(record).usd_value is None:
            continue
        evidence_ids.append(str(evidence_id))
    return evidence_ids


def _evidence_from_record(record: dict[str, Any]) -> Optional[EvidenceRef]:
    """A reused canonical EvidenceRef for a record (None when the record has none)."""
    evidence_id = record.get("_evidence_id")
    if not evidence_id:
        return None
    etype = str(record.get("_evidence_type") or "event")
    if etype not in {
        "event",
        "entity",
        "relationship",
        "document",
        "transaction",
        "model_output",
        "annotation",
    }:
        etype = "event"
    return EvidenceRef(
        id=str(evidence_id),
        type=etype,  # type: ignore[arg-type]
        source=str(record.get("_evidence_source") or "services/api/value/economic"),
        observedAt=record.get("_observed_at") or record.get("_computed_at"),
        uri=record.get("_evidence_uri"),
    )


class Economic360Provider:
    """Intelligence-projection provider for ``economic360`` (read-only)."""

    projection_id = "economic360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(
        self,
        sources: Optional[EconomicSourceReader] = None,
        *,
        agent_identity_reader: Optional[AgentIdentityReader] = None,
        campaign_identity_reader: Optional[CampaignIdentityReader] = None,
        profile_identity_reader: Optional[ProfileIdentityReader] = None,
    ) -> None:
        # Injected canonical reader (test seam); default reads repositories.
        self._sources = sources if sources is not None else RepositoryEconomicSourceReader()
        self._agent_identity = (
            agent_identity_reader
            if agent_identity_reader is not None
            else RepositoryAgentIdentityReader()
        )
        source_campaign_identity = getattr(self._sources, "is_canonical_campaign", None)
        self._campaign_identity = (
            campaign_identity_reader
            if campaign_identity_reader is not None
            else self._sources
            if callable(source_campaign_identity)
            else RepositoryCampaignIdentityReader()
        )
        self._profile_identity = (
            profile_identity_reader
            if profile_identity_reader is not None
            else RepositoryProfileIdentityReader()
        )

    # ── IntelligenceProjectionProvider ─────────────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one read-only Economic360 projection over canonical Aether truth."""
        tenant_id = request.tenantId
        if request.subject.kind == "agent":
            try:
                canonical_agent = await self._agent_identity.is_canonical_agent(
                    tenant_id, request.subject.id
                )
            except Exception:  # noqa: BLE001 - fail closed on authority errors
                canonical_agent = None
            if canonical_agent is not True:
                reason = (
                    "agent_identity_authority_unavailable"
                    if canonical_agent is None
                    else "agent_canonical_identity_unresolved"
                )
                return self._unknown_subject_scope_result(request, context, reason)
        elif request.subject.kind == "campaign":
            try:
                canonical_campaign = await self._campaign_identity.is_canonical_campaign(
                    tenant_id, request.subject.id
                )
            except Exception:  # noqa: BLE001 - fail closed on authority errors
                canonical_campaign = None
            if canonical_campaign is not True:
                reason = (
                    "campaign_identity_authority_unavailable"
                    if canonical_campaign is None
                    else "campaign_canonical_identity_unresolved"
                )
                return self._unknown_subject_scope_result(request, context, reason)

        tenant_filtered: list[dict[str, Any]] = []
        records = await self._safe_records(tenant_id, request.subject)
        source_incomplete_reasons: set[str] = set()
        for record in records:
            # Tenant scope is server-authoritative: never project another
            # tenant's economic sections/evidence.
            if str(record.get("tenant_id", tenant_id)) == tenant_id:
                incomplete_reason = record.get("_source_incomplete_reason")
                if isinstance(incomplete_reason, str) and incomplete_reason:
                    source_incomplete_reasons.add(incomplete_reason)
                else:
                    tenant_filtered.append(record)
        source_truncated = any(
            record.get("_source_truncated") is True for record in tenant_filtered
        )
        source_partial = source_truncated or bool(source_incomplete_reasons)

        warnings = economic_warnings_for_amounts(_monetary_from_record(r) for r in tenant_filtered)

        # AI execution costs are costs of operating the agent, not positive
        # business value. Keep them observable in their dedicated metric while
        # excluding them from the generic value rollup and its claims.
        value_records = [record for record in tenant_filtered if not _is_ai_execution_cost(record)]

        # Canonical safe rollup + value diagnostics over business-value records.
        rollup = self._safe_rollup(value_records)
        diagnostic = self._diagnose(rollup)

        # Double-count detection over economic positions derived from records.
        warnings.extend(self._double_count_warnings(tenant_filtered, request))

        evidence = [
            ref for ref in (_evidence_from_record(r) for r in tenant_filtered) if ref is not None
        ]
        operation_as_of = request.asOf
        if (
            operation_as_of is None
            and request.temporalMode in {"as_of", "compare"}
            and request.timeRange is not None
        ):
            operation_as_of = request.timeRange.from_
        operation_evidence = await self._subject_operation_evidence(
            tenant_id,
            request.subject,
            as_of=operation_as_of,
        )
        operation_evidence_partial = bool(
            operation_evidence
            and (
                operation_evidence.get("reason")
                or operation_evidence.get("evidence_truncated") is True
                or operation_evidence.get("ledger_read_errors", 0)
                or operation_evidence.get("invalid_ledger_records", 0)
                or operation_evidence.get("unresolved_order_references", 0)
            )
        )
        operation_evidence_warning = (
            "campaign_commerce_evidence_partial"
            if operation_evidence
            and operation_evidence.get("join_basis")
            == "explicit_campaign_scoped_canonical_activity_commerce_order_ref"
            else "journey_commerce_evidence_partial"
            if operation_evidence
            and operation_evidence.get("join_basis") == "explicit_journey_step_commerce_order_ref"
            else "entity_commerce_evidence_partial"
            if operation_evidence
            and operation_evidence.get("join_basis")
            == "explicit_canonical_profile_scoped_activity_commerce_order_ref"
            else EPISODE_COMMERCE_ORDER_SCOPE_UNAVAILABLE
            if operation_evidence
            and operation_evidence.get("reason")
            == EPISODE_COMMERCE_ORDER_SCOPE_UNAVAILABLE
            else "commerce_operation_evidence_partial"
        )

        dep_state = context.dependencyState
        source_provenance = _source_provenance(tenant_filtered)
        sections = [
            self._summary_section(
                request,
                tenant_filtered,
                rollup,
                dep_state,
                source_partial,
                sorted(source_incomplete_reasons),
            ),
            self._state_section(tenant_filtered, diagnostic, dep_state, source_partial),
            self._evidence_section(
                evidence,
                operation_evidence,
                source_truncated,
                operation_evidence_partial=operation_evidence_partial,
                operation_evidence_warning=operation_evidence_warning,
                source_provenance=source_provenance,
                source_incomplete_reasons=sorted(source_incomplete_reasons),
            ),
            self._outcomes_section(tenant_filtered, dep_state, source_partial),
            self._findings_section(warnings, evidence, source_partial),
        ]
        claims = self._build_claims(request, tenant_filtered, rollup, warnings, evidence)

        degraded_reasons = []
        if source_truncated:
            degraded_reasons.append("economic_source_read_truncated")
        degraded_reasons.extend(sorted(source_incomplete_reasons))
        if operation_evidence_partial:
            degraded_reasons.append(operation_evidence_warning)
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(dep_state),
            generatedAt=_utc_now_iso(),
            degradedReasons=degraded_reasons,
        )

    def _unknown_subject_scope_result(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        reason: str,
    ) -> ProjectionResult:
        """Return unknown sections when the requested canonical subject is unresolved."""
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=[
                ProjectionSection(
                    id=section_id,
                    state="unknown",
                    warnings=[reason],
                )
                for section_id in OUTPUT_SECTIONS
            ],
            claims=[],
            dependencyState=list(context.dependencyState),
            generatedAt=_utc_now_iso(),
            degradedReasons=[reason],
        )

    # ── Section builders ───────────────────────────────────────────────────

    def _summary_section(
        self,
        request: ProjectionRequest,
        records: list[dict[str, Any]],
        rollup: dict[str, Any],
        dep_state: list[Any],
        source_truncated: bool,
        source_incomplete_reasons: list[str],
    ) -> ProjectionSection:
        """summary — total value observed + the campaign economic metric set."""
        state: str = "available"
        if not records:
            state = "missing"
        elif _dependency_missing(dep_state, SECTION_DEPENDENCIES["summary"]):
            # profile360 is still in_flight: the summary is present but the
            # profile enrichment that would cross-reference it is not available.
            state = "degraded"
        elif rollup.get("rollup_status") in ("unavailable", "conflicted"):
            state = "degraded"
        if source_truncated:
            state = "degraded"

        campaign_cost_records = [
            record for record in records if record.get("_metric_name") == "campaign_spend"
        ]
        spend_amounts = [_monetary_from_record(record) for record in campaign_cost_records]
        campaign_cost_coverage = (
            round(
                sum(record.get("amount") is not None for record in campaign_cost_records)
                / len(campaign_cost_records),
                4,
            )
            if campaign_cost_records
            else None
        )
        gross_value_records = [
            record for record in records if record.get("_metric_name") in ("gross_value", "revenue")
        ]
        gross_amounts = [_monetary_from_record(record) for record in gross_value_records]
        spend_usd, _ = safe_usd_total(spend_amounts)
        gross_usd, _ = safe_usd_total(gross_amounts)
        value_records = [record for record in records if not _is_ai_execution_cost(record)]
        value_usd_records = [
            record for record in value_records if _monetary_from_record(record).usd_value is not None
        ]
        ai_cost_records = [record for record in records if _is_ai_execution_cost(record)]
        ai_cost_amounts = [_monetary_from_record(record) for record in ai_cost_records]
        ai_cost_usd, _ = safe_usd_total(ai_cost_amounts)
        ai_cost_known = sum(record.get("amount") is not None for record in ai_cost_records)
        ai_cost_usd_known = sum(
            _monetary_from_record(record).usd_value is not None for record in ai_cost_records
        )
        ai_cost_coverage = (
            round(ai_cost_known / len(ai_cost_records), 4) if ai_cost_records else None
        )
        ai_cost_usd_coverage = (
            round(ai_cost_usd_known / len(ai_cost_records), 4) if ai_cost_records else None
        )
        ai_cost_basis_counts: dict[str, int] = {}
        for record in ai_cost_records:
            basis = str(record.get("_cost_basis") or "unknown")
            ai_cost_basis_counts[basis] = ai_cost_basis_counts.get(basis, 0) + 1
        ai_cost_scope_reason = next(
            (
                reason
                for reason in source_incomplete_reasons
                if reason
                in {
                    AI_EXECUTION_FACTS_SUBJECT_SCOPE_UNAVAILABLE,
                    AI_EXECUTION_FACTS_SCOPE_READ_FAILED,
                }
            ),
            None,
        )
        ai_cost_metric_name = (
            "agent_execution_cost"
            if request.subject.kind == "agent"
            else "entity_execution_cost"
            if request.subject.kind == "entity"
            else "ai_execution_cost"
        )
        roas: Optional[Decimal] = None
        if spend_usd is not None and gross_usd is not None and spend_usd != 0:
            roas = (gross_usd / spend_usd).quantize(Decimal("0.0001"))

        content: dict[str, Any] = {
            "tenantId": request.tenantId,
            "subject": request.subject.model_dump(),
            "total_usd": rollup.get("total_usd"),  # None preserved — never 0
            "native_currency": rollup.get("native_currency"),
            "native_total": rollup.get("native_total"),
            "rollup_status": rollup.get("rollup_status"),
            "valueEvidenceRefIds": _evidence_ids_for_records(value_records),
            "usdContributionEvidenceRefIds": _evidence_ids_for_records(value_usd_records),
            "metrics": {
                "campaign_spend": {
                    "unit": "usd",
                    "usd_value": None if spend_usd is None else format(spend_usd, "f"),
                    "state": "available" if spend_usd is not None else "missing",
                    "factCount": len(campaign_cost_records),
                    "costCoverage": campaign_cost_coverage,
                    "normalizationState": _normalization_state(spend_amounts),
                    "nativeTotalsByCurrency": _native_totals_by_currency(spend_amounts),
                    "evidenceRefIds": _evidence_ids_for_records(campaign_cost_records),
                    "usdContributionEvidenceRefIds": _evidence_ids_for_records(
                        campaign_cost_records, normalized_only=True
                    ),
                    **(_computed_result_observability(campaign_cost_records) or {}),
                },
                "gross_value": {
                    "unit": "usd",
                    "usd_value": None if gross_usd is None else format(gross_usd, "f"),
                    "state": "available" if gross_usd is not None else "missing",
                    "normalizationState": _normalization_state(gross_amounts),
                    "nativeTotalsByCurrency": _native_totals_by_currency(gross_amounts),
                    "evidenceRefIds": _evidence_ids_for_records(gross_value_records),
                    "usdContributionEvidenceRefIds": _evidence_ids_for_records(
                        gross_value_records, normalized_only=True
                    ),
                    **(_computed_result_observability(gross_value_records) or {}),
                },
                "campaign_roas": {
                    "unit": "ratio",
                    "value": None if roas is None else format(roas, "f"),
                    "state": "available" if roas is not None else "missing",
                    "inputEvidenceRefIds": {
                        "campaign_spend": _evidence_ids_for_records(
                            campaign_cost_records, normalized_only=True
                        ),
                        "gross_value": _evidence_ids_for_records(
                            gross_value_records, normalized_only=True
                        ),
                    },
                },
                "campaign_cac": {
                    "unit": "usd",
                    "usd_value": None,
                    "state": "missing",  # not derivable without customer counts
                },
                "campaign_ltv": {
                    "unit": "usd",
                    "usd_value": None,
                    "state": "missing",
                },
                "ai_execution_cost": {
                    "metricName": ai_cost_metric_name,
                    "unit": "usd",
                    "usd_value": None if ai_cost_usd is None else format(ai_cost_usd, "f"),
                    "state": (
                        "unknown"
                        if ai_cost_scope_reason is not None
                        else "available"
                        if ai_cost_usd is not None
                        else "missing"
                    ),
                    "subjectBinding": {
                        "state": "unknown" if ai_cost_scope_reason is not None else "exact_key",
                        "subject": request.subject.model_dump(),
                        "reason": ai_cost_scope_reason,
                    },
                    "factCount": len(ai_cost_records),
                    "costCoverage": ai_cost_coverage,
                    "usdCoverage": ai_cost_usd_coverage,
                    "costBasisCounts": ai_cost_basis_counts,
                    "nativeTotalsByCurrency": _known_native_cost_totals(ai_cost_records),
                    "normalizationState": _normalization_state(ai_cost_amounts),
                    "observedAt": _observed_at_range(ai_cost_records),
                    "evidenceRefIds": _evidence_ids_for_records(ai_cost_records),
                    "usdContributionEvidenceRefIds": _evidence_ids_for_records(
                        ai_cost_records, normalized_only=True
                    ),
                    "freshness": {
                        "state": "unknown",
                        "reason": "freshness_threshold_not_configured",
                    },
                    "sourceCompleteness": (
                        "unknown"
                        if ai_cost_scope_reason is not None
                        else "partial"
                        if any(
                            record.get("_source_truncated") is True for record in ai_cost_records
                        )
                        else "bounded_read"
                    ),
                },
            },
            "sourceCompleteness": "partial" if source_truncated else "bounded_read",
        }
        warnings: list[str] = []
        if state == "degraded" and _dependency_missing(dep_state, SECTION_DEPENDENCIES["summary"]):
            warnings.append("profile360 dependency not available; summary is degraded")
        return ProjectionSection(
            id="summary",
            state=state,  # type: ignore[arg-type]
            title="Economic summary",
            content=content,
            warnings=warnings or None,
        )

    def _state_section(
        self,
        records: list[dict[str, Any]],
        diagnostic: dict[str, Any],
        dep_state: list[Any],
        source_truncated: bool,
    ) -> ProjectionSection:
        """state — value diagnostics over the canonical rollup."""
        state: str = "available"
        if not records:
            state = "empty"
        elif _dependency_missing(dep_state, SECTION_DEPENDENCIES["state"]):
            # relationship360 is still in_flight: state diagnostics are present
            # but the relationship context that would enrich them is not.
            state = "degraded"
        elif diagnostic.get("valuation_status") in ("unavailable", "conflicted"):
            state = "degraded"
        if source_truncated:
            state = "degraded"
        warnings: list[str] = []
        if state == "degraded" and _dependency_missing(dep_state, SECTION_DEPENDENCIES["state"]):
            warnings.append("relationship360 dependency not available; state is degraded")
        return ProjectionSection(
            id="state",
            state=state,  # type: ignore[arg-type]
            title="Economic state",
            content=diagnostic,
            warnings=warnings or None,
        )

    def _evidence_section(
        self,
        evidence: list[EvidenceRef],
        operation_evidence: Optional[dict[str, Any]] = None,
        source_truncated: bool = False,
        *,
        operation_evidence_partial: bool = False,
        operation_evidence_warning: str = "commerce_operation_evidence_partial",
        source_provenance: Optional[list[dict[str, str]]] = None,
        source_incomplete_reasons: Optional[list[str]] = None,
    ) -> ProjectionSection:
        """evidence — the canonical evidence refs grounding this projection."""
        source_incomplete_reasons = source_incomplete_reasons or []
        source_partial = source_truncated or bool(source_incomplete_reasons)
        content: dict[str, Any] = {
            "count": len(evidence),
            "evidence": [e.model_dump(mode="json") for e in evidence],
            "sourceCompleteness": "partial" if source_partial else "bounded_read",
        }
        if source_provenance:
            content["sourceProvenance"] = source_provenance
        if operation_evidence is not None:
            content["economic_operations"] = operation_evidence
            operation_completeness = operation_evidence.get("completeness")
            content["operationEvidenceCompleteness"] = (
                "unknown"
                if operation_completeness == "unknown"
                else "partial"
                if operation_evidence_partial
                else "bounded_read"
            )
        warnings = []
        if source_truncated:
            warnings.append("economic_source_read_truncated")
        warnings.extend(source_incomplete_reasons)
        if operation_evidence_partial:
            warnings.append(operation_evidence_warning)
        return ProjectionSection(
            id="evidence",
            state=(
                "degraded"
                if source_partial or operation_evidence_partial
                else "available"
                if evidence or operation_evidence
                else "empty"
            ),
            title="Evidence",
            content=content,
            warnings=warnings,
        )

    async def _subject_operation_evidence(
        self, tenant_id: str, subject: Any, *, as_of: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Attach exact-reference commerce links for supported canonical subjects.

        Journey references come from persisted step evidence. Campaign
        references come from a tenant-scoped canonical activity that carries
        both the validated campaign ID and exact commerce order reference. No
        identity, amount, time, provider order ID, or payment ID joins are
        attempted here.
        """
        try:
            from value.economic.journey_operation_evidence import (
                campaign_commerce_operation_evidence,
                entity_commerce_operation_evidence,
                journey_commerce_operation_evidence,
            )

            if getattr(subject, "kind", None) == "journey":
                return await journey_commerce_operation_evidence(tenant_id, subject.id, as_of=as_of)
            if getattr(subject, "kind", None) == "campaign":
                # project() has already validated this subject against the
                # tenant CampaignRegistry before reaching this reader.
                return await campaign_commerce_operation_evidence(
                    tenant_id, subject.id, as_of=as_of
                )
            if getattr(subject, "kind", None) == "episode":
                # EpisodeRecord retains subject, observation IDs, and evidence
                # refs, but no canonical episode-to-commerce_order_ref join is
                # available. Do not reinterpret observation/evidence IDs,
                # timestamps, or coincident amounts as an order association.
                return {
                    "episode_id": subject.id,
                    "join_basis": "unavailable_episode_commerce_order_reference",
                    "completeness": "unknown",
                    "operation_links": [],
                    "payment_facts": [],
                    "association_evidence": [],
                    "amounts_included": False,
                    "facts_are_aggregated": False,
                    "unlinked_evidence": "not_inferred",
                    "reason": EPISODE_COMMERCE_ORDER_SCOPE_UNAVAILABLE,
                    "as_of": as_of,
                }
            if getattr(subject, "kind", None) == "entity":
                try:
                    canonical_profile = await self._profile_identity.is_canonical_profile(
                        tenant_id, subject.id
                    )
                except Exception:  # noqa: BLE001 - fail closed on identity authority errors
                    canonical_profile = None
                if canonical_profile is not True:
                    return {
                        "entity_id": subject.id,
                        "join_basis": "explicit_canonical_profile_scoped_activity_commerce_order_ref",
                        "operation_links": [],
                        "payment_facts": [],
                        "association_evidence": [],
                        "reason": (
                            "profile_identity_authority_unavailable"
                            if canonical_profile is None
                            else "profile_canonical_identity_unresolved"
                        ),
                        "evidence_truncated": True,
                    }
                return await entity_commerce_operation_evidence(tenant_id, subject.id, as_of=as_of)
            return None
        except Exception:
            # Economic360 is fail-isolated; inability to read operation evidence
            # must not hide canonical value records or fabricate links.
            return {
                "join_basis": "exact_canonical_subject_commerce_order_ref",
                "operation_links": [],
                "payment_facts": [],
                "reason": "operation_evidence_unavailable",
            }

    def _outcomes_section(
        self,
        records: list[dict[str, Any]],
        dep_state: list[Any],
        source_truncated: bool,
    ) -> ProjectionSection:
        """outcomes — outcome-economics, degraded honestly until outcome360 lands."""
        outcome = next(
            (d for d in dep_state if d.projectionId == SECTION_DEPENDENCIES["outcomes"]),
            None,
        )
        if not _dependency_missing(dep_state, SECTION_DEPENDENCIES["outcomes"]):
            state = "available"
            reason = None
        else:
            state = "degraded"
            reason = (
                "outcome360 dependency is not yet implemented; outcome "
                "economics are not projected (in_flight)"
            )
        if source_truncated:
            state = "degraded"
        gross_amounts = [
            _monetary_from_record(r)
            for r in records
            if r.get("_metric_name") in ("gross_value", "revenue")
        ]
        gross_usd, _ = safe_usd_total(gross_amounts)
        return ProjectionSection(
            id="outcomes",
            state=state,  # type: ignore[arg-type]
            title="Outcome economics",
            content={
                "dependencyState": {
                    "projectionId": "outcome360",
                    "state": "missing" if outcome is None else outcome.state,
                },
                "reason": reason,
                "outcome_value_usd": (None if gross_usd is None else format(gross_usd, "f")),
                "normalizationState": _normalization_state(gross_amounts),
            },
            warnings=[reason] if reason else None,
        )

    def _findings_section(
        self,
        warnings: list[EconomicWarning],
        evidence: list[EvidenceRef],
        source_truncated: bool,
    ) -> ProjectionSection:
        """findings — typed anti-pattern warnings, never invented values."""
        return ProjectionSection(
            id="findings",
            state="degraded" if source_truncated else "available",
            title="Economic findings",
            content={
                "warnings": [w.model_dump(mode="json") for w in warnings],
                "evidence_count": len(evidence),
                "sourceCompleteness": "partial" if source_truncated else "bounded_read",
            },
        )

    def _double_count_warnings(
        self,
        records: list[dict[str, Any]],
        request: ProjectionRequest,
    ) -> list[EconomicWarning]:
        """POSSIBLE_DOUBLE_COUNT warnings from derivative-receipt records.

        Records that carry ``_derivative_receipt`` + ``_underlying_position_id``
        are modeled as :class:`EconomicPosition` values and run through the
        typed double-count detector — never a fabricated figure.
        """
        flagged = [
            r for r in records if r.get("_derivative_receipt") or r.get("_underlying_position_id")
        ]
        if not flagged:
            return []
        from value.economic.economic360_contracts import EconomicPosition
        from graph.operational_intelligence.models import EntityRef

        positions = [
            EconomicPosition(
                id=str(r.get("_evidence_id") or f"pos-{i}"),
                tenant_id=request.tenantId,
                holder=EntityRef(kind="economic_resource", id=request.subject.id),
                position_type="receipt" if r.get("_derivative_receipt") else "position",
                is_derivative_receipt=bool(r.get("_derivative_receipt")),
                underlying_position_id=r.get("_underlying_position_id"),
            )
            for i, r in enumerate(flagged)
        ]
        return detect_double_count(positions)

    # ── Claims ─────────────────────────────────────────────────────────────

    def _build_claims(
        self,
        request: ProjectionRequest,
        records: list[dict[str, Any]],
        rollup: dict[str, Any],
        warnings: list[EconomicWarning],
        evidence: list[EvidenceRef],
    ) -> list[ClaimEnvelope]:
        """Evidence-grounded claims (requiresEvidence: every claim is grounded)."""
        claims: list[ClaimEnvelope] = []
        subject = request.subject  # canonical subject — never re-derived

        total_usd = rollup.get("total_usd")
        if total_usd is not None:
            value_evidence = [
                ref
                for record in records
                if not _is_ai_execution_cost(record)
                for ref in [_evidence_from_record(record)]
                if ref is not None
            ]
            claims.append(
                ClaimEnvelope(
                    id="summary.total_value_observed",
                    kind="economic_rollup",
                    subject=subject,
                    evidenceRefs=value_evidence,
                    claims=[
                        f"trusted USD total observed: ${total_usd}",
                        f"rollup status: {rollup.get('rollup_status')}",
                    ],
                )
            )
        else:
            unpriced_refs = [
                ref
                for record in records
                if not _is_ai_execution_cost(record)
                for ref in [_evidence_from_record(record)]
                if ref is not None
            ][:5]
            claims.append(
                ClaimEnvelope(
                    id="summary.no_trusted_total",
                    kind="economic_rollup",
                    subject=subject,
                    evidenceRefs=unpriced_refs,
                    claims=[
                        "no trusted USD total is available; unpriced amounts are "
                        "never coerced to zero"
                    ],
                )
            )

        spend_usd, _ = safe_usd_total(
            _monetary_from_record(r) for r in records if r.get("_metric_name") == "campaign_spend"
        )
        if spend_usd is not None:
            spend_refs = [
                ref
                for ref, r in zip(
                    (_evidence_from_record(r) for r in records),
                    records,
                )
                if ref is not None and r.get("_metric_name") == "campaign_spend"
            ]
            claims.append(
                ClaimEnvelope(
                    id="summary.campaign_spend",
                    kind="campaign_spend",
                    subject=subject,
                    evidenceRefs=spend_refs or evidence[:5],
                    claims=[f"campaign spend (USD): {format(spend_usd, 'f')}"],
                )
            )

        ai_cost_records = [record for record in records if _is_ai_execution_cost(record)]
        ai_cost_usd, _ = safe_usd_total(_monetary_from_record(record) for record in ai_cost_records)
        if ai_cost_usd is not None:
            cost_refs = [
                ref
                for record in ai_cost_records
                if str(record.get("_cost_basis") or "unknown") != "unknown"
                and _monetary_from_record(record).usd_value is not None
                for ref in [_evidence_from_record(record)]
                if ref is not None
            ]
            claims.append(
                ClaimEnvelope(
                    id="summary.ai_execution_cost",
                    kind="ai_execution_cost",
                    subject=subject,
                    evidenceRefs=cost_refs,
                    claims=[
                        "observed AI execution cost (USD): "
                        f"{format(ai_cost_usd, 'f')}; this is operating cost, "
                        "not a measured business outcome"
                    ],
                )
            )

        for warning in warnings:
            claims.append(
                ClaimEnvelope(
                    id=f"findings.{warning.code.value.lower()}",
                    kind="economic_warning",
                    subject=subject,
                    evidenceRefs=evidence[:5],
                    claims=[warning.message],
                    confidence=None,
                )
            )

        return claims

    # ── Canonical read helpers (defensive) ─────────────────────────────────

    async def _safe_records(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        """Canonical records for the tenant; any reader failure degrades."""
        try:
            return await self._sources.records(tenant_id=tenant_id, subject=subject)
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []

    def _safe_rollup(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Canonical safe rollup over value records (services/api/value/value semantics)."""
        try:
            from value.value.rollups import safe_rollup

            return safe_rollup(records, metric_kind="flow")
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return {
                "total_usd": None,
                "by_native_currency": {},
                "unpriced_count": 0,
                "stale_count": 0,
                "excluded_count": 0,
                "rollup_status": "unavailable",
                "native_currency": None,
                "native_total": None,
            }

    def _diagnose(self, rollup: dict[str, Any]) -> dict[str, Any]:
        """Value diagnostics over a rollup (services/api/value/economic/value_diagnostics)."""
        try:
            from value.economic.value_diagnostics import diagnose_rollup

            return diagnose_rollup(rollup)
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return {
                "valuation_status": "unavailable",
                "total_usd": rollup.get("total_usd"),
                "has_trusted_total": rollup.get("total_usd") is not None,
            }


def register_provider(registry: ProviderRegistry) -> None:
    """Register :class:`Economic360Provider` on a provider registry.

    Deliberately NOT called at import time: the global ``projection_registry``
    is only mutated by the runtime wiring layer, never by provider modules.
    """
    registry.register(Economic360Provider(), source="services/api/value/economic")


__all__ = [
    "CampaignIdentityReader",
    "Economic360Provider",
    "EconomicSourceReader",
    "OUTPUT_SECTIONS",
    "RepositoryCampaignIdentityReader",
    "RepositoryEconomicSourceReader",
    "SECTION_DEPENDENCIES",
    "register_provider",
]
