"""Read-only Signals360 projection over exact tenant-scoped authorities.

The current ``behavioral_signals`` repository stores translator-produced
behavior-profile signals, not the canonical event/observation stream described
by the Signals360 blueprint. This provider keeps that entity summary separate
from exact SDK observation metadata, identity/campaign links, and typed
RiskSignal records joined on their own canonical tenant and subject keys. The
remaining SSOT slots stay unknown until their intake authorities and exact-
scope joins are available.

Signal explanations and raw evidence-reference strings are intentionally
omitted: existing translators use those fields for model features as well as
event identifiers, so they are not a safe, typed source-evidence contract.
The provider never writes, recomputes, or validates a raw event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from uuid import UUID

from graph.operational_intelligence.models import EvidenceRef
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
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry


PROJECTION_ID = "signals360"
OUTPUT_SECTIONS: tuple[str, ...] = (
    "signal_summary",
    "source_inventory",
    "classification",
    "quality",
    "normalization",
    "linked_entities",
    "campaign_links",
    "risk_flags",
    "freshness",
    "evidence_trace",
)

_MAX_SIGNAL_RECORDS = 100
_MAX_SIGNAL_CAMPAIGN_TOUCHPOINTS = 100
_MAX_RISK_SIGNALS = 100
_MAX_SEMANTIC_EVENT_OBSERVATIONS = 100
_SUMMARY_SOURCE = "repositories.repos.SignalRepository:behavioral_signals"
_RISK_SUBJECT_KINDS = frozenset({"event", "observation", "signal", "source", "stream"})


@dataclass(frozen=True)
class SignalSummaryRead:
    """Bounded exact-entity signal read with explicit completeness."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class ObservationQualityRead:
    """One exact tenant-scoped SDK Bronze event row, when available."""

    record: Optional[dict[str, Any]]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class SemanticEventRead:
    """Capped Silver model-output rows for one exact tenant SDK event."""

    tenant_id: str
    source_event_id: str
    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class ObservationSourceAuthorityRead:
    """Rights Authority trace bound to one exact tenant SDK observation."""

    tenant_id: str
    observation_id: str
    trace: Optional[Any]
    lineage_recorded: bool
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class LinkedEntity:
    """Minimal canonical entity and the evidence for its exact source join."""

    entity_id: str
    entity_type: str
    evidence_refs: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class LinkedEntitiesRead:
    """Exact signal/event identity joins with explicit completeness."""

    tenant_id: str
    subject_kind: str
    subject_id: str
    entities: tuple[LinkedEntity, ...]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class SignalCampaignLink:
    """One exact source-event link to a canonical tenant-owned campaign."""

    campaign_id: str
    evidence_refs: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class CampaignLinksRead:
    """Bounded tenant-scoped event-to-campaign link read."""

    tenant_id: str
    subject_kind: str
    subject_id: str
    links: tuple[SignalCampaignLink, ...]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class RiskFlagsRead:
    """Bounded exact-subject read of canonical RiskSignal records."""

    tenant_id: str
    subject_kind: str
    subject_id: str
    records: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    reason: Optional[str] = None


def _linked_read(
    tenant_id: str,
    subject_kind: str,
    subject_id: str,
    *,
    entities: tuple[LinkedEntity, ...] = (),
    available: bool,
    complete: bool,
    reason: Optional[str] = None,
) -> LinkedEntitiesRead:
    return LinkedEntitiesRead(
        tenant_id=tenant_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        entities=entities,
        available=available,
        complete=complete,
        reason=reason,
    )


def _campaign_links_read(
    tenant_id: str,
    subject_kind: str,
    subject_id: str,
    *,
    links: tuple[SignalCampaignLink, ...] = (),
    available: bool,
    complete: bool,
    reason: Optional[str] = None,
) -> CampaignLinksRead:
    return CampaignLinksRead(
        tenant_id=tenant_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        links=links,
        available=available,
        complete=complete,
        reason=reason,
    )


