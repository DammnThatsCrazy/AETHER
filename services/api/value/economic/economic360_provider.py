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

import hashlib
import json
from datetime import datetime, timezone
from shared.temporal.instant import coerce_utc_lenient
from decimal import Decimal
from typing import Any, Optional, Protocol
from urllib.parse import quote

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
from shared.contracts_models.epistemic import EpistemicStatus

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
from value.economic.revenue_adjustment_observations import (
    AdjustmentSource,
    read_revenue_adjustments,
)

# Sections the registry declares for economic360 (must match outputSections).
OUTPUT_SECTIONS: tuple[str, ...] = ("summary", "state", "evidence", "outcomes", "findings")

# Product-frame slots are explicit routing metadata. The composer deliberately
# does not infer a slot from a projection section or claim kind.
ECONOMIC_FACTS_SLOT_ID = "economic_facts_and_state"
PAYMENTS_COMMERCE_SLOT_ID = "payments_and_commerce_evidence"
CAMPAIGN_PERFORMANCE_SLOT_ID = "performance"
VALUE_SUMMARY_SLOT_ID = "value_summary"
VALUE_WEB2_SLOT_ID = "web2_value"
VALUE_WEB3_SLOT_ID = "web3_value"
VALUE_CONVERSION_INVENTORY_SLOT_ID = "conversion_inventory"
VALUE_ATTRIBUTION_CREDITS_SLOT_ID = "attribution_credits"
VALUE_REVENUE_EVENTS_SLOT_ID = "revenue_events"
VALUE_LTV_SLOT_ID = "ltv"
VALUE_CONFIDENCE_SLOT_ID = "confidence"
VALUE_EVIDENCE_TRACE_SLOT_ID = "evidence_trace"
VALUE_RECONCILIATION_SLOT_ID = "reconciliation"
VALUE_FINANCIAL_RISK_SLOT_ID = "financial_risk"
ACCOUNT_VALUE_SLOT_ID = "value"
_MAX_CONVERSION_INVENTORY_ROWS = 500
_MAX_ATTRIBUTION_CONVERSIONS = 100
_MAX_ATTRIBUTION_CREDITS_PER_RUN = 100
_MAX_ATTRIBUTION_CREDITS_TOTAL = 500
_MAX_ATTRIBUTION_TOUCHPOINT_READS = 500
_FINANCIAL_RISK_SUBJECT_KINDS = {"agent", "cluster", "entity", "source"}
_LTV_JOIN_BASIS_BY_SUBJECT_KIND = {
    "profile": "exact_canonical_profile_conversion_id",
    "entity": "exact_canonical_profile_conversion_id",
    "account": "exact_tenant_conversion_account_id",
    "cluster": "exact_canonical_conversion_cluster_id",
    "campaign": "canonical_campaign_touchpoint_or_attribution_conversion_join",
    "journey": "current_tenant_journey_version_conversion_ids",
    "agent": "validated_agent_identity_exact_conversion_agent_id",
}


def _economic_domain_slot_ids(subject: ProjectionSubject, primary_slot_id: str) -> list[str]:
    """Route exact campaign-scoped economic evidence into Campaign360 performance.

    Economic360 retains its own canonical value slots. Campaign 360 also binds
    Economic360 as the provider for its performance slot, so campaign subjects
    receive both routing IDs without changing other subject surfaces.
    """
    slot_ids = [primary_slot_id]
    if subject.kind == "campaign":
        slot_ids.append(CAMPAIGN_PERFORMANCE_SLOT_ID)
    return slot_ids


def _with_financial_risk_slot(subject: ProjectionSubject, slot_ids: list[str]) -> list[str]:
    """Route a direct, evidence-backed economic fact to the exact-subject risk join."""
    result = list(slot_ids)
    if (
        subject.kind in _FINANCIAL_RISK_SUBJECT_KINDS
        and VALUE_FINANCIAL_RISK_SLOT_ID not in result
    ):
        result.append(VALUE_FINANCIAL_RISK_SLOT_ID)
    return result


def _value_summary_domain_slot_ids(
    subject: ProjectionSubject,
    *,
    entity_profile_verified: bool = False,
) -> list[str]:
    """Route an evidence-backed economic rollup to its exact product slots.

    Entity ``value`` claims are emitted only after project() verifies the
    canonical tenant profile and reads direct subject-scoped records. This is
    an entity's own economic evidence, never a member/descendant aggregate.
    """
    slot_ids = _with_financial_risk_slot(
        subject, _economic_domain_slot_ids(subject, ECONOMIC_FACTS_SLOT_ID)
    )
    slot_ids.extend([VALUE_SUMMARY_SLOT_ID, VALUE_EVIDENCE_TRACE_SLOT_ID])
    if subject.kind == "entity" and entity_profile_verified:
        slot_ids.append(ACCOUNT_VALUE_SLOT_ID)
    return list(dict.fromkeys(slot_ids))


_COMMERCE_JOIN_BASIS_BY_SUBJECT_KIND = {
    "journey": "explicit_journey_step_commerce_order_ref",
    "campaign": "explicit_campaign_scoped_canonical_activity_commerce_order_ref",
    "entity": "explicit_canonical_profile_scoped_activity_commerce_order_ref",
}
_PAYMENT_RAIL_VALUES = {
    "fiat",
    "stripe",
    "coinbase",
    "moonpay",
    "bridge",
    "bank_transfer",
    "card",
    "ach",
    "wire",
    "sepa",
    "onchain",
    "x402",
}
_WEB2_PAYMENT_RAILS = {"bank_transfer", "card", "ach", "wire", "sepa"}
_WEB3_PAYMENT_FLOWS = {
    "crypto_onramp",
    "crypto_deposit",
    "offramp",
    "commerce_payment",
    "settlement",
}
_WEB3_RAILS = {"onchain", "x402"}

# Registry projection dependencies we degrade for honestly while they are
# still in_flight (profile360 / relationship360 / outcome360). Each entry maps
# the section whose enrichment depends on that sibling projection.
SECTION_DEPENDENCIES: dict[str, str] = {
    "summary": "profile360",
    "state": "relationship360",
    "outcomes": "outcome360",
}

AI_EXECUTION_FACTS_SUBJECT_SCOPE_UNAVAILABLE = "ai_execution_facts_subject_scope_unavailable"
AI_EXECUTION_FACTS_SCOPE_READ_FAILED = "ai_execution_facts_scope_read_failed"
EPISODE_COMMERCE_ORDER_SCOPE_UNAVAILABLE = "episode_commerce_order_reference_scope_unavailable"


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


class AccountIdentityReader(Protocol):
    """Resolve an account through the tenant-scoped Account360 entity authority."""

    async def validate_account(
        self, tenant_id: str, account_id: str
    ) -> tuple[Optional[bool], list[EvidenceRef]]:
        """Return a typed verdict and the exact entity evidence when resolved."""
        ...


class ClusterIdentityReader(Protocol):
    """Resolve a conversion cluster through the tenant identity authority."""

    async def validate_cluster(
        self, tenant_id: str, cluster_id: str
    ) -> tuple[Optional[bool], list[EvidenceRef]]:
        ...


class ConversionInventoryReader(Protocol):
    """Narrow read seam for exact, tenant-scoped canonical conversion rows."""

    async def read(self, request: ProjectionRequest) -> dict[str, Any]:
        """Return canonical conversion rows linked through one exact subject join."""
        ...


class AttributionCreditReader(Protocol):
    """Narrow tenant-scoped read seam for active canonical attribution runs."""

    async def read(self, tenant_id: str, conversion_ids: list[str]) -> dict[str, Any]:
        """Return active runs and their credit rows for exact conversion IDs."""
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


class RepositoryAccountIdentityReader:
    """Reuse Account360's exact canonical account-entity scope check."""

    async def validate_account(
        self, tenant_id: str, account_id: str
    ) -> tuple[Optional[bool], list[EvidenceRef]]:
        try:
            from identity.account360_provider import RepositoryAccount360Source

            read = await RepositoryAccount360Source().canonical_entity(tenant_id, account_id)
        except Exception:  # noqa: BLE001 - entity authority outage is unknown
            return None, []
        if (
            read.state == "resolved"
            and read.tenant_id == tenant_id
            and read.entity_id == account_id
            and read.evidence_refs
        ):
            return True, list(read.evidence_refs)
        if read.state == "missing":
            return False, []
        return None, []


class RepositoryClusterIdentityReader:
    """Validate an active identity cluster before using its conversion key."""

    async def validate_cluster(
        self, tenant_id: str, cluster_id: str
    ) -> tuple[Optional[bool], list[EvidenceRef]]:
        try:
            from identity.identity.repository import IdentityResolutionRepository

            row = await IdentityResolutionRepository().get_cluster_for_tenant(
                tenant_id, cluster_id
            )
        except Exception:  # noqa: BLE001 - identity authority outage is unknown
            return None, []
        if row is None:
            return False, []
        if (
            row.get("tenant_id") != tenant_id
            or row.get("id") != cluster_id
            or row.get("status") != "active"
            or not _inventory_text(row.get("canonical_entity_id"), limit=128)
        ):
            return False, []
        ref = EvidenceRef(
            id=cluster_id,
            type="entity",
            source="identity_clusters_v2",
            observedAt=_inventory_iso(row.get("updated_at") or row.get("created_at")),
            uri=f"store://identity_clusters_v2/{quote(cluster_id, safe='')}",
        )
        return True, [ref]


def _attribution_timestamp(value: Any) -> Optional[str]:
    """Normalize an aware canonical timestamp, preserving missing as unknown."""
    if isinstance(value, datetime):
        value = value.isoformat()
    parsed, valid = _inventory_bound(value)
    return parsed.isoformat() if valid and parsed is not None else None


def _attribution_uuid(value: Any) -> Optional[str]:
    """Accept only canonical UUID identifiers for conversion/run/credit joins."""
    from uuid import UUID

    text = _inventory_text(value, limit=64)
    if text is None:
        return None
    try:
        UUID(text)
    except (TypeError, ValueError, AttributeError):
        return None
    return text


def _attribution_confidence(value: Any) -> Optional[float]:
    """Keep only finite confidence values in the canonical probability range."""
    if value is None or isinstance(value, bool):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not 0 <= confidence <= 1:
        return None
    return confidence


def _attribution_run_ref(run_id: str, completed_at: Optional[str]) -> EvidenceRef:
    return EvidenceRef(
        id=run_id,
        type="model_output",
        source="attribution_runs",
        observedAt=completed_at,
        uri=f"store://attribution_runs/{quote(run_id, safe='')}",
    )


def _attribution_credit_ref(credit_id: str, created_at: Optional[str]) -> EvidenceRef:
    return EvidenceRef(
        id=credit_id,
        type="model_output",
        source="attribution_credits",
        observedAt=created_at,
        uri=f"store://attribution_credits/{quote(credit_id, safe='')}",
    )


def _attribution_model_validation_ref(decision_id: str, created_at: Optional[str]) -> EvidenceRef:
    return EvidenceRef(
        id=decision_id,
        type="model_output",
        source="attribution_model_validation_decisions",
        observedAt=created_at,
        uri=f"store://attribution_model_validation_decisions/{quote(decision_id, safe='')}",
    )


def _value_model_approval_ref(decision_id: str, created_at: Optional[str]) -> EvidenceRef:
    return EvidenceRef(
        id=decision_id,
        type="annotation",
        source="value_model_approval_decisions",
        observedAt=created_at,
        uri=f"store://value_model_approval_decisions/{quote(decision_id, safe='')}",
    )


def _campaign_touchpoint_ref(
    touchpoint_id: str,
    received_at: Optional[str],
) -> EvidenceRef:
    """Reference the exact canonical tenant touchpoint row used for a credit join."""
    return EvidenceRef(
        id=touchpoint_id,
        type="event",
        source=(
            "services/api/journeys/measurement/repositories/touchpoint_repo.py:"
            "silver_campaign_touchpoint_facts"
        ),
        observedAt=received_at,
        uri=f"store://silver_campaign_touchpoint_facts/{quote(touchpoint_id, safe='')}",
    )


