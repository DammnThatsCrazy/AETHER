"""Exact canonical cross-authority joins for Geographic360 required slots.

This adapter follows only persisted identity links: exact source-observation IDs
for campaign touchpoints, journey event lists, and evidence-bearing risk/value
records; exact tenant + entity identity for profile context. It does not join on
place labels, coordinates, geohashes, amounts, names, or timestamp proximity.

These authorities do not provide a coordinated bitemporal snapshot or a shared
location-specific freshness/policy disposition. Historical reads therefore
remain unknown, and current records are labelled as subject/source context with
freshness unknown until the owning policy/freshness layer evaluates them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
import math
from typing import Any, Optional, Protocol
from urllib.parse import quote
from uuid import UUID

from graph.operational_intelligence.models import EvidenceRef
from shared.intelligence_projections.contracts import ProjectionSubject

RELATED_LOCATION_READ_CAP = 100

_POLICY_BOUNDARY = {
    "state": "not_evaluated_by_projection_provider",
    "reasonCode": "policy_disposition_is_owned_by_frame_runtime",
}


class GeographicRelatedAuthorityReader(Protocol):
    async def related_slots(
        self,
        *,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        source_observation_id: Optional[str],
        as_of: Optional[datetime],
    ) -> dict[str, dict[str, Any]]: ...


def _slot(
    *,
    state: str,
    reason: str,
    content: Optional[dict[str, Any]] = None,
    evidence: tuple[EvidenceRef, ...] | list[EvidenceRef] = (),
    authorities: tuple[str, ...] | list[str] = (),
    latest_observed_at: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "reasonCode": reason,
        "content": content,
        "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence],
        "freshness": {
            "state": "unknown",
            "reasonCode": "source_freshness_threshold_not_configured",
            "latestObservedAt": latest_observed_at,
            "maximumAgeConfigured": False,
        },
        "policy": dict(_POLICY_BOUNDARY),
        "canonicalAuthorities": list(authorities),
    }


def _unknown(slot_id: str, reason: str) -> dict[str, Any]:
    return _slot(
        state="unknown",
        reason=reason,
        authorities=(slot_id,),
    )


def _as_mapping(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def _as_list(value: Any) -> Optional[list[Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, list) else None
    return None


def _as_utc_text(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc).isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _safe_amount(value: Any) -> Optional[str | int | float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return format(value, "f") if value.is_finite() else None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:128]
    return None


def _source_event_ref(event_id: str, observed_at: Optional[str]) -> EvidenceRef:
    return EvidenceRef(
        id=event_id,
        type="event",
        source="canonical_location_source_observation",
        observedAt=observed_at,
        uri=f"store://source_observations/{quote(event_id, safe='')}",
    )


def _touchpoint_ref(row: dict[str, Any]) -> Optional[EvidenceRef]:
    touchpoint_id = row.get("touchpoint_id")
    if not isinstance(touchpoint_id, (str, UUID)) or not str(touchpoint_id).strip():
        return None
    occurred = _as_utc_text(row.get("occurred_at")) or _as_utc_text(row.get("received_at"))
    return EvidenceRef(
        id=str(touchpoint_id),
        type="event",
        source="services/api/journeys/measurement/repositories/touchpoint_repo.py:silver_campaign_touchpoint_facts",
        observedAt=occurred,
        uri=f"store://silver_campaign_touchpoint_facts/{quote(str(touchpoint_id), safe='')}",
    )


def _journey_ref(row: dict[str, Any]) -> Optional[EvidenceRef]:
    version_id = row.get("journey_version_id")
    journey_id = row.get("journey_id")
    if not isinstance(version_id, (str, UUID)) or not str(version_id).strip():
        return None
    observed = _as_utc_text(row.get("computed_at"))
    return EvidenceRef(
        id=str(version_id),
        type="model_output",
        source="services/api/journeys/measurement/repositories/journey_repo.py:journey_versions",
        observedAt=observed,
        uri=f"store://journey_versions/{quote(str(journey_id or version_id), safe='')}/versions/{quote(str(version_id), safe='')}",
    )


def _record_evidence_refs(record: dict[str, Any]) -> list[EvidenceRef]:
    refs = _as_list(record.get("evidence_refs")) or []
    parsed: list[EvidenceRef] = []
    for raw in refs:
        try:
            if isinstance(raw, EvidenceRef):
                parsed.append(raw)
            elif isinstance(raw, dict):
                parsed.append(EvidenceRef.model_validate(raw))
        except Exception:  # malformed evidence is never promoted
            continue
    return parsed


def _exact_event_refs(record: dict[str, Any], source_observation_id: str) -> list[EvidenceRef]:
    return [
        ref
        for ref in _record_evidence_refs(record)
        if ref.id == source_observation_id and ref.type == "event"
    ]


class RepositoryGeographicRelatedAuthorityReader:
    """Read bounded, exact links from the campaign, journey, identity, risk and value owners."""

    async def related_slots(
        self,
        *,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        source_observation_id: Optional[str],
        as_of: Optional[datetime],
    ) -> dict[str, dict[str, Any]]:
        if not tenant_id or not subject_kind or not subject_id:
            return {
                slot_id: _unknown(slot_id, "location_related_subject_scope_invalid")
                for slot_id in ("campaigns", "journeys", "profiles", "risk", "value")
            }
        if as_of is not None:
            return {
                "campaigns": _unknown("campaign_touchpoints", "campaign_touchpoints_not_bitemporal"),
                "journeys": _unknown("journey_versions", "journey_versions_not_bitemporal"),
                "profiles": _unknown("identity_profiles", "identity_profiles_not_bitemporal"),
                "risk": _unknown("risk_signals", "risk_signals_not_bitemporal"),
                "value": _unknown("economic_facts", "economic_facts_not_bitemporal"),
            }

        event_id = source_observation_id.strip() if isinstance(source_observation_id, str) else ""
        return {
            "campaigns": await self._campaigns(tenant_id, event_id),
            "journeys": await self._journeys(tenant_id, subject_kind, subject_id, event_id),
            "profiles": await self._profile(tenant_id, subject_kind, subject_id),
            "risk": await self._risk(tenant_id, subject_kind, subject_id, event_id),
            "value": await self._value(tenant_id, subject_kind, subject_id, event_id),
        }

    async def _campaigns(self, tenant_id: str, event_id: str) -> dict[str, Any]:
        if not event_id:
            return _unknown("campaign_touchpoints", "location_source_observation_unavailable")
        try:
            from journeys.measurement.repositories.touchpoint_repo import TouchpointRepository

            rows = await TouchpointRepository().list_by_source_event(
                tenant_id, event_id, limit=RELATED_LOCATION_READ_CAP + 1
            )
        except Exception:
            return _unknown("campaign_touchpoints", "campaign_touchpoint_authority_unavailable")
        if not isinstance(rows, list):
            return _unknown("campaign_touchpoints", "campaign_touchpoint_read_invalid")
        if any(
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("source_event_id") != event_id
            for row in rows
        ):
            return _unknown("campaign_touchpoints", "campaign_touchpoint_scope_mismatch")
        source_truncated = len(rows) > RELATED_LOCATION_READ_CAP
        rows = [row for row in rows if row.get("privacy_class") != "deleted"]
        truncated = source_truncated or len(rows) > RELATED_LOCATION_READ_CAP
        listed = rows[:RELATED_LOCATION_READ_CAP]
        evidence: dict[str, EvidenceRef] = {}
        touches: list[dict[str, Any]] = []
        invalid = False
        for row in listed:
            campaign_id = row.get("campaign_id")
            touchpoint_id = row.get("touchpoint_id")
            if not isinstance(campaign_id, (str, UUID)) or not str(campaign_id).strip():
                invalid = True
                continue
            ref = _touchpoint_ref(row)
            if ref is None:
                invalid = True
                continue
            evidence[ref.id] = ref
            touches.append(
                {
                    "campaignId": str(campaign_id),
                    "touchpointId": str(touchpoint_id),
                    "sourceEventId": event_id,
                    "occurredAt": _as_utc_text(row.get("occurred_at")),
                    "channel": row.get("channel") if isinstance(row.get("channel"), str) else None,
                }
            )
        if invalid:
            return _unknown("campaign_touchpoints", "campaign_touchpoint_record_invalid")
        if not touches:
            return _unknown("campaign_touchpoints", "no_campaign_touchpoint_for_exact_location_observation")
        source_ref = _source_event_ref(
            event_id,
            max((ref.observedAt or "" for ref in evidence.values()), default=None) or None,
        )
        evidence[source_ref.id] = source_ref
        return _slot(
            state="degraded",
            reason=("campaign_touchpoint_read_truncated" if truncated else "campaign_touchpoint_freshness_unconfigured"),
            content={
                "joinBasis": "tenant_scoped_touchpoint.source_event_id_equals_location.source_observation_id",
                "locationSpecific": True,
                "sourceEventId": event_id,
                "records": touches,
                "truncated": truncated,
            },
            evidence=list(evidence.values()),
            authorities=("silver_campaign_touchpoint_facts", "campaigns"),
            latest_observed_at=max((ref.observedAt or "" for ref in evidence.values()), default=None) or None,
        )

    async def _journeys(
        self, tenant_id: str, subject_kind: str, subject_id: str, event_id: str
    ) -> dict[str, Any]:
        if subject_kind != "entity":
            return _unknown("journey_versions", "journey_profile_subject_kind_unsupported")
        if not event_id:
            return _unknown("journey_versions", "location_source_observation_unavailable")
        try:
            from journeys.measurement.repositories.journey_repo import JourneyRepository

            rows = await JourneyRepository().find_current_for_profile(
                tenant_id,
                subject_id,
                identity_type="profile",
                limit=RELATED_LOCATION_READ_CAP + 1,
            )
        except Exception:
            return _unknown("journey_versions", "journey_authority_unavailable")
        if not isinstance(rows, list):
            return _unknown("journey_versions", "journey_read_invalid")
        if any(
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or str(row.get("profile_id") or "") != subject_id
            or row.get("is_current") is not True
            for row in rows
        ):
            return _unknown("journey_versions", "journey_subject_scope_mismatch")
        truncated = len(rows) > RELATED_LOCATION_READ_CAP
        linked: list[dict[str, Any]] = []
        evidence: dict[str, EvidenceRef] = {}
        invalid = False
        for row in rows[:RELATED_LOCATION_READ_CAP]:
            event_ids = _as_list(row.get("event_ids"))
            if event_ids is None:
                invalid = True
                continue
            if event_id not in event_ids:
                continue
            ref = _journey_ref(row)
            if ref is None:
                invalid = True
                continue
            evidence[ref.id] = ref
            linked.append(
                {
                    "journeyId": str(row.get("journey_id")),
                    "journeyVersionId": str(row.get("journey_version_id")),
                    "matchedEventId": event_id,
                    "journeyType": row.get("journey_type") if isinstance(row.get("journey_type"), str) else None,
                    "journeyState": row.get("journey_state") if isinstance(row.get("journey_state"), str) else None,
                    "computedAt": ref.observedAt,
                }
            )
        if invalid:
            return _unknown("journey_versions", "journey_event_reference_invalid")
        if not linked:
            if truncated:
                return _unknown("journey_versions", "journey_read_truncated")
            return _unknown("journey_versions", "no_journey_contains_exact_location_observation")
        source_ref = _source_event_ref(event_id, None)
        evidence[source_ref.id] = source_ref
        return _slot(
            state="degraded",
            reason=("journey_read_truncated" if truncated else "journey_freshness_unconfigured"),
            content={
                "joinBasis": "tenant_scoped_current_journey.event_ids_contains_location.source_observation_id",
                "locationSpecific": True,
                "matchedEventId": event_id,
                "records": linked,
                "truncated": truncated,
            },
            evidence=list(evidence.values()),
            authorities=("journey_versions",),
            latest_observed_at=max((ref.observedAt or "" for ref in evidence.values()), default=None) or None,
        )

    async def _profile(self, tenant_id: str, subject_kind: str, subject_id: str) -> dict[str, Any]:
        if subject_kind != "entity":
            return _unknown("identity_profiles", "profile_entity_subject_kind_unsupported")
        try:
            from identity.profile.profile360_provider import RepositoryProfile360Source

            source = RepositoryProfile360Source()
            subject = ProjectionSubject(kind="entity", id=subject_id)
            entity_read = await source.canonical_entity(tenant_id, subject)
            profile_read = await source.identity_record(tenant_id, subject)
        except Exception:
            return _unknown("identity_profiles", "profile_authority_unavailable")
        if not entity_read.available or not profile_read.available:
            return _unknown("identity_profiles", "profile_authority_unavailable")
        if not entity_read.scope_known or not profile_read.scope_known:
            return _unknown(
                "identity_profiles",
                profile_read.reason or entity_read.reason or "canonical_profile_not_resolved",
            )
        entity = entity_read.record or {}
        profile = profile_read.record or {}
        if (
            entity.get("tenant_id") != tenant_id
            or str(entity.get("entity_id") or "") != subject_id
            or profile.get("tenant_id") != tenant_id
            or str(profile.get("user_id") or "") != subject_id
        ):
            return _unknown("identity_profiles", "canonical_profile_scope_mismatch")
        observed = _as_utc_text(profile.get("updated_at")) or _as_utc_text(profile.get("created_at"))
        ref = EvidenceRef(
            id=subject_id,
            type="entity",
            source="repositories.repos.IdentityRepository.get_profile",
            observedAt=observed,
            uri=f"store://identity_profiles/{quote(subject_id, safe='')}",
        )
        return _slot(
            state="degraded",
            reason="profile_scope_is_subject_identity_not_place_membership",
            content={
                "joinBasis": "location_facts.subject_type_and_subject_id_equals_canonical_entity",
                "locationSpecific": False,
                "entityId": subject_id,
                "profileRecordAvailable": True,
                "profileUpdatedAt": observed,
            },
            evidence=[ref],
            authorities=("entities", "identity_profiles"),
            latest_observed_at=observed,
        )

    async def _risk(
        self, tenant_id: str, subject_kind: str, subject_id: str, event_id: str
    ) -> dict[str, Any]:
        if not event_id:
            return _unknown("risk_signals", "location_source_observation_unavailable")
        try:
            from intelligence.risk360.store import RiskSignalRepository

            rows = await RiskSignalRepository().list_by_subject(
                tenant_id,
                subject_kind,
                subject_id,
                limit=RELATED_LOCATION_READ_CAP + 1,
            )
        except Exception:
            return _unknown("risk_signals", "risk_signal_authority_unavailable")
        if not isinstance(rows, list):
            return _unknown("risk_signals", "risk_signal_read_invalid")
        if any(
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("subject_kind") != subject_kind
            or str(row.get("subject_id") or "") != subject_id
            for row in rows
        ):
            return _unknown("risk_signals", "risk_signal_subject_scope_mismatch")
        truncated = len(rows) > RELATED_LOCATION_READ_CAP
        linked: list[dict[str, Any]] = []
        evidence: dict[tuple[str, str], EvidenceRef] = {}
        for row in rows[:RELATED_LOCATION_READ_CAP]:
            refs = _exact_event_refs(row, event_id)
            if not refs:
                continue
            signal_id = row.get("signal_id")
            dimension = row.get("risk_dimension")
            source = row.get("source")
            if not all(isinstance(v, str) and v.strip() for v in (signal_id, dimension, source)):
                return _unknown("risk_signals", "risk_signal_record_invalid")
            for ref in refs:
                evidence[(ref.id, ref.source)] = ref
            linked.append(
                {
                    "signalId": signal_id,
                    "riskDimension": dimension,
                    "claimState": str(row.get("claim_state") or "unknown"),
                    "source": source,
                    "observedAt": _as_utc_text(row.get("observed_at")),
                    "matchedEvidenceIds": [ref.id for ref in refs],
                }
            )
        if not linked:
            if truncated:
                return _unknown("risk_signals", "risk_signal_read_truncated")
            return _unknown("risk_signals", "no_risk_signal_cites_exact_location_observation")
        source_ref = _source_event_ref(event_id, None)
        evidence[(source_ref.id, source_ref.source)] = source_ref
        return _slot(
            state="degraded",
            reason=("risk_signal_read_truncated" if truncated else "risk_freshness_or_policy_unresolved"),
            content={
                "joinBasis": "tenant_scoped_risk_signal.evidence_refs_contains_exact_location.source_observation_id",
                "locationSpecific": True,
                "subject": {"kind": subject_kind, "id": subject_id},
                "matchedEventId": event_id,
                "signals": linked,
                "truncated": truncated,
            },
            evidence=list(evidence.values()),
            authorities=("risk_signals",),
            latest_observed_at=max((item["observedAt"] or "" for item in linked), default=None) or None,
        )

    async def _value(
        self, tenant_id: str, subject_kind: str, subject_id: str, event_id: str
    ) -> dict[str, Any]:
        if not event_id:
            return _unknown("economic_facts", "location_source_observation_unavailable")
        if subject_kind not in {"agent", "campaign", "entity"}:
            return _unknown("economic_facts", "economic_subject_kind_unsupported")
        try:
            from value.economic.economic360_provider import RepositoryEconomicSourceReader

            records = await RepositoryEconomicSourceReader().records(
                tenant_id=tenant_id,
                subject=ProjectionSubject(kind=subject_kind, id=subject_id),
            )
        except Exception:
            return _unknown("economic_facts", "economic_fact_authority_unavailable")
        if not isinstance(records, list):
            return _unknown("economic_facts", "economic_fact_read_invalid")
        if any(not isinstance(row, dict) or row.get("tenant_id") != tenant_id for row in records):
            return _unknown("economic_facts", "economic_fact_tenant_scope_mismatch")
        linked: list[dict[str, Any]] = []
        evidence: dict[tuple[str, str], EvidenceRef] = {}
        incomplete_reasons: list[str] = []
        source_truncated = False
        for row in records:
            incomplete_reason = row.get("_source_incomplete_reason")
            if isinstance(incomplete_reason, str) and incomplete_reason:
                incomplete_reasons.append(incomplete_reason)
                continue
            source_truncated = source_truncated or row.get("_source_truncated") is True
            if (
                row.get("_evidence_id") != event_id
                or row.get("_evidence_type") != "event"
            ):
                continue
            ref = EvidenceRef(
                id=event_id,
                type="event",
                source=str(row.get("_evidence_source") or "services/api/value/economic"),
                observedAt=_as_utc_text(row.get("_observed_at")),
                uri=(str(row.get("_evidence_uri")) if isinstance(row.get("_evidence_uri"), str) else None),
            )
            evidence[(ref.id, ref.source)] = ref
            linked.append(
                {
                    "source": row.get("_source"),
                    "metric": row.get("_metric_name"),
                    "amount": _safe_amount(row.get("amount")),
                    "currency": row.get("currency"),
                    "evidenceId": event_id,
                    "observedAt": ref.observedAt,
                }
            )
        if not linked:
            if incomplete_reasons:
                return _unknown("economic_facts", "economic_fact_source_incomplete")
            if source_truncated:
                return _unknown("economic_facts", "economic_fact_source_truncated")
            return _unknown("economic_facts", "no_economic_fact_cites_exact_location_observation")
        source_ref = _source_event_ref(event_id, None)
        evidence[(source_ref.id, source_ref.source)] = source_ref
        return _slot(
            state="degraded",
            reason=(
                "economic_fact_source_incomplete"
                if incomplete_reasons
                else "economic_fact_source_truncated"
                if source_truncated
                else "economic_source_freshness_or_policy_unresolved"
            ),
            content={
                "joinBasis": "tenant_scoped_subject_economic_fact.evidence_id_equals_location.source_observation_id",
                "locationSpecific": True,
                "subject": {"kind": subject_kind, "id": subject_id},
                "matchedEventId": event_id,
                "records": linked,
                "amountsRemainInSourceCurrency": True,
                "completeness": "partial" if incomplete_reasons or source_truncated else "unknown",
                "sourceIncompleteReasons": sorted(set(incomplete_reasons)),
                "truncated": source_truncated,
            },
            evidence=list(evidence.values()),
            authorities=("economic_facts",),
            latest_observed_at=max((ref.observedAt or "" for ref in evidence.values()), default=None) or None,
        )


__all__ = [
    "GeographicRelatedAuthorityReader",
    "RELATED_LOCATION_READ_CAP",
    "RepositoryGeographicRelatedAuthorityReader",
]