class Signal360Source(Protocol):
    """Tenant-scoped read seam for derived behavior signal records."""

    async def entity_signals(
        self, *, tenant_id: str, entity_id: str, limit: int
    ) -> SignalSummaryRead: ...

    async def observation_quality(
        self, *, tenant_id: str, observation_id: str
    ) -> ObservationQualityRead: ...

    async def semantic_observations_for_event(
        self, *, tenant_id: str, event_id: str, limit: int
    ) -> SemanticEventRead: ...

    async def observation_source_authority(
        self, *, tenant_id: str, observation_id: str, record: dict[str, Any]
    ) -> ObservationSourceAuthorityRead: ...

    async def linked_entities(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> LinkedEntitiesRead: ...

    async def campaign_links(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> CampaignLinksRead: ...

    async def risk_signals_for_subject(
        self, *, tenant_id: str, subject_kind: str, subject_id: str, limit: int
    ) -> RiskFlagsRead: ...


class RepositorySignal360Source:
    """Adapter over behavioral signals and exact SDK observation Bronze rows."""

    def __init__(
        self,
        *,
        bronze: Any = None,
        signals: Any = None,
        identity_repository: Any = None,
        campaign_touchpoints: Any = None,
        campaign_repository: Any = None,
        rights_lineage_repository: Any = None,
        source_authority_trace: Any = None,
        semantic_observations: Any = None,
    ) -> None:
        self._bronze = bronze
        self._signals = signals
        self._identity_repository = identity_repository
        self._campaign_touchpoints = campaign_touchpoints
        self._campaign_repository = campaign_repository
        self._rights_lineage_repository = rights_lineage_repository
        self._source_authority_trace = source_authority_trace
        self._semantic_observations = semantic_observations

    async def semantic_observations_for_event(
        self, *, tenant_id: str, event_id: str, limit: int
    ) -> SemanticEventRead:
        if not _safe_identifier(tenant_id) or not _safe_identifier(event_id):
            return SemanticEventRead(tenant_id, event_id, (), False, False, "exact_event_scope_required")
        cap = min(max(int(limit), 1), _MAX_SEMANTIC_EVENT_OBSERVATIONS)
        try:
            if self._semantic_observations is None:
                from intelligence.semantic_intelligence.repositories.base_fact_repo import (
                    SemanticFactRepository,
                )

                self._semantic_observations = SemanticFactRepository(
                    "silver_semantic_observations"
                )
            rows = await self._semantic_observations.find_by_source_event(
                tenant_id, event_id, limit=cap + 1
            )
        except Exception:  # noqa: BLE001 - authority diagnostics stay private
            return SemanticEventRead(
                tenant_id, event_id, (), False, False, "semantic_event_authority_unavailable"
            )
        if not isinstance(rows, list):
            return SemanticEventRead(
                tenant_id, event_id, (), False, False, "semantic_event_read_invalid"
            )
        if len(rows) > cap:
            return SemanticEventRead(
                tenant_id, event_id, (), True, False, "semantic_event_read_truncated"
            )
        if not all(isinstance(row, dict) for row in rows):
            return SemanticEventRead(
                tenant_id, event_id, (), True, False, "semantic_event_row_invalid"
            )
        return SemanticEventRead(tenant_id, event_id, tuple(rows), True, True)

    async def entity_signals(
        self, *, tenant_id: str, entity_id: str, limit: int
    ) -> SignalSummaryRead:
        if not tenant_id or not entity_id:
            return SignalSummaryRead((), False, False, "exact_entity_scope_required")
        try:
            from repositories.repos import SignalRepository

            rows = await SignalRepository().list_for_entity(
                entity_id,
                tenant_id,
                include_stale=True,
                limit=min(max(int(limit), 1), _MAX_SIGNAL_RECORDS) + 1,
            )
        except Exception:  # noqa: BLE001 - source details stay private
            return SignalSummaryRead((), False, False, "behavioral_signal_repository_unavailable")

        complete = len(rows) <= min(max(int(limit), 1), _MAX_SIGNAL_RECORDS)
        scoped: list[dict[str, Any]] = []
        scope_invalid = False
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("entity_id") != entity_id
                or not _safe_identifier(row.get("signal_id"))
            ):
                scope_invalid = True
                continue
            scoped.append(row)
        if scope_invalid:
            return SignalSummaryRead(
                tuple(scoped[:_MAX_SIGNAL_RECORDS]),
                True,
                False,
                "unscoped_or_invalid_signal_rows_dropped",
            )
        if not complete:
            return SignalSummaryRead(
                tuple(scoped[:_MAX_SIGNAL_RECORDS]),
                True,
                False,
                "behavioral_signal_read_truncated",
            )
        return SignalSummaryRead(tuple(scoped), True, True)

    async def observation_quality(
        self, *, tenant_id: str, observation_id: str
    ) -> ObservationQualityRead:
        """Read gateway quality metadata for one exact SDK observation.

        SDK ingress stores the accepted event under its exact
        ``provider_record_id`` in the tenant-scoped ``sdk_events`` Bronze
        domain. Envelope-B uses that same id as ``observation_id``. No entity,
        alias, provider, or time-window join is performed here.
        """
        if not _safe_identifier(tenant_id) or not _safe_identifier(observation_id):
            return ObservationQualityRead(None, False, False, "exact_observation_scope_required")
        try:
            if self._bronze is None:
                from repositories.lake import BronzeRepository

                self._bronze = BronzeRepository("sdk_events")
            rows = await self._bronze.find_many(
                filters={
                    "tenant_id": tenant_id,
                    "provider_record_id": observation_id,
                },
                limit=2,
            )
        except Exception:  # noqa: BLE001 - storage diagnostics stay private
            return ObservationQualityRead(None, False, False, "sdk_observation_bronze_unavailable")

        if not isinstance(rows, list):
            return ObservationQualityRead(None, False, False, "sdk_observation_read_invalid")
        if not rows:
            return ObservationQualityRead(None, True, True, "exact_sdk_observation_not_found")
        if len(rows) != 1:
            return ObservationQualityRead(None, True, False, "duplicate_exact_sdk_observation_rows")
        row = rows[0]
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("provider_record_id") != observation_id
            or row.get("source") != "sdk"
        ):
            return ObservationQualityRead(None, False, False, "sdk_observation_scope_mismatch")
        payload = row.get("payload")
        envelope = payload.get("observation_envelope") if isinstance(payload, dict) else None
        observation = envelope.get("observation") if isinstance(envelope, dict) else None
        tenancy = envelope.get("tenancy") if isinstance(envelope, dict) else None
        if (
            not isinstance(observation, dict)
            or observation.get("observation_id") != observation_id
            or not isinstance(tenancy, dict)
            or tenancy.get("tenant_id") != tenant_id
        ):
            return ObservationQualityRead(
                row,
                True,
                False,
                "canonical_observation_envelope_missing_or_mismatched",
            )
        return ObservationQualityRead(row, True, True)

    async def observation_source_authority(
        self, *, tenant_id: str, observation_id: str, record: dict[str, Any]
    ) -> ObservationSourceAuthorityRead:
        """Trace only explicit server-owned rights refs for this observation.

        The source instance is an identity namespace, not a source ID. A rights
        decision is eligible only when its exact observation envelope or an
        exact tenant-scoped rights-lineage row records the reference, and the
        canonical decision-to-grant trace agrees with every recorded ref.
        """
        def unknown(reason: str, *, available: bool = True) -> ObservationSourceAuthorityRead:
            return ObservationSourceAuthorityRead(
                tenant_id, observation_id, None, False, available, False, reason
            )

        if (
            not _safe_identifier(tenant_id)
            or not _safe_identifier(observation_id)
            or not isinstance(record, dict)
            or record.get("tenant_id") != tenant_id
            or record.get("provider_record_id") != observation_id
            or record.get("source") != "sdk"
        ):
            return unknown("exact_sdk_observation_scope_required", available=False)
        payload = record.get("payload")
        envelope = payload.get("observation_envelope") if isinstance(payload, dict) else None
        observation = envelope.get("observation") if isinstance(envelope, dict) else None
        tenancy = envelope.get("tenancy") if isinstance(envelope, dict) else None
        source = envelope.get("source") if isinstance(envelope, dict) else None
        if (
            not isinstance(observation, dict)
            or observation.get("observation_id") != observation_id
            or not isinstance(tenancy, dict)
            or tenancy.get("tenant_id") != tenant_id
            or not isinstance(source, dict)
            or source.get("source_type") != "sdk"
        ):
            return unknown("canonical_sdk_observation_envelope_invalid")

        rights = envelope.get("rights")
        if rights is not None and not isinstance(rights, dict):
            return unknown("observation_rights_references_invalid")
        envelope_decisions = rights.get("rights_decision_refs", []) if rights else []
        envelope_grants = rights.get("source_grant_refs", []) if rights else []
        envelope_source_id = rights.get("source_id") if rights else None
        if rights and (
            not isinstance(envelope_decisions, list)
            or not isinstance(envelope_grants, list)
        ):
            return unknown("observation_rights_references_invalid")

        try:
            if self._rights_lineage_repository is None:
                from tenancy.rights_authority.repositories import RightsLineageRepository

                self._rights_lineage_repository = RightsLineageRepository()
            lineage = await self._rights_lineage_repository.get(observation_id)
        except Exception:  # noqa: BLE001 - authority diagnostics stay private
            return unknown("observation_rights_lineage_unavailable", available=False)
        if lineage is not None and (
            not isinstance(lineage, dict)
            or lineage.get("tenant_id") != tenant_id
            or lineage.get("artifact_id") != observation_id
        ):
            return unknown("observation_rights_lineage_scope_mismatch")

        lineage_decisions = lineage.get("rights_decision_refs", []) if lineage else []
        lineage_grants = lineage.get("source_grant_refs", []) if lineage else []
        if lineage is not None and (
            not isinstance(lineage_decisions, list)
            or not isinstance(lineage_grants, list)
        ):
            return unknown("observation_rights_lineage_references_invalid")
        if not envelope_decisions and not lineage_decisions:
            return unknown("canonical_source_authority_reference_not_recorded")
        if (
            (envelope_decisions and len(envelope_decisions) != 1)
            or (lineage_decisions and len(lineage_decisions) != 1)
            or (envelope_grants and len(envelope_grants) != 1)
            or (lineage_grants and len(lineage_grants) != 1)
        ):
            return unknown("observation_source_authority_ambiguous")
        decision_ref = _safe_identifier((envelope_decisions or lineage_decisions)[0])
        grant_ref = _safe_identifier((envelope_grants or lineage_grants)[0]) if (envelope_grants or lineage_grants) else None
        if (
            not decision_ref
            or not decision_ref.startswith("rdec_")
            or (envelope_decisions and lineage_decisions and envelope_decisions != lineage_decisions)
            or (envelope_grants and lineage_grants and envelope_grants != lineage_grants)
            or (lineage and lineage.get("effective_rights_decision_ref") not in (None, decision_ref))
        ):
            return unknown("observation_source_authority_references_mismatch")
        try:
            if self._source_authority_trace is None:
                from tenancy.rights_authority.source_lineage import trace_source_authority

                self._source_authority_trace = trace_source_authority
            trace = await self._source_authority_trace(decision_ref, tenant_id=tenant_id)
        except Exception:  # noqa: BLE001 - authority diagnostics stay private
            return unknown("observation_source_authority_trace_unavailable", available=False)
        if (
            trace is None
            or getattr(trace, "tenant_id", None) != tenant_id
            or getattr(trace, "rights_decision_ref", None) != decision_ref
            or not _safe_identifier(getattr(trace, "source_id", None))
            or not _safe_identifier(getattr(trace, "source_grant_ref", None))
            or not _safe_identifier(getattr(trace, "provider_identity", None))
            or getattr(trace, "source_relationship", None) != source.get("source_relationship")
            or (grant_ref is not None and getattr(trace, "source_grant_ref", None) != grant_ref)
            or (envelope_source_id is not None and getattr(trace, "source_id", None) != envelope_source_id)
        ):
            return unknown("observation_source_authority_trace_mismatch")
        return ObservationSourceAuthorityRead(
            tenant_id, observation_id, trace, lineage is not None, True, True
        )

    async def linked_entities(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> LinkedEntitiesRead:
        """Resolve only exact signal or resolver-event identity bindings.

        SDK observation ids and identity resolver event ids are not assumed to
        be the same identifier. An observation is linked only when its exact id
        is also present as ``source_event_id`` in the identity authority.
        """
        if not _safe_identifier(tenant_id) or not _safe_identifier(subject_id):
            return _linked_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=False,
                complete=False,
                reason="exact_link_subject_scope_required",
            )
        try:
            if subject_kind == "signal":
                return await self._linked_signal_entity(tenant_id, subject_id)
            if subject_kind in {"event", "observation"}:
                return await self._linked_event_entities(
                    tenant_id, subject_kind, subject_id
                )
            return _linked_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=True,
                complete=True,
                reason="subject_kind_has_no_exact_signal_entity_join",
            )
        except Exception:  # noqa: BLE001 - authority details stay private
            return _linked_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=False,
                complete=False,
                reason="canonical_identity_join_unavailable",
            )

    async def campaign_links(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> CampaignLinksRead:
        """Join an exact event id through tenant touchpoints to canonical campaigns.

        The touchpoint row is only a relationship assertion. A campaign is
        exposed as a resolved link only after the same tenant's canonical
        campaign repository returns that exact campaign id.
        """
        if not _safe_identifier(tenant_id) or not _safe_identifier(subject_id):
            return _campaign_links_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=False,
                complete=False,
                reason="exact_campaign_link_subject_scope_required",
            )
        if subject_kind not in {"event", "observation"}:
            return _campaign_links_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=True,
                complete=True,
                reason="subject_kind_has_no_exact_campaign_event_join",
            )

        try:
            if self._campaign_touchpoints is None:
                from journeys.measurement.repositories.touchpoint_repo import (
                    TouchpointRepository,
                )

                self._campaign_touchpoints = TouchpointRepository()
            rows = await self._campaign_touchpoints.list_by_source_event(
                tenant_id,
                subject_id,
                limit=_MAX_SIGNAL_CAMPAIGN_TOUCHPOINTS + 1,
            )
        except Exception:  # noqa: BLE001 - authority diagnostics stay private
            return _campaign_links_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=False,
                complete=False,
                reason="campaign_touchpoint_authority_unavailable",
            )
        if not isinstance(rows, list):
            return _campaign_links_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=False,
                complete=False,
                reason="campaign_touchpoint_read_invalid",
            )

        complete = len(rows) <= _MAX_SIGNAL_CAMPAIGN_TOUCHPOINTS
        if not complete:
            rows = rows[:_MAX_SIGNAL_CAMPAIGN_TOUCHPOINTS]
        campaign_touchpoints: dict[str, list[EvidenceRef]] = {}
        reason: Optional[str] = (
            "campaign_touchpoint_read_truncated" if not complete else None
        )
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("source_event_id") != subject_id
            ):
                complete = False
                reason = "campaign_touchpoint_scope_mismatch"
                continue
            campaign_id = _safe_identifier(row.get("campaign_id"))
            touchpoint_id = _safe_identifier(row.get("touchpoint_id"))
            if campaign_id is None or touchpoint_id is None:
                complete = False
                reason = "campaign_touchpoint_canonical_reference_missing"
                continue
            try:
                canonical_campaign_id = str(UUID(campaign_id))
            except (TypeError, ValueError, AttributeError):
                complete = False
                reason = "campaign_touchpoint_campaign_id_invalid"
                continue
            campaign_touchpoints.setdefault(canonical_campaign_id, []).append(
                EvidenceRef(
                    id=touchpoint_id,
                    type="event",
                    source=(
                        "services/api/journeys/measurement/repositories/"
                        "touchpoint_repo.py:silver_campaign_touchpoint_facts"
                    ),
                    observedAt=_safe_timestamp(row.get("occurred_at")),
                    uri=(
                        "store://silver_campaign_touchpoint_facts/"
                        f"{touchpoint_id}"
                    ),
                )
            )
            campaign_touchpoints[canonical_campaign_id].append(
                EvidenceRef(
                    id=subject_id,
                    type="event",
                    source=(
                        "services/api/journeys/measurement/repositories/"
                        "touchpoint_repo.py:silver_campaign_touchpoint_facts:source_event_id"
                    ),
                    observedAt=_safe_timestamp(row.get("occurred_at")),
                    uri=(
                        "store://silver_campaign_touchpoint_facts/"
                        f"{touchpoint_id}#source_event_id"
                    ),
                )
            )

        if self._campaign_repository is None:
            try:
                from journeys.campaign.repository import CampaignRepository

                self._campaign_repository = CampaignRepository()
            except Exception:  # noqa: BLE001 - authority diagnostics stay private
                return _campaign_links_read(
                    tenant_id,
                    subject_kind,
                    subject_id,
                    available=False,
                    complete=False,
                    reason="canonical_campaign_authority_unavailable",
                )

        links: list[SignalCampaignLink] = []
        for campaign_id, touchpoint_refs in sorted(campaign_touchpoints.items()):
            try:
                campaign = await self._campaign_repository.get_by_id(
                    tenant_id, UUID(campaign_id)
                )
            except Exception:  # noqa: BLE001 - preserve slot-local unknown
                complete = False
                reason = "canonical_campaign_lookup_unavailable"
                continue
            if (
                not isinstance(campaign, dict)
                or campaign.get("tenant_id") != tenant_id
                or str(campaign.get("campaign_id")) != campaign_id
            ):
                complete = False
                reason = "touchpoint_campaign_not_resolved_in_tenant"
                continue
            campaign_evidence = EvidenceRef(
                id=campaign_id,
                type="entity",
                source="services/api/journeys/campaign/repository.py:campaigns",
                observedAt=_safe_timestamp(
                    campaign.get("updated_at") or campaign.get("created_at")
                ),
                uri=f"store://campaigns/{campaign_id}",
            )
            links.append(
                SignalCampaignLink(
                    campaign_id=campaign_id,
                    evidence_refs=tuple(
                        _unique_evidence_refs((*touchpoint_refs, campaign_evidence))
                    ),
                )
            )
        return _campaign_links_read(
            tenant_id,
            subject_kind,
            subject_id,
            links=tuple(links),
            available=True,
            complete=complete,
            reason=reason,
        )

    async def risk_signals_for_subject(
        self, *, tenant_id: str, subject_kind: str, subject_id: str, limit: int
    ) -> RiskFlagsRead:
        """Read only RiskSignals whose persisted tenant and typed subject match.

        RiskSignals are observations, not a complete risk assessment. This
        adapter deliberately does not follow identity aliases, evidence IDs,
        or neighboring graph subjects to find related risk records.
        """
        if (
            not _safe_identifier(tenant_id)
            or not _safe_identifier(subject_id)
            or subject_kind not in _RISK_SUBJECT_KINDS
        ):
            return RiskFlagsRead(
                tenant_id,
                subject_kind,
                subject_id,
                (),
                False,
                False,
                "exact_risk_subject_scope_required",
            )
        bounded_limit = min(max(int(limit), 1), _MAX_RISK_SIGNALS)
        try:
            from intelligence.risk360.store import RiskSignalRepository

            rows = await RiskSignalRepository().list_by_subject(
                tenant_id,
                subject_kind,
                subject_id,
                limit=bounded_limit + 1,
            )
        except Exception:  # noqa: BLE001 - authority diagnostics stay private
            return RiskFlagsRead(
                tenant_id,
                subject_kind,
                subject_id,
                (),
                False,
                False,
                "risk_signal_repository_unavailable",
            )

        if not isinstance(rows, list):
            return RiskFlagsRead(
                tenant_id,
                subject_kind,
                subject_id,
                (),
                False,
                False,
                "risk_signal_read_invalid",
            )
        complete = len(rows) <= bounded_limit
        scoped: list[dict[str, Any]] = []
        invalid_scope = False
        for row in rows[:bounded_limit]:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("subject_kind") != subject_kind
                or row.get("subject_id") != subject_id
            ):
                invalid_scope = True
                continue
            scoped.append(row)
        if invalid_scope:
            complete = False
        reason = (
            "risk_signal_read_truncated"
            if len(rows) > bounded_limit
            else "risk_signal_subject_scope_mismatch"
            if invalid_scope
            else None
        )
        return RiskFlagsRead(
            tenant_id,
            subject_kind,
            subject_id,
            tuple(scoped),
            True,
            complete,
            reason,
        )

    async def _linked_signal_entity(
        self, tenant_id: str, signal_id: str
    ) -> LinkedEntitiesRead:
        try:
            if self._signals is None:
                from repositories.repos import SignalRepository

                self._signals = SignalRepository()
            row = await self._signals.get_signal(tenant_id, signal_id)
        except Exception:  # noqa: BLE001 - authority details stay private
            return _linked_read(
                tenant_id,
                "signal",
                signal_id,
                available=False,
                complete=False,
                reason="behavioral_signal_authority_unavailable",
            )
        if row is None:
            return _linked_read(
                tenant_id,
                "signal",
                signal_id,
                available=True,
                complete=True,
                reason="exact_behavioral_signal_not_found",
            )
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("signal_id") != signal_id
        ):
            return _linked_read(
                tenant_id,
                "signal",
                signal_id,
                available=False,
                complete=False,
                reason="behavioral_signal_scope_mismatch",
            )
        entity_id = _safe_identifier(row.get("entity_id"))
        signal_evidence = _record_evidence(row)
        if entity_id is None or signal_evidence is None:
            return _linked_read(
                tenant_id,
                "signal",
                signal_id,
                available=True,
                complete=False,
                reason="behavioral_signal_entity_link_invalid",
            )

        linked, reason = await self._resolve_canonical_entity(
            tenant_id, entity_id, (signal_evidence,)
        )
        if linked is None:
            return _linked_read(
                tenant_id,
                "signal",
                signal_id,
                available=True,
                complete=False,
                reason=reason,
            )
        return _linked_read(
            tenant_id,
            "signal",
            signal_id,
            entities=(linked,),
            available=True,
            complete=True,
        )

    async def _linked_event_entities(
        self, tenant_id: str, subject_kind: str, subject_id: str
    ) -> LinkedEntitiesRead:
        try:
            identity = self._identity_repo()
            rows = await identity.get_observations_for_events(
                tenant_id, [subject_id], limit=20
            )
        except Exception:  # noqa: BLE001 - authority details stay private
            return _linked_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=False,
                complete=False,
                reason="identity_event_observation_authority_unavailable",
            )
        if not isinstance(rows, list):
            return _linked_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=False,
                complete=False,
                reason="identity_event_observation_read_invalid",
            )
        if not rows:
            reason = (
                "exact_observation_id_not_bound_to_identity_event_id"
                if subject_kind == "observation"
                else "exact_event_identity_observation_not_found"
            )
            return _linked_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=True,
                complete=True,
                reason=reason,
            )
        # IdentityResolutionRepository currently caps this exact event lookup
        # at 20 rows. Treat the cap as possible truncation so a hidden second
        # canonical target can never be mistaken for a single safe join.
        if len(rows) >= 20:
            return _linked_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=True,
                complete=False,
                reason="identity_event_observation_read_truncated",
            )

        evidence_refs: list[EvidenceRef] = []
        canonical_ids: set[str] = set()
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("source_event_id") != subject_id
            ):
                return _linked_read(
                    tenant_id,
                    subject_kind,
                    subject_id,
                    available=False,
                    complete=False,
                    reason="identity_event_observation_scope_mismatch",
                )
            observation_id = _safe_identifier(row.get("id"))
            canonical_entity_id = _safe_identifier(row.get("canonical_entity_id"))
            observed_at = _safe_timestamp(row.get("observed_at"))
            if not observation_id or not canonical_entity_id:
                return _linked_read(
                    tenant_id,
                    subject_kind,
                    subject_id,
                    available=True,
                    complete=False,
                    reason="identity_event_observation_canonical_entity_missing",
                )
            canonical_ids.add(canonical_entity_id)
            evidence_refs.append(
                EvidenceRef(
                    id=observation_id,
                    type="event",
                    source="identity_signal_observations",
                    observedAt=observed_at,
                )
            )

        linked_entities: dict[str, LinkedEntity] = {}
        for canonical_entity_id in sorted(canonical_ids):
            linked, reason = await self._resolve_canonical_entity(
                tenant_id, canonical_entity_id, tuple(evidence_refs)
            )
            if linked is None:
                return _linked_read(
                    tenant_id,
                    subject_kind,
                    subject_id,
                    available=True,
                    complete=False,
                    reason=reason,
                )
            existing = linked_entities.get(linked.entity_id)
            if existing is None:
                linked_entities[linked.entity_id] = linked
            else:
                linked_entities[linked.entity_id] = LinkedEntity(
                    entity_id=linked.entity_id,
                    entity_type=linked.entity_type,
                    evidence_refs=_unique_evidence_refs(
                        (*existing.evidence_refs, *linked.evidence_refs)
                    ),
                )
        if len(linked_entities) != 1:
            return _linked_read(
                tenant_id,
                subject_kind,
                subject_id,
                available=True,
                complete=False,
                reason="identity_event_entity_join_conflicted",
            )
        return _linked_read(
            tenant_id,
            subject_kind,
            subject_id,
            entities=tuple(linked_entities.values()),
            available=True,
            complete=True,
        )

    def _identity_repo(self) -> Any:
        if self._identity_repository is None:
            from identity.identity.repository import IdentityResolutionRepository

            self._identity_repository = IdentityResolutionRepository()
        return self._identity_repository

    async def _resolve_canonical_entity(
        self,
        tenant_id: str,
        entity_id: str,
        source_evidence: tuple[EvidenceRef, ...],
    ) -> tuple[Optional[LinkedEntity], Optional[str]]:
        """Follow tenant-owned merge tombstones to one active identity subject."""
        identity = self._identity_repo()
        current = entity_id
        visited: set[str] = set()
        identity_evidence: list[EvidenceRef] = []
        for _ in range(10):
            if current in visited:
                return None, "canonical_identity_merge_chain_invalid"
            visited.add(current)
            row = await identity.get_subject_by_canonical_entity_id(tenant_id, current)
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("canonical_entity_id") != current
            ):
                return None, "canonical_entity_identity_subject_not_found"
            identity_evidence.append(
                EvidenceRef(
                    id=current,
                    type="entity",
                    source="identity_subjects",
                    observedAt=_safe_timestamp(row.get("last_seen_at")),
                )
            )
            status = row.get("status")
            if status == "active":
                entity_type = _safe_token(
                    row.get("entity_type"),
                    allowed={
                        "human",
                        "anonymous_visitor",
                        "device",
                        "session",
                        "wallet",
                        "agent",
                        "organization",
                        "account",
                        "campaign",
                    },
                )
                if entity_type is None:
                    return None, "canonical_entity_type_unavailable"
                return (
                    LinkedEntity(
                        entity_id=current,
                        entity_type=entity_type,
                        evidence_refs=_unique_evidence_refs(
                            (*source_evidence, *identity_evidence)
                        ),
                    ),
                    None,
                )
            if status != "merged":
                return None, "canonical_entity_identity_subject_not_active"
            next_entity_id = _safe_identifier(row.get("merged_into_entity_id"))
            if next_entity_id is None:
                return None, "canonical_identity_merge_target_missing"
            current = next_entity_id
        return None, "canonical_identity_merge_chain_hop_limit"