class RepositoryAttributionCreditReader:
    """Read active attribution runs and credits for exact canonical conversions.

    The reader never joins by campaign name, amount, timestamp, source label, or
    agent correlation. A conversion row's exact canonical UUID is the only
    bridge from a Value subject to attribution credit rows.
    """

    async def read(self, tenant_id: str, conversion_ids: list[str]) -> dict[str, Any]:
        from uuid import UUID

        requested_ids: list[str] = []
        invalid_ids = 0
        for raw_id in conversion_ids:
            try:
                conversion_id = str(UUID(str(raw_id)))
            except (TypeError, ValueError, AttributeError):
                invalid_ids += 1
                continue
            if conversion_id not in requested_ids:
                requested_ids.append(conversion_id)

        truncated = len(requested_ids) > _MAX_ATTRIBUTION_CONVERSIONS
        scoped_ids = requested_ids[:_MAX_ATTRIBUTION_CONVERSIONS]
        base: dict[str, Any] = {
            "tenantId": tenant_id,
            "conversionIds": scoped_ids,
            "canonicalAuthorityRefs": [
                "attribution_runs",
                "attribution_credits",
                "campaign_touchpoints",
            ],
            "state": "unknown",
            "reason": "canonical_active_attribution_run_unavailable",
            "completeness": "unknown",
            "records": [],
            "runs": [],
            "evidenceRefs": [],
            "freshness": {
                "state": "unknown",
                "reason": "attribution_freshness_threshold_not_configured",
            },
            "limitations": [
                "credit_weights_are_canonical_model_outputs_not_independently_measured_value",
                "attributed_revenue_and_agent_roi_are_not_inferred_or_projected",
                "historical_attribution_state_is_not_bitemporal",
                "touchpoint_joins_require_exact_tenant_scoped_credit_touchpoint_ids",
                "touchpoint_rows_are_current_and_not_bitemporal",
            ],
        }
        if not scoped_ids:
            return {
                **base,
                "reason": "canonical_conversion_ids_unavailable_for_attribution_join",
            }

        try:
            from journeys.measurement.repositories.attribution_run_repo import (
                AttributionRunRepository,
            )
            from journeys.measurement.repositories.touchpoint_repo import TouchpointRepository
            from value.economic.attribution_model_validation import (
                AttributionModelValidationRepository,
                ValueModelApprovalRepository,
                _decision_for,
                _same_decision,
            )

            repository = AttributionRunRepository()
            touchpoint_repository = TouchpointRepository()
            validation_repository = AttributionModelValidationRepository()
            approval_repository = ValueModelApprovalRepository()
            runs: list[dict[str, Any]] = []
            records: list[dict[str, Any]] = []
            refs: list[EvidenceRef] = []
            missing_run_ids: list[str] = []
            invalid_rows = invalid_ids
            errors = 0
            unresolved_touchpoints = 0
            invalid_touchpoints = 0
            touchpoint_errors = 0
            touchpoint_reads = 0
            touchpoint_truncated = False
            credit_rows_examined = 0
            credit_truncated = False

            for conversion_id in scoped_ids:
                try:
                    run = await repository.get_active_run(tenant_id, conversion_id)
                except Exception:  # noqa: BLE001 - keep partial evidence on source faults
                    errors += 1
                    continue
                if run is None:
                    missing_run_ids.append(conversion_id)
                    continue
                run_id = _attribution_uuid(run.get("attribution_run_id"))
                if (
                    run.get("tenant_id") != tenant_id
                    or str(run.get("conversion_id", "")) != conversion_id
                    or run.get("is_active") is not True
                    or run.get("status") != "complete"
                    or run_id is None
                ):
                    invalid_rows += 1
                    continue
                completed_at = _attribution_timestamp(run.get("completed_at"))
                run_ref = _attribution_run_ref(run_id, completed_at)
                governance: dict[str, Any] = {
                    "state": "unknown",
                    "reason": "exact_model_validation_decision_unavailable",
                    "calibrationState": "unvalidated",
                }
                config_id = _attribution_uuid(run.get("model_config_id"))
                if config_id:
                    try:
                        decision = await validation_repository.get(tenant_id, run_id)
                        config = await repository.get_model_config(tenant_id, config_id)
                        expected = (
                            _decision_for(tenant_id, run, config)
                            if isinstance(config, dict) else None
                        )
                        if (
                            isinstance(decision, dict)
                            and expected is not None
                            and _same_decision(decision, expected)
                        ):
                            decision_ref = _attribution_model_validation_ref(
                                decision["decision_id"],
                                _attribution_timestamp(decision.get("created_at")),
                            )
                            governance = {
                                "state": "validated",
                                "validationState": "exact_config_lineage_validated",
                                "calibrationState": "unvalidated",
                                "modelConfigId": config_id,
                                "decisionId": decision["decision_id"],
                                "configSnapshotSha256": decision["config_snapshot_sha256"],
                                "evidenceRef": decision_ref.model_dump(mode="json"),
                                "approvalState": "unknown",
                            }
                            refs.append(decision_ref)
                            approval = await approval_repository.latest(tenant_id, run_id)
                            if (
                                isinstance(approval, dict)
                                and approval.get("tenant_id") == tenant_id
                                and _attribution_uuid(approval.get("attribution_run_id")) == run_id
                                and _attribution_uuid(approval.get("model_config_id")) == config_id
                                and approval.get("model_type") == run.get("model_type")
                                and approval.get("model_version") == run.get("model_version")
                                and approval.get("validation_decision_id") == decision.get("decision_id")
                                and approval.get("decision") in {"approved", "rejected"}
                                and isinstance(approval.get("actor_id"), str)
                                and bool(approval.get("actor_id"))
                                and isinstance(approval.get("reason"), str)
                                and bool(approval.get("reason"))
                            ):
                                approval_ref = _value_model_approval_ref(
                                    approval["decision_id"],
                                    _attribution_timestamp(approval.get("created_at")),
                                )
                                governance["approvalState"] = approval["decision"]
                                governance["approvalActorId"] = approval["actor_id"]
                                governance["approvalReason"] = approval["reason"]
                                governance["approvalEvidenceRef"] = approval_ref.model_dump(mode="json")
                                refs.append(approval_ref)
                    except Exception:  # noqa: BLE001 - unavailable governance stays unknown
                        governance["reason"] = "exact_model_validation_read_failed"
                runs.append(
                    {
                        "tenantId": tenant_id,
                        "conversionId": conversion_id,
                        "attributionRunId": run_id,
                        "modelType": _inventory_text(run.get("model_type"), limit=128),
                        "modelVersion": _inventory_text(run.get("model_version"), limit=128),
                        "status": _inventory_text(run.get("status"), limit=64),
                        "completedAt": completed_at,
                        "dataWatermark": _attribution_timestamp(run.get("data_watermark")),
                        "modelConfidence": _attribution_confidence(run.get("model_confidence")),
                        "modelGovernance": governance,
                        "evidenceRef": run_ref.model_dump(mode="json"),
                    }
                )
                refs.append(run_ref)
                remaining_credits = _MAX_ATTRIBUTION_CREDITS_TOTAL - credit_rows_examined
                if remaining_credits <= 0:
                    credit_truncated = True
                    continue
                credit_limit = min(_MAX_ATTRIBUTION_CREDITS_PER_RUN, remaining_credits)
                try:
                    credits = await repository.list_credits_for_run(
                        tenant_id, run_id, limit=credit_limit + 1
                    )
                except Exception:  # noqa: BLE001 - run evidence remains, credits degrade
                    errors += 1
                    continue
                if not isinstance(credits, list):
                    invalid_rows += 1
                    continue
                if len(credits) > credit_limit:
                    credit_truncated = True
                for credit in credits[:credit_limit]:
                    credit_rows_examined += 1
                    if (
                        not isinstance(credit, dict)
                        or credit.get("tenant_id") != tenant_id
                        or str(credit.get("conversion_id", "")) != conversion_id
                        or str(credit.get("attribution_run_id", "")) != run_id
                    ):
                        invalid_rows += 1
                        continue
                    credit_id = _attribution_uuid(credit.get("credit_id"))
                    weight = _inventory_amount(credit.get("credit_weight"))
                    weight_value = _to_decimal(weight)
                    if (
                        credit_id is None
                        or weight_value is None
                        or not weight_value.is_finite()
                        or weight_value < 0
                        or weight_value > 1
                    ):
                        invalid_rows += 1
                        continue
                    created_at = _attribution_timestamp(credit.get("created_at"))
                    credit_ref = _attribution_credit_ref(credit_id, created_at)
                    refs.append(credit_ref)
                    touchpoint_ref: Optional[EvidenceRef] = None
                    raw_touchpoint_id = _inventory_text(credit.get("touchpoint_id"), limit=64)
                    touchpoint_id = _attribution_uuid(raw_touchpoint_id)
                    canonical_touchpoint: Optional[dict[str, Any]] = None
                    touchpoint_join: dict[str, Any] = {
                        "state": "unknown",
                        "reason": "attribution_credit_touchpoint_id_unavailable",
                    }
                    if raw_touchpoint_id is not None and touchpoint_id is None:
                        invalid_touchpoints += 1
                        touchpoint_join = {
                            "state": "degraded",
                            "reason": "attribution_credit_touchpoint_id_invalid",
                        }
                    elif touchpoint_id is not None:
                        # Normalize UUID text before the repository lookup so
                        # uppercase and lowercase UUID spellings resolve to
                        # the same canonical identifier.
                        from uuid import UUID

                        touchpoint_id = str(UUID(touchpoint_id))
                        if touchpoint_reads >= _MAX_ATTRIBUTION_TOUCHPOINT_READS:
                            touchpoint_truncated = True
                            unresolved_touchpoints += 1
                            touchpoint_join = {
                                "state": "unknown",
                                "reason": "canonical_touchpoint_read_limit_reached",
                            }
                        else:
                            touchpoint_reads += 1
                            try:
                                touchpoint = await touchpoint_repository.get(
                                    tenant_id, touchpoint_id
                                )
                            except Exception:  # noqa: BLE001 - keep credit evidence, degrade join
                                touchpoint = None
                                touchpoint_errors += 1
                                touchpoint_join = {
                                    "state": "missing",
                                    "reason": "canonical_touchpoint_read_failed",
                                }
                            if touchpoint is None:
                                if touchpoint_join.get("state") != "missing":
                                    unresolved_touchpoints += 1
                                    touchpoint_join = {
                                        "state": "unknown",
                                        "reason": "canonical_touchpoint_not_found",
                                    }
                            elif (
                                not isinstance(touchpoint, dict)
                                or touchpoint.get("tenant_id") != tenant_id
                                or _attribution_uuid(touchpoint.get("touchpoint_id"))
                                != touchpoint_id
                            ):
                                invalid_touchpoints += 1
                                touchpoint_join = {
                                    "state": "degraded",
                                    "reason": "canonical_touchpoint_scope_or_identifier_mismatch",
                                }
                            else:
                                credit_campaign_id = _inventory_text(
                                    credit.get("campaign_id"), limit=128
                                )
                                touchpoint_campaign_id = _inventory_text(
                                    touchpoint.get("campaign_id"), limit=128
                                )
                                if (
                                    credit_campaign_id is not None
                                    and touchpoint_campaign_id is not None
                                    and credit_campaign_id != touchpoint_campaign_id
                                ):
                                    invalid_touchpoints += 1
                                    touchpoint_join = {
                                        "state": "conflict",
                                        "reason": "attribution_credit_campaign_does_not_match_touchpoint",
                                    }
                                else:
                                    touchpoint_observed_at = _attribution_timestamp(
                                        touchpoint.get("received_at")
                                    )
                                    touchpoint_ref = _campaign_touchpoint_ref(
                                        touchpoint_id, touchpoint_observed_at
                                    )
                                    refs.append(touchpoint_ref)
                                    canonical_touchpoint = {
                                        "tenantId": tenant_id,
                                        "touchpointId": touchpoint_id,
                                        "campaignId": touchpoint_campaign_id,
                                        "occurredAt": _attribution_timestamp(
                                            touchpoint.get("occurred_at")
                                        ),
                                        "evidenceRef": touchpoint_ref.model_dump(mode="json"),
                                    }
                                    touchpoint_join = {
                                        "state": "resolved",
                                        "joinBasis": "exact_tenant_scoped_credit_touchpoint_id",
                                    }
                    else:
                        unresolved_touchpoints += 1
                    records.append(
                        {
                            "tenantId": tenant_id,
                            "conversionId": conversion_id,
                            "attributionRunId": run_id,
                            "creditId": credit_id,
                            "touchpointId": _inventory_text(credit.get("touchpoint_id")),
                            "touchpointJoin": touchpoint_join,
                            "canonicalTouchpoint": canonical_touchpoint,
                            "campaignId": _inventory_text(credit.get("campaign_id")),
                            "channel": _inventory_text(credit.get("channel"), limit=128),
                            "source": _inventory_text(credit.get("source"), limit=128),
                            "sourceClass": _inventory_text(credit.get("source_class"), limit=128),
                            "actorType": _inventory_text(credit.get("actor_type"), limit=64),
                            "journeyRole": _inventory_text(credit.get("journey_role"), limit=128),
                            "attributionEligible": (
                                credit.get("attribution_eligible")
                                if isinstance(credit.get("attribution_eligible"), bool)
                                else None
                            ),
                            "creditWeight": format(weight_value, "f"),
                            "evidenceConfidence": _attribution_confidence(
                                credit.get("evidence_confidence")
                            ),
                            "identityConfidence": _attribution_confidence(
                                credit.get("identity_confidence")
                            ),
                            "modelConfidence": _attribution_confidence(
                                credit.get("model_confidence")
                            ),
                            "modelGovernance": governance,
                            "verificationLevel": _inventory_text(
                                credit.get("verification_level"), limit=64
                            ),
                            "sourceClassifierVersion": _inventory_text(
                                credit.get("source_classifier_version"), limit=128
                            ),
                            "createdAt": created_at,
                            "evidenceRefs": [
                                run_ref.model_dump(mode="json"),
                                credit_ref.model_dump(mode="json"),
                                *([governance["evidenceRef"]] if governance.get("state") == "validated" else []),
                                *(
                                    [touchpoint_ref.model_dump(mode="json")]
                                    if touchpoint_ref is not None
                                    else []
                                ),
                            ],
                        }
                    )

            distinct_times = [run.get("completedAt") for run in runs if run.get("completedAt")]
            ordered_times = sorted(distinct_times)
            freshness = {
                "state": "unknown",
                "reason": "attribution_freshness_threshold_not_configured",
                "completedAtCoverage": round(len(distinct_times) / len(scoped_ids), 4),
                "oldestCompletedAt": ordered_times[0] if ordered_times else None,
                "latestCompletedAt": ordered_times[-1] if ordered_times else None,
            }
            touchpoint_incomplete = bool(
                unresolved_touchpoints or invalid_touchpoints or touchpoint_errors or touchpoint_truncated
            )
            incomplete = (
                truncated
                or bool(missing_run_ids)
                or bool(invalid_rows)
                or bool(errors)
                or touchpoint_incomplete
                or credit_truncated
            )
            if errors and not runs:
                state = "missing"
                reason = "canonical_attribution_credit_read_failed"
            elif records:
                state = "degraded" if incomplete else "available"
                reason = (
                    "canonical_attribution_credits_partial"
                    if incomplete
                    else None
                )
            elif runs and not incomplete:
                state = "empty"
                reason = "active_attribution_runs_have_no_credit_rows"
            elif runs:
                state = "degraded"
                reason = "canonical_attribution_run_coverage_partial"
            else:
                state = "unknown"
                reason = "canonical_active_attribution_run_unavailable"
            if invalid_rows:
                reason = "canonical_attribution_credit_scope_or_record_invalid"
            elif invalid_touchpoints:
                reason = "canonical_attribution_touchpoint_scope_or_record_invalid"
            elif touchpoint_errors:
                reason = "canonical_attribution_touchpoint_read_failed"
            elif touchpoint_truncated:
                reason = "canonical_attribution_touchpoint_read_truncated"
            elif credit_truncated:
                reason = "canonical_attribution_credit_read_truncated"
            elif unresolved_touchpoints:
                reason = "canonical_attribution_touchpoint_join_partial"
            elif truncated:
                reason = "canonical_attribution_conversion_inventory_truncated"
            elif missing_run_ids and records:
                reason = "canonical_attribution_run_missing_for_some_conversions"
            return {
                **base,
                "state": state,
                "reason": reason,
                "completeness": (
                    "complete" if state in {"available", "empty"}
                    else "partial" if state == "degraded"
                    else "unknown"
                ),
                "records": records,
                "runs": runs,
                "evidenceRefs": [ref.model_dump(mode="json") for ref in refs],
                "freshness": freshness,
                "unresolvedConversionIds": missing_run_ids,
                "invalidRowCount": invalid_rows,
                "readErrorCount": errors,
                "creditRowsExamined": credit_rows_examined,
                "creditReadTruncated": credit_truncated,
                "touchpointReadCount": touchpoint_reads,
                "unresolvedTouchpointCount": unresolved_touchpoints,
                "invalidTouchpointCount": invalid_touchpoints,
                "touchpointReadErrorCount": touchpoint_errors,
                "touchpointReadTruncated": touchpoint_truncated,
            }
        except Exception:  # noqa: BLE001 - adapter failure is explicit missing data
            return {
                **base,
                "state": "missing",
                "reason": "canonical_attribution_credit_repository_unavailable",
            }


