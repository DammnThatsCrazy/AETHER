"""Commerce360 projection over exact, tenant-scoped commerce authorities.

Commerce360 is a read-only projection, not a catalog, checkout, payment, or
risk authority. The current canonical join supports payment/order facts linked
to an exact campaign activity, profile activity, or journey step reference.
Product and offer records are read from the durable tenant-scoped catalog
authority. Exact product/offer catalog records contribute lifecycle evidence to
the availability/price slot, but do not establish inventory availability or
offer price. Explicit intent declarations are read from their own append-only,
tenant-scoped authority and joined only to canonical product and offer IDs.
Accepted Silver exposure and cart/checkout observations join only after an
exact tenant catalog key resolves; they do not prove a purchase or current cart
state. Risk360 signals and assessments can
be joined for current product/offer subjects only after an exact tenant-scoped
catalog record resolves; other commerce subject kinds, historical risk reads,
complete risk history, policy disposition, freshness, and causal validity remain
unknown.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Protocol
from urllib.parse import quote

from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry
from graph.operational_intelligence.models import EvidenceRef
from value.commerce.product_offer_catalog import (
    CommerceOfferRecord,
    CommerceProductOfferCatalogRepository,
    CommerceProductRecord,
)
from value.commerce.commerce_intents import (
    CommerceIntentRecord,
    CommerceIntentRepository,
)
from value.commerce.observed_events import RepositoryCommerceObservedEventSource


PROJECTION_ID = "commerce360"

# SSOT §11.17 order. These section IDs are also the exact product-frame slot
# IDs; the frame composer only routes sections/claims through explicit bindings.
OUTPUT_SECTIONS: tuple[str, ...] = (
    "product_offer_summary",
    "catalog_links",
    "exposures",
    "intent",
    "cart_checkout",
    "purchase",
    "availability_price",
    "campaign_links",
    "value",
    "risk",
    "evidence_trace",
)

_UNKNOWN_SLOT_REASONS: dict[str, str] = {
    "product_offer_summary": "commerce_product_offer_authority_unavailable",
    "catalog_links": "commerce_catalog_subject_join_unavailable",
    "exposures": "commerce_exposure_subject_join_unavailable",
    "intent": "commerce_intent_subject_join_unavailable",
    "cart_checkout": "commerce_cart_checkout_authority_unavailable",
    "availability_price": "commerce_availability_price_authority_unavailable",
    "risk": "commerce_risk_exact_catalog_subject_join_unavailable",
}

_JOIN_BASIS_BY_SUBJECT_KIND: dict[str, str] = {
    "journey": "explicit_journey_step_commerce_order_ref",
    "campaign": "explicit_campaign_scoped_canonical_activity_commerce_order_ref",
    "entity": "explicit_canonical_profile_scoped_activity_commerce_order_ref",
}
_SUBJECT_ID_FIELD = {
    "journey": "journey_id",
    "campaign": "campaign_id",
    "entity": "entity_id",
}
_PAYMENT_FACT_KINDS = frozenset({"order", "payment", "refund", "adjustment", "settlement"})
_SUPPORTED_PAYMENT_SECTIONS = frozenset({"purchase", "value", "evidence_trace"})
_SOURCE_FRESHNESS_UNKNOWN = "commerce_source_freshness_threshold_not_configured"
_POLICY_OWNER = "experience360_frame_runtime"
_MAX_PAYMENT_FACTS = 500
_MAX_CAMPAIGN_ASSOCIATIONS = 500
_MAX_OPERATION_LINKS = 500
_MAX_CATALOG_OFFERS = 500
_MAX_COMMERCE_RISK_SIGNALS = 100
_MAX_COMMERCE_RISK_ASSESSMENTS = 50
_RISK_JOIN_BASIS = "exact_tenant_scoped_catalog_subject_to_risk360_subject"
_RISK_PARTIAL_REASON = (
    "exact_product_or_offer_risk_records_observed_but_freshness_history_and_causality_unresolved"
)
_RISK_HISTORICAL_UNKNOWN = "commerce_risk_historical_snapshot_unavailable"
_RISK_WINDOW_UNKNOWN = "commerce_risk_requested_temporal_window_unavailable"
_RISK_SOURCE_COMPLETENESS_UNKNOWN = "commerce_risk_history_coverage_not_established"
_RISK_FRESHNESS_UNKNOWN = "commerce_risk_freshness_threshold_not_configured"

_CATALOG_JOIN_BASIS_BY_SUBJECT_KIND: dict[str, str] = {
    "product": "tenant_scoped_canonical_product_id",
    "offer": "tenant_scoped_canonical_offer_product_id",
}
_INTENT_JOIN_BASIS_BY_SUBJECT_KIND: dict[str, str] = {
    "product": "explicit_tenant_scoped_product_intent_reference",
    "offer": "explicit_tenant_scoped_offer_intent_reference",
}
_AVAILABILITY_UNKNOWN = "commerce_inventory_authority_not_connected"
_OFFER_PRICE_UNKNOWN = "commerce_offer_price_authority_not_connected"
_AVAILABILITY_PRICE_PARTIAL = "commerce_availability_price_authority_not_connected"
_MAX_INTENT_RECORDS = 500
_OBSERVATION_SLOTS = ("exposures", "cart_checkout")
_OBSERVATION_TABLES = {
    "exposures": "silver_exposure_facts",
    "cart_checkout": "silver_commerce_flow_facts",
}


class CommerceOperationEvidenceSource(Protocol):
    """Narrow read seam for exact commerce-operation evidence."""

    async def read(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        as_of: Optional[str],
    ) -> dict[str, Any]:
        """Return evidence for exactly one tenant and canonical subject."""


class CommerceProductOfferCatalogEvidenceSource(Protocol):
    """Narrow read seam for canonical product/offer catalog records."""

    async def read(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        as_of: Optional[str],
    ) -> dict[str, Any]:
        """Return catalog evidence for exactly one tenant and subject."""


class CommerceIntentEvidenceSource(Protocol):
    """Narrow read seam for explicit commerce intent declarations."""

    async def read(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        as_of: Optional[str],
    ) -> dict[str, Any]:
        """Return intent records for exactly one tenant and canonical subject."""


class CommerceRiskEvidenceSource(Protocol):
    """Bounded exact-subject reader for canonical Risk360 outputs."""

    async def read(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        signal_limit: int,
        assessment_limit: int,
    ) -> dict[str, Any]:
        """Return risk records for exactly one tenant and typed subject."""


class CommerceObservedEventEvidenceSource(Protocol):
    """Read bounded source events for an exact canonical catalog key."""

    async def read(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        slot: str,
        as_of: str,
        historical: bool,
    ) -> dict[str, Any]:
        """Return accepted event observations without raw payloads."""


class RepositoryCommerceRiskEvidenceSource:
    """Read current Risk360 records by exact tenant, subject kind, and ID."""

    async def read(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        signal_limit: int,
        assessment_limit: int,
    ) -> dict[str, Any]:
        signals, assessments = await _read_commerce_risk_repositories(
            tenant_id,
            subject,
            signal_limit=signal_limit,
            assessment_limit=assessment_limit,
        )
        return {
            "_scope": {
                "tenantId": tenant_id,
                "subjectKind": subject.kind,
                "subjectId": subject.id,
            },
            "join_basis": "exact_tenant_scoped_catalog_subject_to_risk360_subject",
            "sourceState": "available",
            "signals": signals,
            "assessments": assessments,
            "truncated": (len(signals) > signal_limit or len(assessments) > assessment_limit),
            "authorityRefs": [
                "commerce_product_offer_graph",
                "risk_outputs",
                "risk_signals",
                "risk_assessments",
                "source_provenance",
            ],
        }


async def _read_commerce_risk_repositories(
    tenant_id: str,
    subject: ProjectionSubject,
    *,
    signal_limit: int,
    assessment_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep repository calls in a seam that can be asserted in focused tests."""
    from intelligence.risk360.store import RiskAssessmentRepository, RiskSignalRepository

    signals = await RiskSignalRepository().list_by_subject(
        tenant_id,
        subject.kind,
        subject.id,
        limit=signal_limit,
        offset=0,
    )
    assessments = await RiskAssessmentRepository().list_by_subject(
        tenant_id,
        subject.kind,
        subject.id,
        limit=assessment_limit,
        offset=0,
    )
    return signals, assessments


class RepositoryCommerceProductOfferCatalogEvidenceSource:
    """Read immutable catalog revisions through exact tenant and ID queries."""

    def __init__(
        self,
        repository: Optional[CommerceProductOfferCatalogRepository] = None,
    ) -> None:
        self._repository = repository or CommerceProductOfferCatalogRepository()

    async def read(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        as_of: Optional[str],
    ) -> dict[str, Any]:
        scope = {
            "tenantId": tenant_id,
            "subjectKind": subject.kind,
            "subjectId": subject.id,
        }
        join_basis = _CATALOG_JOIN_BASIS_BY_SUBJECT_KIND.get(subject.kind)
        if join_basis is None:
            return {
                "_scope": scope,
                "join_basis": "unsupported_catalog_subject_kind",
                "sourceState": "unknown",
                "reason": "commerce_catalog_subject_kind_not_supported",
            }

        anchor = _parse_catalog_anchor(as_of)
        if as_of is not None and anchor is None:
            return {
                "_scope": scope,
                "join_basis": join_basis,
                "sourceState": "unknown",
                "reason": "commerce_catalog_as_of_invalid",
                "product": None,
                "offers": [],
            }

        try:
            if subject.kind == "product":
                product = await self._repository.get_product(tenant_id, subject.id, as_of=anchor)
                if product is None:
                    return {
                        "_scope": scope,
                        "join_basis": join_basis,
                        "sourceState": "missing",
                        "reason": "commerce_product_record_not_found",
                        "product": None,
                        "offers": [],
                        "asOf": as_of,
                    }
                offers, truncated = await self._repository.list_offers_for_product(
                    tenant_id,
                    product.product_id,
                    as_of=anchor,
                    limit=_MAX_CATALOG_OFFERS,
                )
                return {
                    "_scope": scope,
                    "join_basis": join_basis,
                    "sourceState": "degraded" if truncated else "available",
                    "reason": "commerce_catalog_offer_list_truncated" if truncated else None,
                    "product": product.model_dump(mode="json"),
                    "offers": [offer.model_dump(mode="json") for offer in offers],
                    "truncated": truncated,
                    "asOf": as_of,
                }

            offer = await self._repository.get_offer(tenant_id, subject.id, as_of=anchor)
            if offer is None:
                return {
                    "_scope": scope,
                    "join_basis": join_basis,
                    "sourceState": "missing",
                    "reason": "commerce_offer_record_not_found",
                    "product": None,
                    "offers": [],
                    "asOf": as_of,
                }
            product = await self._repository.get_product(tenant_id, offer.product_id, as_of=anchor)
            if product is None:
                return {
                    "_scope": scope,
                    "join_basis": join_basis,
                    "sourceState": "degraded",
                    "reason": "commerce_offer_product_reference_unresolved",
                    "product": None,
                    "offers": [offer.model_dump(mode="json")],
                    "asOf": as_of,
                }
            return {
                "_scope": scope,
                "join_basis": join_basis,
                "sourceState": "available",
                "reason": None,
                "product": product.model_dump(mode="json"),
                "offers": [offer.model_dump(mode="json")],
                "truncated": False,
                "asOf": as_of,
            }
        except Exception:  # noqa: BLE001 - a failed authority read is explicit unknown
            return {
                "_scope": scope,
                "join_basis": join_basis,
                "sourceState": "unknown",
                "reason": "commerce_product_offer_catalog_unavailable",
                "product": None,
                "offers": [],
                "asOf": as_of,
            }