class Signals360Provider(IntelligenceProjectionProvider):
    """Tenant-safe, read-only projection for the Signals360 contract."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(self, *, source: Optional[Signal360Source] = None) -> None:
        self._source = source or RepositorySignal360Source()

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        tenant_id = request.tenantId
        if context.tenantId != tenant_id or context.projectionId != self.projection_id:
            raise ValueError("Signals360 request and projection context scope must match")

        read: Optional[SignalSummaryRead] = None
        if request.subject.kind == "entity":
            try:
                read = await self._source.entity_signals(
                    tenant_id=tenant_id,
                    entity_id=request.subject.id,
                    limit=_MAX_SIGNAL_RECORDS,
                )
            except Exception:  # noqa: BLE001 - source diagnostics stay private
                read = SignalSummaryRead(
                    (), False, False, "behavioral_signal_repository_unavailable"
                )

        requested_sections = set(request.includeSections or OUTPUT_SECTIONS)
        quality_read: Optional[ObservationQualityRead] = None
        if {"quality", "source_inventory", "normalization"}.intersection(requested_sections) and request.subject.kind in {
            "event",
            "observation",
        }:
            reader = getattr(self._source, "observation_quality", None)
            if callable(reader):
                try:
                    quality_read = await reader(
                        tenant_id=tenant_id,
                        observation_id=request.subject.id,
                    )
                except Exception:  # noqa: BLE001 - diagnostics stay private
                    quality_read = ObservationQualityRead(
                        None,
                        False,
                        False,
                        "sdk_observation_bronze_unavailable",
                    )

        # Reuse the exact, bounded SDK Bronze read for canonical event
        # classification. Translator output and free-form payload properties
        # are not source-event classification authorities.
        if (
            "classification" in requested_sections
            and request.subject.kind in {"event", "observation"}
            and quality_read is None
        ):
            reader = getattr(self._source, "observation_quality", None)
            if callable(reader):
                try:
                    quality_read = await reader(
                        tenant_id=tenant_id,
                        observation_id=request.subject.id,
                    )
                except Exception:  # noqa: BLE001 - diagnostics stay private
                    quality_read = ObservationQualityRead(
                        None,
                        False,
                        False,
                        "sdk_observation_bronze_unavailable",
                    )

        semantic_read: Optional[SemanticEventRead] = None
        semantic_skip_reason: Optional[str] = None
        if "classification" in requested_sections and request.subject.kind in {"event", "observation"}:
            if request.asOf is not None or request.timeRange is not None:
                semantic_skip_reason = "semantic_event_temporal_read_not_supported"
            elif quality_read is not None and quality_read.available and quality_read.complete and quality_read.record is not None:
                semantic_reader = getattr(self._source, "semantic_observations_for_event", None)
                if callable(semantic_reader):
                    try:
                        semantic_read = await semantic_reader(
                            tenant_id=tenant_id,
                            event_id=request.subject.id,
                            limit=_MAX_SEMANTIC_EVENT_OBSERVATIONS,
                        )
                        if not isinstance(semantic_read, SemanticEventRead):
                            semantic_read = None
                            semantic_skip_reason = "semantic_event_read_invalid"
                    except Exception:  # noqa: BLE001 - authority diagnostics stay private
                        semantic_skip_reason = "semantic_event_authority_unavailable"
                else:
                    semantic_skip_reason = "semantic_event_authority_not_joined"

        source_authority_read: Optional[ObservationSourceAuthorityRead] = None
        if (
            "source_inventory" in requested_sections
            and quality_read is not None
            and quality_read.available
            and quality_read.complete
            and isinstance(quality_read.record, dict)
        ):
            authority_reader = getattr(self._source, "observation_source_authority", None)
            if callable(authority_reader):
                try:
                    source_authority_read = await authority_reader(
                        tenant_id=tenant_id,
                        observation_id=request.subject.id,
                        record=quality_read.record,
                    )
                except Exception:  # noqa: BLE001 - source diagnostics stay private
                    source_authority_read = ObservationSourceAuthorityRead(
                        tenant_id,
                        request.subject.id,
                        None,
                        False,
                        False,
                        False,
                        "observation_source_authority_unavailable",
                    )

        linked_read: Optional[LinkedEntitiesRead] = None
        if "linked_entities" in requested_sections:
            reader = getattr(self._source, "linked_entities", None)
            if callable(reader):
                try:
                    linked_read = await reader(
                        tenant_id=tenant_id,
                        subject_kind=request.subject.kind,
                        subject_id=request.subject.id,
                    )
                except Exception:  # noqa: BLE001 - source diagnostics stay private
                    linked_read = LinkedEntitiesRead(
                        tenant_id=tenant_id,
                        subject_kind=request.subject.kind,
                        subject_id=request.subject.id,
                        entities=(),
                        available=False,
                        complete=False,
                        reason="canonical_identity_join_unavailable",
                    )

        campaign_links_read: Optional[CampaignLinksRead] = None
        if "campaign_links" in requested_sections:
            reader = getattr(self._source, "campaign_links", None)
            if callable(reader):
                try:
                    campaign_links_read = await reader(
                        tenant_id=tenant_id,
                        subject_kind=request.subject.kind,
                        subject_id=request.subject.id,
                    )
                except Exception:  # noqa: BLE001 - source details stay private
                    campaign_links_read = _campaign_links_read(
                        tenant_id,
                        request.subject.kind,
                        request.subject.id,
                        available=False,
                        complete=False,
                        reason="campaign_touchpoint_authority_unavailable",
                    )

        risk_flags_read: Optional[RiskFlagsRead] = None
        risk_flags_skip_reason: Optional[str] = (
            None
            if "risk_flags" in requested_sections
            else "risk_flags_slot_not_requested"
        )
        if "risk_flags" in requested_sections:
            if request.asOf is not None or request.timeRange is not None:
                # RiskSignal has an observed_at field, but this repository read
                # is not a complete bitemporal history or bounded time-window
                # query. Never apply current risk records to a historical frame.
                risk_flags_skip_reason = "risk_signal_temporal_filter_not_supported"
            elif request.subject.kind not in _RISK_SUBJECT_KINDS:
                risk_flags_skip_reason = "risk_subject_kind_not_supported"
            else:
                reader = getattr(self._source, "risk_signals_for_subject", None)
                if callable(reader):
                    try:
                        risk_flags_read = await reader(
                            tenant_id=tenant_id,
                            subject_kind=request.subject.kind,
                            subject_id=request.subject.id,
                            limit=_MAX_RISK_SIGNALS,
                        )
                        if not isinstance(risk_flags_read, RiskFlagsRead):
                            risk_flags_read = RiskFlagsRead(
                                tenant_id,
                                request.subject.kind,
                                request.subject.id,
                                (),
                                False,
                                False,
                                "risk_signal_read_invalid",
                            )
                    except Exception:  # noqa: BLE001 - authority diagnostics stay private
                        risk_flags_read = RiskFlagsRead(
                            tenant_id,
                            request.subject.kind,
                            request.subject.id,
                            (),
                            False,
                            False,
                            "risk_signal_repository_unavailable",
                        )
                else:
                    risk_flags_skip_reason = "canonical_signal_risk_join_not_available"

        rows, scope_mismatch = _scoped_rows(
            read.rows if read is not None else (),
            tenant_id=tenant_id,
            entity_id=request.subject.id if request.subject.kind == "entity" else None,
        )
        read_complete = bool(
            read is not None and read.available and read.complete and not scope_mismatch
        )
        read_available = bool(read is not None and read.available)
        read_reason = (
            "unscoped_or_invalid_signal_rows_dropped"
            if scope_mismatch
            else _safe_reason(read.reason)
            if read is not None
            else "subject_kind_not_supported_by_signal_repository"
        )
        refs = [_record_evidence(row) for row in rows]
        valid_refs = [ref for ref in refs if ref is not None]
        records = [_public_signal(row) for row in rows]
        if read is not None and read.available and read.complete and not read.rows:
            summary_state = "empty"
            summary_warnings = None
        elif read_available and read_complete:
            summary_state = "available" if records else "degraded"
            summary_warnings = None if records else ["signal rows lacked safe display identifiers"]
        else:
            summary_state = (
                "degraded" if read_available or request.subject.kind == "entity" else "unknown"
            )
            summary_warnings = [read_reason or "behavioral signal summary is unavailable"]

        summary_content: dict[str, Any] = {
            "tenantId": tenant_id,
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "authority": _SUMMARY_SOURCE,
            "signalKind": "translator_derived_behavioral_signal",
            "scopeState": "complete" if read_complete else "partial_or_unknown",
            "signals": records,
            "evidenceRefs": [ref.model_dump(mode="json") for ref in valid_refs],
        }
        if read_available:
            summary_content["returnedSignalCount"] = len(records)
        if read_complete:
            summary_content["signalCount"] = len(records)
            summary_content["countsBySeverity"] = _count_values(records, "severity")
            summary_content["countsBySentiment"] = _count_values(records, "sentiment")
        else:
            summary_content["reasonCode"] = read_reason or "signal_summary_read_incomplete"

        claims: list[ClaimEnvelope] = []
        if request.subject.kind == "entity":
            for row, record, evidence in zip(rows, records, valid_refs):
                claims.append(
                    ClaimEnvelope(
                        id=f"signals360.behavioral_signal_record.{record['signalId']}",
                        kind="stored_behavioral_signal_record",
                        subject=request.subject,
                        evidenceRefs=[evidence],
                        claims=[
                            "A translator-derived behavioral signal record is stored for this entity; its label is a derived signal and is not a source-event truth claim."
                        ],
                        confidence=_confidence(row.get("confidence")),
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["signal_summary"],
                    )
                )

        sections: list[ProjectionSection] = [
            ProjectionSection(
                id="signal_summary",
                state=summary_state,
                title="Stored behavioral signal summary",
                content=summary_content,
                warnings=summary_warnings,
                canonicalAuthorityRefs=["behavioral_signals"],
            )
        ]
        for slot_id in OUTPUT_SECTIONS[1:8]:
            if slot_id == "source_inventory":
                source_section, source_claim = _source_inventory_section(
                    request.subject,
                    tenant_id=tenant_id,
                    read=quality_read,
                    authority_read=source_authority_read,
                )
                sections.append(source_section)
                if source_claim is not None:
                    claims.append(source_claim)
            elif slot_id == "quality":
                quality_section, quality_claim = _quality_section(
                    request.subject,
                    tenant_id=tenant_id,
                    read=quality_read,
                )
                sections.append(quality_section)
                if quality_claim is not None:
                    claims.append(quality_claim)
            elif slot_id == "normalization":
                normalization_section, normalization_claim = _normalization_section(
                    request.subject,
                    tenant_id=tenant_id,
                    read=quality_read,
                )
                sections.append(normalization_section)
                if normalization_claim is not None:
                    claims.append(normalization_claim)
            elif slot_id == "classification":
                classification_section, classification_claim = _classification_section(
                    request.subject,
                    tenant_id=tenant_id,
                    read=quality_read,
                    semantic_read=semantic_read,
                    semantic_skip_reason=semantic_skip_reason,
                )
                sections.append(classification_section)
                if classification_claim is not None:
                    claims.append(classification_claim)
            elif slot_id == "linked_entities":
                linked_section, linked_claims = _linked_entities_section(
                    request.subject,
                    tenant_id=tenant_id,
                    read=linked_read,
                )
                sections.append(linked_section)
                claims.extend(linked_claims)
            elif slot_id == "campaign_links":
                campaign_section, campaign_claims = _campaign_links_section(
                    request.subject,
                    tenant_id=tenant_id,
                    read=campaign_links_read,
                )
                sections.append(campaign_section)
                claims.extend(campaign_claims)
            elif slot_id == "risk_flags":
                risk_section, risk_claims = _risk_flags_section(
                    request.subject,
                    tenant_id=tenant_id,
                    read=risk_flags_read,
                    skip_reason=risk_flags_skip_reason,
                )
                sections.append(risk_section)
                claims.extend(risk_claims)
            else:
                sections.append(_unknown_section(slot_id))
        sections.extend(
            [
                _freshness_section(
                    request.subject,
                    tenant_id=tenant_id,
                    rows=rows,
                    available=read_available,
                    complete=read_complete,
                    reason=read_reason,
                ),
                _evidence_trace_section(
                    request.subject,
                    tenant_id=tenant_id,
                    refs=valid_refs,
                    available=read_available,
                    complete=read_complete,
                    reason=read_reason,
                ),
            ]
        )
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
        )


def _unknown_section(slot_id: str) -> ProjectionSection:
    reasons = {
        "source_inventory": "canonical_signal_source_inventory_not_joined",
        "classification": "canonical_event_signal_classifier_not_joined",
        "quality": "canonical_ingestion_quality_read_not_joined",
        "normalization": "canonical_observation_normalization_read_not_joined",
        "linked_entities": "exact_signal_event_identity_join_not_available",
        "campaign_links": "canonical_signal_campaign_join_not_available",
        "risk_flags": "canonical_signal_risk_join_not_available",
    }
    return ProjectionSection(
        id=slot_id,
        state="unknown",
        title=slot_id.replace("_", " ").title(),
        content={"state": "unknown", "reasonCode": reasons[slot_id]},
        warnings=[reasons[slot_id]],
        # This slot is not currently connected to a canonical signal-event
        # intake authority, so do not advertise the blueprint owner as a live
        # source for the unknown result.
    )


def _risk_flags_section(
    subject: ProjectionSubject,
    *,
    tenant_id: str,
    read: Optional[RiskFlagsRead],
    skip_reason: Optional[str],
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    """Render exact-subject canonical RiskSignals without inferring coverage.

    RiskSignals are atomic detector records. This section does not join the
    Risk360 aggregate assessment, infer that the source event caused a risk,
    or treat an empty subject query as evidence that the subject is risk-free.
    """
    scope_mismatch = bool(
        read is not None
        and (
            read.tenant_id != tenant_id
            or read.subject_kind != subject.kind
            or read.subject_id != subject.id
        )
    )
    records = (
        read.records
        if read is not None and isinstance(read.records, (tuple, list))
        else ()
    )
    invalid_read_shape = read is not None and not isinstance(read.records, (tuple, list))
    read_truncated = len(records) > _MAX_RISK_SIGNALS
    read_complete = bool(
        read is not None and read.complete and not read_truncated and not invalid_read_shape
    )
    reason = (
        "risk_signal_read_scope_mismatch"
        if scope_mismatch
        else "risk_signal_read_invalid"
        if invalid_read_shape
        else _safe_reason_code(read.reason)
        if read is not None
        else _safe_reason_code(skip_reason)
        if skip_reason is not None
        else "canonical_signal_risk_join_not_available"
    )
    parsed_signals: list[Any] = []
    signal_rows: list[dict[str, Any]] = []
    invalid_record = False
    if read is not None and not scope_mismatch and not invalid_read_shape:
        # Import lazily so Signals360 keeps the risk authority as a read
        # dependency and does not create a module-level provider cycle.
        from intelligence.risk360.contracts import RiskSignal

        for raw in records[:_MAX_RISK_SIGNALS]:
            try:
                signal = RiskSignal.model_validate(raw)
            except Exception:  # noqa: BLE001 - malformed source rows fail closed
                invalid_record = True
                continue
            if (
                signal.tenant_id != tenant_id
                or signal.subject_kind != subject.kind
                or signal.subject_id != subject.id
                or not signal.evidence_refs
                or not _safe_identifier(signal.source)
            ):
                invalid_record = True
                continue
            evidence_refs = [
                ref for ref in signal.evidence_refs if isinstance(ref, EvidenceRef)
            ]
            if not evidence_refs:
                invalid_record = True
                continue
            signal_id = _safe_identifier(signal.signal_id)
            if signal_id is None:
                invalid_record = True
                continue
            parsed_signals.append(signal)
            signal_rows.append(
                {
                    "signalId": signal_id,
                    "subject": {
                        "kind": signal.subject_kind,
                        "id": signal.subject_id,
                    },
                    "riskDimension": signal.risk_dimension,
                    "claimState": signal.claim_state.value,
                    "confidence": signal.confidence,
                    "score": signal.score,
                    "source": signal.source,
                    "detectorVersion": signal.detector_version,
                    "observedAt": _safe_timestamp(signal.observed_at),
                    "evidenceRefs": [
                        ref.model_dump(mode="json") for ref in evidence_refs
                    ],
                    "causalAttribution": "not_established",
                }
            )

    parsed_signals.sort(
        key=lambda signal: (
            _safe_timestamp(signal.observed_at) or "",
            signal.signal_id,
        )
    )
    signal_rows.sort(key=lambda row: (row["observedAt"] or "", row["signalId"]))
    if read_truncated:
        reason = reason or "risk_signal_read_truncated"
    if invalid_record:
        reason = "risk_signal_rows_invalid_or_missing_evidence"
    if read is not None and not read.available:
        reason = reason or "risk_signal_authority_unavailable"
    elif read is not None and not read_complete:
        reason = reason or "risk_signal_read_incomplete"
    if invalid_record:
        read_complete = False
    if read is None:
        state = "unknown"
    elif scope_mismatch or not read.available or not read_complete or invalid_record:
        state = "degraded"
    elif not signal_rows:
        # No risk producer coverage contract exists for Signals360, so a
        # complete exact query with no rows cannot prove risk absence.
        state = "unknown"
        reason = "no_exact_subject_risk_signals_observed"
    else:
        # The linked records are usable, but the lack of producer coverage,
        # policy, history and freshness still makes the posture partial.
        state = "degraded"

    claims = [
        ClaimEnvelope(
            id=f"signals360.risk_signal.{subject.kind}.{subject.id}.{signal.signal_id}",
            kind="exact_subject_risk_signal_record",
            subject=subject,
            evidenceRefs=list(signal.evidence_refs),
            claims=[
                f"Canonical RiskSignal {signal.signal_id} is recorded for this exact tenant-scoped {subject.kind} subject; this records subject association only and does not establish event causality or a complete risk assessment."
            ],
            confidence=signal.confidence,
            claimState=signal.claim_state,
            domainSlotIds=["risk_flags"],
        )
        for signal in parsed_signals
    ]
    content: dict[str, Any] = {
        "tenantId": tenant_id,
        "subject": {"kind": subject.kind, "id": subject.id},
        "authority": "intelligence.risk360.store.RiskSignalRepository",
        "coverage": "exact_tenant_typed_subject_risk_signal_records",
        "signals": signal_rows,
        "producerCoverageState": "unknown",
        "riskHistoryState": "unknown",
        "assessmentState": "not_joined",
        "policyState": "not_evaluated_by_signals360_risk_read",
        "freshnessState": "unknown",
        "freshnessThresholdSeconds": None,
        "causalAttributionState": "not_established",
        "authorityReadAvailable": bool(
            read is not None
            and read.available
            and not scope_mismatch
            and not invalid_read_shape
        ),
        "authorityReadComplete": bool(
            read is not None
            and read.available
            and read_complete
            and not scope_mismatch
            and not invalid_record
        ),
        "readTruncated": read_truncated,
        "reasonCode": reason or "exact_subject_risk_signals_observed_with_partial_coverage",
        "evidenceRefs": [
            ref.model_dump(mode="json")
            for signal in parsed_signals
            for ref in signal.evidence_refs
        ],
    }
    if read is not None and read.available and not scope_mismatch:
        content["returnedSignalCount"] = len(signal_rows)
    section = ProjectionSection(
        id="risk_flags",
        state=state,
        title="Exact-subject RiskSignal observations",
        content=content,
        warnings=(
            []
            if state == "available"
            else [
                reason
                or "risk signals are partial observations; coverage, history, policy, freshness, and causality are unknown"
            ]
        )
        + [
            "Recorded RiskSignals do not establish complete subject risk coverage or that the subject caused a signal.",
            "Risk policy and freshness are not evaluated by this exact-record read.",
        ],
        canonicalAuthorityRefs=["risk_outputs"] if read is not None else [],
    )
    return section, claims


def _classification_section(
    subject: ProjectionSubject,
    *,
    tenant_id: str,
    read: Optional[ObservationQualityRead],
    semantic_read: Optional[SemanticEventRead] = None,
    semantic_skip_reason: Optional[str] = None,
) -> tuple[ProjectionSection, Optional[ClaimEnvelope]]:
    """Project the canonical event type/family for one exact SDK observation.

    This is deliberately narrower than source attribution or semantic signal
    classification. The event registry and gateway prove only that the exact
    tenant-owned SDK row names a registered event type and family.
    """
    reason: Optional[str] = None
    row: Optional[dict[str, Any]] = None
    if subject.kind not in {"event", "observation"}:
        reason = "exact_sdk_event_or_observation_subject_required"
    elif read is None:
        reason = "exact_sdk_event_classification_read_unavailable"
    elif not read.available or not read.complete:
        reason = read.reason or "exact_sdk_event_classification_read_incomplete"
    elif read.record is None:
        reason = read.reason or "exact_sdk_event_classification_not_found"
    elif (
        read.record.get("tenant_id") != tenant_id
        or read.record.get("provider_record_id") != subject.id
        or read.record.get("source") != "sdk"
    ):
        reason = "sdk_event_classification_scope_mismatch"
    else:
        row = read.record

    envelope: Optional[dict[str, Any]] = None
    observation: Optional[dict[str, Any]] = None
    if row is not None:
        payload = row.get("payload")
        envelope = payload.get("observation_envelope") if isinstance(payload, dict) else None
        observation = envelope.get("observation") if isinstance(envelope, dict) else None
        tenancy = envelope.get("tenancy") if isinstance(envelope, dict) else None
        if (
            not isinstance(observation, dict)
            or observation.get("observation_id") != subject.id
            or not isinstance(tenancy, dict)
            or tenancy.get("tenant_id") != tenant_id
        ):
            reason = "canonical_observation_envelope_missing_or_mismatched"

    validation_state = None
    if envelope is not None:
        quality = envelope.get("quality")
        validation_state = (
            _safe_token(quality.get("validation_state"))
            if isinstance(quality, dict)
            else None
        )
    if row is not None and validation_state != "gateway:accepted":
        reason = reason or "observation_gateway_validation_state_not_stamped"

    event_type: Optional[str] = None
    event_family: Optional[str] = None
    if row is not None and observation is not None:
        from ingestion.ingestion.generated_registry import (
            CANONICAL_EVENT_TYPES,
            EVENT_FAMILY,
        )

        envelope_type = _safe_token(observation.get("observation_type"))
        payload = row.get("payload")
        stored_type = (
            _safe_token(payload.get("event_type"))
            if isinstance(payload, dict)
            else None
        )
        registered_family = EVENT_FAMILY.get(envelope_type or "")
        envelope_family = _safe_token(observation.get("family"))
        if (
            envelope_type is None
            or envelope_type not in CANONICAL_EVENT_TYPES
            or envelope_type != stored_type
            or registered_family is None
        ):
            reason = reason or "canonical_event_type_not_registered_or_mismatched"
        elif envelope_family is not None and envelope_family != registered_family:
            reason = reason or "canonical_event_family_mismatch"
        else:
            event_type = envelope_type
            event_family = registered_family

    if reason is not None or event_type is None or event_family is None or row is None:
        failure_reason = reason or "canonical_event_classification_unavailable"
        return (
            ProjectionSection(
                id="classification",
                state=(
                    "degraded"
                    if read is not None and (not read.available or not read.complete)
                    else "unknown"
                ),
                title="Canonical event classification",
                content={
                    "tenantId": tenant_id,
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "classificationState": "unknown",
                    "reasonCode": failure_reason,
                },
                warnings=[failure_reason],
                canonicalAuthorityRefs=["events", "observations"],
            ),
            None,
        )

    observed_at = _safe_timestamp(
        observation.get("ingested_at") or row.get("ingested_at")
    )
    event_evidence = EvidenceRef(
        id=subject.id,
        type="event",
        source="bronze_sdk_events",
        observedAt=observed_at,
    )
    registry_evidence = EvidenceRef(
        id=event_type,
        type="annotation",
        source="ingestion.ingestion.generated_registry:CANONICAL_EVENT_TYPES/EVENT_FAMILY",
    )
    section = ProjectionSection(
        id="classification",
        state="available",
        title="Canonical event classification",
        content={
            "tenantId": tenant_id,
            "subject": {"kind": subject.kind, "id": subject.id},
            "coverage": "one_exact_tenant_scoped_sdk_event",
            "classificationState": "canonical_event_type_and_family_available",
            "eventType": event_type,
            "eventFamily": event_family,
            "classificationBasis": "gateway_accepted_canonical_event_registry",
            "sourceClassificationState": "unknown",
            "sourceClassificationReason": "tenant_source_classification_authority_not_joined",
            "semanticSignalState": "unknown",
            "semanticSignalReason": semantic_skip_reason or "semantic_event_authority_not_joined",
            "policyState": "not_evaluated_by_signals360_classification_read",
            "freshnessState": "unknown",
            "evidenceRefs": [
                event_evidence.model_dump(mode="json"),
                registry_evidence.model_dump(mode="json"),
            ],
            "reasonCode": "event_type_family_only_source_classification_unjoined",
        },
        warnings=[
            "canonical event type and family are available; source classification, semantic signal quality, policy, and freshness are not joined"
        ],
        canonicalAuthorityRefs=["events", "observations"],
    )
    claim = ClaimEnvelope(
        id=f"signals360.canonical_event_classification.{subject.id}",
        kind="canonical_event_type_family",
        subject=subject,
        evidenceRefs=[event_evidence, registry_evidence],
        claims=[
            "The exact tenant-scoped SDK event has a gateway-accepted event type and family that match the canonical event registry."
        ],
        confidence=1.0,
        claimState=EpistemicStatus.OBSERVED,
        domainSlotIds=["classification"],
    )
    semantic_content, semantic_evidence = _exact_semantic_event_metadata(
        tenant_id=tenant_id,
        event_id=subject.id,
        event_type=event_type,
        envelope=envelope,
        row=row,
        read=semantic_read,
        skip_reason=semantic_skip_reason,
    )
    section.content.update(semantic_content)
    if semantic_evidence:
        section.content["evidenceRefs"].extend(
            ref.model_dump(mode="json") for ref in semantic_evidence
        )
        section.canonicalAuthorityRefs.append("silver_semantic_observations")
        section.content["reasonCode"] = "event_registry_and_exact_semantic_model_output_metadata_only"
        section.warnings = [
            "Event type and family and stored semantic model-output metadata are observed; model correctness, source classification, policy, producer coverage, and freshness remain unknown."
        ]
    return section, claim


def _exact_semantic_event_metadata(
    *,
    tenant_id: str,
    event_id: str,
    event_type: str,
    envelope: dict[str, Any],
    row: dict[str, Any],
    read: Optional[SemanticEventRead],
    skip_reason: Optional[str],
) -> tuple[dict[str, Any], list[EvidenceRef]]:
    """Admit only active model-output metadata for the exact stamped SDK event.

    This verifies association, not model correctness, consent, source trust,
    complete producer coverage, or an as-of semantic state. Derived labels and
    actor/subject references remain suppressed by this projection.
    """
    def unknown(reason: str) -> tuple[dict[str, Any], list[EvidenceRef]]:
        return {"semanticSignalState": "unknown", "semanticSignalReason": reason}, []

    if skip_reason is not None:
        return unknown(skip_reason)
    if read is None:
        return unknown("semantic_event_authority_not_joined")
    if read.tenant_id != tenant_id or read.source_event_id != event_id:
        return unknown("semantic_event_read_scope_mismatch")
    if not read.available or not read.complete:
        return unknown(read.reason or "semantic_event_read_incomplete")
    if len(read.rows) > _MAX_SEMANTIC_EVENT_OBSERVATIONS:
        return unknown("semantic_event_read_truncated")
    if not read.rows:
        return unknown("semantic_event_producer_coverage_unknown")
    payload = row.get("payload")
    context = payload.get("context") if isinstance(payload, dict) else None
    source = envelope.get("source")
    observation = envelope.get("observation")
    namespace = source.get("source_instance") if isinstance(source, dict) else None
    event_at = _safe_timestamp(observation.get("occurred_at")) if isinstance(observation, dict) else None
    if (
        not isinstance(context, dict)
        or not isinstance(namespace, str)
        or namespace != context.get("identity_namespace")
        or not (
            namespace == f"tenant:{tenant_id}"
            or (namespace.startswith("site:") and bool(namespace[5:].strip()))
        )
        or event_at is None
    ):
        return unknown("semantic_event_source_namespace_or_time_unverified")

    records: list[dict[str, Any]] = []
    evidence: list[EvidenceRef] = []
    seen: set[str] = set()
    for semantic in read.rows:
        if not isinstance(semantic, dict):
            return unknown("semantic_event_row_invalid")
        if (
            semantic.get("tenant_id") != tenant_id
            or semantic.get("source_event_id") != event_id
            or semantic.get("source_namespace") != namespace
            or semantic.get("source_type") != event_type
        ):
            return unknown("semantic_event_row_scope_mismatch")
        status = _safe_token(semantic.get("status"))
        if status in {"deleted", "expired", "superseded", "failed", "quarantined", "consent_restricted"}:
            continue
        semantic_id = _safe_identifier(semantic.get("observation_id"))
        model_id = _safe_identifier(semantic.get("model_id"))
        model_version = _safe_identifier(semantic.get("model_version"))
        processed_at = _safe_timestamp(semantic.get("processed_at"))
        supporting = semantic.get("evidence_refs")
        if (
            _safe_timestamp(semantic.get("occurred_at")) != event_at
            or status not in {"classified", "partial", "abstained"}
            or semantic_id is None
            or semantic_id in seen
            or model_id is None
            or model_version is None
            or processed_at is None
            or not isinstance(supporting, list)
            or not any(
                isinstance(ref, dict)
                and ref.get("source_ref") == event_id
                and ref.get("source_type") == event_type
                for ref in supporting
            )
        ):
            return unknown("semantic_event_row_evidence_mismatch")
        seen.add(semantic_id)
        evidence.append(
            EvidenceRef(
                id=semantic_id,
                type="model_output",
                source="silver_semantic_observations",
                observedAt=processed_at,
            )
        )
        records.append(
            {
                "observationId": semantic_id,
                "status": status,
                "modelId": model_id,
                "modelVersion": model_version,
            }
        )
    if not records:
        return unknown("no_active_semantic_event_model_output")
    return (
        {
            "semanticSignalState": "stored_model_output_observed",
            "semanticSignalReason": "exact_tenant_event_namespace_and_evidence_join",
            "semanticObservations": records,
            "semanticCorrectnessState": "unknown",
            "semanticProducerCoverageState": "unknown",
        },
        evidence,
    )


def _linked_entities_section(
    subject: ProjectionSubject,
    *,
    tenant_id: str,
    read: Optional[LinkedEntitiesRead],
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    """Publish exact identity-backed signal/event links with bounded claims."""
    scope_mismatch = bool(
        read is not None
        and (
            read.tenant_id != tenant_id
            or read.subject_kind != subject.kind
            or read.subject_id != subject.id
        )
    )
    reason = (
        "canonical_identity_join_scope_mismatch"
        if scope_mismatch
        else _safe_reason(read.reason)
        if read is not None
        else "exact_signal_event_identity_join_not_available"
    )
    entities: list[dict[str, str]] = []
    evidence_refs: list[EvidenceRef] = []
    invalid_entity = False
    if read is not None and not scope_mismatch:
        for linked in read.entities:
            entity_id = _safe_identifier(linked.entity_id)
            entity_type = _safe_token(
                linked.entity_type,
                allowed={
                    "human",
                    "anonymous_visitor",
                    "device",
                    "session",
                    "wallet",
                    "agent",
                    "organization",
                    "account",
                    "campaign",
                },
            )
            refs = [ref for ref in linked.evidence_refs if isinstance(ref, EvidenceRef)]
            if entity_id is None or entity_type is None or not refs:
                invalid_entity = True
                break
            entities.append({"id": entity_id, "entityType": entity_type, "state": "active"})
            evidence_refs.extend(refs)
    if invalid_entity:
        entities = []
        evidence_refs = []
        reason = "canonical_entity_link_evidence_invalid"

    evidence_refs = list(_unique_evidence_refs(evidence_refs))
    if read is None or scope_mismatch or invalid_entity or not read.available or not read.complete:
        state = "degraded" if read is not None else "unknown"
        entities = []
        evidence_refs = []
    elif entities:
        state = "available"
    else:
        # A bounded exact lookup that produced no link is not proof that an
        # event/observation has no entity link; identity evidence may be absent.
        state = "unknown"

    content: dict[str, Any] = {
        "tenantId": tenant_id,
        "subject": {"kind": subject.kind, "id": subject.id},
        "coverage": (
            "exact_tenant_signal_record_to_identity_subject"
            if subject.kind == "signal"
            else "exact_tenant_identity_event_observation_to_identity_subject"
            if subject.kind == "event"
            else "exact_observation_id_to_identity_source_event_id"
            if subject.kind == "observation"
            else "unsupported_exact_entity_join"
        ),
        "linkedEntities": entities,
        "authorityReadComplete": bool(
            read is not None
            and not scope_mismatch
            and read.available
            and read.complete
        ),
        "reasonCode": reason or ("exact_canonical_entity_link_observed" if entities else "canonical_entity_link_unknown"),
        "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence_refs],
    }
    if read is not None and read.available:
        content["returnedEntityCount"] = len(entities)
    canonical_authorities = (
        ["behavioral_signals", "identity"]
        if subject.kind == "signal"
        else ["identity"]
        if subject.kind in {"event", "observation"}
        else []
    )
    section = ProjectionSection(
        id="linked_entities",
        state=state,
        title="Canonical entities linked to signal or event",
        content=content,
        warnings=(
            []
            if entities
            else [reason or "canonical entity links are unknown or unresolved"]
        ),
        canonicalAuthorityRefs=canonical_authorities,
    )
    claims: list[ClaimEnvelope] = []
    if entities:
        for entity, linked in zip(entities, read.entities):
            source_label = {
                "signal": "the exact tenant-scoped behavioral signal record",
                "event": "the exact tenant-scoped identity resolution observation for this event",
                "observation": (
                    "the exact tenant-scoped identity resolution observation whose "
                    "source_event_id equals this observation id"
                ),
            }.get(subject.kind, "the exact tenant-scoped source record")
            claims.append(
                ClaimEnvelope(
                    id=(
                        f"signals360.linked_entity.{subject.kind}."
                        f"{subject.id}.{entity['id']}"
                    ),
                    kind=f"exact_{subject.kind}_canonical_entity_binding",
                    subject=subject,
                    evidenceRefs=list(linked.evidence_refs),
                    claims=[
                        f"{source_label} is associated with active canonical entity {entity['id']} under the same tenant scope."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["linked_entities"],
                )
            )
    return section, claims


def _campaign_links_section(
    subject: ProjectionSubject,
    *,
    tenant_id: str,
    read: Optional[CampaignLinksRead],
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    """Render only exact touchpoint references resolved by the campaign owner."""
    scope_mismatch = bool(
        read is not None
        and (
            read.tenant_id != tenant_id
            or read.subject_kind != subject.kind
            or read.subject_id != subject.id
        )
    )
    reason = (
        "campaign_link_read_scope_mismatch"
        if scope_mismatch
        else _safe_reason(read.reason)
        if read is not None
        else "canonical_signal_campaign_join_not_available"
    )
    links: list[dict[str, Any]] = []
    claim_refs: list[tuple[str, tuple[EvidenceRef, ...]]] = []
    invalid_link = False
    if read is not None and not scope_mismatch:
        for link in read.links:
            campaign_id = _safe_identifier(link.campaign_id)
            refs = [ref for ref in link.evidence_refs if isinstance(ref, EvidenceRef)]
            try:
                valid_campaign_id = campaign_id is not None and str(UUID(campaign_id)) == campaign_id
            except (TypeError, ValueError, AttributeError):
                valid_campaign_id = False
            required_sources = {
                "services/api/journeys/measurement/repositories/"
                "touchpoint_repo.py:silver_campaign_touchpoint_facts",
                "services/api/journeys/measurement/repositories/"
                "touchpoint_repo.py:silver_campaign_touchpoint_facts:source_event_id",
                "services/api/journeys/campaign/repository.py:campaigns",
            }
            if (
                not valid_campaign_id
                or not refs
                or not required_sources.issubset({ref.source for ref in refs})
            ):
                invalid_link = True
                break
            links.append(
                {
                    "campaignId": campaign_id,
                    "linkState": "exact_tenant_campaign_touchpoint",
                }
            )
            claim_refs.append((campaign_id, tuple(refs)))
    if invalid_link:
        links = []
        claim_refs = []
        reason = "campaign_link_evidence_invalid"

    if (
        read is None
        or scope_mismatch
        or invalid_link
        or not read.available
        or not read.complete
    ):
        state = "degraded" if read is not None and not scope_mismatch else "unknown"
    elif read.reason == "subject_kind_has_no_exact_campaign_event_join":
        state = "unknown"
    elif links:
        state = "available"
    else:
        state = "empty"

    all_refs = _unique_evidence_refs(
        [ref for _, refs in claim_refs for ref in refs]
    )
    content: dict[str, Any] = {
        "tenantId": tenant_id,
        "subject": {"kind": subject.kind, "id": subject.id},
        "coverage": (
            "exact_tenant_source_event_campaign_touchpoint"
            if subject.kind in {"event", "observation"}
            else "unsupported_subject_kind"
        ),
        "links": links,
        "authorityReadComplete": bool(
            read is not None
            and not scope_mismatch
            and read.available
            and read.complete
        ),
        "reasonCode": reason or (
            "exact_tenant_campaign_touchpoint_links_observed"
            if links
            else "no_exact_tenant_campaign_touchpoint_link"
        ),
        "evidenceRefs": [ref.model_dump(mode="json") for ref in all_refs],
    }
    if read is not None and read.available and not scope_mismatch:
        content["returnedCampaignCount"] = len(links)
    section = ProjectionSection(
        id="campaign_links",
        state=state,
        title="Campaigns linked by exact source-event touchpoints",
        content=content,
        warnings=(
            []
            if links and read is not None and read.complete
            else [reason or "campaign links are unavailable or incomplete"]
        ),
        canonicalAuthorityRefs=(
            ["campaign_touchpoints", "campaign_facts"]
            if subject.kind in {"event", "observation"}
            else []
        ),
    )
    claims = [
        ClaimEnvelope(
            id=f"signals360.campaign_link.{subject.kind}.{subject.id}.{campaign_id}",
            kind="exact_source_event_campaign_touchpoint_link",
            subject=subject,
            evidenceRefs=list(refs),
            claims=[
                f"A tenant-scoped campaign touchpoint for this exact source event resolves to canonical campaign {campaign_id}."
            ],
            claimState=EpistemicStatus.OBSERVED,
            domainSlotIds=["campaign_links"],
        )
        for campaign_id, refs in claim_refs
    ]
    return section, claims


def _quality_section(
    subject: ProjectionSubject,
    *,
    tenant_id: str,
    read: Optional[ObservationQualityRead],
) -> tuple[ProjectionSection, Optional[ClaimEnvelope]]:
    """Expose only gateway-stamped quality from an exact SDK observation."""
    reason: Optional[str] = None
    row: Optional[dict[str, Any]] = None
    if subject.kind not in {"event", "observation"}:
        reason = "exact_event_or_observation_quality_subject_required"
    elif read is None:
        reason = "exact_observation_quality_read_not_requested_or_available"
    elif not read.available:
        reason = read.reason or "sdk_observation_quality_authority_unavailable"
    elif not read.complete:
        reason = read.reason or "sdk_observation_quality_scope_incomplete"
    elif read.record is None:
        reason = read.reason or "exact_sdk_observation_not_found"
    elif (
        not isinstance(read.record, dict)
        or read.record.get("tenant_id") != tenant_id
        or read.record.get("provider_record_id") != subject.id
        or read.record.get("source") != "sdk"
    ):
        reason = "sdk_observation_scope_mismatch"
    else:
        row = read.record

    if row is None:
        state = (
            "degraded"
            if read is not None and (not read.available or not read.complete)
            else "unknown"
        )
        return (
            ProjectionSection(
                id="quality",
                state=state,
                title="Observation ingestion quality",
                content={
                    "tenantId": tenant_id,
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "qualityState": "unknown",
                    "reasonCode": reason or "canonical_observation_quality_unknown",
                },
                warnings=[reason or "canonical observation quality is unknown"],
                canonicalAuthorityRefs=["observations"],
            ),
            None,
        )

    payload = row.get("payload")
    envelope = payload.get("observation_envelope") if isinstance(payload, dict) else None
    observation = envelope.get("observation") if isinstance(envelope, dict) else None
    tenancy = envelope.get("tenancy") if isinstance(envelope, dict) else None
    quality = envelope.get("quality") if isinstance(envelope, dict) else None
    if (
        not isinstance(observation, dict)
        or observation.get("observation_id") != subject.id
        or not isinstance(tenancy, dict)
        or tenancy.get("tenant_id") != tenant_id
    ):
        reason = "canonical_observation_envelope_missing_or_mismatched"
    validation_state = (
        _safe_token(quality.get("validation_state")) if isinstance(quality, dict) else None
    )
    if validation_state != "gateway:accepted":
        reason = reason or "observation_gateway_validation_state_not_stamped"

    if reason is not None:
        return (
            ProjectionSection(
                id="quality",
                state="unknown",
                title="Observation ingestion quality",
                content={
                    "tenantId": tenant_id,
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "qualityState": "unknown",
                    "reasonCode": reason,
                },
                warnings=[reason],
                canonicalAuthorityRefs=["observations"],
            ),
            None,
        )

    # The gateway's accepted disposition is one quality dimension. It does not
    # establish end-to-end source reliability, a freshness SLA, or event meaning.
    quality_values = {
        key: _safe_token(quality.get(key)) if isinstance(quality, dict) else None
        for key in (
            "completeness",
            "freshness",
            "sequencing_state",
        )
    }
    observed_at = _safe_timestamp(observation.get("ingested_at"))
    evidence = EvidenceRef(
        id=subject.id,
        type="event",
        source="bronze_sdk_events",
        observedAt=observed_at,
    )
    section = ProjectionSection(
        id="quality",
        state="degraded",
        title="Observation ingestion quality",
        content={
            "tenantId": tenant_id,
            "subject": {"kind": subject.kind, "id": subject.id},
            "authority": "repositories.lake.BronzeRepository:sdk_events",
            "coverage": "one_exact_sdk_observation",
            "qualityState": "gateway_validation_only",
            "validationState": validation_state,
            "completeness": quality_values["completeness"],
            "freshness": quality_values["freshness"],
            "sequencingState": quality_values["sequencing_state"],
            "sourceReliability": "unknown",
            "eventSemanticQuality": "unknown",
            "freshnessSla": "unknown",
            "evidenceRefs": [evidence.model_dump(mode="json")],
            "reasonCode": "gateway_validation_only_quality",
        },
        warnings=[
            "gateway validation is observed; source reliability, event semantics, and freshness SLA remain unknown"
        ],
        canonicalAuthorityRefs=["observations"],
    )
    claim = ClaimEnvelope(
        id=f"signals360.observation_quality.{subject.id}",
        kind="gateway_observation_validation_record",
        subject=subject,
        evidenceRefs=[evidence],
        claims=[
            "The tenant-scoped SDK observation envelope records gateway:accepted validation; this does not establish source reliability, event semantic quality, or a freshness SLA."
        ],
        confidence=1.0,
        claimState=EpistemicStatus.OBSERVED,
        domainSlotIds=["quality"],
    )
    return section, claim


def _normalization_section(
    subject: ProjectionSubject,
    *,
    tenant_id: str,
    read: Optional[ObservationQualityRead],
) -> tuple[ProjectionSection, Optional[ClaimEnvelope]]:
    """Expose the exact SDK adapter and schema recorded on a Bronze observation.

    The envelope proves that the gateway accepted one normalized event. It
    does not prove semantic correctness, complete source mapping, or producer
    coverage, so the slot remains degraded even with a valid record.
    """
    reason: Optional[str] = None
    row: Optional[dict[str, Any]] = None
    if subject.kind not in {"event", "observation"}:
        reason = "exact_event_or_observation_subject_required"
    elif read is None:
        reason = "exact_observation_normalization_read_unavailable"
    elif not read.available or not read.complete:
        reason = read.reason or "exact_observation_normalization_read_incomplete"
    elif read.record is None:
        reason = read.reason or "exact_sdk_observation_not_found"
    elif (
        read.record.get("tenant_id") != tenant_id
        or read.record.get("provider_record_id") != subject.id
        or read.record.get("source") != "sdk"
    ):
        reason = "sdk_observation_scope_mismatch"
    else:
        row = read.record

    observation: Optional[dict[str, Any]] = None
    provenance: Optional[dict[str, Any]] = None
    temporal: Optional[dict[str, Any]] = None
    if row is not None:
        payload = row.get("payload")
        envelope = payload.get("observation_envelope") if isinstance(payload, dict) else None
        observation = envelope.get("observation") if isinstance(envelope, dict) else None
        tenancy = envelope.get("tenancy") if isinstance(envelope, dict) else None
        source = envelope.get("source") if isinstance(envelope, dict) else None
        provenance = envelope.get("provenance") if isinstance(envelope, dict) else None
        quality = envelope.get("quality") if isinstance(envelope, dict) else None
        temporal = envelope.get("temporal") if isinstance(envelope, dict) else None
        from ingestion.ingestion.generated_registry import CANONICAL_EVENT_TYPES, EVENT_FAMILY
        from ingestion.ingestion.observation_envelope import ENVELOPE_SCHEMA_VERSION

        event_type = (
            _safe_token(observation.get("observation_type"))
            if isinstance(observation, dict)
            else None
        )
        if (
            not isinstance(observation, dict)
            or observation.get("observation_id") != subject.id
            or not isinstance(tenancy, dict)
            or tenancy.get("tenant_id") != tenant_id
            or not isinstance(source, dict)
            or source.get("source_type") != "sdk"
            or not isinstance(provenance, dict)
            or provenance.get("adapter") != "sdk"
            or not _safe_token(provenance.get("adapter_version"))
            or not isinstance(quality, dict)
            or quality.get("validation_state") != "gateway:accepted"
            or observation.get("schema_version") != ENVELOPE_SCHEMA_VERSION
            or event_type not in CANONICAL_EVENT_TYPES
            or payload.get("event_type") != event_type
            or observation.get("family") != EVENT_FAMILY.get(event_type)
        ):
            reason = "canonical_sdk_normalization_lineage_missing_or_mismatched"

    if reason is not None or row is None or observation is None or provenance is None:
        failure = reason or "canonical_observation_normalization_unavailable"
        return (
            ProjectionSection(
                id="normalization",
                state=(
                    "degraded" if read is not None and (not read.available or not read.complete)
                    else "unknown"
                ),
                title="Canonical observation normalization",
                content={
                    "tenantId": tenant_id,
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "normalizationState": "unknown",
                    "reasonCode": failure,
                },
                warnings=[failure],
                canonicalAuthorityRefs=["observations", "source_schema"],
            ),
            None,
        )

    observed_at = _safe_timestamp(observation.get("ingested_at") or row.get("ingested_at"))
    evidence = EvidenceRef(
        id=subject.id,
        type="event",
        source="bronze_sdk_events",
        observedAt=observed_at,
    )
    section = ProjectionSection(
        id="normalization",
        state="degraded",
        title="Canonical observation normalization",
        content={
            "tenantId": tenant_id,
            "subject": {"kind": subject.kind, "id": subject.id},
            "coverage": "one_exact_tenant_scoped_sdk_observation",
            "normalizationState": "gateway_accepted_sdk_adapter_envelope",
            "adapter": "sdk",
            "adapterVersion": _safe_token(provenance.get("adapter_version")),
            "envelopeSchemaVersion": observation.get("schema_version"),
            "eventType": observation.get("observation_type"),
            "eventFamily": observation.get("family"),
            "sourceTemporalQuality": (
                _safe_token(temporal.get("temporal_quality"))
                if isinstance(temporal, dict)
                else None
            ),
            "semanticCorrectness": "unknown",
            "producerCoverage": "unknown",
            "freshnessSla": "unknown",
            "evidenceRefs": [evidence.model_dump(mode="json")],
            "reasonCode": "exact_gateway_normalization_only",
        },
        warnings=[
            "adapter and schema lineage are observed; semantic correctness, producer coverage, and freshness remain unknown"
        ],
        canonicalAuthorityRefs=["observations", "source_schema"],
    )
    claim = ClaimEnvelope(
        id=f"signals360.observation_normalization.{subject.id}",
        kind="sdk_observation_normalization_lineage",
        subject=subject,
        evidenceRefs=[evidence],
        claims=[
            "The exact tenant-scoped SDK observation records a gateway-accepted adapter and envelope schema version."
        ],
        claimState=EpistemicStatus.OBSERVED,
        domainSlotIds=["normalization"],
    )
    return section, claim


def _source_inventory_section(
    subject: ProjectionSubject,
    *,
    tenant_id: str,
    read: Optional[ObservationQualityRead],
    authority_read: Optional[ObservationSourceAuthorityRead],
) -> tuple[ProjectionSection, Optional[ClaimEnvelope]]:
    """Expose one SDK event's source facts and independently traced authority."""
    reason: Optional[str] = None
    row: Optional[dict[str, Any]] = None
    if subject.kind not in {"event", "observation"}:
        reason = "exact_sdk_event_or_observation_subject_required"
    elif read is None:
        reason = "exact_sdk_source_inventory_read_unavailable"
    elif not read.available or not read.complete:
        reason = read.reason or "exact_sdk_source_inventory_read_incomplete"
    elif read.record is None:
        reason = read.reason or "exact_sdk_source_inventory_not_found"
    elif (
        read.record.get("tenant_id") != tenant_id
        or read.record.get("provider_record_id") != subject.id
        or read.record.get("source") != "sdk"
    ):
        reason = "sdk_source_inventory_scope_mismatch"
    else:
        row = read.record

    envelope = None
    if row is not None:
        payload = row.get("payload")
        envelope = payload.get("observation_envelope") if isinstance(payload, dict) else None
        observation = envelope.get("observation") if isinstance(envelope, dict) else None
        tenancy = envelope.get("tenancy") if isinstance(envelope, dict) else None
        if (
            not isinstance(observation, dict)
            or observation.get("observation_id") != subject.id
            or not isinstance(tenancy, dict)
            or tenancy.get("tenant_id") != tenant_id
        ):
            reason = "canonical_observation_envelope_missing_or_mismatched"

    source = envelope.get("source") if isinstance(envelope, dict) else None
    provenance = envelope.get("provenance") if isinstance(envelope, dict) else None
    source_type = _safe_token(source.get("source_type")) if isinstance(source, dict) else None
    source_relationship = (
        _safe_token(source.get("source_relationship")) if isinstance(source, dict) else None
    )
    ingress_path = _safe_path(source.get("ingress_path")) if isinstance(source, dict) else None
    adapter = _safe_token(provenance.get("adapter")) if isinstance(provenance, dict) else None
    adapter_version = (
        _safe_token(provenance.get("adapter_version")) if isinstance(provenance, dict) else None
    )
    if not all((source_type, source_relationship, ingress_path, adapter, adapter_version)):
        reason = reason or "canonical_observation_source_provenance_incomplete"

    if row is None or reason is not None:
        return (
            ProjectionSection(
                id="source_inventory",
                state="unknown",
                title="Exact observation source inventory",
                content={
                    "tenantId": tenant_id,
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "coverage": "unknown",
                    "sourceReliability": "unknown",
                    "reasonCode": reason or "canonical_observation_source_inventory_unknown",
                },
                warnings=[reason or "canonical observation source inventory is unknown"],
                canonicalAuthorityRefs=["observations", "source_provenance"],
            ),
            None,
        )

    observation = envelope["observation"]
    observed_at = _safe_timestamp(observation.get("ingested_at"))
    evidence = EvidenceRef(
        id=subject.id,
        type="event",
        source="bronze_sdk_events",
        observedAt=observed_at,
    )
    authority_reason = "canonical_source_authority_reader_unavailable"
    authority: dict[str, Any] = {"state": "unknown"}
    authority_evidence: list[EvidenceRef] = []
    if authority_read is not None:
        if (
            authority_read.tenant_id != tenant_id
            or authority_read.observation_id != subject.id
        ):
            authority_reason = "observation_source_authority_scope_mismatch"
        elif authority_read.available and authority_read.complete and authority_read.trace is not None:
            trace = authority_read.trace
            if (
                _safe_identifier(getattr(trace, "source_id", None))
                and _safe_identifier(getattr(trace, "rights_decision_ref", None))
                and _safe_identifier(getattr(trace, "source_grant_ref", None))
                and _safe_identifier(getattr(trace, "provider_identity", None))
                and getattr(trace, "tenant_id", None) == tenant_id
            ):
                authority_evidence = [
                    EvidenceRef(
                        id=trace.rights_decision_ref,
                        type="document",
                        source="rights_decisions",
                    ),
                    EvidenceRef(
                        id=trace.source_grant_ref,
                        type="document",
                        source="data_rights_grants",
                    ),
                ]
                authority = {
                    "state": "available",
                    "sourceId": trace.source_id,
                    "sourceRelationship": _safe_token(trace.source_relationship),
                    "providerIdentity": trace.provider_identity,
                    "rightsSourceClass": _safe_token(trace.rights_source_class),
                    "lineageRecordPresent": authority_read.lineage_recorded,
                    "evidenceRefs": [
                        ref.model_dump(mode="json") for ref in authority_evidence
                    ],
                }
                authority_reason = "exact_source_authority_traced_inventory_unknown"
            else:
                authority_reason = "observation_source_authority_trace_invalid"
        else:
            authority_reason = (
                _safe_reason_code(authority_read.reason)
                or "canonical_source_authority_unavailable"
            )
            if not authority_read.available:
                authority["state"] = "degraded"
    authority["reasonCode"] = authority_reason
    item = {
        "observationId": subject.id,
        "sourceType": source_type,
        "sourceRelationship": source_relationship,
        "ingressPath": ingress_path,
        "adapter": adapter,
        "adapterVersion": adapter_version,
        "observedAt": observed_at,
        "sourceAuthority": authority,
        "evidenceRefs": [evidence.model_dump(mode="json")],
    }
    evidence_refs = [evidence, *authority_evidence]
    section = ProjectionSection(
        id="source_inventory",
        state="available",
        title="Exact observation source inventory",
        content={
            "tenantId": tenant_id,
            "subject": {"kind": subject.kind, "id": subject.id},
            "coverage": "one_exact_sdk_observation",
            "sources": [item],
            "sourceReliability": "unknown",
            "inventoryCompleteness": "unknown",
            "reasonCode": "single_event_source_seen_no_inventory_completeness_or_reliability",
            "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence_refs],
        },
        warnings=[
            "one exact SDK observation is described; fleet inventory and source reliability remain unknown",
            authority_reason,
        ],
        canonicalAuthorityRefs=["observations", "source_provenance"],
    )
    claim = ClaimEnvelope(
        id=f"signals360.source_inventory.{subject.id}",
        kind="authenticated_observation_source_metadata",
        subject=subject,
        evidenceRefs=evidence_refs,
        claims=[
            "The exact tenant SDK observation records authenticated source and adapter metadata."
            + (
                " Its recorded rights reference resolves to the same tenant's source grant."
                if authority["state"] == "available"
                else " Canonical source authority remains unverified."
            )
            + " Source reliability and fleet inventory completeness remain unknown."
        ],
        confidence=1.0,
        claimState=EpistemicStatus.OBSERVED,
        domainSlotIds=["source_inventory"],
    )
    return section, claim