def _inventory_text(value: Any, *, limit: int = 512) -> Optional[str]:
    """Return a bounded scalar identifier without coercing missing values."""
    if value is None:
        return None
    if hasattr(value, "value") and isinstance(value.value, str):
        value = value.value
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if (
        not value
        or len(value) > limit
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return None
    return value


def _inventory_bound(value: Any) -> tuple[Optional[datetime], bool]:
    """Parse an aware ISO timestamp bound; naive or malformed bounds fail closed."""
    if value is None:
        return None, True
    if not isinstance(value, str):
        return None, False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, False
    if parsed.tzinfo is None:
        return None, False
    return parsed.astimezone(timezone.utc), True


def _inventory_occurred_at(row: dict[str, Any]) -> Optional[datetime]:
    raw = row.get("occurred_at")
    if isinstance(raw, (datetime, str)):
        parsed = coerce_utc_lenient(raw)
        return parsed.astimezone(timezone.utc) if parsed else None
    return None


def _inventory_iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return _inventory_text(value, limit=128)


def _inventory_amount(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except Exception:  # noqa: BLE001 - malformed amount stays unknown
        return None
    return format(amount, "f") if amount.is_finite() else None


def _inventory_evidence_refs(value: Any) -> list[EvidenceRef]:
    if not isinstance(value, list):
        return []
    refs: list[EvidenceRef] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in value:
        try:
            ref = EvidenceRef.model_validate(raw)
        except Exception:  # noqa: BLE001 - malformed source evidence fails closed
            continue
        expected_uri = f"store://canonical_conversions/{quote(ref.id, safe='')}"
        if (
            ref.source != "canonical_conversions"
            or ref.type != "transaction"
            or ref.uri != expected_uri
        ):
            continue
        key = (ref.id, ref.type, ref.source)
        if key not in seen:
            refs.append(ref)
            seen.add(key)
    return refs


def _value_ltv_observation(
    request: ProjectionRequest,
    conversion_inventory: dict[str, Any],
) -> dict[str, Any]:
    """Summarize exact canonical net conversion values without currency guessing.

    The measure is deliberately an observed net-value subtotal over the
    requested occurred-at window (or the current canonical rows returned for
    the subject). The repository cannot prove complete customer-lifecycle
    coverage, so this function never emits a scalar LTV amount. Native values
    stay partitioned by currency as supporting observations only.
    """
    inventory_state = conversion_inventory.get("state")
    inventory_reason = conversion_inventory.get("reason")
    inventory_completeness = conversion_inventory.get("completeness") or "unknown"
    inventory_time_scope = conversion_inventory.get("timeScope")
    time_range = request.timeRange
    explicit_window = time_range is not None
    time_scope = {
        "mode": (
            "explicit_occurred_at_window"
            if explicit_window
            else "all_current_canonical_conversion_rows"
        ),
        "boundarySemantics": "strictly_after_from_and_strictly_before_to",
        "fromExclusive": time_range.from_ if time_range else None,
        "toExclusive": time_range.to if time_range else None,
        "historicalState": "unknown",
        "lifetimeCompleteness": "unknown",
        "observedAtFrom": None,
        "observedAtTo": None,
    }
    if isinstance(inventory_time_scope, dict):
        # Preserve the canonical reader's actual query bounds and temporal
        # limitation while making the LTV slot's boundary semantics explicit.
        time_scope["fromExclusive"] = (
            time_range.from_
            if time_range and time_range.from_ is not None
            else inventory_time_scope.get("occurredAtFrom")
        )
        time_scope["toExclusive"] = (
            time_range.to
            if time_range and time_range.to is not None
            else inventory_time_scope.get("occurredAtTo")
        )
        time_scope["historicalState"] = inventory_time_scope.get("historicalState", "unknown")

    base: dict[str, Any] = {
        "tenantId": request.tenantId,
        "subject": request.subject.model_dump(),
        "canonicalAuthority": "canonical_conversions",
        "canonicalAuthorityRefs": ["canonical_conversions"],
        "joinBasis": conversion_inventory.get("joinBasis"),
        "freshness": conversion_inventory.get("freshness")
        or {"state": "unknown", "reason": "conversion_freshness_threshold_not_configured"},
        "state": "unknown",
        "reason": None,
        "measure": "observed_confirmed_adjusted_net_conversion_value",
        "amount": None,
        "currency": None,
        "amountBasis": None,
        "observedNetValueByCurrency": {},
        "eligibleConversionCount": 0,
        "excludedNonFinalCount": 0,
        "missingNetValueCount": 0,
        "undatedConversionCount": 0,
        "outOfWindowConversionCount": 0,
        "sourceCompleteness": inventory_completeness,
        "completeness": "unknown",
        "coverage": {"knownNetValueCount": 0, "eligibleConversionCount": 0, "ratio": None},
        "timeScope": time_scope,
        "evidenceRefs": [],
        "limitations": [
            "current_canonical_conversion_rows_are_not_bitemporal",
            "lifetime_completeness_and_measurement_outcome_linkage_are_unknown",
            "native_currency_totals_are_never_added_across_currencies",
        ],
    }
    if request.subject.kind == "conversion":
        return {**base, "reason": "ltv_requires_a_lifecycle_subject_not_a_single_conversion"}
    if request.subject.kind not in {
        "profile",
        "entity",
        "account",
        "cluster",
        "campaign",
        "journey",
        "agent",
    }:
        return {**base, "reason": "canonical_conversion_subject_join_unavailable_for_ltv"}

    if inventory_state not in {"available", "degraded", "empty"}:
        return {
            **base,
            "state": "missing" if inventory_state == "missing" else "unknown",
            "reason": inventory_reason or "canonical_conversion_inventory_not_available_for_ltv",
        }
    expected_join_basis = _LTV_JOIN_BASIS_BY_SUBJECT_KIND.get(request.subject.kind)
    if not expected_join_basis or conversion_inventory.get("joinBasis") != expected_join_basis:
        return {
            **base,
            "state": "unknown",
            "reason": "canonical_conversion_subject_join_unverified_for_ltv",
        }

    records = conversion_inventory.get("records")
    if not isinstance(records, list):
        return {**base, "state": "unknown", "reason": "canonical_conversion_inventory_result_invalid"}
    if inventory_state == "empty" and not records:
        return {
            **base,
            "state": "empty",
            "reason": inventory_reason or "no_canonical_conversion_rows_for_exact_subject",
            "completeness": "unknown",
        }

    evidence_by_id = {
        ref.id: ref
        for ref in _inventory_evidence_refs(conversion_inventory.get("evidenceRefs"))
    }
    totals: dict[str, Decimal] = {}
    eligible_refs: list[EvidenceRef] = []
    eligible_count = 0
    excluded_non_final = 0
    missing_net = 0
    known_net_count = 0
    malformed_rows = 0
    undated_count = 0
    out_of_window_count = 0
    seen_ids: set[str] = set()
    after, after_ok = _inventory_bound(time_range.from_ if time_range else None)
    before, before_ok = _inventory_bound(time_range.to if time_range else None)
    if not after_ok or not before_ok or (after is not None and before is not None and after >= before):
        return {**base, "state": "unknown", "reason": "conversion_inventory_time_range_invalid"}
    observed_times: list[datetime] = []

    for row in records:
        if not isinstance(row, dict):
            malformed_rows += 1
            continue
        conversion_id = _inventory_text(row.get("conversionId"), limit=128)
        if not conversion_id or conversion_id in seen_ids:
            malformed_rows += 1
            continue
        seen_ids.add(conversion_id)
        ref = evidence_by_id.get(conversion_id)
        if ref is None:
            malformed_rows += 1
            continue
        status = str(row.get("status") or "").strip().lower()
        if status not in {"confirmed", "adjusted"}:
            excluded_non_final += 1
            continue
        eligible_count += 1
        occurred = coerce_utc_lenient(row.get("occurredAt"))
        if occurred is None:
            undated_count += 1
            continue
        occurred = occurred.astimezone(timezone.utc)
        if (after is not None and occurred <= after) or (before is not None and occurred >= before):
            out_of_window_count += 1
            continue
        observed_times.append(occurred)
        record_refs = _inventory_evidence_refs(row.get("evidenceRefs"))
        if not any(record_ref.id == conversion_id for record_ref in record_refs):
            # The provider-level inventory validator normally guarantees this;
            # retain a fail-closed check at the value calculation boundary.
            malformed_rows += 1
            continue
        eligible_refs.append(ref)
        amount = _inventory_amount(row.get("netValue"))
        currency = _inventory_text(row.get("currency"), limit=16)
        if amount is None or currency is None:
            missing_net += 1
            continue
        currency = currency.upper()
        totals[currency] = totals.get(currency, Decimal("0")) + Decimal(amount)
        known_net_count += 1

    native_totals = {currency: format(total, "f") for currency, total in sorted(totals.items())}
    if observed_times:
        time_scope["observedAtFrom"] = min(observed_times).isoformat()
        time_scope["observedAtTo"] = max(observed_times).isoformat()
    state = "available"
    reason = None
    source_read_partial = (
        inventory_state != "available" or inventory_completeness != "complete"
    )
    if source_read_partial or malformed_rows or missing_net or undated_count or out_of_window_count:
        state = "degraded"
        reason = (
            str(inventory_reason)
            if source_read_partial and inventory_reason
            else "canonical_ltv_conversion_inventory_partial"
            if source_read_partial
            else "canonical_ltv_conversion_coverage_partial"
        )
    elif eligible_count == 0:
        state = "empty"
        reason = "no_confirmed_or_adjusted_conversion_rows_for_ltv"
    else:
        # The exact conversion query proves row membership, but not that every
        # source event in this subject's lifetime has reached the ledger.
        state = "degraded"
        reason = "canonical_ltv_lifecycle_coverage_not_proven"

    completeness = (
        "partial"
        if state == "degraded"
        else "unknown"
        if state == "empty"
        else inventory_completeness
    )
    unique_refs_by_key = {
        (ref.id, ref.type, ref.source): ref
        for ref in eligible_refs
    }
    unique_refs = list(unique_refs_by_key.values())
    return {
        **base,
        "state": state,
        "reason": reason,
        # Current conversion value is evidence for LTV, not a full LTV result.
        "amount": None,
        "currency": None,
        "amountBasis": None,
        "observedNetValueByCurrency": native_totals,
        "eligibleConversionCount": eligible_count,
        "excludedNonFinalCount": excluded_non_final,
        "missingNetValueCount": missing_net,
        "undatedConversionCount": undated_count,
        "outOfWindowConversionCount": out_of_window_count,
        "sourceCompleteness": inventory_completeness,
        "completeness": completeness,
        "coverage": {
            "knownNetValueCount": known_net_count,
            "eligibleConversionCount": eligible_count,
            "ratio": round(known_net_count / eligible_count, 4) if eligible_count else None,
        },
        "timeScope": time_scope,
        "evidenceRefs": [ref.model_dump(mode="json") for ref in unique_refs],
        "limitations": [
            *base["limitations"],
            *(["multiple_native_currencies_prevent_a_single_total"] if len(totals) > 1 else []),
        ],
    }


def _attribution_evidence_refs(value: Any) -> list[EvidenceRef]:
    """Validate evidence refs against the canonical attribution/conversion stores."""
    if not isinstance(value, list):
        return []
    allowed_sources = {
        "canonical_conversions": "transaction",
        "attribution_runs": "model_output",
        "attribution_credits": "model_output",
        "attribution_model_validation_decisions": "model_output",
        (
            "services/api/journeys/measurement/repositories/touchpoint_repo.py:"
            "silver_campaign_touchpoint_facts"
        ): "event",
    }
    refs: list[EvidenceRef] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in value:
        try:
            ref = EvidenceRef.model_validate(raw)
        except Exception:  # noqa: BLE001 - malformed source evidence fails closed
            continue
        if ref.type != allowed_sources.get(ref.source):
            continue
        expected_uri = (
            f"store://silver_campaign_touchpoint_facts/{quote(ref.id, safe='')}"
            if ref.source.startswith(
                "services/api/journeys/measurement/repositories/touchpoint_repo.py:"
            )
            else f"store://{ref.source}/{quote(ref.id, safe='')}"
        )
        if ref.uri != expected_uri:
            continue
        key = (ref.id, ref.type, ref.source)
        if key not in seen:
            refs.append(ref)
            seen.add(key)
    return refs


class RepositoryConversionInventoryReader:
    """Read exact conversion records from the canonical conversion ledger.

    This reader does not turn Outcome360 IDs into conversion IDs. It uses only
    explicit ledger keys, a current journey version's recorded conversion ID
    list, or canonical campaign/profile/cluster subject queries. The repository
    does not expose a coordinated bitemporal snapshot, so historical/as-of and
    comparison requests remain unknown.
    """

    def __init__(
        self,
        *,
        agent_identity_reader: Optional[AgentIdentityReader] = None,
        account_identity_reader: Optional[AccountIdentityReader] = None,
        cluster_identity_reader: Optional[ClusterIdentityReader] = None,
        campaign_identity_reader: Optional[CampaignIdentityReader] = None,
        profile_identity_reader: Optional[ProfileIdentityReader] = None,
    ) -> None:
        self._agent_identity = agent_identity_reader or RepositoryAgentIdentityReader()
        self._account_identity = account_identity_reader or RepositoryAccountIdentityReader()
        self._cluster_identity = cluster_identity_reader or RepositoryClusterIdentityReader()
        self._campaign_identity = campaign_identity_reader or RepositoryCampaignIdentityReader()
        self._profile_identity = profile_identity_reader or RepositoryProfileIdentityReader()

    async def read(self, request: ProjectionRequest) -> dict[str, Any]:
        subject = request.subject
        base = {
            "tenantId": request.tenantId,
            "subject": subject.model_dump(),
            "canonicalAuthority": "canonical_conversions",
            "canonicalAuthorityRefs": ["canonical_conversions"],
            "measurementOutcomeLinkage": {
                "state": "unknown",
                "reason": "outcome360_rows_do_not_expose_canonical_conversion_id",
            },
            "freshness": {
                "state": "unknown",
                "reason": "conversion_freshness_threshold_not_configured",
            },
        }
        if subject.kind == "agent":
            base["agentRoster"] = {
                "identityState": "not_validated",
                "completeness": "unknown",
                "freshness": {
                    "state": "unknown",
                    "reason": "agent_roster_completeness_and_freshness_not_read",
                },
            }

        if request.asOf is not None or request.temporalMode in {"as_of", "compare", "relative"}:
            return {
                **base,
                "state": "unknown",
                "reason": "canonical_conversion_history_not_bitemporal",
                "joinBasis": None,
                "completeness": "unknown",
                "records": [],
                "evidenceRefs": [],
            }
        if request.page is not None and request.page.cursor:
            return {
                **base,
                "state": "unknown",
                "reason": "conversion_inventory_cursor_contract_unavailable",
                "joinBasis": None,
                "completeness": "unknown",
                "records": [],
                "evidenceRefs": [],
            }

        time_range = request.timeRange
        after, after_ok = _inventory_bound(time_range.from_ if time_range else None)
        before, before_ok = _inventory_bound(time_range.to if time_range else None)
        if not after_ok or not before_ok or (after is not None and before is not None and after >= before):
            return {
                **base,
                "state": "unknown",
                "reason": "conversion_inventory_time_range_invalid",
                "joinBasis": None,
                "completeness": "unknown",
                "records": [],
                "evidenceRefs": [],
            }

        limit = request.page.limit if request.page is not None else _MAX_CONVERSION_INVENTORY_ROWS
        limit = min(max(limit, 1), _MAX_CONVERSION_INVENTORY_ROWS)
        try:
            from journeys.measurement.repositories.conversion_repo import ConversionRepository

            conversions = ConversionRepository()
        except Exception:  # noqa: BLE001 - missing canonical reader is not an empty inventory
            return {
                **base,
                "state": "missing",
                "reason": "canonical_conversion_repository_unavailable",
                "joinBasis": None,
                "completeness": "unknown",
                "records": [],
                "evidenceRefs": [],
            }

        join_basis: Optional[str] = None
        rows: list[dict[str, Any]] = []
        resolved_subject = False
        truncated = False
        unresolved_ids = 0
        scope_violation = False
        account_identity_refs: list[EvidenceRef] = []
        cluster_identity_refs: list[EvidenceRef] = []
        try:
            if subject.kind == "conversion":
                join_basis = "exact_canonical_conversion_id"
                row = await conversions.get(request.tenantId, subject.id)
                if row is not None:
                    if (
                        str(row.get("tenant_id", "")) == request.tenantId
                        and str(row.get("conversion_id", "")) == subject.id
                    ):
                        rows = [row]
                        resolved_subject = True
                    else:
                        scope_violation = True

            elif subject.kind in {"profile", "entity"}:
                identity = await self._profile_identity.is_canonical_profile(
                    request.tenantId, subject.id
                )
                if identity is not True:
                    return {
                        **base,
                        "state": "unknown",
                        "reason": (
                            "profile_identity_authority_unavailable"
                            if identity is None
                            else "profile_canonical_identity_unresolved"
                        ),
                        "joinBasis": None,
                        "completeness": "unknown",
                        "records": [],
                        "evidenceRefs": [],
                    }
                join_basis = "exact_canonical_profile_conversion_id"
                rows = await conversions.list_by_profile(
                    request.tenantId,
                    subject.id,
                    identity_type="profile",
                    after_occurred=after,
                    before_occurred=before,
                    limit=limit + 1,
                )
                resolved_subject = True

            elif subject.kind == "campaign":
                identity = await self._campaign_identity.is_canonical_campaign(
                    request.tenantId, subject.id
                )
                if identity is not True:
                    return {
                        **base,
                        "state": "unknown",
                        "reason": (
                            "campaign_identity_authority_unavailable"
                            if identity is None
                            else "campaign_canonical_identity_unresolved"
                        ),
                        "joinBasis": None,
                        "completeness": "unknown",
                        "records": [],
                        "evidenceRefs": [],
                    }
                join_basis = "canonical_campaign_touchpoint_or_attribution_conversion_join"
                rows = await conversions.list_by_campaign(
                    request.tenantId,
                    subject.id,
                    after_occurred=after,
                    before_occurred=before,
                    include_unattributed=True,
                    limit=limit + 1,
                )
                if not rows:
                    # The in-memory repository adapter cannot execute the
                    # canonical touchpoint join. An empty local result is
                    # therefore unknown, not proof of an empty campaign.
                    pool_reader = getattr(conversions, "_pool", None)
                    if callable(pool_reader) and await pool_reader() is None:
                        return {
                            **base,
                            "state": "unknown",
                            "reason": "campaign_conversion_touchpoint_join_unavailable_in_local_store",
                            "joinBasis": join_basis,
                            "completeness": "unknown",
                            "records": [],
                            "evidenceRefs": [],
                        }
                resolved_subject = True

            elif subject.kind == "cluster":
                identity, cluster_identity_refs = await self._cluster_identity.validate_cluster(
                    request.tenantId, subject.id
                )
                if identity is not True or not cluster_identity_refs:
                    return {
                        **base,
                        "state": "unknown",
                        "reason": (
                            "cluster_identity_authority_unavailable"
                            if identity is None
                            else "canonical_cluster_identity_unresolved"
                        ),
                        "joinBasis": None,
                        "completeness": "unknown",
                        "records": [],
                        "evidenceRefs": [],
                    }
                base["canonicalAuthorityRefs"] = [
                    "canonical_conversions", "identity_clusters_v2"
                ]
                base["clusterIdentity"] = {
                    "state": "validated",
                    "evidenceRefs": [
                        ref.model_dump(mode="json") for ref in cluster_identity_refs
                    ],
                }
                join_basis = "exact_canonical_conversion_cluster_id"
                rows = await conversions.list_by_profile(
                    request.tenantId,
                    subject.id,
                    identity_type="cluster",
                    after_occurred=after,
                    before_occurred=before,
                    limit=limit + 1,
                )
                resolved_subject = True

            elif subject.kind == "journey":
                from journeys.measurement.repositories.journey_repo import JourneyRepository

                join_basis = "current_tenant_journey_version_conversion_ids"
                journey = await JourneyRepository().get_current(request.tenantId, subject.id)
                if not isinstance(journey, dict):
                    return {
                        **base,
                        "state": "unknown",
                        "reason": "canonical_journey_conversion_reference_unavailable",
                        "joinBasis": join_basis,
                        "completeness": "unknown",
                        "records": [],
                        "evidenceRefs": [],
                    }
                if (
                    str(journey.get("tenant_id", "")) != request.tenantId
                    or str(journey.get("journey_id", "")) != subject.id
                    or journey.get("is_current") is False
                ):
                    return {
                        **base,
                        "state": "unknown",
                        "reason": "canonical_journey_subject_scope_unresolved",
                        "joinBasis": join_basis,
                        "completeness": "unknown",
                        "records": [],
                        "evidenceRefs": [],
                    }
                conversion_ids = journey.get("conversion_ids") or []
                if isinstance(conversion_ids, str):
                    try:
                        conversion_ids = json.loads(conversion_ids)
                    except (TypeError, ValueError):
                        conversion_ids = None
                if not isinstance(conversion_ids, list):
                    conversion_ids = []
                    unresolved_ids += 1
                unique_ids = list(
                    dict.fromkeys(
                        item.strip()
                        for item in conversion_ids
                        if isinstance(item, str) and item.strip()
                    )
                )
                if len(unique_ids) != len(conversion_ids):
                    unresolved_ids += 1
                truncated = len(unique_ids) > limit
                for conversion_id in unique_ids[:limit]:
                    row = await conversions.get(request.tenantId, conversion_id)
                    if not isinstance(row, dict):
                        unresolved_ids += 1
                        continue
                    if (
                        str(row.get("tenant_id", "")) != request.tenantId
                        or str(row.get("conversion_id", "")) != conversion_id
                    ):
                        scope_violation = True
                        continue
                    rows.append(row)
                resolved_subject = True

            elif subject.kind in {"account", "agent"}:
                if subject.kind == "account":
                    identity, account_identity_refs = await self._account_identity.validate_account(
                        request.tenantId, subject.id
                    )
                    if identity is not True or not account_identity_refs:
                        return {
                            **base,
                            "state": "unknown",
                            "reason": (
                                "account_identity_authority_unavailable"
                                if identity is None
                                else "canonical_account_identity_unresolved"
                            ),
                            "joinBasis": None,
                            "completeness": "unknown",
                            "records": [],
                            "evidenceRefs": [],
                        }
                    base["canonicalAuthorityRefs"] = [
                        "canonical_conversions", "entity_registry"
                    ]
                    base["accountIdentity"] = {
                        "state": "validated",
                        "evidenceRefs": [
                            ref.model_dump(mode="json") for ref in account_identity_refs
                        ],
                    }
                if subject.kind == "agent":
                    identity = await self._agent_identity.is_canonical_agent(
                        request.tenantId, subject.id
                    )
                    if identity is not True:
                        return {
                            **base,
                            "state": "unknown",
                            "reason": (
                                "agent_identity_authority_unavailable"
                                if identity is None
                                else "agent_canonical_identity_unresolved"
                            ),
                            "joinBasis": None,
                            "completeness": "unknown",
                            "records": [],
                            "evidenceRefs": [],
                        }
                    base["agentRoster"]["identityState"] = "validated"
                if subject.kind == "account":
                    join_basis = "exact_tenant_conversion_account_id"
                    rows = await conversions.list_by_account(
                        request.tenantId,
                        subject.id,
                        after_occurred=after,
                        before_occurred=before,
                        limit=limit + 1,
                    )
                else:
                    join_basis = "validated_agent_identity_exact_conversion_agent_id"
                    rows = await conversions.list_by_agent(
                        request.tenantId,
                        subject.id,
                        after_occurred=after,
                        before_occurred=before,
                        limit=limit + 1,
                    )
                truncated = len(rows) > limit
                resolved_subject = True

            else:
                return {
                    **base,
                    "state": "unknown",
                    "reason": "canonical_conversion_subject_join_unavailable",
                    "joinBasis": None,
                    "completeness": "unknown",
                    "records": [],
                    "evidenceRefs": [],
                }
        except Exception:  # noqa: BLE001 - source outages stay visible as missing
            return {
                **base,
                "state": "missing",
                "reason": "canonical_conversion_inventory_read_failed",
                "joinBasis": join_basis,
                "completeness": "unknown",
                "records": [],
                "evidenceRefs": [],
            }

        filtered: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                unresolved_ids += 1
                continue
            if str(row.get("tenant_id", "")) != request.tenantId:
                scope_violation = True
                continue
            if subject.kind in {"conversion", "profile", "entity", "cluster", "account", "agent"}:
                expected_field = {
                    "conversion": "conversion_id",
                    "profile": "profile_id",
                    "entity": "profile_id",
                    "cluster": "cluster_id",
                    "account": "account_id",
                    "agent": "agent_id",
                }[subject.kind]
                if str(row.get(expected_field, "")) != subject.id:
                    scope_violation = True
                    continue
            occurred = _inventory_occurred_at(row)
            if (after is not None or before is not None) and occurred is None:
                unresolved_ids += 1
                continue
            if occurred is not None and (
                (after is not None and occurred <= after)
                or (before is not None and occurred >= before)
            ):
                continue
            filtered.append(row)

        if len(filtered) > limit:
            truncated = True
            filtered = filtered[:limit]
        # If a source query returned rows outside the exact subject or tenant,
        # do not silently treat the resulting partial set as exhaustive.
        partial = (
            truncated
            or bool(unresolved_ids)
            or scope_violation
        )
        if filtered:
            state = "degraded" if partial else "available"
        elif partial:
            state = "degraded"
        elif resolved_subject:
            state = "empty"
        else:
            state = "unknown"

        rendered_records: list[dict[str, Any]] = []
        evidence_refs: list[EvidenceRef] = []
        for row in filtered:
            conversion_id = _inventory_text(row.get("conversion_id"))
            if conversion_id is None:
                partial = True
                continue
            ref = EvidenceRef(
                id=conversion_id,
                type="transaction",
                source="canonical_conversions",
                observedAt=_inventory_iso(row.get("observed_at")),
                uri=f"store://canonical_conversions/{quote(conversion_id, safe='')}",
            )
            evidence_refs.append(ref)
            rendered_records.append(_render_conversion_inventory_record(row, ref))
        if partial and state == "available":
            state = "degraded"
        if not evidence_refs and state == "available":
            state = "degraded"
            partial = True
        reason = None
        if scope_violation:
            reason = "canonical_conversion_subject_scope_violation"
        elif unresolved_ids:
            reason = "canonical_conversion_references_unresolved"
        elif truncated:
            reason = "canonical_conversion_inventory_truncated"
        elif state == "empty":
            reason = "no_canonical_conversion_rows_for_exact_subject"
        elif state == "unknown":
            reason = "canonical_conversion_subject_identity_unresolved"
        completeness = (
            "complete" if state in {"available", "empty"} else "partial" if state == "degraded" else "unknown"
        )
        return {
            **base,
            "state": state,
            "reason": reason,
            "joinBasis": join_basis,
            "completeness": completeness,
            "records": rendered_records,
            "recordCount": len(rendered_records),
            "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence_refs],
            "timeScope": {
                "mode": "current_canonical_state",
                "occurredAtFrom": time_range.from_ if time_range else None,
                "occurredAtTo": time_range.to if time_range else None,
                "historicalState": "unknown",
            },
            "limitations": [
                "records_are_canonical_conversion_rows_not_outcome360_measured_outcomes",
                "missing_amounts_remain_unknown_and_values_are_not_aggregated",
            ],
        }


def _render_conversion_inventory_record(
    row: dict[str, Any], evidence_ref: EvidenceRef
) -> dict[str, Any]:
    """Render a safe value-preserving view of one canonical conversion row."""
    field_map = {
        "conversionId": "conversion_id",
        "conversionType": "conversion_type",
        "status": "conversion_status",
        "occurredAt": "occurred_at",
        "observedAt": "observed_at",
        "confirmedAt": "confirmed_at",
        "adjustedAt": "adjusted_at",
        "reversedAt": "reversed_at",
        "grossValue": "gross_value",
        "netValue": "net_value",
        "refundValue": "refund_value",
        "chargebackValue": "chargeback_value",
        "currency": "currency",
        "normalizedCurrency": "normalized_currency",
        "exchangeRate": "exchange_rate",
        "attributionEligible": "attribution_eligible",
        "conversionSource": "conversion_source",
        "sourceConnectorId": "source_connector_id",
        "sourceEventId": "source_event_id",
    }
    record: dict[str, Any] = {}
    for output, source in field_map.items():
        value = row.get(source)
        if source.endswith("_at"):
            record[output] = _inventory_iso(value)
        elif source in {
            "gross_value",
            "net_value",
            "refund_value",
            "chargeback_value",
            "exchange_rate",
        }:
            record[output] = _inventory_amount(value)
        elif isinstance(value, bool):
            record[output] = value
        else:
            record[output] = _inventory_text(value)
    record["evidenceRefs"] = [evidence_ref.model_dump(mode="json")]
    return record


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
                        "_source_incomplete_reason": (AI_EXECUTION_FACTS_SUBJECT_SCOPE_UNAVAILABLE),
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
        parsed = coerce_utc_lenient(raw)
        if parsed is None:
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


def _verified_commerce_order_refs(
    tenant_id: str,
    subject: ProjectionSubject,
    operation_evidence: dict[str, Any],
) -> dict[str, list[EvidenceRef]]:
    """Admit only order references with both subject and ledger evidence."""
    scope_field = {
        "journey": "journey_id",
        "campaign": "campaign_id",
        "entity": "entity_id",
    }.get(subject.kind)
    if scope_field is None or operation_evidence.get(scope_field) != subject.id:
        return {}
    raw_associations = operation_evidence.get("association_evidence")
    raw_links = operation_evidence.get("operation_links")
    if not isinstance(raw_associations, list) or not isinstance(raw_links, list):
        return {}

    associated: dict[str, EvidenceRef] = {}
    for association in raw_associations:
        if not isinstance(association, dict):
            continue
        order_ref = association.get("commerceOrderRef")
        if (
            not isinstance(order_ref, str)
            or not order_ref
            or len(order_ref) > 512
            or association.get("subjectKind") != subject.kind
            or association.get("subjectId") != subject.id
        ):
            continue
        evidence = association.get("evidence")
        try:
            ref = EvidenceRef.model_validate(evidence)
        except Exception:  # noqa: BLE001 - untyped activity is not a join
            continue
        if (
            ref.type != "event"
            or ref.id not in {association.get("activityId"), association.get("stepId")}
            or not ref.source
        ):
            continue
        associated.setdefault(order_ref, ref)

    ledger_backed: dict[str, list[EvidenceRef]] = {}
    for link in raw_links:
        if not isinstance(link, dict) or link.get("tenant_id") != tenant_id:
            continue
        order_ref = link.get("operation_ref")
        if (
            not isinstance(order_ref, str)
            or order_ref not in associated
            or link.get("identity_basis") != "source_shared_identifier"
        ):
            continue
        raw_refs = link.get("identity_evidence")
        if not isinstance(raw_refs, list):
            continue
        for raw_ref in raw_refs:
            try:
                ref = EvidenceRef.model_validate(raw_ref)
            except Exception:  # noqa: BLE001 - ledger evidence is required
                continue
            if (
                ref.id == order_ref
                and ref.type == "transaction"
                and ref.source == "commerce_order_payment_ledger"
            ):
                ledger_backed[order_ref] = [associated[order_ref], ref]
                break
    return ledger_backed


def _validated_commerce_operation_evidence(
    tenant_id: str,
    subject: ProjectionSubject,
    operation_evidence: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Keep only exact subject-to-order-to-payment facts in Value sections."""
    if not isinstance(operation_evidence, dict):
        return operation_evidence
    expected_basis = _COMMERCE_JOIN_BASIS_BY_SUBJECT_KIND.get(subject.kind)
    if expected_basis is None:
        return operation_evidence
    admitted = (
        _verified_commerce_order_refs(tenant_id, subject, operation_evidence)
        if operation_evidence.get("join_basis") == expected_basis
        else {}
    )
    raw_facts = operation_evidence.get("payment_facts")
    raw_links = operation_evidence.get("operation_links")
    raw_associations = operation_evidence.get("association_evidence")
    if (
        raw_facts == []
        and raw_links == []
        and raw_associations is None
        and operation_evidence.get("reason")
    ):
        return {**operation_evidence, "association_evidence": []}
    if not all(isinstance(rows, list) for rows in (raw_facts, raw_links, raw_associations)):
        return {
            **operation_evidence,
            "payment_facts": [],
            "operation_links": [],
            "association_evidence": [],
            "reason": "commerce_operation_evidence_contract_invalid",
            "evidence_truncated": True,
        }

    facts: list[dict[str, Any]] = []
    for fact in raw_facts:
        if (
            not isinstance(fact, dict)
            or fact.get("commerceOrderRef") not in admitted
            or fact.get("joinBasis") != expected_basis
            or not isinstance(fact.get("evidence"), list)
        ):
            continue
        try:
            refs = [EvidenceRef.model_validate(ref) for ref in fact["evidence"]]
        except Exception:  # noqa: BLE001 - untyped source evidence is not a payment join
            continue
        if not any(
            ref.id == fact.get("evidenceRecordId")
            and ref.source == fact.get("provider")
            and ref.type == "transaction"
            for ref in refs
        ):
            continue
        facts.append(fact)

    links = [
        link
        for link in raw_links
        if isinstance(link, dict)
        and link.get("tenant_id") == tenant_id
        and link.get("operation_ref") in admitted
    ]
    associations = [
        association
        for association in raw_associations
        if isinstance(association, dict)
        and association.get("commerceOrderRef") in admitted
        and association.get("subjectKind") == subject.kind
        and association.get("subjectId") == subject.id
    ]
    incomplete = (
        operation_evidence.get("join_basis") != expected_basis
        or len(facts) != len(raw_facts)
        or len(links) != len(raw_links)
        or len(associations) != len(raw_associations)
    )
    return {
        **operation_evidence,
        "payment_facts": facts,
        "operation_links": links,
        "association_evidence": associations,
        "reason": (
            "commerce_operation_evidence_scope_or_provenance_invalid"
            if incomplete
            else operation_evidence.get("reason")
        ),
        "evidence_truncated": bool(operation_evidence.get("evidence_truncated") or incomplete),
    }


def _commerce_fact_claims(
    tenant_id: str,
    subject: ProjectionSubject,
    operation_evidence: Optional[dict[str, Any]],
) -> list[ClaimEnvelope]:
    """Expose exact-reference commerce facts as evidence-backed Value360 claims.

    This accepts only the subject-specific explicit-reference joins produced
    by ``journey_operation_evidence``. An amount, timestamp, order ID, or
    payment ID alone never creates a claim, and a fact without a canonical
    transaction EvidenceRef remains section data only.
    """
    if not isinstance(operation_evidence, dict):
        return []
    expected_join_basis = _COMMERCE_JOIN_BASIS_BY_SUBJECT_KIND.get(subject.kind)
    if expected_join_basis is None or operation_evidence.get("join_basis") != expected_join_basis:
        return []
    admitted_order_refs = _verified_commerce_order_refs(
        tenant_id, subject, operation_evidence
    )
    if not admitted_order_refs:
        return []

    payment_facts = operation_evidence.get("payment_facts")
    if not isinstance(payment_facts, list):
        return []

    claims: list[ClaimEnvelope] = []
    seen_fact_ids: set[str] = set()
    for fact in payment_facts:
        if not isinstance(fact, dict):
            continue
        fact_id = fact.get("factId")
        fact_kind = fact.get("kind")
        amount = fact.get("amount")
        currency = fact.get("currency")
        if (
            not isinstance(fact_id, str)
            or not fact_id.strip()
            or fact_id in seen_fact_ids
            or not isinstance(fact_kind, str)
            or fact_kind.strip() not in {"order", "payment", "adjustment", "settlement"}
            or not isinstance(amount, str)
            or not amount.strip()
            or not isinstance(currency, str)
            or not currency.strip()
            or len(fact_id) > 512
            or len(amount.strip()) > 128
            or not currency.strip().isascii()
            or not currency.strip().isalnum()
            or len(currency.strip()) > 16
            or not fact_id.startswith("commerce:")
            or fact.get("joinBasis", expected_join_basis) != expected_join_basis
            or fact.get("commerceOrderRef") not in admitted_order_refs
        ):
            continue
        amount_value = _to_decimal(amount)
        if amount_value is None or not amount_value.is_finite():
            continue

        raw_evidence = fact.get("evidence")
        if not isinstance(raw_evidence, list):
            continue
        fact_evidence: list[EvidenceRef] = []
        seen_evidence_ids: set[str] = set()
        for raw_ref in raw_evidence:
            try:
                evidence_ref = EvidenceRef.model_validate(raw_ref)
            except Exception:  # noqa: BLE001 - malformed source evidence fails closed
                continue
            if evidence_ref.type == "transaction" and evidence_ref.id not in seen_evidence_ids:
                fact_evidence.append(evidence_ref)
                seen_evidence_ids.add(evidence_ref.id)
        if not fact_evidence or not any(
            ref.id == fact.get("evidenceRecordId")
            and ref.source == fact.get("provider")
            for ref in fact_evidence
        ):
            continue

        claim_evidence = [
            *admitted_order_refs[fact["commerceOrderRef"]],
            *fact_evidence,
        ]
        seen_fact_ids.add(fact_id)
        lifecycle_state = fact.get("lifecycleState")
        reconciliation_state = fact.get("reconciliationState")
        text = (
            f"canonical commerce {fact_kind.strip()} fact records "
            f"{format(amount_value, 'f')} {currency.strip()}"
        )
        if _safe_source_label(lifecycle_state):
            text += f"; lifecycle state: {lifecycle_state.strip()}"
        if _safe_source_label(reconciliation_state):
            text += f"; reconciliation state: {reconciliation_state.strip()}"

        slot_ids = [PAYMENTS_COMMERCE_SLOT_ID, VALUE_EVIDENCE_TRACE_SLOT_ID]
        if (
            fact_kind.strip() == "payment"
            and isinstance(lifecycle_state, str)
            and lifecycle_state.strip().lower() == "settled"
        ):
            # Only an explicit source-settled payment is a revenue-event
            # candidate. The wording below preserves the source semantics and
            # does not claim attribution or recognized revenue.
            slot_ids.append(VALUE_REVENUE_EVENTS_SLOT_ID)
            text += "; source-recorded settled payment event, not an attributed revenue total"

        claims.append(
            ClaimEnvelope(
                id=f"commerce.fact.{hashlib.sha256(fact_id.encode('utf-8')).hexdigest()[:32]}",
                kind="commerce_economic_fact",
                subject=subject,
                evidenceRefs=claim_evidence,
                claims=[text],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=list(
                    dict.fromkeys(
                        _economic_domain_slot_ids(subject, PAYMENTS_COMMERCE_SLOT_ID) + slot_ids
                    )
                ),
            )
        )
        if fact_kind.strip() != "payment":
            continue
        payment_rail = fact.get("paymentRail")
        flow_type = fact.get("flowType")
        lifecycle = lifecycle_state.strip().lower() if isinstance(lifecycle_state, str) else ""
        if (
            isinstance(payment_rail, str)
            and payment_rail in _WEB2_PAYMENT_RAILS
            and flow_type == "commerce_payment"
            and lifecycle in {"completed", "settled"}
        ):
            claims.append(
                ClaimEnvelope(
                    id=(
                        "commerce.web2."
                        + hashlib.sha256(fact_id.encode("utf-8")).hexdigest()[:32]
                    ),
                    kind="web2_payment_value",
                    subject=subject,
                    evidenceRefs=claim_evidence,
                    claims=[
                        "source-reported Web2 payment records "
                        f"{format(amount_value, 'f')} {currency.strip()} via the explicit "
                        f"{payment_rail} rail; native currency only, with no attribution or "
                        "aggregate asserted"
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=list(
                        dict.fromkeys(
                            _economic_domain_slot_ids(subject, VALUE_WEB2_SLOT_ID)
                            + [VALUE_EVIDENCE_TRACE_SLOT_ID]
                        )
                    ),
                )
            )

        for side, asset_amount, asset, chain in _web3_payment_legs(
            fact,
            fact_evidence,
        ):
            leg_digest = hashlib.sha256(f"{fact_id}:{side}".encode("utf-8")).hexdigest()[:32]
            claims.append(
                ClaimEnvelope(
                    id=f"commerce.web3.{leg_digest}",
                    kind="web3_payment_value",
                    subject=subject,
                    evidenceRefs=claim_evidence,
                    claims=[
                        "source-reported Web3 payment records "
                        f"{format(asset_amount, 'f')} {asset} on {chain} ({side} side) "
                        f"for the explicit {flow_type} flow; the provider transaction and "
                        "transaction-hash references support this native-asset observation; "
                        "wallet identity, conversion, and attribution are not asserted"
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=list(
                        dict.fromkeys(
                            _economic_domain_slot_ids(subject, VALUE_WEB3_SLOT_ID)
                            + [VALUE_EVIDENCE_TRACE_SLOT_ID]
                        )
                    ),
                )
            )
    return claims


def _revenue_adjustment_claims(
    subject: ProjectionSubject, observations: Optional[dict[str, Any]]
) -> list[ClaimEnvelope]:
    """Route exact adjustment events without presenting them as revenue totals."""
    if not isinstance(observations, dict) or observations.get("state") not in {
        "available", "degraded"
    }:
        return []
    rows = observations.get("records")
    if not isinstance(rows, list):
        return []
    claims: list[ClaimEnvelope] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        adjustment_id = _inventory_text(row.get("adjustmentId"))
        conversion_id = _inventory_text(row.get("conversionId"))
        adjustment_type = _inventory_text(row.get("adjustmentType"), limit=32)
        amount = _inventory_amount(row.get("amount"))
        currency = _inventory_text(row.get("currency"), limit=16)
        if not all((adjustment_id, conversion_id, adjustment_type, amount, currency)):
            continue
        raw_refs = row.get("evidenceRefs")
        if not isinstance(raw_refs, list):
            continue
        refs: list[EvidenceRef] = []
        for raw_ref in raw_refs:
            try:
                refs.append(EvidenceRef.model_validate(raw_ref))
            except Exception:  # noqa: BLE001 - invalid evidence cannot ground a claim
                continue
        if not any(
            ref.id == conversion_id
            and ref.type == "transaction"
            and ref.source == "canonical_conversions"
            and ref.uri == f"store://canonical_conversions/{quote(conversion_id, safe='')}"
            for ref in refs
        ) or not any(
            ref.id == adjustment_id
            and ref.type == "transaction"
            and ref.source == "revenue_adjustments"
            and ref.uri == f"store://revenue_adjustments/{quote(adjustment_id, safe='')}"
            for ref in refs
        ):
            continue
        claims.append(
            ClaimEnvelope(
                id=(
                    "value.revenue_adjustment."
                    + hashlib.sha256(
                        f"{conversion_id}:{adjustment_id}".encode("utf-8")
                    ).hexdigest()[:32]
                ),
                kind="canonical_revenue_adjustment_event",
                subject=subject,
                evidenceRefs=refs,
                claims=[
                    f"canonical conversion {conversion_id} records a {adjustment_type} "
                    f"adjustment of {amount} {currency}; this is a source adjustment event, "
                    "not recognized revenue, attributed value, or a reconciled total"
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=[VALUE_REVENUE_EVENTS_SLOT_ID, VALUE_EVIDENCE_TRACE_SLOT_ID],
            )
        )
    return claims


def _web3_payment_legs(
    fact: dict[str, Any],
    fact_evidence: list[EvidenceRef],
) -> list[tuple[str, Decimal, str, str]]:
    """Return complete native-asset legs backed by an exact transaction hash."""
    rail = fact.get("paymentRail")
    flow_type = fact.get("flowType")
    lifecycle = fact.get("lifecycleState")
    if (
        not isinstance(rail, str)
        or rail not in _PAYMENT_RAIL_VALUES
        or not isinstance(flow_type, str)
        or flow_type not in _WEB3_PAYMENT_FLOWS
        or not isinstance(lifecycle, str)
        or lifecycle.strip().lower() not in {"completed", "settled"}
        or not _safe_source_label(rail)
        or not _safe_source_label(flow_type)
    ):
        return []
    tx_hash = fact.get("txHash")
    if (
        not isinstance(tx_hash, str)
        or not tx_hash.strip()
        or len(tx_hash.strip()) > 512
        or any(ord(char) < 32 or ord(char) == 127 for char in tx_hash.strip())
    ):
        return []
    tx_reference = next(
        (
            ref
            for ref in fact_evidence
            if ref.type == "transaction" and ref.id == tx_hash.strip()
        ),
        None,
    )
    provider = fact.get("provider")
    if (
        tx_reference is None
        or not isinstance(provider, str)
        or tx_reference.source != provider
    ):
        return []

    sides = (
        ("destination",)
        if flow_type in {"crypto_onramp", "crypto_deposit"}
        else ("source",)
        if flow_type == "offramp"
        else ("source", "destination")
        if rail in _WEB3_RAILS
        else ()
    )
    legs: list[tuple[str, Decimal, str, str]] = []
    for side in sides:
        amount = fact.get(f"{side}Amount")
        asset = fact.get(f"{side}Asset")
        chain = fact.get(f"{side}Chain")
        amount_value = _to_decimal(amount)
        if (
            amount_value is None
            or not amount_value.is_finite()
            or not isinstance(asset, str)
            or not _safe_source_label(asset)
            or not isinstance(chain, str)
            or not _safe_source_label(chain)
        ):
            continue
        legs.append((side, amount_value, asset.strip(), chain.strip()))
    return legs


def _value_reconciliation_observations(
    subject: ProjectionSubject,
    records: list[dict[str, Any]],
    operation_evidence: Optional[dict[str, Any]],
) -> tuple[dict[str, Any], list[ClaimEnvelope]]:
    """Expose source-side currency/reconciliation facts without cross-source math.

    Economic360 has exact subject-scoped economic rows and a separate path from
    Journey/Campaign/Entity subjects to a tenant-scoped commerce ledger through
    explicit commerce-order references. The persisted economic rows do not
    retain those order/payment/settlement identifiers, so the two authorities
    cannot be reconciled to each other. Keep both inventories separate and make
    that gap explicit instead of comparing totals by subject, time, or currency.
    """
    expected_join_basis = _COMMERCE_JOIN_BASIS_BY_SUBJECT_KIND.get(subject.kind)
    scope_field = {
        "journey": "journey_id",
        "campaign": "campaign_id",
        "entity": "entity_id",
    }.get(subject.kind)

    commerce_facts: list[dict[str, Any]] = []
    claims: list[ClaimEnvelope] = []
    if (
        isinstance(operation_evidence, dict)
        and expected_join_basis is not None
        and scope_field is not None
        and operation_evidence.get("join_basis") == expected_join_basis
        and operation_evidence.get(scope_field) == subject.id
    ):
        raw_facts = operation_evidence.get("payment_facts")
        if isinstance(raw_facts, list):
            seen_fact_ids: set[str] = set()
            for fact in raw_facts:
                if not isinstance(fact, dict):
                    continue
                fact_id = _inventory_text(fact.get("factId"), limit=512)
                fact_kind = _inventory_text(fact.get("kind"), limit=32)
                order_ref = _inventory_text(fact.get("commerceOrderRef"), limit=512)
                provider = _inventory_text(fact.get("provider"), limit=96)
                source_record_id = _inventory_text(fact.get("sourceRecordId"), limit=512)
                evidence_record_id = _inventory_text(fact.get("evidenceRecordId"), limit=512)
                amount = _to_decimal(fact.get("amount"))
                currency = _inventory_text(fact.get("currency"), limit=16)
                if (
                    fact_id is None
                    or not fact_id.startswith("commerce:")
                    or fact_id in seen_fact_ids
                    or fact_kind not in {"order", "payment", "adjustment", "refund", "settlement"}
                    or order_ref is None
                    or provider is None
                    or source_record_id is None
                    or amount is None
                    or not amount.is_finite()
                    or currency is None
                    or not currency.isascii()
                    or not currency.isalnum()
                    or fact.get("joinBasis", expected_join_basis) != expected_join_basis
                ):
                    continue

                refs: list[EvidenceRef] = []
                raw_refs = fact.get("evidence")
                if isinstance(raw_refs, list):
                    for raw_ref in raw_refs:
                        try:
                            ref = EvidenceRef.model_validate(raw_ref)
                        except Exception:  # noqa: BLE001 - malformed source evidence fails closed
                            continue
                        if ref.type == "transaction":
                            refs.append(ref)
                if not refs:
                    continue
                if evidence_record_id is None:
                    evidence_record_id = source_record_id
                if not any(ref.id == evidence_record_id for ref in refs):
                    continue

                source_normalization = fact.get("normalizationState")
                source_normalization = (
                    source_normalization.strip()
                    if _safe_source_label(source_normalization)
                    else "unknown"
                )
                # The commerce ledger currently makes only native USD identity
                # normalization. Ignore any non-USD amountUsd claim here.
                normalized_usd = None
                normalization_state = "not_normalized"
                candidate_usd = _to_decimal(fact.get("amountUsd"))
                if (
                    currency.upper() == "USD"
                    and source_normalization == "native_currency_usd"
                    and candidate_usd is not None
                    and candidate_usd.is_finite()
                    and candidate_usd == amount
                ):
                    normalized_usd = format(candidate_usd, "f")
                    normalization_state = "native_currency_usd"

                lifecycle_state = fact.get("lifecycleState")
                lifecycle_state = (
                    lifecycle_state.strip()
                    if _safe_source_label(lifecycle_state)
                    else "unknown"
                )
                reconciliation_state = fact.get("reconciliationState")
                reconciliation_state = (
                    reconciliation_state.strip()
                    if _safe_source_label(reconciliation_state)
                    else "unknown"
                )
                settles_payment_refs: list[dict[str, str]] = []
                raw_settles_refs = fact.get("settlesPaymentRefs")
                if isinstance(raw_settles_refs, list):
                    for raw_settles_ref in raw_settles_refs:
                        if not isinstance(raw_settles_ref, dict):
                            continue
                        referenced_provider = _inventory_text(
                            raw_settles_ref.get("provider"), limit=96
                        )
                        referenced_payment_id = _inventory_text(
                            raw_settles_ref.get("providerPaymentId"), limit=512
                        )
                        if referenced_provider and referenced_payment_id:
                            settles_payment_refs.append(
                                {
                                    "provider": referenced_provider,
                                    "providerPaymentId": referenced_payment_id,
                                }
                            )
                fact_observation = {
                    "factId": fact_id,
                    "commerceOrderRef": order_ref,
                    "kind": fact_kind,
                    "provider": provider,
                    "sourceRecordId": source_record_id,
                    "amount": format(amount, "f"),
                    "currency": currency,
                    "normalizationState": normalization_state,
                    "sourceNormalizationState": source_normalization,
                    "amountUsd": normalized_usd,
                    "lifecycleState": lifecycle_state,
                    "reconciliationState": reconciliation_state,
                    "settlesPaymentRefs": settles_payment_refs,
                    "evidenceRefs": [ref.model_dump(mode="json") for ref in refs],
                }
                commerce_facts.append(fact_observation)
                seen_fact_ids.add(fact_id)
                claims.append(
                    ClaimEnvelope(
                        id=(
                            "reconciliation.commerce."
                            + hashlib.sha256(fact_id.encode("utf-8")).hexdigest()[:32]
                        ),
                        kind="commerce_value_reconciliation_observation",
                        subject=subject,
                        evidenceRefs=refs,
                        claims=[
                            f"tenant-scoped commerce {fact_kind} record from {provider} "
                            f"references order {order_ref} and records "
                            f"{format(amount, 'f')} {currency}; source normalization state "
                            f"{source_normalization}; ledger reconciliation state "
                            f"{reconciliation_state}. This remains a source observation only; "
                            "Economic360 does not match it to a separate economic record or "
                            "compute a reconciled total."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[
                            VALUE_RECONCILIATION_SLOT_ID,
                            VALUE_EVIDENCE_TRACE_SLOT_ID,
                        ],
                    )
                )

    settlement_payment_links: list[dict[str, Any]] = []
    for settlement in commerce_facts:
        if settlement["kind"] != "settlement":
            continue
        for payment_ref in settlement["settlesPaymentRefs"]:
            exact_payments = [
                payment
                for payment in commerce_facts
                if payment["kind"] == "payment"
                and payment["provider"] == payment_ref["provider"]
                and payment["sourceRecordId"] == payment_ref["providerPaymentId"]
                and payment["commerceOrderRef"] == settlement["commerceOrderRef"]
            ]
            if len(exact_payments) != 1:
                settlement_payment_links.append(
                    {
                        "settlementFactId": settlement["factId"],
                        "provider": payment_ref["provider"],
                        "providerPaymentId": payment_ref["providerPaymentId"],
                        "state": (
                            "referenced_payment_unavailable"
                            if not exact_payments
                            else "referenced_payment_ambiguous"
                        ),
                        "evidenceRefs": settlement["evidenceRefs"],
                    }
                )
                continue

            payment = exact_payments[0]
            link_evidence = [
                EvidenceRef.model_validate(raw_ref)
                for raw_ref in payment["evidenceRefs"] + settlement["evidenceRefs"]
            ]
            link = {
                "settlementFactId": settlement["factId"],
                "paymentFactId": payment["factId"],
                "commerceOrderRef": settlement["commerceOrderRef"],
                "provider": payment_ref["provider"],
                "providerPaymentId": payment_ref["providerPaymentId"],
                "providerSettlementId": settlement["sourceRecordId"],
                "state": "source_reference_resolved",
                "basis": "exact_provider_payment_id_and_same_commerce_order_ref",
                "evidenceRefs": [ref.model_dump(mode="json") for ref in link_evidence],
            }
            settlement_payment_links.append(link)
            claims.append(
                ClaimEnvelope(
                    id=(
                        "reconciliation.settlement-payment."
                        + hashlib.sha256(
                            f"{settlement['factId']}:{payment['factId']}".encode("utf-8")
                        ).hexdigest()[:32]
                    ),
                    kind="canonical_settlement_payment_reference",
                    subject=subject,
                    evidenceRefs=link_evidence,
                    claims=[
                        f"canonical {payment_ref['provider']} settlement "
                        f"{settlement['sourceRecordId']} explicitly references payment "
                        f"{payment_ref['providerPaymentId']} for the same commerce order; "
                        "this exact source reference does not establish equal amounts, "
                        "settlement finality, or reconciled value."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[
                        VALUE_RECONCILIATION_SLOT_ID,
                        VALUE_EVIDENCE_TRACE_SLOT_ID,
                    ],
                )
            )

    economic_records: list[dict[str, Any]] = []
    for record in records:
        evidence_ref = _evidence_from_record(record)
        amount = _to_decimal(record.get("amount"))
        currency = _inventory_text(record.get("currency"), limit=16)
        if (
            evidence_ref is None
            or amount is None
            or not amount.is_finite()
            or currency is None
            or not currency.isascii()
            or not currency.isalnum()
        ):
            continue
        monetary = _monetary_from_record(record)
        normalized_usd = monetary.usd_value
        if normalized_usd is None or not normalized_usd.is_finite():
            normalization_state = "not_normalized"
            usd_value = None
        elif currency.upper() == "USD" and normalized_usd == amount:
            normalization_state = "native_currency_usd"
            usd_value = format(normalized_usd, "f")
        else:
            # Explicit non-USD USD values are preserved only as source-reported
            # normalization evidence; this provider does not recompute FX.
            normalization_state = "canonical_source_reported_usd"
            usd_value = format(normalized_usd, "f")

        source = _inventory_text(record.get("_source"), limit=256) or "unknown"
        economic_observation = {
            "evidenceRef": evidence_ref.model_dump(mode="json"),
            "source": source,
            "metric": _inventory_text(record.get("_metric_name"), limit=128) or "unknown",
            "amount": format(amount, "f"),
            "currency": currency,
            "normalizationState": normalization_state,
            "amountUsd": usd_value,
        }
        economic_records.append(economic_observation)
        claims.append(
            ClaimEnvelope(
                id=(
                    "reconciliation.economic."
                    + hashlib.sha256(
                        f"{subject.kind}:{subject.id}:{evidence_ref.source}:{evidence_ref.id}".encode(
                            "utf-8"
                        )
                    ).hexdigest()[:32]
                ),
                kind="economic_currency_normalization_observation",
                subject=subject,
                evidenceRefs=[evidence_ref],
                claims=[
                    f"exact subject-scoped economic record from {source} records "
                    f"{format(amount, 'f')} {currency}; normalization state "
                    f"{normalization_state}"
                    + (f" with source-reported USD value {usd_value}" if usd_value else "")
                    + ". The record has no exact commerce order, payment, or settlement "
                    "reference, so it is not reconciled to the commerce observations."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=[
                    VALUE_RECONCILIATION_SLOT_ID,
                    VALUE_EVIDENCE_TRACE_SLOT_ID,
                ],
            )
        )

    operation_reason = (
        _inventory_text(operation_evidence.get("reason"), limit=128)
        if isinstance(operation_evidence, dict)
        else None
    )
    operation_completeness = (
        _inventory_text(operation_evidence.get("completeness"), limit=48)
        if isinstance(operation_evidence, dict)
        else None
    ) or (
        "partial"
        if isinstance(operation_evidence, dict)
        and (
            operation_evidence.get("evidence_truncated") is True
            or operation_evidence.get("ledger_read_errors", 0)
            or operation_evidence.get("invalid_ledger_records", 0)
            or operation_evidence.get("unresolved_order_references", 0)
        )
        else "bounded_read"
        if isinstance(operation_evidence, dict)
        else "unknown"
    )
    has_evidence = bool(commerce_facts or economic_records)
    return (
        {
            "state": "partial" if has_evidence else "unknown",
            "subject": {"kind": subject.kind, "id": subject.id},
            "joinBasis": expected_join_basis
            if isinstance(operation_evidence, dict)
            and operation_evidence.get("join_basis") == expected_join_basis
            else None,
            "operationEvidenceCompleteness": operation_completeness,
            "operationEvidenceReason": operation_reason,
            "commerceFacts": commerce_facts,
            "settlementPaymentLinks": settlement_payment_links,
            "economicRecords": economic_records,
            "crossSourceMatch": {
                "state": "unavailable",
                "reason": "economic_records_do_not_retain_exact_commerce_order_payment_or_settlement_ids",
            },
            "limitations": [
                "commerce_facts_remain_separate_source_observations",
                "non_usd_commerce_facts_are_not_normalized_by_economic360",
                "subject_economic_and_commerce_amounts_are_not_compared_or_aggregated",
                "settlement_payment_references_do_not_establish_amount_equality_or_finality",
                "source_and_currency_reconciliation_remains_incomplete",
            ],
        },
        claims,
    )


def _safe_source_label(value: Any) -> bool:
    """Allow bounded source enum-like values in claim text without controls."""
    return bool(
        isinstance(value, str)
        and value.strip()
        and len(value.strip()) <= 64
        and value.strip().isascii()
        and all(char.isalnum() or char in {"_", "-"} for char in value.strip())
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
        conversion_inventory_reader: Optional[ConversionInventoryReader] = None,
        attribution_credit_reader: Optional[AttributionCreditReader] = None,
        revenue_adjustment_reader: Optional[AdjustmentSource] = None,
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
        self._conversion_inventory = (
            conversion_inventory_reader
            if conversion_inventory_reader is not None
            else RepositoryConversionInventoryReader(
                agent_identity_reader=self._agent_identity,
                campaign_identity_reader=self._campaign_identity,
                profile_identity_reader=self._profile_identity,
            )
        )
        self._attribution_credits = (
            attribution_credit_reader
            if attribution_credit_reader is not None
            else RepositoryAttributionCreditReader()
        )
        self._revenue_adjustments = revenue_adjustment_reader

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
        entity_profile_verified = False
        entity_profile_identity_state: Optional[bool] = None
        if request.subject.kind == "entity":
            # Account360's `value` slot may contain only economics for a
            # canonical tenant profile. This identity check does not create a
            # graph join or authorize member/descendant aggregation.
            try:
                entity_profile_identity_state = await self._profile_identity.is_canonical_profile(
                    tenant_id, request.subject.id
                )
            except Exception:  # noqa: BLE001 - unresolved identity remains unknown
                entity_profile_identity_state = None
            entity_profile_verified = entity_profile_identity_state is True
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
            # tenant's economic sections/evidence. Missing tenant attribution
            # is incomplete source data, never an implicit match to the caller.
            if record.get("tenant_id") != tenant_id:
                source_incomplete_reasons.add("economic_source_tenant_scope_mismatch")
                continue
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
            entity_profile_identity_state=entity_profile_identity_state,
        )
        operation_evidence = _validated_commerce_operation_evidence(
            tenant_id, request.subject, operation_evidence
        )
        conversion_inventory = await self._safe_conversion_inventory(request)
        adjustment_inventory = conversion_inventory
        adjustment_inventory_unwindowed = False
        if (
            request.subject.kind == "conversion"
            and request.timeRange is not None
            and request.asOf is None
            and request.temporalMode not in {"as_of", "compare", "relative"}
        ):
            # An adjustment can occur inside this window for a conversion
            # created years before it. Resolve that exact conversion without
            # a conversion-occurrence filter, then window the adjustment read.
            adjustment_inventory = await self._safe_conversion_inventory(
                request.model_copy(update={"timeRange": None})
            )
            adjustment_inventory_unwindowed = True
        revenue_adjustments = await read_revenue_adjustments(
            request,
            adjustment_inventory,
            source=self._revenue_adjustments,
            conversion_inventory_unwindowed_for_adjustments=adjustment_inventory_unwindowed,
        )
        ltv_observation = _value_ltv_observation(request, conversion_inventory)
        attribution_credits = await self._safe_attribution_credits(
            request, conversion_inventory
        )
        value_reconciliation, reconciliation_claims = _value_reconciliation_observations(
            request.subject,
            tenant_filtered,
            operation_evidence,
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
            and operation_evidence.get("reason") == EPISODE_COMMERCE_ORDER_SCOPE_UNAVAILABLE
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
                conversion_inventory=conversion_inventory,
                revenue_adjustments=revenue_adjustments,
                ltv_observation=ltv_observation,
                attribution_credits=attribution_credits,
                value_reconciliation=value_reconciliation,
            ),
            self._outcomes_section(tenant_filtered, dep_state, source_partial),
            self._findings_section(warnings, evidence, source_partial),
        ]
        claims = self._build_claims(
            request,
            tenant_filtered,
            rollup,
            warnings,
            evidence,
            operation_evidence=operation_evidence,
            entity_profile_verified=entity_profile_verified,
            conversion_inventory=conversion_inventory,
            revenue_adjustments=revenue_adjustments,
            ltv_observation=ltv_observation,
            attribution_credits=attribution_credits,
            reconciliation_claims=reconciliation_claims,
        )

        degraded_reasons = []
        if source_truncated:
            degraded_reasons.append("economic_source_read_truncated")
        degraded_reasons.extend(sorted(source_incomplete_reasons))
        if operation_evidence_partial:
            degraded_reasons.append(operation_evidence_warning)
        if conversion_inventory.get("state") == "degraded":
            degraded_reasons.append(
                str(conversion_inventory.get("reason") or "canonical_conversion_inventory_partial")
            )
        if revenue_adjustments.get("state") in {"degraded", "missing"}:
            degraded_reasons.append(
                str(
                    revenue_adjustments.get("reason")
                    or "canonical_revenue_adjustment_read_partial"
                )
            )
        if attribution_credits.get("state") in {"degraded", "missing"}:
            degraded_reasons.append(
                str(
                    attribution_credits.get("reason")
                    or "canonical_attribution_credit_inventory_partial"
                )
            )
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
            record
            for record in value_records
            if _monetary_from_record(record).usd_value is not None
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
        conversion_inventory: Optional[dict[str, Any]] = None,
        revenue_adjustments: Optional[dict[str, Any]] = None,
        ltv_observation: Optional[dict[str, Any]] = None,
        attribution_credits: Optional[dict[str, Any]] = None,
        value_reconciliation: Optional[dict[str, Any]] = None,
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
        conversion_inventory = conversion_inventory or {}
        if conversion_inventory:
            content["conversion_inventory"] = conversion_inventory
        revenue_adjustments = revenue_adjustments or {}
        if revenue_adjustments:
            content["revenue_adjustments"] = revenue_adjustments
        ltv_observation = ltv_observation or {}
        if ltv_observation:
            content["ltv"] = ltv_observation
        attribution_credits = attribution_credits or {}
        if attribution_credits:
            content["attribution_credits"] = attribution_credits
        if value_reconciliation is not None:
            content["value_reconciliation"] = value_reconciliation
        warnings = []
        if source_truncated:
            warnings.append("economic_source_read_truncated")
        warnings.extend(source_incomplete_reasons)
        if operation_evidence_partial:
            warnings.append(operation_evidence_warning)
        if conversion_inventory.get("state") == "degraded":
            warnings.append(
                str(
                    conversion_inventory.get("reason")
                    or "canonical_conversion_inventory_partial"
                )
            )
        if revenue_adjustments.get("state") in {"degraded", "missing"}:
            warnings.append(
                str(
                    revenue_adjustments.get("reason")
                    or "canonical_revenue_adjustment_read_partial"
                )
            )
        if ltv_observation.get("state") in {"degraded", "missing", "unknown"}:
            warnings.append(
                str(ltv_observation.get("reason") or "canonical_ltv_measurement_partial")
            )
        if attribution_credits.get("state") in {"degraded", "missing"}:
            warnings.append(
                str(
                    attribution_credits.get("reason")
                    or "canonical_attribution_credit_inventory_partial"
                )
            )
        return ProjectionSection(
            id="evidence",
            state=(
                "degraded"
                if source_partial
                or operation_evidence_partial
                or revenue_adjustments.get("state") in {"degraded", "missing"}
                or ltv_observation.get("state") in {"degraded", "missing", "unknown"}
                or attribution_credits.get("state") in {"degraded", "missing"}
                else "available"
                if evidence
                or operation_evidence
                or conversion_inventory.get("evidenceRefs")
                or revenue_adjustments.get("records")
                else "empty"
            ),
            title="Evidence",
            content=content,
            warnings=warnings,
        )

    async def _subject_operation_evidence(
        self,
        tenant_id: str,
        subject: Any,
        *,
        as_of: Optional[str] = None,
        entity_profile_identity_state: Optional[bool] = None,
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
                canonical_profile = entity_profile_identity_state
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
        *,
        operation_evidence: Optional[dict[str, Any]] = None,
        entity_profile_verified: bool = False,
        conversion_inventory: Optional[dict[str, Any]] = None,
        revenue_adjustments: Optional[dict[str, Any]] = None,
        ltv_observation: Optional[dict[str, Any]] = None,
        attribution_credits: Optional[dict[str, Any]] = None,
        reconciliation_claims: Optional[list[ClaimEnvelope]] = None,
    ) -> list[ClaimEnvelope]:
        """Evidence-grounded claims (requiresEvidence: every claim is grounded)."""
        claims: list[ClaimEnvelope] = []
        subject = request.subject  # canonical subject — never re-derived

        total_usd = rollup.get("total_usd")
        value_evidence = [
            ref
            for record in records
            if not _is_ai_execution_cost(record)
            for ref in [_evidence_from_record(record)]
            if ref is not None
        ]
        if total_usd is not None and value_evidence:
            claims.append(
                ClaimEnvelope(
                    id="summary.total_value_observed",
                    kind="economic_rollup",
                    subject=subject,
                    evidenceRefs=value_evidence,
                    claims=(
                        [
                            f"entity-scoped trusted USD economic total observed: ${total_usd}; "
                            "records are directly bound to this entity and do not include "
                            "member or descendant economics",
                            f"rollup status: {rollup.get('rollup_status')}",
                        ]
                        if subject.kind == "entity"
                        else [
                            f"trusted USD total observed: ${total_usd}",
                            f"rollup status: {rollup.get('rollup_status')}",
                        ]
                    ),
                    domainSlotIds=_value_summary_domain_slot_ids(
                        subject,
                        entity_profile_verified=entity_profile_verified,
                    ),
                )
            )
        elif total_usd is None:
            unpriced_refs = [
                ref
                for record in records
                if not _is_ai_execution_cost(record)
                for ref in [_evidence_from_record(record)]
                if ref is not None
            ][:5]
            if unpriced_refs:
                claims.append(
                    ClaimEnvelope(
                        id="summary.no_trusted_total",
                        kind="economic_rollup",
                        subject=subject,
                        evidenceRefs=unpriced_refs,
                        claims=(
                            [
                                "no trusted USD total is available for directly subject-scoped "
                                "entity economics; unpriced amounts are never coerced to zero, "
                                "and member/descendant economics are not included"
                            ]
                            if subject.kind == "entity"
                            else [
                                "no trusted USD total is available; unpriced amounts are "
                                "never coerced to zero"
                            ]
                        ),
                        domainSlotIds=_value_summary_domain_slot_ids(
                            subject,
                            entity_profile_verified=entity_profile_verified,
                        ),
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
                    domainSlotIds=_with_financial_risk_slot(
                        subject, _economic_domain_slot_ids(subject, ECONOMIC_FACTS_SLOT_ID)
                    ),
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
                    domainSlotIds=_with_financial_risk_slot(
                        subject, _economic_domain_slot_ids(subject, ECONOMIC_FACTS_SLOT_ID)
                    ),
                )
            )

        claims.extend(
            _commerce_fact_claims(
                request.tenantId,
                request.subject,
                operation_evidence,
            )
        )
        claims.extend(reconciliation_claims or [])
        claims.extend(_revenue_adjustment_claims(subject, revenue_adjustments))

        inventory = conversion_inventory or {}
        inventory_refs = _inventory_evidence_refs(inventory.get("evidenceRefs"))
        inventory_records = inventory.get("records")
        if (
            inventory.get("state") in {"available", "degraded"}
            and isinstance(inventory_records, list)
            and inventory_records
            and inventory_refs
            and inventory.get("joinBasis")
        ):
            inventory_count = len(inventory_records)
            completeness = inventory.get("completeness") or "unknown"
            join_basis = str(inventory["joinBasis"])
            claims.append(
                ClaimEnvelope(
                    id=(
                        "outcomes.conversion_inventory."
                        + hashlib.sha256(
                            f"{request.tenantId}:{subject.kind}:{subject.id}".encode("utf-8")
                        ).hexdigest()[:32]
                    ),
                    kind="canonical_conversion_inventory",
                    subject=subject,
                    evidenceRefs=inventory_refs,
                    claims=[
                        f"{inventory_count} canonical conversion record(s) are observed for "
                        f"this exact subject through {join_basis}; inventory completeness is "
                        f"{completeness}. These are current canonical conversion rows, not a "
                        "join to Outcome360 measured-outcome IDs; monetary fields remain in "
                        "their source currency and are not aggregated."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[
                        VALUE_CONVERSION_INVENTORY_SLOT_ID,
                        VALUE_EVIDENCE_TRACE_SLOT_ID,
                    ],
                )
            )

        ltv = ltv_observation or {}
        ltv_refs = _inventory_evidence_refs(ltv.get("evidenceRefs"))
        observed_totals = ltv.get("observedNetValueByCurrency")
        if ltv_refs and isinstance(observed_totals, dict) and observed_totals:
            coverage = ltv.get("coverage") if isinstance(ltv.get("coverage"), dict) else {}
            known_count = coverage.get("knownNetValueCount", 0)
            eligible_count = coverage.get("eligibleConversionCount", 0)
            description = ", ".join(
                f"{value} {code}"
                for code, value in sorted(observed_totals.items())
                if _inventory_text(code, limit=16) and _inventory_amount(value) is not None
            )
            if description:
                claims.append(
                    ClaimEnvelope(
                        id=(
                            "value.ltv.evidence."
                            + hashlib.sha256(
                                (
                                    f"{request.tenantId}:{subject.kind}:{subject.id}:"
                                    f"{json.dumps(ltv.get('timeScope'), sort_keys=True, default=str)}"
                                ).encode("utf-8")
                            ).hexdigest()[:32]
                        ),
                        kind="ltv_evidence",
                        subject=subject,
                        evidenceRefs=ltv_refs,
                        claims=[
                            "observed confirmed/adjusted canonical conversion net values by native currency: "
                            f"{description}; these are supporting observations, not an LTV amount; "
                            f"known net-value coverage is {known_count}/{eligible_count} final rows "
                            "and applies only to this observed subtotal; "
                            f"conversion inventory completeness is {ltv.get('sourceCompleteness') or 'unknown'}",
                            "the canonical conversion ledger does not prove complete subject lifecycle coverage; "
                            "this is not a forecast and is not reported as complete lifetime value",
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[VALUE_LTV_SLOT_ID, VALUE_EVIDENCE_TRACE_SLOT_ID],
                    )
                )

        attribution = attribution_credits or {}
        attribution_records = attribution.get("records")
        if isinstance(attribution_records, list):
            for record in attribution_records:
                if not isinstance(record, dict):
                    continue
                refs = _attribution_evidence_refs(record.get("evidenceRefs"))
                if not refs:
                    continue
                weight = _inventory_amount(record.get("creditWeight"))
                if weight is None:
                    continue
                conversion_id = _inventory_text(record.get("conversionId"))
                credit_id = _inventory_text(record.get("creditId"))
                run_id = _inventory_text(record.get("attributionRunId"))
                if not conversion_id or not credit_id or not run_id:
                    continue
                model_version = _inventory_text(record.get("modelVersion"), limit=128)
                model_type = _inventory_text(record.get("modelType"), limit=128)
                model_label = (
                    f"{model_type}@{model_version}"
                    if model_type and model_version
                    else model_version or model_type or "unreported model version"
                )
                confidence = _attribution_confidence(record.get("modelConfidence"))
                model_lineage_reported = bool(model_type and model_version)
                governance = record.get("modelGovernance") or {}
                governance_note = (
                    "; exact tenant run/model-config snapshot lineage validated by append-only decision "
                    f"{governance.get('decisionId')}; model approval and calibration remain unvalidated"
                    if governance.get("state") == "validated"
                    else "; model governance validation is unavailable"
                )
                confidence_note = (
                    f"; model-reported attribution confidence {confidence:.3f} "
                    "(calibration and applicability to realized value are not independently validated)"
                    f"{governance_note}"
                    if confidence is not None and model_lineage_reported
                    else ""
                )
                domain_slot_ids = [
                    VALUE_ATTRIBUTION_CREDITS_SLOT_ID,
                    VALUE_EVIDENCE_TRACE_SLOT_ID,
                ]
                if confidence is not None and model_lineage_reported:
                    domain_slot_ids.append(VALUE_CONFIDENCE_SLOT_ID)
                claims.append(
                    ClaimEnvelope(
                        id=(
                            "attribution.credit."
                            + hashlib.sha256(
                                f"{request.tenantId}:{conversion_id}:{credit_id}".encode("utf-8")
                            ).hexdigest()[:32]
                        ),
                        kind="canonical_attribution_credit",
                        subject=subject,
                        evidenceRefs=refs,
                        claims=[
                            f"active canonical attribution run {run_id} ({model_label}) records "
                            f"credit weight {weight} for conversion {conversion_id}"
                            f"{confidence_note}; this is "
                            "attribution-model output, not independently measured realized "
                            "value or agent ROI"
                        ],
                        confidence=confidence,
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=domain_slot_ids,
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
                    domainSlotIds=_economic_domain_slot_ids(subject, ECONOMIC_FACTS_SLOT_ID),
                )
            )

        return claims

    # ── Canonical read helpers (defensive) ─────────────────────────────────

    async def _safe_conversion_inventory(
        self,
        request: ProjectionRequest,
    ) -> dict[str, Any]:
        """Read exact canonical conversion rows or expose an explicit unknown."""
        fallback = {
            "tenantId": request.tenantId,
            "subject": request.subject.model_dump(),
            "canonicalAuthority": "canonical_conversions",
            "canonicalAuthorityRefs": ["canonical_conversions"],
            "state": "unknown",
            "reason": "canonical_conversion_inventory_unavailable",
            "joinBasis": None,
            "completeness": "unknown",
            "records": [],
            "evidenceRefs": [],
            "measurementOutcomeLinkage": {
                "state": "unknown",
                "reason": "outcome360_rows_do_not_expose_canonical_conversion_id",
            },
            "freshness": {
                "state": "unknown",
                "reason": "conversion_freshness_threshold_not_configured",
            },
        }
        if request.subject.kind == "agent":
            fallback["agentRoster"] = {
                "identityState": "unknown",
                "completeness": "unknown",
                "freshness": {
                    "state": "unknown",
                    "reason": "agent_roster_completeness_and_freshness_not_read",
                },
            }
        # Do not let an injected or future reader accidentally serve current
        # canonical rows on a request that asks for historical state.
        if request.asOf is not None or request.temporalMode in {"as_of", "compare", "relative"}:
            return {
                **fallback,
                "reason": "canonical_conversion_history_not_bitemporal",
            }
        try:
            result = await self._conversion_inventory.read(request)
        except Exception:  # noqa: BLE001 - a source outage is not empty data
            return {
                **fallback,
                "state": "missing",
                "reason": "canonical_conversion_inventory_read_failed",
            }
        if not isinstance(result, dict):
            return {
                **fallback,
                "state": "missing",
                "reason": "canonical_conversion_inventory_result_invalid",
            }
        if result.get("tenantId") != request.tenantId or result.get("subject") != request.subject.model_dump():
            return {
                **fallback,
                "reason": "canonical_conversion_inventory_subject_scope_mismatch",
            }
        allowed_states = {"available", "degraded", "empty", "missing", "unknown"}
        state = result.get("state")
        if state not in allowed_states or not isinstance(result.get("records"), list):
            return {
                **fallback,
                "state": "missing",
                "reason": "canonical_conversion_inventory_result_invalid",
            }
        normalized = {**fallback, **result}
        refs = _inventory_evidence_refs(normalized.get("evidenceRefs"))
        if state not in {"available", "degraded"}:
            normalized["records"] = []
            normalized["evidenceRefs"] = []
            refs = []
        elif not normalized["records"]:
            normalized["evidenceRefs"] = []
            refs = []
        elif normalized.get("records") and not refs:
            normalized.update(
                state="degraded",
                completeness="partial",
                reason="canonical_conversion_inventory_evidence_missing",
                records=[],
                evidenceRefs=[],
            )
        else:
            refs_by_id = {ref.id: ref for ref in refs}
            evidenced_records = []
            for record in normalized["records"]:
                if not isinstance(record, dict):
                    continue
                ref = refs_by_id.get(record.get("conversionId"))
                if ref is None:
                    continue
                safe_record = dict(record)
                safe_record["evidenceRefs"] = [ref.model_dump(mode="json")]
                evidenced_records.append(safe_record)
            if len(evidenced_records) != len(normalized["records"]):
                normalized.update(
                    state="degraded",
                    completeness="partial",
                    reason="canonical_conversion_inventory_record_evidence_mismatch",
                    records=evidenced_records,
                )
                retained_ids = {record.get("conversionId") for record in evidenced_records}
                refs = [ref for ref in refs if ref.id in retained_ids]
            normalized["records"] = evidenced_records
            normalized["evidenceRefs"] = [ref.model_dump(mode="json") for ref in refs]
        normalized["measurementOutcomeLinkage"] = fallback["measurementOutcomeLinkage"]
        normalized["freshness"] = fallback["freshness"]
        normalized["canonicalAuthority"] = "canonical_conversions"
        normalized["canonicalAuthorityRefs"] = ["canonical_conversions"]
        if request.subject.kind in {"account", "cluster"} and normalized["state"] in {
            "available", "degraded", "empty"
        }:
            identity_key = (
                "accountIdentity" if request.subject.kind == "account" else "clusterIdentity"
            )
            expected_source = (
                "entity_registry"
                if request.subject.kind == "account"
                else "identity_clusters_v2"
            )
            identity = normalized.get(identity_key)
            identity_refs: list[EvidenceRef] = []
            if isinstance(identity, dict) and identity.get("state") == "validated":
                for raw_ref in identity.get("evidenceRefs", []):
                    try:
                        ref = EvidenceRef.model_validate(raw_ref)
                    except Exception:  # noqa: BLE001 - scope evidence fails closed
                        continue
                    if (
                        ref.id == request.subject.id
                        and ref.type == "entity"
                        and ref.source == expected_source
                        and (
                            request.subject.kind == "account"
                            or ref.uri
                            == f"store://identity_clusters_v2/{quote(request.subject.id, safe='')}"
                        )
                    ):
                        identity_refs.append(ref)
            if not identity_refs:
                normalized.update(
                    state="unknown",
                    completeness="unknown",
                    reason=f"canonical_{request.subject.kind}_identity_evidence_missing",
                    records=[],
                    evidenceRefs=[],
                )
                normalized[identity_key] = {"state": "unknown", "evidenceRefs": []}
            else:
                normalized[identity_key] = {
                    "state": "validated",
                    "evidenceRefs": [ref.model_dump(mode="json") for ref in identity_refs],
                }
                normalized["canonicalAuthorityRefs"].append(expected_source)
        if request.subject.kind == "agent":
            agent_roster = normalized.get("agentRoster")
            identity_state = (
                agent_roster.get("identityState")
                if isinstance(agent_roster, dict)
                and agent_roster.get("identityState")
                in {"not_validated", "unresolved", "unknown", "validated"}
                else "unknown"
            )
            normalized["agentRoster"] = {
                "identityState": identity_state,
                "completeness": "unknown",
                "freshness": fallback["agentRoster"]["freshness"],
            }
        return normalized

    async def _safe_attribution_credits(
        self,
        request: ProjectionRequest,
        conversion_inventory: dict[str, Any],
    ) -> dict[str, Any]:
        """Expose active attribution credits only through exact conversion IDs."""
        fallback = {
            "tenantId": request.tenantId,
            "subject": request.subject.model_dump(),
            "canonicalAuthorityRefs": [
                "attribution_runs",
                "attribution_credits",
                "campaign_touchpoints",
            ],
            "state": "unknown",
            "reason": "canonical_attribution_credit_inventory_unavailable",
            "completeness": "unknown",
            "records": [],
            "runs": [],
            "evidenceRefs": [],
            "freshness": {
                "state": "unknown",
                "reason": "attribution_freshness_threshold_not_configured",
            },
            "timeScope": {
                "mode": "current_active_attribution_run",
                "historicalState": "unknown",
            },
            "limitations": [
                "credit_weights_are_canonical_model_outputs_not_independently_measured_value",
                "attributed_revenue_and_agent_roi_are_not_inferred_or_projected",
                "touchpoint_joins_require_exact_tenant_scoped_credit_touchpoint_ids",
                "touchpoint_rows_are_current_and_not_bitemporal",
            ],
        }
        if request.asOf is not None or request.temporalMode in {"as_of", "compare", "relative"}:
            return {**fallback, "reason": "canonical_attribution_history_not_bitemporal"}
        inventory_state = conversion_inventory.get("state")
        if inventory_state == "empty" and conversion_inventory.get("completeness") == "complete":
            return {
                **fallback,
                "state": "empty",
                "reason": "no_exact_canonical_conversions_for_subject",
                "completeness": "complete",
                "conversionCount": 0,
            }
        if inventory_state not in {"available", "degraded"}:
            return {
                **fallback,
                "reason": "canonical_conversion_inventory_not_available_for_attribution_join",
                "conversionInventoryState": inventory_state or "unknown",
            }
        inventory_records = conversion_inventory.get("records")
        if not isinstance(inventory_records, list):
            return {**fallback, "reason": "canonical_conversion_inventory_result_invalid"}
        conversion_refs = {
            ref.id: ref
            for ref in _inventory_evidence_refs(conversion_inventory.get("evidenceRefs"))
        }
        conversion_ids = list(
            dict.fromkeys(
                conversion_id
                for raw in inventory_records
                if isinstance(raw, dict)
                for conversion_id in [_attribution_uuid(raw.get("conversionId"))]
                if conversion_id and conversion_id in conversion_refs
            )
        )
        if not conversion_ids:
            return {**fallback, "reason": "canonical_conversion_inventory_evidence_missing"}
        try:
            result = await self._attribution_credits.read(request.tenantId, conversion_ids)
        except Exception:  # noqa: BLE001 - canonical source outage is not empty data
            return {
                **fallback,
                "state": "missing",
                "reason": "canonical_attribution_credit_read_failed",
            }
        if not isinstance(result, dict):
            return {
                **fallback,
                "state": "missing",
                "reason": "canonical_attribution_credit_result_invalid",
            }
        result_ids = result.get("conversionIds")
        if (
            result.get("tenantId") != request.tenantId
            or not isinstance(result_ids, list)
            or result_ids != conversion_ids
        ):
            return {
                **fallback,
                "reason": "canonical_attribution_credit_subject_scope_mismatch",
            }
        allowed_states = {"available", "degraded", "empty", "missing", "unknown"}
        if (
            result.get("state") not in allowed_states
            or not isinstance(result.get("records"), list)
            or not isinstance(result.get("runs"), list)
        ):
            return {
                **fallback,
                "state": "missing",
                "reason": "canonical_attribution_credit_result_invalid",
            }

        runs_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        run_refs: dict[tuple[str, str], EvidenceRef] = {}
        output_runs: list[dict[str, Any]] = []
        invalid_rows = 0
        from value.economic.attribution_model_validation import _decision_id_for_scope

        for raw_run in result["runs"]:
            if not isinstance(raw_run, dict) or raw_run.get("tenantId") != request.tenantId:
                invalid_rows += 1
                continue
            conversion_id = _attribution_uuid(raw_run.get("conversionId"))
            run_id = _attribution_uuid(raw_run.get("attributionRunId"))
            if (
                not conversion_id
                or conversion_id not in conversion_refs
                or not run_id
                or raw_run.get("status") != "complete"
            ):
                invalid_rows += 1
                continue
            completed_at = _attribution_timestamp(raw_run.get("completedAt"))
            run_ref = _attribution_run_ref(run_id, completed_at)
            raw_governance = raw_run.get("modelGovernance")
            governance: dict[str, Any] = {
                "state": "unknown",
                "reason": "exact_model_validation_decision_unavailable",
                "calibrationState": "unvalidated",
            }
            if isinstance(raw_governance, dict) and raw_governance.get("state") == "validated":
                decision_id = _inventory_text(raw_governance.get("decisionId"), limit=64)
                config_id = _attribution_uuid(raw_governance.get("modelConfigId"))
                expected_ref = (
                    _attribution_model_validation_ref(
                        decision_id, _attribution_timestamp(
                            (raw_governance.get("evidenceRef") or {}).get("observedAt")
                        ),
                    ) if decision_id and isinstance(raw_governance.get("evidenceRef"), dict) else None
                )
                if (
                    decision_id
                    and decision_id == _decision_id_for_scope(
                        request.tenantId,
                        run_id,
                        config_id,
                        raw_governance.get("configSnapshotSha256"),
                    )
                    and config_id
                    and raw_governance.get("validationState") == "exact_config_lineage_validated"
                    and raw_governance.get("calibrationState") == "unvalidated"
                    and expected_ref is not None
                    and raw_governance.get("evidenceRef") == expected_ref.model_dump(mode="json")
                ):
                    governance = {
                        "state": "validated",
                        "validationState": "exact_config_lineage_validated",
                        "calibrationState": "unvalidated",
                        "modelConfigId": config_id,
                        "decisionId": decision_id,
                        "configSnapshotSha256": raw_governance.get("configSnapshotSha256"),
                        "evidenceRef": expected_ref.model_dump(mode="json"),
                        "approvalState": "unknown",
                    }
                    raw_approval_ref = raw_governance.get("approvalEvidenceRef")
                    approval_state = raw_governance.get("approvalState")
                    if (
                        approval_state in {"approved", "rejected"}
                        and isinstance(raw_approval_ref, dict)
                        and isinstance(raw_approval_ref.get("id"), str)
                        and raw_approval_ref.get("source") == "value_model_approval_decisions"
                        and raw_governance.get("approvalActorId")
                        and raw_governance.get("approvalReason")
                    ):
                        expected_approval_ref = _value_model_approval_ref(
                            raw_approval_ref["id"],
                            _attribution_timestamp(raw_approval_ref.get("observedAt")),
                        )
                        durable_approval = None
                        try:
                            from value.economic.attribution_model_validation import ValueModelApprovalRepository
                            durable_approval = await ValueModelApprovalRepository().latest(
                                request.tenantId, run_id
                            )
                        except Exception:  # noqa: BLE001 - approval authority is fail-closed
                            durable_approval = None
                        if (
                            raw_approval_ref == expected_approval_ref.model_dump(mode="json")
                            and isinstance(durable_approval, dict)
                            and durable_approval.get("tenant_id") == request.tenantId
                            and _attribution_uuid(durable_approval.get("attribution_run_id")) == run_id
                            and _attribution_uuid(durable_approval.get("model_config_id")) == config_id
                            and durable_approval.get("validation_decision_id") == decision_id
                            and durable_approval.get("decision") == approval_state
                            and durable_approval.get("decision_id") == raw_approval_ref.get("id")
                            and durable_approval.get("actor_id") == raw_governance.get("approvalActorId")
                            and durable_approval.get("reason") == raw_governance.get("approvalReason")
                            and _attribution_timestamp(durable_approval.get("created_at")) == raw_approval_ref.get("observedAt")
                        ):
                            governance.update({
                                "approvalState": approval_state,
                                "approvalActorId": raw_governance["approvalActorId"],
                                "approvalReason": raw_governance["approvalReason"],
                                "approvalEvidenceRef": expected_approval_ref.model_dump(mode="json"),
                            })
            key = (conversion_id, run_id)
            runs_by_key[key] = {
                "tenantId": request.tenantId,
                "conversionId": conversion_id,
                "attributionRunId": run_id,
                "modelType": _inventory_text(raw_run.get("modelType"), limit=128),
                "modelVersion": _inventory_text(raw_run.get("modelVersion"), limit=128),
                "status": _inventory_text(raw_run.get("status"), limit=64),
                "completedAt": completed_at,
                "dataWatermark": _attribution_timestamp(raw_run.get("dataWatermark")),
                "modelConfidence": _attribution_confidence(raw_run.get("modelConfidence")),
                "modelGovernance": governance,
            }
            run_refs[key] = run_ref
            output_runs.append({**runs_by_key[key], "evidenceRef": run_ref.model_dump(mode="json")})

        output_records: list[dict[str, Any]] = []
        evidence_refs: list[EvidenceRef] = list(run_refs.values())
        seen_credit_ids: set[str] = set()
        unresolved_touchpoints = 0
        invalid_touchpoints = 0
        for raw_record in result["records"]:
            if not isinstance(raw_record, dict) or raw_record.get("tenantId") != request.tenantId:
                invalid_rows += 1
                continue
            conversion_id = _attribution_uuid(raw_record.get("conversionId"))
            credit_id = _attribution_uuid(raw_record.get("creditId"))
            run_id = _attribution_uuid(raw_record.get("attributionRunId"))
            key = (conversion_id or "", run_id or "")
            weight = _inventory_amount(raw_record.get("creditWeight"))
            weight_value = _to_decimal(weight)
            if (
                conversion_id not in conversion_refs
                or credit_id is None
                or run_id is None
                or key not in runs_by_key
                or credit_id in seen_credit_ids
                or weight_value is None
                or not weight_value.is_finite()
                or weight_value < 0
                or weight_value > 1
            ):
                invalid_rows += 1
                continue
            created_at = _attribution_timestamp(raw_record.get("createdAt"))
            seen_credit_ids.add(credit_id)
            credit_ref = _attribution_credit_ref(credit_id, created_at)
            run_ref = run_refs[key]
            conversion_ref = conversion_refs[conversion_id]
            row_refs = [run_ref, credit_ref, conversion_ref]
            evidence_refs.extend([credit_ref, conversion_ref])
            raw_touchpoint_id = _inventory_text(raw_record.get("touchpointId"), limit=64)
            touchpoint_id = _attribution_uuid(raw_touchpoint_id)
            raw_touchpoint = raw_record.get("canonicalTouchpoint")
            touchpoint_join = raw_record.get("touchpointJoin")
            canonical_touchpoint: Optional[dict[str, Any]] = None
            touchpoint_ref: Optional[EvidenceRef] = None
            touchpoint_reason = (
                _inventory_text(touchpoint_join.get("reason"), limit=256)
                if isinstance(touchpoint_join, dict)
                else None
            )
            if raw_touchpoint_id is None:
                unresolved_touchpoints += 1
                touchpoint_state = "unknown"
                touchpoint_reason = touchpoint_reason or "attribution_credit_touchpoint_id_unavailable"
            elif touchpoint_id is None:
                invalid_touchpoints += 1
                touchpoint_state = "degraded"
                touchpoint_reason = "attribution_credit_touchpoint_id_invalid"
            elif not isinstance(raw_touchpoint, dict):
                unresolved_touchpoints += 1
                touchpoint_state = (
                    _inventory_text(touchpoint_join.get("state"), limit=32)
                    if isinstance(touchpoint_join, dict)
                    else "unknown"
                )
                touchpoint_state = touchpoint_state if touchpoint_state in {
                    "unknown", "missing", "degraded", "conflict"
                } else "unknown"
                touchpoint_reason = touchpoint_reason or "canonical_touchpoint_join_not_resolved"
            else:
                from uuid import UUID

                touchpoint_id = str(UUID(touchpoint_id))
                touchpoint_tenant = raw_touchpoint.get("tenantId")
                joined_touchpoint_id = _attribution_uuid(raw_touchpoint.get("touchpointId"))
                if joined_touchpoint_id is not None:
                    joined_touchpoint_id = str(UUID(joined_touchpoint_id))
                raw_touchpoint_ref = raw_touchpoint.get("evidenceRef")
                try:
                    parsed_touchpoint_ref = EvidenceRef.model_validate(raw_touchpoint_ref)
                except Exception:  # noqa: BLE001 - malformed canonical evidence fails closed
                    parsed_touchpoint_ref = None
                touchpoint_campaign_id = _inventory_text(
                    raw_touchpoint.get("campaignId"), limit=128
                )
                credit_campaign_id = _inventory_text(
                    raw_record.get("campaignId"), limit=128
                )
                if (
                    touchpoint_tenant != request.tenantId
                    or joined_touchpoint_id != touchpoint_id
                    or (
                        credit_campaign_id is not None
                        and touchpoint_campaign_id is not None
                        and credit_campaign_id != touchpoint_campaign_id
                    )
                    or parsed_touchpoint_ref is None
                    or parsed_touchpoint_ref.id != touchpoint_id
                    or parsed_touchpoint_ref.type != "event"
                    or parsed_touchpoint_ref.source
                    != (
                        "services/api/journeys/measurement/repositories/touchpoint_repo.py:"
                        "silver_campaign_touchpoint_facts"
                    )
                ):
                    invalid_touchpoints += 1
                    touchpoint_state = "degraded"
                    touchpoint_reason = "canonical_touchpoint_scope_or_evidence_mismatch"
                else:
                    touchpoint_ref = parsed_touchpoint_ref
                    row_refs.append(touchpoint_ref)
                    evidence_refs.append(touchpoint_ref)
                    touchpoint_state = "resolved"
                    touchpoint_reason = None
                    canonical_touchpoint = {
                        "tenantId": request.tenantId,
                        "touchpointId": touchpoint_id,
                        "campaignId": touchpoint_campaign_id,
                        "occurredAt": _attribution_timestamp(
                            raw_touchpoint.get("occurredAt")
                        ),
                        "evidenceRef": touchpoint_ref.model_dump(mode="json"),
                    }
            run = runs_by_key[key]
            governance = run["modelGovernance"]
            if governance.get("state") == "validated":
                governance_ref = EvidenceRef.model_validate(governance["evidenceRef"])
                row_refs.append(governance_ref)
                evidence_refs.append(governance_ref)
            credit_confidence = _attribution_confidence(raw_record.get("modelConfidence"))
            output_records.append(
                {
                    "tenantId": request.tenantId,
                    "conversionId": conversion_id,
                    "attributionRunId": run_id,
                    "creditId": credit_id,
                    "touchpointId": touchpoint_id,
                    "touchpointJoin": {
                        "state": touchpoint_state,
                        "joinBasis": (
                            "exact_tenant_scoped_credit_touchpoint_id"
                            if touchpoint_state == "resolved"
                            else None
                        ),
                        "reason": touchpoint_reason,
                    },
                    "canonicalTouchpoint": canonical_touchpoint,
                    "campaignId": _inventory_text(raw_record.get("campaignId")),
                    "channel": _inventory_text(raw_record.get("channel"), limit=128),
                    "source": _inventory_text(raw_record.get("source"), limit=128),
                    "sourceClass": _inventory_text(raw_record.get("sourceClass"), limit=128),
                    "actorType": _inventory_text(raw_record.get("actorType"), limit=64),
                    "journeyRole": _inventory_text(raw_record.get("journeyRole"), limit=128),
                    "attributionEligible": (
                        raw_record.get("attributionEligible")
                        if isinstance(raw_record.get("attributionEligible"), bool)
                        else None
                    ),
                    "creditWeight": format(weight_value, "f"),
                    "evidenceConfidence": _attribution_confidence(
                        raw_record.get("evidenceConfidence")
                    ),
                    "identityConfidence": _attribution_confidence(
                        raw_record.get("identityConfidence")
                    ),
                    "modelConfidence": (
                        credit_confidence
                        if credit_confidence is not None
                        else run.get("modelConfidence")
                    ),
                    "verificationLevel": _inventory_text(
                        raw_record.get("verificationLevel"), limit=64
                    ),
                    "sourceClassifierVersion": _inventory_text(
                        raw_record.get("sourceClassifierVersion"), limit=128
                    ),
                    "modelType": run.get("modelType"),
                    "modelVersion": run.get("modelVersion"),
                    "modelGovernance": governance,
                    "createdAt": created_at,
                    "evidenceRefs": [ref.model_dump(mode="json") for ref in row_refs],
                }
            )
        state = result["state"]
        source_reason = _inventory_text(result.get("reason"), limit=256)
        if invalid_rows:
            state = "degraded"
            source_reason = "canonical_attribution_credit_scope_or_record_invalid"
        elif invalid_touchpoints:
            state = "degraded"
            source_reason = "canonical_attribution_touchpoint_scope_or_record_invalid"
        elif unresolved_touchpoints:
            state = "degraded"
            source_reason = source_reason or "canonical_attribution_touchpoint_join_partial"
        elif conversion_inventory.get("state") == "degraded" and state in {"available", "empty"}:
            state = "degraded"
            source_reason = "canonical_attribution_conversion_inventory_partial"
        elif state == "available" and not output_records:
            if len(output_runs) == len(conversion_ids):
                state = "empty"
                source_reason = "active_attribution_runs_have_no_credit_rows"
            else:
                state = "degraded"
                source_reason = "canonical_attribution_run_coverage_partial"
        elif state == "empty" and (
            output_records or len(output_runs) != len(conversion_ids)
        ):
            state = "degraded"
            source_reason = "canonical_attribution_credit_state_or_run_coverage_mismatch"
        elif state in {"unknown", "missing"} and output_records:
            state = "degraded"
            source_reason = "canonical_attribution_credit_state_mismatch"

        deduped_refs: list[EvidenceRef] = []
        seen_refs: set[tuple[str, str, str]] = set()
        for ref in evidence_refs:
            key = (ref.id, ref.type, ref.source)
            if key not in seen_refs:
                deduped_refs.append(ref)
                seen_refs.add(key)
        completed_times = sorted(
            run["completedAt"] for run in output_runs if run.get("completedAt")
        )
        freshness = {
            "state": "unknown",
            "reason": "attribution_freshness_threshold_not_configured",
            "completedAtCoverage": round(len(completed_times) / len(conversion_ids), 4),
            "oldestCompletedAt": completed_times[0] if completed_times else None,
            "latestCompletedAt": completed_times[-1] if completed_times else None,
        }
        return {
            **fallback,
            "state": state,
            "reason": source_reason,
            "touchpointReadCount": (
                result.get("touchpointReadCount")
                if isinstance(result.get("touchpointReadCount"), int)
                and not isinstance(result.get("touchpointReadCount"), bool)
                else None
            ),
            "unresolvedTouchpointCount": unresolved_touchpoints,
            "invalidTouchpointCount": invalid_touchpoints,
            "touchpointReadTruncated": result.get("touchpointReadTruncated") is True,
            "completeness": (
                "complete" if state in {"available", "empty"}
                else "partial" if state == "degraded"
                else "unknown"
            ),
            "conversionCount": len(conversion_ids),
            "recordCount": len(output_records),
            "records": output_records,
            "runs": output_runs,
            "evidenceRefs": [ref.model_dump(mode="json") for ref in deduped_refs],
            "freshness": freshness,
            "unresolvedConversionIds": result.get("unresolvedConversionIds", []),
            "limitations": list(result.get("limitations") or fallback["limitations"]),
        }

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
    "AttributionCreditReader",
    "CampaignIdentityReader",
    "ConversionInventoryReader",
    "Economic360Provider",
    "EconomicSourceReader",
    "OUTPUT_SECTIONS",
    "RepositoryCampaignIdentityReader",
    "RepositoryAttributionCreditReader",
    "RepositoryConversionInventoryReader",
    "RepositoryEconomicSourceReader",
    "SECTION_DEPENDENCIES",
    "register_provider",
]