class RepositoryCommerceIntentEvidenceSource:
    """Read complete, bounded intent revisions for exact product/offer IDs."""

    def __init__(
        self,
        repository: Optional[CommerceIntentRepository] = None,
        catalog: Optional[CommerceProductOfferCatalogRepository] = None,
    ) -> None:
        self._repository = repository or CommerceIntentRepository(catalog=catalog)
        self._catalog = catalog or CommerceProductOfferCatalogRepository()

    async def read(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        as_of: Optional[str],
    ) -> dict[str, Any]:
        scope = {
            "tenantId": tenant_id,
            "subjectKind": subject.kind,
            "subjectId": subject.id,
        }
        join_basis = _INTENT_JOIN_BASIS_BY_SUBJECT_KIND.get(subject.kind)
        if join_basis is None:
            return {
                "_scope": scope,
                "join_basis": "unsupported_intent_subject_kind",
                "sourceState": "unknown",
                "reason": "commerce_intent_subject_kind_not_supported",
                "records": [],
                "truncated": False,
                "asOf": as_of,
                "sourceCompleteness": "unknown",
                "authorityRefs": [
                    "commerce_intent_authority",
                    "commerce_product_offer_graph",
                    "source_provenance",
                ],
            }

        anchor = _parse_catalog_anchor(as_of)
        if as_of is not None and anchor is None:
            return {
                "_scope": scope,
                "join_basis": join_basis,
                "sourceState": "unknown",
                "reason": "commerce_intent_as_of_invalid",
                "records": [],
                "truncated": False,
                "asOf": as_of,
                "sourceCompleteness": "unknown",
                "authorityRefs": [
                    "commerce_intent_authority",
                    "commerce_product_offer_graph",
                    "source_provenance",
                ],
            }

        try:
            if subject.kind == "product":
                canonical_subject = await self._catalog.get_product(
                    tenant_id, subject.id, as_of=anchor
                )
            else:
                canonical_subject = await self._catalog.get_offer(
                    tenant_id, subject.id, as_of=anchor
                )
            if canonical_subject is None:
                return {
                    "_scope": scope,
                    "join_basis": join_basis,
                    "sourceState": "missing",
                    "reason": "commerce_intent_canonical_subject_not_found",
                    "records": [],
                    "truncated": False,
                    "asOf": as_of,
                    "sourceCompleteness": "complete",
                    "authorityRefs": [
                        "commerce_intent_authority",
                        "commerce_product_offer_graph",
                        "source_provenance",
                    ],
                }
            records, truncated = await self._repository.list_for_subject(
                tenant_id,
                subject.kind,  # type: ignore[arg-type] - guarded by the join-basis map
                subject.id,
                as_of=anchor,
                limit=_MAX_INTENT_RECORDS,
            )
            state = "degraded" if truncated else "available" if records else "empty"
            return {
                "_scope": scope,
                "join_basis": join_basis,
                "sourceState": state,
                "reason": "commerce_intent_record_list_truncated" if truncated else None,
                "records": [record.model_dump(mode="json") for record in records],
                "truncated": truncated,
                "asOf": as_of,
                "sourceCompleteness": "partial" if truncated else "complete",
                "authorityRefs": [
                    "commerce_intent_authority",
                    "commerce_product_offer_graph",
                    "source_provenance",
                ],
            }
        except Exception:  # noqa: BLE001 - a failed authority read is explicit unknown
            return {
                "_scope": scope,
                "join_basis": join_basis,
                "sourceState": "unknown",
                "reason": "commerce_intent_authority_unavailable",
                "records": [],
                "truncated": False,
                "asOf": as_of,
                "sourceCompleteness": "unknown",
                "authorityRefs": [
                    "commerce_intent_authority",
                    "commerce_product_offer_graph",
                    "source_provenance",
                ],
            }


class RepositoryCommerceOperationEvidenceSource:
    """Reuse the existing exact commerce-order/payment reference readers."""

    async def read(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        as_of: Optional[str],
    ) -> dict[str, Any]:
        scope = {
            "tenantId": tenant_id,
            "subjectKind": subject.kind,
            "subjectId": subject.id,
        }
        join_basis = _JOIN_BASIS_BY_SUBJECT_KIND.get(subject.kind)
        if join_basis is None:
            return {
                "_scope": scope,
                "join_basis": "unsupported_subject_kind",
                "reason": "commerce_operation_subject_kind_not_supported",
            }

        try:
            if subject.kind == "journey":
                from value.economic.journey_operation_evidence import (
                    journey_commerce_operation_evidence,
                )

                result = await journey_commerce_operation_evidence(
                    tenant_id, subject.id, as_of=as_of
                )
            elif subject.kind == "campaign":
                from value.economic.economic360_provider import (
                    RepositoryCampaignIdentityReader,
                )
                from value.economic.journey_operation_evidence import (
                    campaign_commerce_operation_evidence,
                )

                identity = await RepositoryCampaignIdentityReader().is_canonical_campaign(
                    tenant_id, subject.id
                )
                if identity is not True:
                    return {
                        "_scope": scope,
                        "join_basis": join_basis,
                        "reason": (
                            "campaign_identity_authority_unavailable"
                            if identity is None
                            else "campaign_canonical_identity_unresolved"
                        ),
                    }
                result = await campaign_commerce_operation_evidence(
                    tenant_id, subject.id, as_of=as_of
                )
            else:
                from value.economic.economic360_provider import (
                    RepositoryProfileIdentityReader,
                )
                from value.economic.journey_operation_evidence import (
                    entity_commerce_operation_evidence,
                )

                identity = await RepositoryProfileIdentityReader().is_canonical_profile(
                    tenant_id, subject.id
                )
                if identity is not True:
                    return {
                        "_scope": scope,
                        "join_basis": join_basis,
                        "reason": (
                            "profile_identity_authority_unavailable"
                            if identity is None
                            else "profile_canonical_identity_unresolved"
                        ),
                    }
                result = await entity_commerce_operation_evidence(
                    tenant_id, subject.id, as_of=as_of
                )
        except Exception:  # noqa: BLE001 - an unavailable source stays unknown
            return {
                "_scope": scope,
                "join_basis": join_basis,
                "reason": "commerce_operation_evidence_unavailable",
            }

        if not isinstance(result, dict):
            return {
                "_scope": scope,
                "join_basis": join_basis,
                "reason": "commerce_operation_evidence_invalid",
            }
        return {**result, "_scope": scope}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_catalog_anchor(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    try:
        anchor = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if anchor.tzinfo is None:
        return None
    return anchor.astimezone(timezone.utc)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}.{digest}"


def _safe_text(value: Any, *, limit: int = 256) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit or any(ord(char) < 32 for char in value):
        return None
    return value