def _freshness_section(
    subject: ProjectionSubject,
    *,
    tenant_id: str,
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    available: bool,
    complete: bool,
    reason: Optional[str],
) -> ProjectionSection:
    observed = [
        {
            "signalId": _safe_identifier(row.get("signal_id")),
            "lastDetected": _safe_timestamp(row.get("last_detected")),
            "translatorStaleFlag": row.get("is_stale")
            if isinstance(row.get("is_stale"), bool)
            else None,
        }
        for row in rows
        if _safe_identifier(row.get("signal_id"))
    ]
    state = "degraded" if available and observed else "unknown"
    return ProjectionSection(
        id="freshness",
        state=state,
        title="Signal freshness",
        content={
            "tenantId": tenant_id,
            "subject": {"kind": subject.kind, "id": subject.id},
            "derivedSignalTimestamps": observed,
            "sourceFreshnessState": "unknown",
            "freshnessThresholdSeconds": None,
            "readComplete": complete,
            "reasonCode": (
                "translator_stale_flag_is_not_a_canonical_source_freshness_sla"
                if observed
                else reason or "canonical_signal_freshness_not_available"
            ),
        },
        warnings=(
            [
                "only translator timestamps and local stale flags are available; canonical freshness is unknown"
            ]
            if observed
            else [reason or "canonical signal freshness is unknown"]
        ),
        canonicalAuthorityRefs=["behavioral_signals"],
    )


def _evidence_trace_section(
    subject: ProjectionSubject,
    *,
    tenant_id: str,
    refs: list[EvidenceRef],
    available: bool,
    complete: bool,
    reason: Optional[str],
) -> ProjectionSection:
    state = "degraded" if available and refs else "unknown"
    return ProjectionSection(
        id="evidence_trace",
        state=state,
        title="Signal evidence trace",
        content={
            "tenantId": tenant_id,
            "subject": {"kind": subject.kind, "id": subject.id},
            "storedSignalRecordRefs": [ref.model_dump(mode="json") for ref in refs],
            "sourceEventEvidenceState": "unknown",
            "readComplete": complete,
            "reasonCode": (
                "signal_source_event_lineage_not_joined"
                if refs
                else reason or "signal_evidence_trace_not_available"
            ),
        },
        warnings=(
            [
                "stored signal records are referenced, but translator evidence strings are not typed source EvidenceRefs"
            ]
            if refs
            else [reason or "canonical signal evidence trace is unknown"]
        ),
        canonicalAuthorityRefs=["behavioral_signals"],
    )


def _scoped_rows(
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    tenant_id: str,
    entity_id: Optional[str],
) -> tuple[list[dict[str, Any]], bool]:
    scoped: list[dict[str, Any]] = []
    scope_mismatch = False
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or (entity_id is not None and row.get("entity_id") != entity_id)
            or not _safe_identifier(row.get("signal_id"))
        ):
            scope_mismatch = True
            continue
        scoped.append(row)
    return scoped[:_MAX_SIGNAL_RECORDS], scope_mismatch