def _money_string(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        return None
    try:
        amount = Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None
    return format(amount, "f") if amount.is_finite() else None


def _parse_evidence_refs(value: Any, *, required_type: Optional[str] = None) -> list[EvidenceRef]:
    if not isinstance(value, list):
        return []
    refs: list[EvidenceRef] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in value:
        try:
            ref = EvidenceRef.model_validate(raw)
        except Exception:  # noqa: BLE001 - malformed provenance fails closed
            continue
        if required_type is not None and ref.type != required_type:
            continue
        key = (ref.id, ref.type, ref.source)
        if key not in seen:
            refs.append(ref)
            seen.add(key)
    return refs


def _catalog_record_output(
    record: CommerceProductRecord | CommerceOfferRecord,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "tenantId": record.tenant_id,
        "title": record.title,
        "description": record.description,
        "lifecycleState": record.lifecycle_state,
        "validFrom": record.valid_from.isoformat() if record.valid_from else None,
        "validTo": record.valid_to.isoformat() if record.valid_to else None,
        "observedAt": record.observed_at.isoformat(),
        "sourceProvider": record.source_provider,
        "sourceRecordId": record.source_record_id,
        "sourceRevisionId": record.source_revision_id,
        "evidenceRefs": [ref.model_dump(mode="json") for ref in record.evidence_refs],
    }
    if isinstance(record, CommerceProductRecord):
        output["productId"] = record.product_id
    else:
        output["offerId"] = record.offer_id
        output["productId"] = record.product_id
    return output


def _intent_record_output(record: CommerceIntentRecord) -> dict[str, Any]:
    """Render an explicit declaration with actor, time, and exact evidence."""
    return {
        "intentId": record.intent_id,
        "subjectKind": record.subject_kind,
        "subjectId": record.subject_id,
        "intentKind": record.intent_kind,
        "state": record.state,
        "actor": {"kind": record.actor_kind, "id": record.actor_id},
        "effectiveAt": record.effective_at.isoformat(),
        "observedAt": record.observed_at.isoformat(),
        "sourceProvider": record.source_provider,
        "sourceRecordId": record.source_record_id,
        "sourceRevisionId": record.source_revision_id,
        "evidenceRefs": [ref.model_dump(mode="json") for ref in record.evidence_refs],
    }


def _availability_catalog_record_output(
    record: CommerceProductRecord | CommerceOfferRecord,
    *,
    record_type: str,
) -> dict[str, Any]:
    """Render source lifecycle evidence without implying sellable inventory."""
    output: dict[str, Any] = {
        "recordType": record_type,
        "tenantId": record.tenant_id,
        "lifecycleState": record.lifecycle_state,
        "validFrom": record.valid_from.isoformat() if record.valid_from else None,
        "validTo": record.valid_to.isoformat() if record.valid_to else None,
        "observedAt": record.observed_at.isoformat(),
        "sourceProvider": record.source_provider,
        "sourceRecordId": record.source_record_id,
        "sourceRevisionId": record.source_revision_id,
        "evidenceRefs": [ref.model_dump(mode="json") for ref in record.evidence_refs],
    }
    if isinstance(record, CommerceProductRecord):
        output["productId"] = record.product_id
    else:
        output["offerId"] = record.offer_id
        output["productId"] = record.product_id
    return output


def _slot_content(
    *,
    state: str,
    request: ProjectionRequest,
    reason_codes: list[str],
    as_of: Optional[str],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "state": state,
        "tenantId": request.tenantId,
        "subject": request.subject.model_dump(mode="json"),
        "reasonCodes": reason_codes,
        "asOf": as_of,
        "freshness": {"state": "unknown", "reasonCode": _SOURCE_FRESHNESS_UNKNOWN},
        "policy": {
            "evaluationOwner": _POLICY_OWNER,
            "projectionDisclosesOnlyScopedCommerceFacts": True,
        },
        **extra,
    }


class Commerce360Provider:
    """Read-only Commerce360 provider over explicit order/payment references."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(
        self,
        source: Optional[CommerceOperationEvidenceSource] = None,
        catalog_source: Optional[CommerceProductOfferCatalogEvidenceSource] = None,
        intent_source: Optional[CommerceIntentEvidenceSource] = None,
        risk_source: Optional[CommerceRiskEvidenceSource] = None,
        observed_event_source: Optional[CommerceObservedEventEvidenceSource] = None,
    ) -> None:
        self._source = source if source is not None else RepositoryCommerceOperationEvidenceSource()
        self._catalog_source = catalog_source
        if self._catalog_source is None and source is None:
            self._catalog_source = RepositoryCommerceProductOfferCatalogEvidenceSource()
        self._intent_source = intent_source or RepositoryCommerceIntentEvidenceSource()
        self._risk_source = risk_source or RepositoryCommerceRiskEvidenceSource()
        self._observed_event_source = (
            observed_event_source or RepositoryCommerceObservedEventSource()
        )

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        requested_as_of = request.asOf or context.asOf or _utc_now_iso()
        scope_valid = (
            bool(request.tenantId.strip())
            and bool(request.subject.id.strip())
            and context.tenantId == request.tenantId
            and context.projectionId == self.projection_id
        )
        if scope_valid:
            try:
                raw = await self._source.read(
                    request.tenantId,
                    request.subject,
                    as_of=requested_as_of,
                )
            except Exception:  # noqa: BLE001 - source outage becomes explicit unknown
                raw = {
                    "_scope": {
                        "tenantId": request.tenantId,
                        "subjectKind": request.subject.kind,
                        "subjectId": request.subject.id,
                    },
                    "join_basis": _JOIN_BASIS_BY_SUBJECT_KIND.get(request.subject.kind),
                    "reason": "commerce_operation_evidence_unavailable",
                }
        else:
            raw = {
                "_scope": {
                    "tenantId": request.tenantId,
                    "subjectKind": request.subject.kind,
                    "subjectId": request.subject.id,
                },
                "join_basis": _JOIN_BASIS_BY_SUBJECT_KIND.get(request.subject.kind),
                "reason": "commerce_projection_context_scope_mismatch",
            }

        evidence = self._validate_source_result(raw, request)
        section_states = self._section_states(evidence, request.subject.kind, scope_valid)

        catalog_raw: dict[str, Any]
        if scope_valid and self._catalog_source is not None:
            try:
                catalog_raw = await self._catalog_source.read(
                    request.tenantId,
                    request.subject,
                    as_of=requested_as_of,
                )
            except Exception:  # noqa: BLE001 - catalog outage remains explicit unknown
                catalog_raw = self._unknown_catalog_result(
                    request,
                    reason="commerce_product_offer_catalog_unavailable",
                )
        else:
            catalog_raw = self._unknown_catalog_result(
                request,
                reason=(
                    "commerce_projection_context_scope_mismatch"
                    if not scope_valid
                    else "commerce_product_offer_catalog_source_not_configured"
                ),
            )
        catalog = self._validate_catalog_result(catalog_raw, request, as_of=requested_as_of)
        section_states.update(self._catalog_section_states(catalog, request.subject.kind))

        observations: dict[str, dict[str, Any]] = {}
        canonical_catalog_subject = self._catalog_subject_is_canonical(
            request.subject.kind, request.subject.id, catalog
        )
        for slot in _OBSERVATION_SLOTS:
            if (
                request.includeSections is not None
                and slot not in request.includeSections
                and "evidence_trace" not in request.includeSections
            ):
                observation_raw = self._unknown_observation_result(
                    request, slot, reason="commerce_observation_slot_not_requested"
                )
            elif not scope_valid:
                observation_raw = self._unknown_observation_result(
                    request, slot, reason="commerce_projection_context_scope_mismatch"
                )
            elif not canonical_catalog_subject:
                observation_raw = self._unknown_observation_result(
                    request, slot, reason="commerce_observation_requires_canonical_catalog_key"
                )
            else:
                try:
                    observation_raw = await self._observed_event_source.read(
                        request.tenantId,
                        request.subject,
                        slot=slot,
                        as_of=requested_as_of,
                        historical=(request.asOf is not None or request.temporalMode == "as_of"),
                    )
                except Exception:  # noqa: BLE001 - isolate a Silver read failure
                    observation_raw = self._unknown_observation_result(
                        request, slot, reason="commerce_observation_source_unavailable"
                    )
            observations[slot] = self._validate_observation_result(
                observation_raw, request, slot=slot, as_of=requested_as_of
            )
            section_states[slot] = observations[slot]["sourceState"]

        if scope_valid:
            try:
                intent_raw = await self._intent_source.read(
                    request.tenantId,
                    request.subject,
                    as_of=requested_as_of,
                )
            except Exception:  # noqa: BLE001 - intent authority outage is explicit unknown
                intent_raw = self._unknown_intent_result(
                    request, reason="commerce_intent_authority_unavailable"
                )
        else:
            intent_raw = self._unknown_intent_result(
                request, reason="commerce_projection_context_scope_mismatch"
            )
        intents = self._validate_intent_result(intent_raw, request, as_of=requested_as_of)
        section_states["intent"] = intents.get("sourceState", "unknown")
        if intents.get("records") and section_states.get("evidence_trace") in {"empty", "unknown"}:
            section_states["evidence_trace"] = "available"
        if any(observations[slot]["records"] for slot in _OBSERVATION_SLOTS) and (
            section_states.get("evidence_trace") in {"empty", "unknown"}
        ):
            section_states["evidence_trace"] = "degraded"

        risk_requested = request.includeSections is None or "risk" in request.includeSections
        has_canonical_risk_subject = self._catalog_subject_is_canonical(
            request.subject.kind,
            request.subject.id,
            catalog,
        )
        risk_raw: dict[str, Any]
        if not risk_requested:
            risk_raw = self._unknown_risk_result(
                request,
                reason="commerce_risk_slot_not_requested",
            )
        elif (
            request.asOf is not None or context.asOf is not None or request.temporalMode == "as_of"
        ):
            # The risk stores expose current tenant/subject rows and do not
            # reconstruct prior assessment/signal revisions. Never present a
            # current read as a historical point-in-time answer.
            risk_raw = self._unknown_risk_result(request, reason=_RISK_HISTORICAL_UNKNOWN)
        elif request.timeRange is not None or request.temporalMode in {"compare", "relative"}:
            # Risk repositories do not support temporal window filtering.
            risk_raw = self._unknown_risk_result(request, reason=_RISK_WINDOW_UNKNOWN)
        elif not scope_valid:
            risk_raw = self._unknown_risk_result(
                request,
                reason="commerce_projection_context_scope_mismatch",
            )
        elif not has_canonical_risk_subject:
            risk_raw = self._unknown_risk_result(
                request,
                reason="commerce_risk_requires_exact_canonical_product_or_offer_record",
            )
        else:
            try:
                risk_raw = await self._risk_source.read(
                    request.tenantId,
                    request.subject,
                    signal_limit=_MAX_COMMERCE_RISK_SIGNALS + 1,
                    assessment_limit=_MAX_COMMERCE_RISK_ASSESSMENTS + 1,
                )
            except Exception:  # noqa: BLE001 - risk outage remains isolated to its slot
                risk_raw = self._unknown_risk_result(
                    request,
                    reason="commerce_risk_authority_unavailable",
                )
        risk = self._validate_risk_result(
            risk_raw,
            request,
            as_of=requested_as_of,
            has_canonical_subject=has_canonical_risk_subject,
        )
        section_states["risk"] = risk.get("sourceState", "unknown")

        sections = self._build_sections(
            request,
            evidence,
            catalog,
            intents,
            risk,
            observations,
            section_states,
            as_of=requested_as_of,
        )
        claims = self._build_claims(
            request, evidence, catalog, intents, risk, observations, section_states
        )
        if request.includeSections is not None:
            include = set(request.includeSections)
            sections = [section for section in sections if section.id in include]
            claims = [
                claim for claim in claims if set(claim.domainSlotIds or []).intersection(include)
            ]
        if request.includeClaims is False:
            claims = []

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            asOf=requested_as_of,
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
        )

    @staticmethod
    def _catalog_subject_is_canonical(
        subject_kind: str,
        subject_id: str,
        catalog: dict[str, Any],
    ) -> bool:
        """Require a persisted product/offer row before using its ID as a risk join."""
        if subject_kind == "product":
            product = catalog.get("product")
            return bool(
                catalog.get("sourceState") in {"available", "degraded"}
                and isinstance(product, CommerceProductRecord)
                and product.product_id == subject_id
            )
        if subject_kind == "offer":
            return bool(
                catalog.get("sourceState") in {"available", "degraded"}
                and any(
                    isinstance(offer, CommerceOfferRecord) and offer.offer_id == subject_id
                    for offer in catalog.get("offers", [])
                )
            )
        return False

    @staticmethod
    def _unknown_catalog_result(
        request: ProjectionRequest,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "_scope": {
                "tenantId": request.tenantId,
                "subjectKind": request.subject.kind,
                "subjectId": request.subject.id,
            },
            "join_basis": _CATALOG_JOIN_BASIS_BY_SUBJECT_KIND.get(
                request.subject.kind,
                "unsupported_catalog_subject_kind",
            ),
            "sourceState": "unknown",
            "reason": reason,
            "product": None,
            "offers": [],
        }

    @staticmethod
    def _unknown_observation_result(
        request: ProjectionRequest, slot: str, *, reason: str
    ) -> dict[str, Any]:
        return {
            "_scope": {
                "tenantId": request.tenantId,
                "subjectKind": request.subject.kind,
                "subjectId": request.subject.id,
            },
            "slot": slot,
            "sourceState": "unknown",
            "reason": reason,
            "records": [],
            "sourceCompleteness": "unknown",
            "truncated": False,
            "authorityRefs": [
                "commerce_product_offer_graph",
                _OBSERVATION_TABLES[slot],
                "source_provenance",
            ],
        }

    def _validate_observation_result(
        self,
        raw: Any,
        request: ProjectionRequest,
        *,
        slot: str,
        as_of: str,
    ) -> dict[str, Any]:
        empty = self._unknown_observation_result(
            request, slot, reason="commerce_observation_source_scope_mismatch"
        )
        expected_scope = empty["_scope"]
        if (
            not isinstance(raw, dict)
            or raw.get("_scope") != expected_scope
            or raw.get("slot") != slot
        ):
            return empty
        state = raw.get("sourceState")
        if state not in {"unknown", "degraded", "available"}:
            return {**empty, "reason": "commerce_observation_state_invalid"}
        if state == "unknown":
            return {**empty, "reason": _safe_text(raw.get("reason"), limit=128) or empty["reason"]}
        if raw.get("asOf") != as_of:
            return {**empty, "reason": "commerce_observation_as_of_scope_mismatch"}
        authority_refs = raw.get("authorityRefs")
        required = {
            "commerce_product_offer_graph",
            _OBSERVATION_TABLES[slot],
            "source_provenance",
        }
        if not isinstance(authority_refs, list) or not required.issubset(
            set(ref for ref in authority_refs if isinstance(ref, str))
        ):
            return {**empty, "reason": "commerce_observation_authority_refs_missing"}
        raw_records = raw.get("records")
        if not isinstance(raw_records, list) or len(raw_records) > 500:
            return {**empty, "reason": "commerce_observation_records_invalid"}
        anchor = _parse_catalog_anchor(as_of)
        if anchor is None:
            return {**empty, "reason": "commerce_observation_anchor_invalid"}
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        historical = request.asOf is not None or request.temporalMode == "as_of"
        for row in raw_records:
            if not isinstance(row, dict):
                return {**empty, "reason": "commerce_observation_record_invalid"}
            source_id = _safe_text(row.get("sourceEventId"), limit=512)
            event_type = _safe_text(row.get("eventType"), limit=128)
            occurred = _parse_catalog_anchor(row.get("occurredAt"))
            received = _parse_catalog_anchor(row.get("receivedAt"))
            if (
                not source_id
                or source_id in seen
                or not event_type
                or occurred is None
                or occurred > anchor
                or row.get("subjectKind") != request.subject.kind
                or row.get("subjectId") != request.subject.id
                or row.get("sourceTable") != _OBSERVATION_TABLES[slot]
                or (received is not None and received > anchor)
                or (historical and received is None)
            ):
                return {**empty, "reason": "commerce_observation_record_invalid"}
            seen.add(source_id)
            record = {
                "sourceEventId": source_id,
                "eventType": event_type,
                "subjectKind": request.subject.kind,
                "subjectId": request.subject.id,
                "occurredAt": occurred.isoformat(),
                "receivedAt": received.isoformat() if received else None,
                "sourceTable": _OBSERVATION_TABLES[slot],
                "consentSnapshotId": _safe_text(row.get("consentSnapshotId"), limit=512),
            }
            if slot == "cart_checkout":
                if event_type not in {
                    "cart_item_added", "cart_item_removed", "cart_updated",
                    "checkout_started", "checkout_step_completed",
                }:
                    return {**empty, "reason": "commerce_observation_event_type_invalid"}
                record["cartId"] = _safe_text(row.get("cartId"), limit=256)
                record["checkoutId"] = _safe_text(row.get("checkoutId"), limit=256)
            records.append(record)
        if not records:
            return {**empty, "reason": "no_exact_source_observation_source_coverage_unknown"}
        return {
            "sourceState": "degraded",
            "reason": _safe_text(raw.get("reason"), limit=128)
            or "source_asserted_observations_coverage_and_freshness_unknown",
            "records": records,
            "truncated": raw.get("truncated") is True,
            "sourceCompleteness": (
                "partial" if raw.get("sourceCompleteness") == "partial" else "unknown"
            ),
            "authorityRefs": list(authority_refs),
        }

    @staticmethod
    def _unknown_intent_result(
        request: ProjectionRequest,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "_scope": {
                "tenantId": request.tenantId,
                "subjectKind": request.subject.kind,
                "subjectId": request.subject.id,
            },
            "join_basis": _INTENT_JOIN_BASIS_BY_SUBJECT_KIND.get(
                request.subject.kind, "unsupported_intent_subject_kind"
            ),
            "sourceState": "unknown",
            "reason": reason,
            "records": [],
            "truncated": False,
            "asOf": None,
            "sourceCompleteness": "unknown",
            "authorityRefs": [
                "commerce_intent_authority",
                "commerce_product_offer_graph",
                "source_provenance",
            ],
        }

    @staticmethod
    def _unknown_risk_result(
        request: ProjectionRequest,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "_scope": {
                "tenantId": request.tenantId,
                "subjectKind": request.subject.kind,
                "subjectId": request.subject.id,
            },
            "join_basis": _RISK_JOIN_BASIS,
            "sourceState": "unknown",
            "reason": reason,
            "signals": [],
            "assessments": [],
            "truncated": False,
            "authorityRefs": [
                "commerce_product_offer_graph",
                "risk_outputs",
                "risk_signals",
                "risk_assessments",
                "source_provenance",
            ],
        }

    def _validate_risk_result(
        self,
        raw: Any,
        request: ProjectionRequest,
        *,
        as_of: Optional[str],
        has_canonical_subject: bool,
    ) -> dict[str, Any]:
        """Validate exact risk records without upgrading their epistemic state."""
        empty: dict[str, Any] = {
            "sourceState": "unknown",
            "reason": "commerce_risk_source_scope_mismatch",
            "signals": [],
            "assessments": [],
            "evidence": [],
            "truncated": False,
            "sourceCompleteness": "unknown",
            "join_basis": _RISK_JOIN_BASIS,
            "authorityRefs": [
                "commerce_product_offer_graph",
                "risk_outputs",
                "risk_signals",
                "risk_assessments",
                "source_provenance",
            ],
        }
        expected_scope = {
            "tenantId": request.tenantId,
            "subjectKind": request.subject.kind,
            "subjectId": request.subject.id,
        }
        if not has_canonical_subject:
            return {
                **empty,
                "reason": (
                    _safe_text(raw.get("reason"), limit=96) if isinstance(raw, dict) else None
                )
                or "commerce_risk_requires_exact_canonical_product_or_offer_record",
            }
        if (
            not isinstance(raw, dict)
            or raw.get("_scope") != expected_scope
            or raw.get("join_basis") != _RISK_JOIN_BASIS
        ):
            return empty

        authority_refs = raw.get("authorityRefs")
        required_authorities = {
            "commerce_product_offer_graph",
            "risk_outputs",
            "risk_signals",
            "risk_assessments",
            "source_provenance",
        }
        if (
            not isinstance(authority_refs, list)
            or not all(isinstance(ref, str) and ref for ref in authority_refs)
            or not required_authorities.issubset(set(authority_refs))
        ):
            return {**empty, "reason": "commerce_risk_authority_references_missing"}
        state = raw.get("sourceState")
        if state not in {"available", "empty", "missing", "unknown", "degraded"}:
            return {**empty, "reason": "commerce_risk_source_state_invalid"}
        if "truncated" in raw and not isinstance(raw.get("truncated"), bool):
            return {**empty, "reason": "commerce_risk_truncation_state_invalid"}

        anchor = _parse_catalog_anchor(as_of)
        if anchor is None:
            return {**empty, "reason": "commerce_risk_effective_anchor_invalid"}

        from intelligence.risk360.contracts import RiskAssessment, RiskSignal

        invalid_records = 0
        signals: list[dict[str, Any]] = []
        assessments: list[dict[str, Any]] = []
        evidence: list[EvidenceRef] = []
        raw_signals = raw.get("signals")
        raw_assessments = raw.get("assessments")
        if not isinstance(raw_signals, list):
            raw_signals = []
            invalid_records += 1
        if not isinstance(raw_assessments, list):
            raw_assessments = []
            invalid_records += 1
        source_capped = (
            len(raw_signals) > _MAX_COMMERCE_RISK_SIGNALS
            or len(raw_assessments) > _MAX_COMMERCE_RISK_ASSESSMENTS
        )
        seen_signal_ids: set[str] = set()
        seen_assessment_ids: set[str] = set()

        for row in raw_signals[:_MAX_COMMERCE_RISK_SIGNALS]:
            try:
                signal = RiskSignal.model_validate(row)
            except Exception:  # noqa: BLE001 - invalid canonical row fails closed
                invalid_records += 1
                continue
            if (
                signal.tenant_id != request.tenantId
                or signal.subject_kind != request.subject.kind
                or signal.subject_id != request.subject.id
                or signal.signal_id in seen_signal_ids
                or not signal.evidence_refs
                or (signal.observed_at is not None and signal.observed_at > anchor)
            ):
                invalid_records += 1
                continue
            seen_signal_ids.add(signal.signal_id)
            signal_refs = _parse_evidence_refs(
                [ref.model_dump(mode="json", exclude_none=True) for ref in signal.evidence_refs]
            )
            if not signal_refs:
                invalid_records += 1
                continue
            record_ref = EvidenceRef(
                id=signal.signal_id,
                type="event",
                source="risk360/risk_signals",
                observedAt=signal.observed_at.isoformat() if signal.observed_at else None,
                uri=f"store://risk_signals/{quote(signal.signal_id, safe='')}",
            )
            evidence.extend([record_ref, *signal_refs])
            signals.append(
                {
                    "signalId": signal.signal_id,
                    "subject": {"kind": signal.subject_kind, "id": signal.subject_id},
                    "riskDimension": signal.risk_dimension,
                    "claimState": getattr(signal.claim_state, "value", signal.claim_state),
                    "confidence": signal.confidence,
                    "score": signal.score,
                    "value": signal.value,
                    "source": signal.source,
                    "detectorVersion": signal.detector_version,
                    "observedAt": signal.observed_at.isoformat() if signal.observed_at else None,
                    "evidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in [record_ref, *signal_refs]
                    ],
                }
            )

        for row in raw_assessments[:_MAX_COMMERCE_RISK_ASSESSMENTS]:
            try:
                assessment = RiskAssessment.model_validate(row)
            except Exception:  # noqa: BLE001 - invalid canonical row fails closed
                invalid_records += 1
                continue
            if (
                assessment.tenant_id != request.tenantId
                or assessment.subject_kind != request.subject.kind
                or assessment.subject_id != request.subject.id
                or assessment.assessment_id in seen_assessment_ids
                or not assessment.evidence_refs
                or (assessment.assessed_at is not None and assessment.assessed_at > anchor)
                or (
                    assessment.exposure is not None
                    and (
                        assessment.exposure.tenant_id != request.tenantId
                        or assessment.exposure.subject_kind != request.subject.kind
                        or assessment.exposure.subject_id != request.subject.id
                    )
                )
            ):
                invalid_records += 1
                continue
            seen_assessment_ids.add(assessment.assessment_id)
            assessment_refs = _parse_evidence_refs(
                [ref.model_dump(mode="json", exclude_none=True) for ref in assessment.evidence_refs]
            )
            if not assessment_refs:
                invalid_records += 1
                continue
            record_ref = EvidenceRef(
                id=assessment.assessment_id,
                type="document",
                source="risk360/risk_assessments",
                observedAt=assessment.assessed_at.isoformat() if assessment.assessed_at else None,
                uri=f"store://risk_assessments/{quote(assessment.assessment_id, safe='')}",
            )
            evidence.extend([record_ref, *assessment_refs])
            assessment_payload = assessment.model_dump(mode="json", exclude_none=True)
            assessment_payload["evidence_refs"] = [
                record_ref.model_dump(mode="json", exclude_none=True),
                *[ref.model_dump(mode="json", exclude_none=True) for ref in assessment_refs],
            ]
            assessments.append(assessment_payload)

        deduped_evidence = _parse_evidence_refs(
            [ref.model_dump(mode="json", exclude_none=True) for ref in evidence]
        )
        truncated = raw.get("truncated") is True or source_capped
        reason = _safe_text(raw.get("reason"), limit=96)
        if state in {"missing", "empty"} and (signals or assessments):
            return {**empty, "reason": "commerce_risk_empty_state_contains_records"}
        if state == "unknown":
            signals = []
            assessments = []
            deduped_evidence = []
        if signals or assessments:
            state = "degraded"
            reason = reason or _RISK_PARTIAL_REASON
        elif invalid_records or truncated or state == "degraded":
            state = "degraded"
            reason = reason or "commerce_risk_read_incomplete_or_contains_no_evidenced_record"
        else:
            # An empty exact-subject query does not establish the absence of risk.
            state = "unknown"
            reason = (
                reason or "no_exact_product_or_offer_risk_record_observed_absence_not_established"
            )

        if invalid_records or truncated:
            state = "degraded"
            reason = reason or "commerce_risk_records_invalid_or_truncated"
        return {
            "sourceState": state,
            "reason": reason,
            "signals": signals,
            "assessments": assessments,
            "evidence": deduped_evidence,
            "truncated": truncated,
            "sourceCompleteness": "partial" if truncated or invalid_records else "unknown",
            "join_basis": _RISK_JOIN_BASIS,
            "authorityRefs": list(authority_refs),
        }

    def _validate_intent_result(
        self,
        raw: Any,
        request: ProjectionRequest,
        *,
        as_of: Optional[str],
    ) -> dict[str, Any]:
        expected_scope = {
            "tenantId": request.tenantId,
            "subjectKind": request.subject.kind,
            "subjectId": request.subject.id,
        }
        expected_join_basis = _INTENT_JOIN_BASIS_BY_SUBJECT_KIND.get(request.subject.kind)
        empty: dict[str, Any] = {
            "sourceState": "unknown",
            "reason": "commerce_intent_source_scope_mismatch",
            "records": [],
            "truncated": False,
            "sourceCompleteness": "unknown",
            "authorityRefs": [
                "commerce_intent_authority",
                "commerce_product_offer_graph",
                "source_provenance",
            ],
        }
        if (
            not isinstance(raw, dict)
            or raw.get("_scope") != expected_scope
            or expected_join_basis is None
            or raw.get("join_basis") != expected_join_basis
        ):
            return empty

        state = raw.get("sourceState")
        if state not in {"available", "empty", "missing", "unknown", "degraded"}:
            return {**empty, "reason": "commerce_intent_source_state_invalid"}
        reason = _safe_text(raw.get("reason"), limit=96)
        raw_records = raw.get("records")
        invalid_records = 0
        if not isinstance(raw_records, list):
            raw_records = []
            invalid_records += 1
        source_capped = len(raw_records) > _MAX_INTENT_RECORDS
        records: list[CommerceIntentRecord] = []
        seen_intent_ids: set[str] = set()
        for row in raw_records[:_MAX_INTENT_RECORDS]:
            try:
                record = CommerceIntentRecord.model_validate(row)
            except Exception:  # noqa: BLE001 - malformed provenance fails closed
                invalid_records += 1
                continue
            if (
                record.tenant_id != request.tenantId
                or record.subject_kind != request.subject.kind
                or record.subject_id != request.subject.id
                or record.intent_id in seen_intent_ids
            ):
                invalid_records += 1
                continue
            refs = _parse_evidence_refs(
                [ref.model_dump(mode="json") for ref in record.evidence_refs]
            )
            if not any(
                ref.source == record.source_provider and ref.id == record.source_record_id
                for ref in refs
            ):
                invalid_records += 1
                continue
            anchor = _parse_catalog_anchor(as_of)
            if anchor is None or record.effective_at > anchor or record.observed_at > anchor:
                invalid_records += 1
                continue
            seen_intent_ids.add(record.intent_id)
            records.append(record)

        if "truncated" in raw and not isinstance(raw.get("truncated"), bool):
            return {**empty, "reason": "commerce_intent_truncation_state_invalid"}
        truncated = raw.get("truncated") is True or source_capped
        if state == "missing" and records:
            return {**empty, "reason": "commerce_intent_missing_state_contains_records"}
        if state == "empty" and records:
            return {**empty, "reason": "commerce_intent_empty_state_contains_records"}
        if invalid_records or truncated:
            if state in {"available", "empty", "missing"}:
                state = "degraded"
            reason = reason or "commerce_intent_records_invalid_or_truncated"
        elif state == "available" and not records:
            state = "empty"

        anchor = _parse_catalog_anchor(as_of)
        raw_as_of = raw.get("asOf")
        if state in {"available", "empty", "missing", "degraded"}:
            source_anchor = _parse_catalog_anchor(raw_as_of)
            if anchor is None or source_anchor is None or source_anchor != anchor:
                return {**empty, "reason": "commerce_intent_as_of_scope_mismatch"}

        source_completeness = raw.get("sourceCompleteness")
        if source_completeness not in {"complete", "partial", "unknown"}:
            source_completeness = "unknown"
        if truncated or invalid_records:
            source_completeness = "partial"
        elif source_completeness == "partial" and state in {"available", "empty"}:
            state = "degraded"
            reason = reason or "commerce_intent_source_completeness_partial"
        elif (
            state in {"available", "empty", "missing", "degraded"}
            and source_completeness == "unknown"
        ):
            return {**empty, "reason": "commerce_intent_completeness_not_established"}

        authority_refs = raw.get("authorityRefs")
        if not isinstance(authority_refs, list) or not all(
            isinstance(ref, str) and ref for ref in authority_refs
        ):
            return {**empty, "reason": "commerce_intent_authority_references_missing"}
        required_authorities = {
            "commerce_intent_authority",
            "commerce_product_offer_graph",
            "source_provenance",
        }
        if not required_authorities.issubset(set(authority_refs)):
            return {**empty, "reason": "commerce_intent_authority_references_missing"}
        if state == "unknown":
            records = []
        return {
            "sourceState": state,
            "reason": reason,
            "records": records,
            "truncated": truncated,
            "sourceCompleteness": source_completeness,
            "join_basis": expected_join_basis,
            "asOf": _safe_text(raw_as_of, limit=96),
            "authorityRefs": authority_refs,
        }

    def _validate_catalog_result(
        self,
        raw: Any,
        request: ProjectionRequest,
        *,
        as_of: Optional[str],
    ) -> dict[str, Any]:
        expected_scope = {
            "tenantId": request.tenantId,
            "subjectKind": request.subject.kind,
            "subjectId": request.subject.id,
        }
        expected_join_basis = _CATALOG_JOIN_BASIS_BY_SUBJECT_KIND.get(request.subject.kind)
        empty = {
            "sourceState": "unknown",
            "reason": "commerce_catalog_source_scope_mismatch",
            "product": None,
            "offers": [],
            "sourceCompleteness": "unknown",
        }
        if (
            not isinstance(raw, dict)
            or raw.get("_scope") != expected_scope
            or expected_join_basis is None
            or raw.get("join_basis") != expected_join_basis
        ):
            return empty

        state = raw.get("sourceState")
        if state not in {"available", "missing", "unknown", "degraded"}:
            return {**empty, "reason": "commerce_catalog_source_state_invalid"}
        reason = _safe_text(raw.get("reason"), limit=96)
        product: Optional[CommerceProductRecord] = None
        product_raw = raw.get("product")
        invalid_records = 0
        if product_raw is not None:
            try:
                product = CommerceProductRecord.model_validate(product_raw)
            except Exception:  # noqa: BLE001 - malformed catalog records are omitted
                invalid_records += 1
                product = None
        if product is not None and (
            product.tenant_id != request.tenantId
            or (request.subject.kind == "product" and product.product_id != request.subject.id)
        ):
            return {**empty, "reason": "commerce_catalog_product_scope_mismatch"}

        offers: list[CommerceOfferRecord] = []
        raw_offers = raw.get("offers")
        if raw_offers is not None and not isinstance(raw_offers, list):
            invalid_records += 1
            raw_offers = []
        if len(raw_offers or []) > _MAX_CATALOG_OFFERS:
            invalid_records += 1
        seen_offer_ids: set[tuple[str, str]] = set()
        for row in (raw_offers or [])[:_MAX_CATALOG_OFFERS]:
            try:
                offer = CommerceOfferRecord.model_validate(row)
            except Exception:  # noqa: BLE001 - malformed catalog records are omitted
                invalid_records += 1
                continue
            if offer.tenant_id != request.tenantId:
                invalid_records += 1
                continue
            if request.subject.kind == "product" and offer.product_id != request.subject.id:
                invalid_records += 1
                continue
            if request.subject.kind == "offer" and offer.offer_id != request.subject.id:
                invalid_records += 1
                continue
            if (
                request.subject.kind == "offer"
                and product is not None
                and offer.product_id != product.product_id
            ):
                return {**empty, "reason": "commerce_catalog_offer_product_mismatch"}
            if product is not None and offer.product_id != product.product_id:
                invalid_records += 1
                continue
            key = (offer.tenant_id, offer.offer_id)
            if key in seen_offer_ids:
                invalid_records += 1
                continue
            seen_offer_ids.add(key)
            offers.append(offer)

        if request.subject.kind == "offer" and offers and product is None:
            state = "degraded"
            reason = reason or "commerce_offer_product_reference_unresolved"
        elif (
            request.subject.kind == "offer" and offers and offers[0].offer_id != request.subject.id
        ):
            return {**empty, "reason": "commerce_catalog_offer_scope_mismatch"}
        if raw.get("truncated") is True:
            invalid_records += 1
        if invalid_records:
            state = "degraded" if state == "available" else state
            reason = reason or "commerce_catalog_records_invalid_or_truncated"

        anchor = _parse_catalog_anchor(as_of)
        if as_of is not None and anchor is None:
            return {
                **empty,
                "reason": "commerce_catalog_as_of_invalid",
            }
        raw_as_of = raw.get("asOf")
        if anchor is not None and state in {"available", "missing", "degraded"}:
            source_anchor = _parse_catalog_anchor(raw_as_of)
            if source_anchor is None or source_anchor != anchor:
                return {
                    **empty,
                    "reason": "commerce_catalog_as_of_scope_mismatch",
                }
        if anchor is not None and any(
            record.observed_at > anchor
            for record in ([product] if product is not None else []) + offers
        ):
            return {
                **empty,
                "reason": "commerce_catalog_record_after_requested_as_of",
            }

        if "truncated" in raw and not isinstance(raw.get("truncated"), bool):
            return {
                **empty,
                "reason": "commerce_catalog_truncation_state_invalid",
            }
        if state == "missing" and (
            product is not None or offers or raw.get("product") is not None or raw.get("offers")
        ):
            return {
                **empty,
                "reason": "commerce_catalog_missing_state_contains_records",
            }
        if request.subject.kind == "product" and state in {"available", "degraded"}:
            if product is None:
                return {
                    **empty,
                    "reason": "commerce_catalog_product_record_unavailable",
                }
        if request.subject.kind == "offer" and state == "available":
            if len(offers) != 1 or product is None:
                return {
                    **empty,
                    "reason": "commerce_catalog_offer_identity_unresolved",
                }
            if product.product_id != offers[0].product_id:
                return {
                    **empty,
                    "reason": "commerce_catalog_offer_product_mismatch",
                }
        if request.subject.kind == "offer" and offers and product is not None:
            if product.product_id != offers[0].product_id:
                return {
                    **empty,
                    "reason": "commerce_catalog_offer_product_mismatch",
                }

        return {
            "sourceState": state,
            "reason": reason,
            "product": product,
            "offers": offers,
            "sourceCompleteness": (
                "partial" if state == "degraded" or invalid_records else "complete"
            ),
            "join_basis": expected_join_basis,
            "asOf": _safe_text(raw_as_of, limit=96),
            "authorityRefs": ["commerce_product_offer_graph", "source_provenance"],
        }

    @staticmethod
    def _catalog_section_states(
        catalog: dict[str, Any],
        subject_kind: str,
    ) -> dict[str, str]:
        if subject_kind not in _CATALOG_JOIN_BASIS_BY_SUBJECT_KIND:
            return {
                "product_offer_summary": "unknown",
                "catalog_links": "unknown",
                "availability_price": "unknown",
            }
        state = catalog.get("sourceState", "unknown")
        product = catalog.get("product")
        offers = catalog.get("offers", [])
        has_exact_catalog_evidence = product is not None or bool(offers)
        availability_price_state = (
            "degraded"
            if state in {"available", "degraded"} and has_exact_catalog_evidence
            else "unknown"
        )
        if state != "available":
            return {
                "product_offer_summary": state,
                "catalog_links": state,
                "availability_price": availability_price_state,
            }
        if product is None:
            return {
                "product_offer_summary": "unknown",
                "catalog_links": "unknown",
                "availability_price": availability_price_state,
            }
        return {
            "product_offer_summary": "available",
            "catalog_links": "available" if offers else "empty",
            "availability_price": availability_price_state,
        }

    def _validate_source_result(
        self,
        raw: Any,
        request: ProjectionRequest,
    ) -> dict[str, Any]:
        expected_scope = {
            "tenantId": request.tenantId,
            "subjectKind": request.subject.kind,
            "subjectId": request.subject.id,
        }
        expected_join_basis = _JOIN_BASIS_BY_SUBJECT_KIND.get(request.subject.kind)
        if not isinstance(raw, dict) or raw.get("_scope") != expected_scope:
            return {
                "sourceState": "unknown",
                "reason": "commerce_operation_source_scope_mismatch",
                "join_basis": expected_join_basis,
                "facts": [],
                "associations": [],
                "operation_links": [],
                "evidence": [],
            }

        source_subject_id = raw.get(_SUBJECT_ID_FIELD.get(request.subject.kind, ""))
        if expected_join_basis is None or raw.get("join_basis") != expected_join_basis:
            return {
                "sourceState": "unknown",
                "reason": str(raw.get("reason") or "commerce_operation_join_basis_unavailable"),
                "join_basis": expected_join_basis,
                "facts": [],
                "associations": [],
                "operation_links": [],
                "evidence": [],
            }

        reason = _safe_text(raw.get("reason"), limit=96)
        source_state = "available"
        if source_subject_id != request.subject.id and reason is None:
            return {
                "sourceState": "unknown",
                "reason": "commerce_operation_subject_scope_mismatch",
                "join_basis": expected_join_basis,
                "facts": [],
                "associations": [],
                "operation_links": [],
                "evidence": [],
            }
        elif reason == "journey_not_found":
            source_state = "missing"
        elif reason in {
            "campaign_canonical_identity_unresolved",
            "profile_canonical_identity_unresolved",
        }:
            source_state = "missing"
        elif reason in {
            "campaign_identity_authority_unavailable",
            "profile_identity_authority_unavailable",
        }:
            source_state = "unknown"
        elif reason is not None:
            source_state = "degraded"

        facts: list[dict[str, Any]] = []
        seen_fact_ids: set[str] = set()
        evidence_refs: list[EvidenceRef] = []
        invalid_facts = 0
        raw_facts = raw.get("payment_facts")
        if raw_facts is not None and not isinstance(raw_facts, list):
            invalid_facts += 1
            raw_facts = []
        raw_facts = raw_facts or []
        source_capped = len(raw_facts) > _MAX_PAYMENT_FACTS
        for row in raw_facts[:_MAX_PAYMENT_FACTS]:
            if not isinstance(row, dict):
                invalid_facts += 1
                continue
            fact_id = _safe_text(row.get("factId"), limit=512)
            fact_kind = _safe_text(row.get("kind"), limit=32)
            amount = _money_string(row.get("amount"))
            currency = _safe_text(row.get("currency"), limit=16)
            order_ref = _safe_text(row.get("commerceOrderRef"), limit=512)
            if (
                fact_id is None
                or not fact_id.startswith("commerce:")
                or fact_kind not in _PAYMENT_FACT_KINDS
                or amount is None
                or currency is None
                or not currency.isascii()
                or not currency.isalnum()
                or order_ref is None
                or row.get("joinBasis") != expected_join_basis
                or fact_id in seen_fact_ids
            ):
                invalid_facts += 1
                continue
            fact_evidence = _parse_evidence_refs(row.get("evidence"), required_type="transaction")
            if not fact_evidence:
                invalid_facts += 1
                continue
            evidence_refs.extend(fact_evidence)
            normalized_usd = _money_string(row.get("amountUsd"))
            normalization_state = _safe_text(row.get("normalizationState"), limit=48)
            if (
                currency.upper() != "USD"
                or normalization_state != "native_currency_usd"
                or normalized_usd != amount
            ):
                # This source currently makes only identity normalization for
                # native USD. Never accept an unverified FX conversion.
                normalized_usd = None
            facts.append(
                {
                    "factId": fact_id,
                    "kind": fact_kind,
                    "commerceOrderRef": order_ref,
                    "joinBasis": expected_join_basis,
                    "amount": amount,
                    "currency": currency,
                    "amountUsd": normalized_usd,
                    "normalizationState": normalization_state,
                    "lifecycleState": _safe_text(row.get("lifecycleState"), limit=48),
                    "reconciliationState": _safe_text(row.get("reconciliationState"), limit=48),
                    "provider": _safe_text(row.get("provider"), limit=96),
                    "sourceRecordId": _safe_text(row.get("sourceRecordId"), limit=512),
                    "evidenceRecordId": _safe_text(row.get("evidenceRecordId"), limit=512),
                    "occurredAt": _safe_text(row.get("occurredAt"), limit=96),
                    "observedAt": _safe_text(row.get("observedAt"), limit=96),
                    "ledgerCreatedAt": _safe_text(row.get("ledgerCreatedAt"), limit=96),
                    "ledgerUpdatedAt": _safe_text(row.get("ledgerUpdatedAt"), limit=96),
                    "evidence": [ref.model_dump(mode="json") for ref in fact_evidence],
                }
            )
            seen_fact_ids.add(fact_id)

        associations: list[dict[str, Any]] = []
        raw_associations = raw.get("association_evidence")
        if raw_associations is not None and not isinstance(raw_associations, list):
            invalid_facts += 1
            raw_associations = []
        raw_associations = raw_associations or []
        source_capped = source_capped or len(raw_associations) > _MAX_CAMPAIGN_ASSOCIATIONS
        if request.subject.kind == "campaign":
            for row in raw_associations[:_MAX_CAMPAIGN_ASSOCIATIONS]:
                if not isinstance(row, dict):
                    invalid_facts += 1
                    continue
                if (
                    row.get("subjectKind") != "campaign"
                    or row.get("subjectId") != request.subject.id
                    or row.get("commerceOrderRef") is None
                ):
                    invalid_facts += 1
                    continue
                activity_id = _safe_text(row.get("activityId"), limit=512)
                order_ref = _safe_text(row.get("commerceOrderRef"), limit=512)
                refs = _parse_evidence_refs([row.get("evidence")], required_type="event")
                if activity_id is None or order_ref is None or not refs:
                    invalid_facts += 1
                    continue
                associations.append(
                    {
                        "commerceOrderRef": order_ref,
                        "activityId": activity_id,
                        "joinBasis": expected_join_basis,
                        "sourceTable": _safe_text(row.get("silverTable"), limit=128),
                        "evidence": [ref.model_dump(mode="json") for ref in refs],
                    }
                )
                evidence_refs.extend(refs)

        operation_links: list[dict[str, Any]] = []
        raw_links = raw.get("operation_links")
        if raw_links is not None and not isinstance(raw_links, list):
            invalid_facts += 1
            raw_links = []
        raw_links = raw_links or []
        source_capped = source_capped or len(raw_links) > _MAX_OPERATION_LINKS
        for link in raw_links[:_MAX_OPERATION_LINKS]:
            if not isinstance(link, dict) or link.get("tenant_id") != request.tenantId:
                invalid_facts += 1
                continue
            if link.get("operation_ref") not in {
                fact["commerceOrderRef"] for fact in facts
            } and not any(
                link.get("operation_ref") == association["commerceOrderRef"]
                for association in associations
            ):
                invalid_facts += 1
                continue
            operation_links.append(link)

        seen: set[tuple[str, str, str]] = set()
        deduped_evidence: list[EvidenceRef] = []
        for ref in evidence_refs:
            key = (ref.id, ref.type, ref.source)
            if key not in seen:
                seen.add(key)
                deduped_evidence.append(ref)

        incomplete = bool(
            raw.get("evidence_truncated") is True
            or source_capped
            or invalid_facts
            or any(
                isinstance(raw.get(key), int) and raw.get(key) > 0
                for key in (
                    "invalid_order_reference_count",
                    "ledger_read_errors",
                    "invalid_ledger_records",
                    "unresolved_order_references",
                )
            )
        )
        if source_state == "available" and incomplete:
            source_state = "degraded"

        return {
            "sourceState": source_state,
            "reason": reason,
            "join_basis": expected_join_basis,
            "facts": facts,
            "associations": associations,
            "operation_links": operation_links,
            "evidence": deduped_evidence,
            "incomplete": incomplete,
            "sourceCompleteness": "partial" if incomplete else "complete",
            "asOf": _safe_text(raw.get("as_of"), limit=96),
        }

    def _section_states(
        self,
        evidence: dict[str, Any],
        subject_kind: str,
        scope_valid: bool,
    ) -> dict[str, str]:
        base_state = evidence.get("sourceState", "unknown")
        if not scope_valid:
            base_state = "degraded"
        states = {section_id: "unknown" for section_id in OUTPUT_SECTIONS}
        if base_state in {"available", "degraded", "missing", "unknown"}:
            for section_id in _SUPPORTED_PAYMENT_SECTIONS:
                states[section_id] = (
                    base_state
                    if base_state != "available"
                    else "available"
                    if evidence.get("facts")
                    else "empty"
                )
            if base_state != "available":
                states["evidence_trace"] = base_state
            else:
                states["evidence_trace"] = "available" if evidence.get("evidence") else "empty"
        if subject_kind == "campaign":
            states["campaign_links"] = (
                base_state
                if base_state != "available"
                else "available"
                if evidence.get("associations")
                else "empty"
            )
        else:
            # The current profile/journey commerce references do not carry a
            # canonical campaign join; no campaign association is inferred.
            states["campaign_links"] = "unknown"
        return states

    def _build_sections(
        self,
        request: ProjectionRequest,
        evidence: dict[str, Any],
        catalog: dict[str, Any],
        intents: dict[str, Any],
        risk: dict[str, Any],
        observations: dict[str, dict[str, Any]],
        states: dict[str, str],
        *,
        as_of: Optional[str],
    ) -> list[ProjectionSection]:
        facts = evidence.get("facts", [])
        associations = evidence.get("associations", [])
        policy = {
            "evaluationOwner": _POLICY_OWNER,
            "projectionDisclosesOnlyScopedCommerceFacts": True,
        }
        sections: list[ProjectionSection] = []
        for section_id in OUTPUT_SECTIONS:
            state = states[section_id]
            reason_codes: list[str] = []
            authorities: Optional[list[str]] = None
            if section_id in {"product_offer_summary", "catalog_links"}:
                authorities = catalog.get(
                    "authorityRefs",
                    ["commerce_product_offer_graph", "source_provenance"],
                )
                product = catalog.get("product")
                offers = catalog.get("offers", [])
                if section_id == "product_offer_summary":
                    if product is None and not offers:
                        reason_codes.append(
                            catalog.get("reason") or "commerce_product_offer_record_unavailable"
                        )
                    content = _slot_content(
                        state=state,
                        request=request,
                        reason_codes=reason_codes,
                        as_of=as_of,
                        joinBasis=catalog.get("join_basis"),
                        product=(_catalog_record_output(product) if product is not None else None),
                        offers=[_catalog_record_output(offer) for offer in offers],
                        sourceCompleteness=catalog.get("sourceCompleteness", "unknown"),
                        policy=policy,
                    )
                else:
                    if not offers and state in {"empty", "missing"}:
                        reason_codes.append(
                            catalog.get("reason") or "commerce_catalog_has_no_explicit_offer_links"
                        )
                    content = _slot_content(
                        state=state,
                        request=request,
                        reason_codes=reason_codes,
                        as_of=as_of,
                        joinBasis=catalog.get("join_basis"),
                        links=[
                            {
                                "offerId": offer.offer_id,
                                "productId": offer.product_id,
                                "productResolved": (
                                    product is not None and product.product_id == offer.product_id
                                ),
                                "offerEvidence": [
                                    ref.model_dump(mode="json") for ref in offer.evidence_refs
                                ],
                                "productEvidence": (
                                    [ref.model_dump(mode="json") for ref in product.evidence_refs]
                                    if product is not None
                                    and product.product_id == offer.product_id
                                    else []
                                ),
                            }
                            for offer in offers
                        ],
                        sourceCompleteness=catalog.get("sourceCompleteness", "unknown"),
                        policy=policy,
                    )
                if state in {"unknown", "missing", "degraded"}:
                    reason_codes.append(
                        catalog.get("reason")
                        or "commerce_product_offer_catalog_not_fully_available"
                    )
                    content["reasonCodes"] = reason_codes
                sections.append(
                    ProjectionSection(
                        id=section_id,
                        state=state,
                        title=section_id.replace("_", " ").title(),
                        content=content,
                        warnings=reason_codes or None,
                        canonicalAuthorityRefs=authorities,
                    )
                )
                continue
            elif section_id in _OBSERVATION_SLOTS:
                observed = observations[section_id]
                authorities = observed.get("authorityRefs")
                if state in {"unknown", "degraded"}:
                    reason_codes.append(
                        observed.get("reason") or _UNKNOWN_SLOT_REASONS[section_id]
                    )
                records = observed.get("records", [])
                content = _slot_content(
                    state=state,
                    request=request,
                    reason_codes=reason_codes,
                    as_of=as_of,
                    sourceObservedEvents=[
                        {
                            **record,
                            "evidenceRefs": [
                                EvidenceRef(
                                    id=record["sourceEventId"],
                                    type="event",
                                    source=record["sourceTable"],
                                    observedAt=record["receivedAt"] or record["occurredAt"],
                                ).model_dump(mode="json", exclude_none=True)
                            ],
                        }
                        for record in records
                    ],
                    sourceCompleteness=observed.get("sourceCompleteness", "unknown"),
                    truncated=observed.get("truncated", False),
                    freshness={"state": "unknown", "reasonCode": _SOURCE_FRESHNESS_UNKNOWN},
                    inference={
                        "purchase": "not_established",
                        "currentCartState": "not_established",
                        "exposureEffect": "not_established",
                    },
                    policy=policy,
                )
                sections.append(
                    ProjectionSection(
                        id=section_id,
                        state=state,
                        title=section_id.replace("_", " ").title(),
                        content=content,
                        warnings=reason_codes or None,
                        canonicalAuthorityRefs=authorities,
                    )
                )
                continue
            elif section_id == "availability_price":
                authorities = catalog.get(
                    "authorityRefs",
                    ["commerce_product_offer_graph", "source_provenance"],
                )
                product = catalog.get("product")
                offers = catalog.get("offers", [])
                catalog_records = []
                if product is not None:
                    catalog_records.append(
                        _availability_catalog_record_output(
                            product,
                            record_type="product_catalog_lifecycle",
                        )
                    )
                catalog_records.extend(
                    _availability_catalog_record_output(
                        offer,
                        record_type="offer_catalog_lifecycle",
                    )
                    for offer in offers
                )
                if state == "unknown":
                    reason_codes.append(
                        catalog.get("reason") or _UNKNOWN_SLOT_REASONS["availability_price"]
                    )
                elif state == "degraded":
                    catalog_reason = _safe_text(catalog.get("reason"), limit=96)
                    if catalog_reason:
                        reason_codes.append(catalog_reason)
                    reason_codes.append(_AVAILABILITY_PRICE_PARTIAL)
                content = _slot_content(
                    state=state,
                    request=request,
                    reason_codes=reason_codes,
                    as_of=as_of,
                    joinBasis=catalog.get("join_basis"),
                    catalogLifecycleRecords=catalog_records,
                    availability={"state": "unknown", "reasonCode": _AVAILABILITY_UNKNOWN},
                    price={"state": "unknown", "reasonCode": _OFFER_PRICE_UNKNOWN},
                    sourceCompleteness=catalog.get("sourceCompleteness", "unknown"),
                    freshness={
                        "state": "unknown",
                        "reasonCode": _SOURCE_FRESHNESS_UNKNOWN,
                        "catalogRecordTimestampFieldsIncluded": bool(catalog_records),
                    },
                    policy=policy,
                )
                sections.append(
                    ProjectionSection(
                        id=section_id,
                        state=state,
                        title=section_id.replace("_", " ").title(),
                        content=content,
                        warnings=reason_codes or None,
                        canonicalAuthorityRefs=authorities,
                    )
                )
                continue
            elif section_id == "intent":
                authorities = intents.get(
                    "authorityRefs",
                    [
                        "commerce_intent_authority",
                        "commerce_product_offer_graph",
                        "source_provenance",
                    ],
                )
                content = _slot_content(
                    state=state,
                    request=request,
                    reason_codes=reason_codes,
                    as_of=as_of,
                    joinBasis=intents.get("join_basis"),
                    intents=[
                        _intent_record_output(record) for record in intents.get("records", [])
                    ],
                    sourceCompleteness=intents.get("sourceCompleteness", "unknown"),
                    truncated=intents.get("truncated", False),
                    freshness={
                        "state": "unknown",
                        "reasonCode": _SOURCE_FRESHNESS_UNKNOWN,
                        "sourceTimestampsPreserved": True,
                    },
                    policy=policy,
                )
            elif section_id == "purchase":
                authorities = ["commerce", "payments", "source_provenance"]
                if not facts and state == "empty":
                    reason_codes.append("no_explicit_commerce_order_payment_refs")
                content = _slot_content(
                    state=state,
                    request=request,
                    reason_codes=reason_codes,
                    as_of=as_of,
                    joinBasis=evidence.get("join_basis"),
                    purchaseFacts=facts,
                    operationLinks=evidence.get("operation_links", []),
                    sourceCompleteness=evidence.get("sourceCompleteness", "unknown"),
                    freshness={
                        "state": "unknown",
                        "reasonCode": _SOURCE_FRESHNESS_UNKNOWN,
                        "sourceTimestampsPreserved": True,
                    },
                    policy=policy,
                )
            elif section_id == "value":
                authorities = ["payments", "source_provenance"]
                if not facts and state == "empty":
                    reason_codes.append("no_explicit_commerce_value_facts")
                content = _slot_content(
                    state=state,
                    request=request,
                    reason_codes=reason_codes,
                    as_of=as_of,
                    values=[
                        {
                            "factId": fact["factId"],
                            "kind": fact["kind"],
                            "amount": fact["amount"],
                            "currency": fact["currency"],
                            "amountUsd": fact["amountUsd"],
                            "normalizationState": fact["normalizationState"],
                            "occurredAt": fact["occurredAt"],
                            "observedAt": fact["observedAt"],
                            "evidence": fact["evidence"],
                        }
                        for fact in facts
                    ],
                    aggregation="not_aggregated",
                    sourceCompleteness=evidence.get("sourceCompleteness", "unknown"),
                    policy=policy,
                )
            elif section_id == "campaign_links":
                authorities = ["campaign_facts", "commerce", "source_provenance"]
                if request.subject.kind != "campaign":
                    reason_codes.append("campaign_link_join_unavailable_for_subject_kind")
                elif not associations and state == "empty":
                    reason_codes.append("no_explicit_campaign_commerce_order_refs")
                content = _slot_content(
                    state=state,
                    request=request,
                    reason_codes=reason_codes,
                    as_of=as_of,
                    joinBasis=evidence.get("join_basis"),
                    links=associations if request.subject.kind == "campaign" else [],
                    sourceCompleteness=evidence.get("sourceCompleteness", "unknown"),
                    policy=policy,
                )
            elif section_id == "evidence_trace":
                authorities = [
                    "commerce",
                    "payments",
                    "commerce_intent_authority",
                    "silver_exposure_facts",
                    "silver_commerce_flow_facts",
                    "source_provenance",
                ]
                intent_evidence = [
                    ref for record in intents.get("records", []) for ref in record.evidence_refs
                ]
                merged_evidence = _parse_evidence_refs(
                    [
                        *[ref.model_dump(mode="json") for ref in evidence.get("evidence", [])],
                        *[ref.model_dump(mode="json") for ref in intent_evidence],
                        *[
                            EvidenceRef(
                                id=record["sourceEventId"],
                                type="event",
                                source=record["sourceTable"],
                                observedAt=record["receivedAt"] or record["occurredAt"],
                            ).model_dump(mode="json", exclude_none=True)
                            for slot in _OBSERVATION_SLOTS
                            for record in observations[slot].get("records", [])
                        ],
                    ]
                )
                if not merged_evidence and state == "empty":
                    reason_codes.append("no_explicit_commerce_source_evidence")
                content = _slot_content(
                    state=state,
                    request=request,
                    reason_codes=reason_codes,
                    as_of=as_of,
                    evidence=[ref.model_dump(mode="json") for ref in merged_evidence],
                    sourceCompleteness=(
                        intents.get("sourceCompleteness", "unknown")
                        if intent_evidence and not evidence.get("evidence")
                        else evidence.get("sourceCompleteness", "unknown")
                    ),
                    policy=policy,
                )
            elif section_id == "risk":
                authorities = risk.get(
                    "authorityRefs",
                    [
                        "commerce_product_offer_graph",
                        "risk_outputs",
                        "risk_signals",
                        "risk_assessments",
                        "source_provenance",
                    ],
                )
                risk_reason = risk.get("reason") or _UNKNOWN_SLOT_REASONS[section_id]
                if state in {"unknown", "missing", "degraded"}:
                    reason_codes.append(str(risk_reason))
                if risk.get("signals") or risk.get("assessments"):
                    reason_codes.append(_RISK_PARTIAL_REASON)
                content = _slot_content(
                    state=state,
                    request=request,
                    reason_codes=reason_codes,
                    as_of=as_of,
                    joinBasis=risk.get("join_basis"),
                    signals=risk.get("signals", []),
                    assessments=risk.get("assessments", []),
                    evidence=[
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in risk.get("evidence", [])
                    ],
                    sourceCompleteness=risk.get("sourceCompleteness", "unknown"),
                    truncated=risk.get("truncated", False),
                    historyCoverage={
                        "state": "unknown",
                        "reasonCode": _RISK_SOURCE_COMPLETENESS_UNKNOWN,
                    },
                    causalValidity={
                        "state": "unknown",
                        "reasonCode": "commerce_risk_causality_not_established",
                    },
                    freshness={
                        "state": "unknown",
                        "reasonCode": _RISK_FRESHNESS_UNKNOWN,
                        "assessmentTimestampsPreserved": True,
                    },
                    policy={
                        "evaluationOwner": _POLICY_OWNER,
                        "disclosureGate": "experience360_frame_runtime",
                        "riskPolicyReferencesPreserved": True,
                    },
                )
            else:
                reason_code = _UNKNOWN_SLOT_REASONS[section_id]
                content = _slot_content(
                    state="unknown",
                    request=request,
                    reason_codes=[reason_code],
                    as_of=as_of,
                    authority="commerce_product_offer_graph",
                    policy=policy,
                )
                warnings = [reason_code]
                sections.append(
                    ProjectionSection(
                        id=section_id,
                        state="unknown",
                        title=section_id.replace("_", " ").title(),
                        content=content,
                        warnings=warnings,
                        canonicalAuthorityRefs=authorities,
                    )
                )
                continue

            if state in {"unknown", "missing", "degraded"}:
                if section_id == "intent":
                    reason = intents.get("reason") or _UNKNOWN_SLOT_REASONS["intent"]
                elif section_id == "risk":
                    reason = risk.get("reason") or _UNKNOWN_SLOT_REASONS["risk"]
                elif section_id == "evidence_trace" and any(
                    observations[slot]["records"] for slot in _OBSERVATION_SLOTS
                ):
                    reason = "commerce_observation_evidence_source_coverage_unknown"
                else:
                    reason = evidence.get("reason") or (
                        "commerce_projection_context_scope_mismatch"
                        if not request.tenantId.strip()
                        else "commerce_operation_evidence_unavailable"
                    )
                reason_codes.append(str(reason))
                content["reasonCodes"] = reason_codes
            warnings = reason_codes or None
            sections.append(
                ProjectionSection(
                    id=section_id,
                    state=state,
                    title=section_id.replace("_", " ").title(),
                    content=content,
                    warnings=warnings,
                    canonicalAuthorityRefs=authorities,
                )
            )
        return sections

    def _build_claims(
        self,
        request: ProjectionRequest,
        evidence: dict[str, Any],
        catalog: dict[str, Any],
        intents: dict[str, Any],
        risk: dict[str, Any],
        observations: dict[str, dict[str, Any]],
        states: dict[str, str],
    ) -> list[ClaimEnvelope]:
        claims: list[ClaimEnvelope] = []
        for slot in _OBSERVATION_SLOTS:
            for record in observations[slot].get("records", []):
                reference = EvidenceRef(
                    id=record["sourceEventId"],
                    type="event",
                    source=record["sourceTable"],
                    observedAt=record["receivedAt"] or record["occurredAt"],
                )
                claims.append(
                    ClaimEnvelope(
                        id=_stable_id(
                            f"commerce.{slot}",
                            f"{request.tenantId}:{record['sourceEventId']}:{slot}",
                        ),
                        kind="commerce_source_observation",
                        subject=request.subject,
                        evidenceRefs=[reference],
                        claims=[
                            f"accepted source event reports {record['eventType']} for exact "
                            f"tenant catalog {request.subject.kind} {request.subject.id}; "
                            "purchase, current cart state, and effect are unverified"
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[slot, "evidence_trace"],
                    )
                )
        if states.get("intent") in {"available", "degraded"}:
            for record in intents.get("records", []):
                refs = _parse_evidence_refs(
                    [ref.model_dump(mode="json") for ref in record.evidence_refs]
                )
                if not refs:
                    continue
                claims.append(
                    ClaimEnvelope(
                        id=_stable_id(
                            "commerce.intent",
                            f"{record.tenant_id}:{record.intent_id}:{record.source_revision_id}",
                        ),
                        kind="commerce_intent_declaration",
                        subject=request.subject,
                        evidenceRefs=refs,
                        claims=[
                            f"actor {record.actor_kind}:{record.actor_id} explicitly declared "
                            f"{record.intent_kind} intent for canonical {record.subject_kind} "
                            f"{record.subject_id}; state: {record.state}"
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["intent", "evidence_trace"],
                    )
                )
        if states.get("purchase") in {"available", "degraded"}:
            for fact in evidence.get("facts", []):
                refs = _parse_evidence_refs(fact.get("evidence"), required_type="transaction")
                if not refs:
                    continue
                fact_id = fact["factId"]
                amount = fact["amount"]
                currency = fact["currency"]
                kind = fact["kind"]
                lifecycle = fact.get("lifecycleState")
                text = f"canonical commerce {kind} fact records {amount} {currency}"
                if lifecycle:
                    text += f"; lifecycle state: {lifecycle}"
                text += "; source records are not aggregated"
                claims.append(
                    ClaimEnvelope(
                        id=_stable_id("commerce.purchase", fact_id),
                        kind="commerce_purchase_fact",
                        subject=request.subject,
                        evidenceRefs=refs,
                        claims=[text],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["purchase"],
                    )
                )
                claims.append(
                    ClaimEnvelope(
                        id=_stable_id("commerce.value", fact_id),
                        kind="commerce_value_fact",
                        subject=request.subject,
                        evidenceRefs=refs,
                        claims=[
                            f"canonical commerce {kind} amount is {amount} {currency}; "
                            f"normalization state: {fact.get('normalizationState') or 'unknown'}; "
                            "no aggregate value is computed"
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["value"],
                    )
                )

        product = catalog.get("product")
        offers = catalog.get("offers", [])
        if states.get("product_offer_summary") in {"available", "degraded"}:
            summary_refs: list[EvidenceRef] = []
            if product is not None:
                summary_refs.extend(product.evidence_refs)
            for offer in offers:
                summary_refs.extend(offer.evidence_refs)
            summary_refs = _parse_evidence_refs(
                [ref.model_dump(mode="json") for ref in summary_refs]
            )
            if summary_refs:
                if product is not None:
                    product_text = (
                        f"tenant catalog product {product.product_id} is recorded as "
                        f"{product.lifecycle_state}"
                    )
                elif offers:
                    product_text = (
                        f"tenant catalog offer {offers[0].offer_id} explicitly references "
                        f"product {offers[0].product_id}; product record is unresolved"
                    )
                else:
                    product_text = "tenant catalog product and offer records are unavailable"
                claims.append(
                    ClaimEnvelope(
                        id=_stable_id(
                            "commerce.product_offer_summary",
                            ":".join(
                                [
                                    product.product_id if product is not None else "unresolved",
                                    *(offer.offer_id for offer in offers),
                                ]
                            ),
                        ),
                        kind="commerce_product_offer_catalog_summary",
                        subject=request.subject,
                        evidenceRefs=summary_refs,
                        claims=[product_text],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["product_offer_summary"],
                    )
                )
        if states.get("catalog_links") in {"available", "degraded"}:
            for offer in offers:
                refs = list(offer.evidence_refs)
                product_resolved = product is not None and product.product_id == offer.product_id
                if product_resolved:
                    refs.extend(product.evidence_refs)
                refs = _parse_evidence_refs([ref.model_dump(mode="json") for ref in refs])
                if not refs:
                    continue
                relation_claim = (
                    f"tenant catalog offer {offer.offer_id} explicitly links to canonical "
                    f"product {offer.product_id}"
                )
                if not product_resolved:
                    relation_claim += "; product record is unresolved"
                claims.append(
                    ClaimEnvelope(
                        id=_stable_id(
                            "commerce.catalog_link",
                            f"{offer.tenant_id}:{offer.offer_id}:{offer.source_revision_id}:{offer.product_id}",
                        ),
                        kind="commerce_catalog_product_offer_link",
                        subject=request.subject,
                        evidenceRefs=refs,
                        claims=[relation_claim],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["catalog_links"],
                    )
                )

        if states.get("availability_price") == "degraded":
            lifecycle_records: list[CommerceProductRecord | CommerceOfferRecord] = []
            if product is not None:
                lifecycle_records.append(product)
            lifecycle_records.extend(offers)
            for record in lifecycle_records:
                refs = _parse_evidence_refs(
                    [ref.model_dump(mode="json") for ref in record.evidence_refs]
                )
                if not refs:
                    continue
                if isinstance(record, CommerceProductRecord):
                    record_type = "product"
                    record_id = record.product_id
                else:
                    record_type = "offer"
                    record_id = record.offer_id
                claims.append(
                    ClaimEnvelope(
                        id=_stable_id(
                            "commerce.availability_price.catalog_lifecycle",
                            f"{record.tenant_id}:{record_type}:{record_id}:{record.source_revision_id}",
                        ),
                        kind="commerce_catalog_lifecycle_observation",
                        subject=request.subject,
                        evidenceRefs=refs,
                        claims=[
                            f"tenant catalog {record_type} {record_id} records lifecycle state "
                            f"{record.lifecycle_state} in source revision {record.source_revision_id}"
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["availability_price"],
                    )
                )

        if states.get("risk") == "degraded":
            for signal in risk.get("signals", []):
                signal_id = signal.get("signalId")
                refs = _parse_evidence_refs(signal.get("evidenceRefs"))
                if not signal_id or not refs:
                    continue
                claim_state = signal.get("claimState") or EpistemicStatus.UNKNOWN
                claims.append(
                    ClaimEnvelope(
                        id=_stable_id("commerce.risk_signal", str(signal_id)),
                        kind="commerce_risk_signal_reference",
                        subject=request.subject,
                        evidenceRefs=refs,
                        claims=[
                            f"RiskSignal {signal_id} records risk dimension "
                            f"{signal.get('riskDimension') or 'unknown'} for the exact subject; "
                            f"claim state: {claim_state}"
                        ],
                        claimState=claim_state,
                        domainSlotIds=["risk"],
                    )
                )
            for assessment in risk.get("assessments", []):
                assessment_id = assessment.get("assessment_id")
                refs = _parse_evidence_refs(
                    assessment.get("evidence_refs") if isinstance(assessment, dict) else None
                )
                if not assessment_id or not refs:
                    continue
                claim_state = assessment.get("claim_state") or EpistemicStatus.UNKNOWN
                claims.append(
                    ClaimEnvelope(
                        id=_stable_id("commerce.risk_assessment", str(assessment_id)),
                        kind="commerce_risk_assessment_reference",
                        subject=request.subject,
                        evidenceRefs=refs,
                        claims=[
                            f"RiskAssessment {assessment_id} is recorded for the exact "
                            f"subject; policy {assessment.get('policy_id') or 'unknown'} "
                            "and history coverage are not evaluated by Commerce360"
                        ],
                        claimState=claim_state,
                        domainSlotIds=["risk"],
                    )
                )

        if request.subject.kind == "campaign" and states.get("campaign_links") in {
            "available",
            "degraded",
        }:
            for association in evidence.get("associations", []):
                refs = _parse_evidence_refs(association.get("evidence"), required_type="event")
                if not refs:
                    continue
                claims.append(
                    ClaimEnvelope(
                        id=_stable_id(
                            "commerce.campaign_link",
                            association["activityId"],
                        ),
                        kind="campaign_commerce_order_link",
                        subject=request.subject,
                        evidenceRefs=refs,
                        claims=[
                            "a tenant-scoped canonical campaign activity explicitly references a commerce order"
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["campaign_links"],
                    )
                )
        for ref in evidence.get("evidence", []):
            claims.append(
                ClaimEnvelope(
                    id=_stable_id("commerce.evidence", f"{ref.type}:{ref.source}:{ref.id}"),
                    kind="commerce_evidence_reference",
                    subject=request.subject,
                    evidenceRefs=[ref],
                    claims=[
                        "canonical commerce evidence is linked to the requested subject by an exact reference"
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["evidence_trace"],
                )
            )
        return claims


def register_provider(registry: ProviderRegistry) -> None:
    """Register the provider explicitly from central runtime wiring."""
    registry.register(Commerce360Provider(), source="services/api/value/commerce")


__all__ = [
    "CommerceRiskEvidenceSource",
    "Commerce360Provider",
    "CommerceOperationEvidenceSource",
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "RepositoryCommerceOperationEvidenceSource",
    "RepositoryCommerceRiskEvidenceSource",
    "register_provider",
]