def _public_signal(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "signalId": _safe_identifier(row.get("signal_id")),
        "signalType": _safe_token(row.get("signal_type")),
        "family": _safe_token(row.get("family")),
        "severity": _safe_token(
            row.get("severity"), allowed={"critical", "high", "medium", "low", "info"}
        ),
        "sentiment": _safe_token(
            row.get("sentiment"), allowed={"positive", "caution", "negative", "informational"}
        ),
        "confidence": _confidence(row.get("confidence")),
        "lastDetected": _safe_timestamp(row.get("last_detected")),
        "translatorStaleFlag": row.get("is_stale")
        if isinstance(row.get("is_stale"), bool)
        else None,
        "signalKind": "translator_derived_behavioral_signal",
    }


def _record_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    signal_id = _safe_identifier(row.get("signal_id"))
    if signal_id is None:
        return None
    return EvidenceRef(
        id=signal_id,
        type="model_output",
        source="behavioral_signals",
        observedAt=_safe_timestamp(row.get("last_detected") or row.get("created_at")),
        confidence=_confidence(row.get("confidence")),
    )


def _unique_evidence_refs(
    refs: tuple[EvidenceRef, ...] | list[EvidenceRef],
) -> tuple[EvidenceRef, ...]:
    unique: list[EvidenceRef] = []
    seen: set[tuple[str, str, str, Optional[str]]] = set()
    for ref in refs:
        key = (ref.source, ref.id, ref.type, ref.observedAt)
        if key not in seen:
            seen.add(key)
            unique.append(ref)
    return tuple(unique)


def _count_values(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record.get(field)
        if isinstance(value, str):
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _safe_identifier(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in text):
        return None
    return text


def _safe_token(value: Any, *, allowed: Optional[set[str]] = None) -> Optional[str]:
    token = _safe_identifier(value)
    if token is None or len(token) > 128:
        return None
    if any(not (char.isalnum() or char in "._:-") for char in token):
        return None
    return token if allowed is None or token in allowed else None


def _safe_path(value: Any) -> Optional[str]:
    path = _safe_identifier(value)
    if path is None or len(path) > 256 or not path.startswith("/"):
        return None
    if any(not (char.isalnum() or char in "._:/-") for char in path):
        return None
    return path


def _safe_reason(value: Any) -> Optional[str]:
    return _safe_token(value)


def _safe_reason_code(value: Any) -> Optional[str]:
    token = _safe_identifier(value)
    if token is None or len(token) > 128:
        return None
    return token if all(char.isalnum() or char in "._:-_" for char in token) else None


def _confidence(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 1 else None


def _safe_timestamp(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_provider(registry: ProviderRegistry) -> None:
    """Register the Signals360 provider when its generated id is available."""
    registry.register(
        Signals360Provider(),
        source="services/api/intelligence/signals/signals360_provider",
    )


__all__ = [
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "RiskFlagsRead",
    "RepositorySignal360Source",
    "Signals360Provider",
    "Signal360Source",
    "SignalSummaryRead",
    "register_provider",
]
