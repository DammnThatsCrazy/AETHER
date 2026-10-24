"""Communication360 intelligence-projection provider (Phase 4).

``communication360`` is an intelligence projection over canonical Aether
communication truth — never a competing system of record (ADR-010). This
provider projects the *communication + information-flow* domain for a subject
of kind ``campaign`` / ``episode`` / ``source`` / ``entity`` from the Phase-2/3
canonical surface: the shipped message spine (``services/api/journeys/comms``
silver path, read through :class:`SilverCommsSource`) and the Phase-3
canonical-authority fact store (``services/api/journeys/communication360``
:class:`CanonicalFactSource`). Entity scope requires an exact tenant-owned
entity-registry match and a matching endpoint identity-binding record; it does
not expand through organization membership.

The provider is a read-only, fail-isolated, tenant-scoped projection:

* It NEVER crashes and NEVER fabricates. An unavailable backing source DEGRADES
  its section (typed ``degraded`` / ``missing`` / ``not_applicable`` states)
  with a typed short-string code in ``result.degradedReasons`` and NO numeric
  invented in its place. A section whose source is genuinely reachable but
  empty renders a REAL zero (an available empty subject) — a distinct state
  from an unavailable pool.
* Every claim is a :class:`ClaimEnvelope` with id/kind/subject/evidenceRefs/
  claims/claimState + confidence. Message/transport facts are capped at
  ``EpistemicStatus.OBSERVED`` (never ``verified``); delivery never grants
  knowledge (R4), and the result NEVER raises any exception class outside the
  :class:`ProjectionError` hierarchy.
* The six sections render in the registry's declared output order — summary,
  state, timeline, evidence, interactions, outcomes. ``state`` carries the six
  communication dimensions (delivery, engagement, campaign-context,
  information, knowledge, authority); a dimension that is ``missing`` /
  ``not_applicable`` never renders a fabricated zero.
* ``dependencyState`` echoes the registry-computed context verbatim
  (``profile360`` / ``relationship360`` / ``episode360`` / ``outcome360`` are
  in_flight siblings). Sibling-induced degradation (episode binding,
  outcome links) lives on the section content / reasons — mirroring the
  Economic360 fail-isolation pattern — NOT in ``result.degradedReasons``.
* A ``campaign`` subject binds ``subject.id`` as the message-spine
  ``campaign_id``. ``episode`` / ``source`` subjects have no Phase-4 message
  binding, so their message-spine sections degrade with an honest note
  (episode binding is an episode360 sibling) rather than erroring.

Imports stay light and side-effect free: importing this module never opens a
database connection, never registers on the global registry, and never imports
a provider library. Registration is an explicit wiring seam —
``register_provider(registry)`` — that only the central runtime wiring calls.

Section content schema (stable for central integration):
----------------------------------------------
``summary``   ``{scope, counts | None, reasons}`` — counts is a real, fully
              enumerated zero when the reachable spine is empty.
``state``     ``{dimensions: [{dimension, state, observed | None, breakdown |
              None, reason | None}]}`` over delivery / engagement /
              campaign-context / information / knowledge / authority.
``timeline``  ``{order, orderLabeled, causalRelationsDeclared,
              causalNote, entryCount, entries}`` — ordering by occurred_at is a
              display sort, NEVER a causal claim; causality would require
              declared lineage fields (none exist in Phase 4).
``evidence``  ``{count, evidence}`` — the reused EvidenceRefs grounding the
              sequence, deduped by id.
``interactions`` ``{count, interactions}`` — exact subject-bound canonical
              communication records, including threads/conversations,
              participants, requests/commitments, knowledge, authority, and
              provider capability/quality metadata. Message or interpretation
              body text is not exposed.
``outcomes``  ``{outcomeLinks | None, dependencies, reason}`` — degraded until
              the outcome360 slice (and its links) lands; never a redefinition
              of Outcome.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol, Union
from urllib.parse import quote
from uuid import UUID

# Lightweight plane imports — always importable.
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import ProjectionError
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    PRODUCT_360_SURFACE_DEFINITIONS,
)
from shared.intelligence_projections.registry import ProviderRegistry

# Reused canonical primitives (never redefined here).
from journeys.communication360.contracts import CommunicationMessage
from journeys.communication360.reader import (
    CommunicationSource,
    default_sources,
)
from graph.operational_intelligence.models import EvidenceRef
from identity.identity.source_subject_scope import (
    RepositorySourceSubjectScopeReader,
    SourceSubjectScopeRead,
    SourceSubjectScopeReader,
)
from intelligence.risk360.contracts import RiskSignal
from shared.contracts_models.epistemic import EpistemicStatus

# Sections the registry declares for communication360 (JSON output order —
# summary, state, timeline, evidence, interactions, outcomes).
OUTPUT_SECTIONS: tuple[str, ...] = (
    "summary",
    "state",
    "timeline",
    "evidence",
    "interactions",
    "outcomes",
)

# Subject kinds communication360 serves (registry subjectKinds).
_SCOPED_SUBJECT_KINDS: frozenset[str] = frozenset(
    {"agent", "campaign", "entity", "episode", "journey", "source"}
)

# Typed degraded-reason codes surfaced on ``result.degradedReasons`` (short
# strings only — NEVER an exception body / secret detail). Provider-side only:
# sibling-dependency degradation is section-level, mirroring Economic360.
REASON_SILVER_SOURCE_UNAVAILABLE = "silver_source_unavailable"
REASON_CANONICAL_SOURCE_UNAVAILABLE = "canonical_source_unavailable"
REASON_SOURCE_READ_TRUNCATED = "communication_source_read_truncated"
_DEFAULT_READ_LIMIT = 100
_MAX_READ_LIMIT = 500
_MAX_JOURNEY_LINK_READS = 50
_MAX_RISK_SIGNAL_READS = 100
_MAX_RECIPIENT_RISK_IDENTITY_READS = 50
_MAX_CONSENT_POLICY_READS = 100
_MAX_PROFILE_LINK_READS = 50

# Section-level limitation note for subjects without a message-spine join.
_SCOPE_NOTES: dict[str, str] = {
    "episode": (
        "messages have no canonical episode join; exact episode_id communication facts remain readable"
    ),
    "journey": (
        "messages have no canonical journey join; exact journey_id communication facts remain readable"
    ),
    "source": (
        "messages have no canonical source join; exact source reference communication facts remain readable"
    ),
}

_ENTITY_BINDING_EVIDENCE_URIS = {
    "agent_deployment_identity_bindings": "store://agent_identity_bindings/",
    "comms_provider_identities": "store://comms_provider_identities/",
}
_ENTITY_REFERENCE_KEYS = frozenset(
    {
        "entity_id",
        "entity_ids",
        "actor_id",
        "actor_entity_id",
        "participant_id",
        "participant_ids",
        "participant_entity_id",
        "participant_entity_ids",
        "sender_entity_id",
        "sender_entity_ids",
        "recipient_entity_id",
        "recipient_entity_ids",
    }
)

# Canonical fact ``kind`` discriminators each state dimension / section reads.
_KINDS_INFORMATION = frozenset({"information", "information_transformation"})
_KINDS_KNOWLEDGE = frozenset({"knowledge_state", "context_inclusion", "interpretation"})
_KINDS_AUTHORITY = frozenset({"authority_evaluation"})
_KINDS_INTERACTIONS = frozenset(
    {
        "communication_act",
        "participant_binding",
        "conversation",
        "provider_thread",
        "matter",
        "request",
        "commitment",
        "response_expectation",
        "knowledge_state",
        "interpretation",
        "context_inclusion",
        "authority_evaluation",
        "provider_capability",
        "communication_quality",
        "information",
        "information_transformation",
    }
)

# Engagement states are a strict subset of the delivery ladder.
_ENGAGEMENT_STATES: tuple[str, ...] = ("opened", "clicked", "replied")
_DIRECTION_KEYS: tuple[str, ...] = (
    "outbound",
    "inbound",
    "internal",
    "system_generated",
)
_COMMUNICATION_REQUIRED_SLOT_IDS = (
    "thread_summary",
    "message_inventory",
    "participants",
    "campaign_links",
    "profile_links",
    "journey_links",
    "response_events",
    "agent_authorship",
    "policy_state",
    "risk_flags",
    "evidence_trace",
)

_FACT_REF_SOURCE = "services/api/journeys/communication360/communication360_facts"


# ─────────────────────────────────────────────────────────────────────────────
# Scope resolution
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Scope:
    """How a subject binds to message and canonical communication sources."""

    kind: str
    id: str
    campaign_id: Optional[str] = None
    participant_entity_id: Optional[str] = None
    participant_identity_ids: tuple[str, ...] = ()
    identity_resolution_state: Optional[str] = None
    identity_evidence: tuple[EvidenceRef, ...] = ()
    bindable: bool = True
    canonical_fact_bindable: bool = True
    note: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "campaignId": self.campaign_id,
            "participantEntityId": self.participant_entity_id,
            "identityResolutionState": self.identity_resolution_state,
            "identityEvidenceRefs": [
                evidence.model_dump(mode="json") for evidence in self.identity_evidence
            ],
            "bindable": self.bindable,
            "canonicalFactBindable": self.canonical_fact_bindable,
            "note": self.note,
        }


@dataclass(frozen=True)
class AgentIdentityRead:
    """Tenant-scoped result for resolving a source agent reference."""

    state: str
    canonical_agent_entity_id: Optional[str] = None
    evidence: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None


class AgentIdentityReader(Protocol):
    async def resolve(self, tenant_id: str, source_agent_ref: str) -> AgentIdentityRead:
        """Resolve only through a tenant-owned canonical Agent identity authority."""
        ...


@dataclass(frozen=True)
class EntityIdentityRead:
    """Tenant-scoped result for resolving an exact canonical entity id."""

    state: str
    canonical_entity_id: Optional[str] = None
    evidence: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None


class EntityIdentityReader(Protocol):
    async def resolve(self, tenant_id: str, canonical_entity_id: str) -> EntityIdentityRead:
        """Resolve only an exact entity id owned by the requesting tenant."""
        ...


@dataclass(frozen=True)
class ProfileLinkRead:
    """Exact tenant profile identity read for one typed communication reference."""

    state: str
    profile_id: Optional[str] = None
    evidence: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None


class ProfileLinkReader(Protocol):
    async def resolve(self, tenant_id: str, profile_id: str) -> ProfileLinkRead:
        """Verify one direct profile ID in the canonical tenant profile store."""
        ...


class RepositoryProfileLinkReader:
    """Verify exact tenant/profile identity using the existing profile authority."""

    async def resolve(self, tenant_id: str, profile_id: str) -> ProfileLinkRead:
        if not tenant_id or not profile_id:
            return ProfileLinkRead(state="unknown", reason="profile_link_scope_invalid")
        try:
            from dependencies.providers import get_cache, get_graph
            from repositories.repos import IdentityRepository, tenant_record_id

            row = await IdentityRepository(get_graph(), get_cache()).get_profile(
                tenant_id, profile_id
            )
        except Exception:  # noqa: BLE001 - identity outage stays unknown
            return ProfileLinkRead(
                state="degraded", reason="profile_identity_authority_unavailable"
            )
        if row is None:
            return ProfileLinkRead(state="unresolved", reason="profile_identity_not_found")
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or str(row.get("user_id") or "") != profile_id
        ):
            return ProfileLinkRead(state="ambiguous", reason="profile_identity_scope_mismatch")
        observed_at = row.get("updated_at") or row.get("created_at")
        if isinstance(observed_at, datetime):
            observed_at = observed_at.isoformat()
        evidence = EvidenceRef(
            id=profile_id,
            type="entity",
            source="identity.profiles",
            observedAt=observed_at if isinstance(observed_at, str) and observed_at else None,
            uri=f"store://profiles/{quote(tenant_record_id(tenant_id, profile_id), safe='')}",
        )
        return ProfileLinkRead(
            state="resolved", profile_id=profile_id, evidence=(evidence,)
        )


@dataclass(frozen=True)
class RecipientIdentityRead:
    """Tenant-scoped exact resolution of one communication recipient binding."""

    state: str
    canonical_entity_id: Optional[str] = None
    evidence: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None


class RecipientIdentityReader(Protocol):
    async def resolve(
        self, tenant_id: str, identity_binding_id: str, expected_entity_id: str
    ) -> RecipientIdentityRead:
        """Resolve an exact provider recipient binding to its canonical entity."""
        ...


class RepositoryEntityIdentityReader:
    """Exact entity-registry lookup used before entity-scoped communication reads."""

    async def resolve(self, tenant_id: str, canonical_entity_id: str) -> EntityIdentityRead:
        if not tenant_id or not canonical_entity_id:
            return EntityIdentityRead(state="unknown", reason="entity_identity_scope_invalid")
        try:
            from repositories.repos import EntityRepository

            rows = await EntityRepository().find_many(
                filters={"tenant_id": tenant_id, "entity_id": canonical_entity_id},
                limit=2,
            )
        except Exception:  # noqa: BLE001 - identity outage remains unknown
            return EntityIdentityRead(state="unknown", reason="entity_identity_authority_unavailable")
        if not isinstance(rows, list):
            return EntityIdentityRead(state="unknown", reason="entity_identity_authority_invalid_response")
        if len(rows) > 1:
            return EntityIdentityRead(state="ambiguous", reason="entity_identity_multiple_matches")
        if not rows:
            return EntityIdentityRead(state="unresolved", reason="entity_identity_binding_not_found")
        row = rows[0]
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("entity_id") != canonical_entity_id
        ):
            return EntityIdentityRead(state="ambiguous", reason="entity_identity_scope_mismatch")
        observed_at = row.get("updated_at") or row.get("created_at")
        evidence = EvidenceRef(
            id=canonical_entity_id,
            type="entity",
            source="entity_registry",
            observedAt=observed_at if isinstance(observed_at, str) and observed_at else None,
        )
        return EntityIdentityRead(
            state="resolved",
            canonical_entity_id=canonical_entity_id,
            evidence=(evidence,),
        )


class RepositoryRecipientIdentityReader:
    """Verify an exact resolved provider-recipient mapping in its tenant."""

    async def resolve(
        self, tenant_id: str, identity_binding_id: str, expected_entity_id: str
    ) -> RecipientIdentityRead:
        if not tenant_id or not identity_binding_id or not expected_entity_id:
            return RecipientIdentityRead(state="unknown", reason="recipient_identity_scope_invalid")
        try:
            from journeys.comms.identity_bridge import ProviderIdentityRepository

            row = await ProviderIdentityRepository().find_by_id(identity_binding_id)
        except Exception:  # noqa: BLE001 - identity outage remains unknown
            return RecipientIdentityRead(
                state="unknown", reason="recipient_identity_authority_unavailable"
            )
        if not isinstance(row, dict):
            return RecipientIdentityRead(
                state="unresolved", reason="recipient_identity_binding_not_found"
            )
        if (
            row.get("tenant_id") != tenant_id
            or str(row.get("identity_id") or row.get("id") or "") != identity_binding_id
        ):
            return RecipientIdentityRead(
                state="ambiguous", reason="recipient_identity_scope_mismatch"
            )
        if row.get("resolution_status") != "resolved":
            return RecipientIdentityRead(
                state="unresolved", reason="recipient_identity_binding_unresolved"
            )
        canonical_entity_id = row.get("canonical_entity_id")
        if canonical_entity_id != expected_entity_id:
            return RecipientIdentityRead(
                state="ambiguous", reason="recipient_identity_canonical_entity_mismatch"
            )
        evidence = EvidenceRef(
            id=identity_binding_id,
            type="entity",
            source="comms_provider_identities",
            observedAt=row.get("verified_at") or row.get("updated_at"),
            uri=f"store://comms_provider_identities/{quote(identity_binding_id, safe='')}",
        )
        return RecipientIdentityRead(
            state="resolved",
            canonical_entity_id=expected_entity_id,
            evidence=(evidence,),
        )


class CurrentJourneyReader(Protocol):
    async def get_current(self, tenant_id: str, journey_id: str) -> Optional[dict[str, Any]]:
        """Read the current version by the exact tenant and canonical journey ID."""
        ...


class RepositoryCurrentJourneyReader:
    """Exact current journey lookup over the canonical ``journey_versions`` authority."""

    async def get_current(self, tenant_id: str, journey_id: str) -> Optional[dict[str, Any]]:
        from journeys.measurement.repositories.journey_repo import JourneyRepository

        return await JourneyRepository().get_current(tenant_id, journey_id)


@dataclass(frozen=True)
class JourneyLinkRead:
    """Evidence-backed explicit communication-to-current-journey joins."""

    state: str
    reason: str
    evidence_refs: tuple[EvidenceRef, ...] = ()
    links: tuple[tuple[str, EvidenceRef, EvidenceRef], ...] = ()


@dataclass(frozen=True)
class ProfileLinksRead:
    """Bounded joins from typed communication profile IDs to tenant profiles."""

    state: str
    reason: str
    evidence_refs: tuple[EvidenceRef, ...] = ()
    links: tuple[dict[str, Any], ...] = ()


class RiskSignalReader(Protocol):
    async def signals(
        self, *, tenant_id: str, subject: ProjectionSubject, limit: int
    ) -> list[dict[str, Any]]:
        """Read signals for one exact tenant and typed Risk360 subject."""
        ...


class ConsentPolicyReader(Protocol):
    async def evaluate(
        self, tenant_id: str, subject_id: str, purpose: str
    ) -> Any:
        """Evaluate current server consent for one exact tenant/subject/purpose."""
        ...


class RepositoryConsentPolicyReader:
    """Read current consent from the canonical server consent authority."""

    async def evaluate(self, tenant_id: str, subject_id: str, purpose: str) -> Any:
        # Keep governance imports lazy so importing the projection stays
        # database-free. The authority performs the exact tenant, subject and
        # purpose lookup and fails closed when a receipt is absent or invalid.
        from governance.consent.authority import evaluate_consent_with_receipt

        return await evaluate_consent_with_receipt(
            tenant_id=tenant_id,
            subject_id=subject_id,
            anonymous_id=None,
            purpose=purpose,
        )


@dataclass(frozen=True)
class ConsentPolicyRead:
    """Bounded current-consent evaluation over exact communication recipients."""

    state: str
    content: dict[str, Any]


class RepositoryRiskSignalReader:
    """Exact subject read over the canonical tenant-scoped RiskSignal store."""

    async def signals(
        self, *, tenant_id: str, subject: ProjectionSubject, limit: int
    ) -> list[dict[str, Any]]:
        from intelligence.risk360.store import RiskSignalRepository

        return await RiskSignalRepository().list_by_subject(
            tenant_id, subject.kind, subject.id, limit=limit
        )


@dataclass(frozen=True)
class RiskFlagRead:
    """Exact-subject canonical risk signals safe to cite in Communication360."""

    state: str
    reason: str
    evidence_refs: tuple[EvidenceRef, ...] = ()
    signals: tuple[RiskSignal, ...] = ()
    authority_refs: tuple[EvidenceRef, ...] = ()
    source_coverage_state: str = "unknown"
    freshness_state: str = "unknown"


class RepositoryAgentIdentityReader:
    """Reuse Agent360's tenant-admin binding and canonical entity checks."""

    async def resolve(self, tenant_id: str, source_agent_ref: str) -> AgentIdentityRead:
        try:
            from actions.agent.agent360_provider import RepositoryAgent360Source

            batch = await RepositoryAgent360Source().actor_identity(tenant_id, source_agent_ref)
        except Exception:  # noqa: BLE001 - identity outage remains unknown
            return AgentIdentityRead(state="unknown", reason="agent_identity_authority_unavailable")

        if batch.truncated:
            return AgentIdentityRead(state="unknown", reason="agent_identity_scan_incomplete")
        if batch.scope_mismatch:
            return AgentIdentityRead(state="ambiguous", reason="agent_identity_scope_ambiguous")

        rows = [
            row for row in batch.rows if isinstance(row, dict) and row.get("tenant_id") == tenant_id
        ]
        canonical_ids = {
            str(row.get("canonical_agent_entity_id"))
            for row in rows
            if isinstance(row.get("canonical_agent_entity_id"), str)
            and row.get("canonical_agent_entity_id")
        }
        if len(canonical_ids) > 1:
            return AgentIdentityRead(
                state="ambiguous", reason="agent_identity_multiple_canonical_matches"
            )
        if not canonical_ids:
            return AgentIdentityRead(state="unresolved", reason="agent_identity_binding_not_found")

        canonical_id = next(iter(canonical_ids))
        evidence: dict[tuple[str, str], EvidenceRef] = {}
        for row in rows:
            if row.get("canonical_agent_entity_id") != canonical_id:
                continue
            evidence_id = row.get("identity_evidence_id")
            evidence_source = row.get("identity_evidence_source")
            if not isinstance(evidence_id, str) or not evidence_id:
                continue
            if not isinstance(evidence_source, str) or not evidence_source:
                continue
            ref = EvidenceRef(
                id=evidence_id,
                type="entity",
                source=evidence_source,
                observedAt=row.get("identity_bound_at"),
            )
            evidence[(ref.source, ref.id)] = ref
        if not evidence:
            return AgentIdentityRead(state="unknown", reason="agent_identity_evidence_missing")
        return AgentIdentityRead(
            state="resolved",
            canonical_agent_entity_id=canonical_id,
            evidence=tuple(evidence.values()),
        )


def _resolve_scope(request: ProjectionRequest) -> _Scope:
    """Resolve direct message joins; other supported subjects use exact facts."""
    kind = request.subject.kind
    if kind == "campaign":
        return _Scope(kind=kind, id=request.subject.id, campaign_id=request.subject.id)
    if kind == "agent":
        return _Scope(
            kind=kind,
            id=request.subject.id,
            participant_entity_id=request.subject.id,
            participant_identity_ids=(request.subject.id,),
        )
    if kind == "entity":
        return _Scope(
            kind=kind,
            id=request.subject.id,
            participant_entity_id=request.subject.id,
            participant_identity_ids=(request.subject.id,),
        )
    if kind in {"episode", "journey", "source"}:
        return _Scope(
            kind=kind,
            id=request.subject.id,
            bindable=False,
            note=_SCOPE_NOTES[kind],
        )
    # source (and any future unbound kind) — honest, no Phase-4 binding.
    note = _SCOPE_NOTES.get(kind)
    if note is None:
        note = f"subject kind {kind!r} has no Phase-4 binding to communication truth"
    return _Scope(
        kind=kind,
        id=request.subject.id,
        bindable=False,
        canonical_fact_bindable=False,
        note=note,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Small value helpers
# ─────────────────────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_value(value: Any) -> Optional[str]:
    """Enum member / string -> its string value (None stays None)."""
    if value is None:
        return None
    return value.value if isinstance(value, Enum) else str(value)


def _payload_of(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload.strip():
        try:
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _row_matches_scope(
    row: dict[str, Any],
    tenant_id: str,
    scope: _Scope,
) -> bool:
    """A canonical fact is in-scope when it names the subject in its row/payload.

    The Phase-4 fact spine has no dedicated subject column beyond the envelope
    columns (``actor_id`` / ``agent_id``) plus the JSONB ``payload``, so scope
    matching reads those: the subject is bound when its id appears as the fact's
    declared actor/agent or anywhere in the stored payload. This is presence
    matching over what the store declares — never an inference about meaning.
    """
    if str(row.get("tenant_id", "")) != tenant_id:
        return False
    reference_keys = {
        "agent": {"agent_id", "actor_id", "actor_entity_id", "agent_entity_id", "entity_id"},
        "entity": set(_ENTITY_REFERENCE_KEYS),
        "campaign": {"campaign_id", "campaign_ids"},
        "episode": {"episode_id", "episode_ids"},
        "journey": {"journey_id", "journey_ids"},
        "source": {"source_id", "source_namespace", "provider_id"},
    }.get(scope.kind, set())
    reference_ids = (
        scope.participant_identity_ids if scope.kind in {"agent", "entity"} else (scope.id,)
    )
    for reference_id in reference_ids:
        if any(str(row.get(key) or "") == reference_id for key in reference_keys):
            return True
        if _payload_has_exact_reference(_payload_of(row), reference_keys, reference_id):
            return True
    return False


def _payload_has_exact_reference(value: Any, keys: set[str], reference: str) -> bool:
    """Match typed reference fields exactly; never substring-search payload text."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys:
                if not isinstance(item, (dict, list)) and str(item or "") == reference:
                    return True
                if isinstance(item, list) and any(
                    not isinstance(candidate, (dict, list)) and str(candidate or "") == reference
                    for candidate in item
                ):
                    return True
            if _payload_has_exact_reference(item, keys, reference):
                return True
    elif isinstance(value, list):
        return any(_payload_has_exact_reference(item, keys, reference) for item in value)
    return False


def _has_exact_entity_binding(
    *,
    side: str,
    entity_id: Optional[str],
    binding_id: Optional[str],
    evidence_ref: Optional[EvidenceRef],
    expected_entity_id: str,
) -> bool:
    """Require a typed canonical binding record for one exact message endpoint."""
    if (
        entity_id != expected_entity_id
        or not isinstance(binding_id, str)
        or not binding_id.strip()
        or evidence_ref is None
        or evidence_ref.id != binding_id
        or evidence_ref.type != "entity"
    ):
        return False
    expected_source = {
        "sender": "agent_deployment_identity_bindings",
        "recipient": "comms_provider_identities",
    }.get(side)
    source_uri = _ENTITY_BINDING_EVIDENCE_URIS.get(expected_source or "")
    if source_uri is None or evidence_ref.source != expected_source:
        return False
    return evidence_ref.uri == f"{source_uri}{quote(binding_id, safe='')}"


def _message_matches_scope(message: CommunicationMessage, scope: _Scope) -> bool:
    if scope.kind == "campaign":
        return str(message.campaign_id or "") == scope.id
    if scope.kind == "agent":
        return bool(
            set(scope.participant_identity_ids)
            & {message.sender_entity_id, message.recipient_entity_id}
        )
    if scope.kind == "entity":
        return _has_exact_entity_binding(
            side="sender",
            entity_id=message.sender_entity_id,
            binding_id=message.sender_identity_binding_id,
            evidence_ref=message.sender_identity_evidence_ref,
            expected_entity_id=scope.id,
        ) or _has_exact_entity_binding(
            side="recipient",
            entity_id=message.recipient_entity_id,
            binding_id=message.recipient_identity_binding_id,
            evidence_ref=message.recipient_identity_evidence_ref,
            expected_entity_id=scope.id,
        )
    return False


def _projection_requests_noncurrent_scope(request: ProjectionRequest) -> bool:
    """Current-only authorities must not leak into an anchored or bounded frame."""
    return bool(
        request.asOf is not None
        or request.timeRange is not None
        or request.temporalMode in {"window", "as_of", "compare", "relative"}
    )


def _communication_slot_ids(
    subject_kind: str,
    slot_ids: set[str],
    section_ids: set[str],
) -> list[str]:
    """Return catalog slots bound to this subject and evidence section.

    Keep claim attribution within explicit product-surface bindings. A
    technical communication fact may feed other projections, but that does
    not make its claim part of every other surface's slot contract.
    """
    result: set[str] = set()
    for surface in PRODUCT_360_SURFACE_DEFINITIONS.values():
        if not isinstance(surface, dict):
            continue
        for slot in surface.get("domainSlots", []):
            if not isinstance(slot, dict):
                continue
            slot_id = slot.get("id")
            if not isinstance(slot_id, str) or slot_id not in slot_ids:
                continue
            for binding in slot.get("projectionBindings", []):
                if (
                    not isinstance(binding, dict)
                    or binding.get("projectionId") != "communication360"
                ):
                    continue
                if subject_kind not in binding.get("subjectKinds", []):
                    continue
                if not set(binding.get("sectionIds", [])).intersection(section_ids):
                    continue
                result.add(slot_id)
    return sorted(result)


def _canonical_communication_slot_ids(
    subject_kind: str,
    subject_id: str,
    row: dict[str, Any],
) -> list[str]:
    """Attribute a canonical fact only to its exact catalog slots."""
    kind = str(row.get("kind") or "")
    payload = _payload_of(row)
    supported: set[str] = {"evidence_trace"}
    evidence_sections = {"evidence"}
    interaction_sections = {"interactions"}

    if kind in {"conversation", "provider_thread"}:
        supported.add("thread_summary")
    if kind == "participant_binding":
        supported.add("participants")
        role = str(payload.get("role") or "").strip().lower()
        entity_type = str(payload.get("entity_type") or "").strip().lower()
        has_agent_identity = (
            entity_type == "agent"
            or bool(payload.get("agent_id"))
            or bool(row.get("agent_id"))
        )
        has_author = bool(
            payload.get("entity_id")
            or payload.get("principal_entity_id")
            or row.get("actor_id")
        )
        if subject_kind == "agent" and role == "author" and has_agent_identity and has_author:
            supported.add("agent_authorship")
    if (
        kind == "communication_act"
        and str(payload.get("act_type") or "").strip().lower()
        in {"acknowledge", "reply", "replied", "respond", "responded"}
    ):
        supported.add("response_events")

    if subject_kind == "campaign" and _row_reference_values(row, "campaign_id", "campaign_ids"):
        supported.add("campaign_links")
    if subject_kind == "entity" and _payload_has_exact_reference(
        {"row": row, "payload": payload}, set(_ENTITY_REFERENCE_KEYS), subject_id
    ):
        supported.add("communications")
    if subject_kind == "episode" and subject_id in _row_reference_values(
        row, "episode_id", "episode_ids"
    ):
        # Episode-linked communication facts are an exact canonical join. The
        # message spine still has no episode join, so the product slot remains
        # partial and receives no claims from unscoped message inventory.
        supported.add("communications")
    if subject_kind == "journey" and subject_id in _row_reference_values(
        row, "journey_id", "journey_ids"
    ):
        # Journey attribution is limited to explicit typed IDs on the
        # tenant-scoped canonical fact row. Message endpoints and free text do
        # not establish a communication-to-journey join.
        supported.add("communications")

    bound = _communication_slot_ids(
        subject_kind,
        supported,
        evidence_sections | interaction_sections,
    )
    return bound


def _communication_fact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep known canonical communication objects for timeline and evidence."""
    kinds = _KINDS_INFORMATION | _KINDS_KNOWLEDGE | _KINDS_AUTHORITY | _KINDS_INTERACTIONS
    return [row for row in rows if row.get("kind") in kinds]


def _has_typed_reference(value: Any, keys: frozenset[str]) -> bool:
    """Recognize non-empty typed IDs without scanning free-text values."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys:
                if isinstance(item, str) and item.strip():
                    return True
                if isinstance(item, (list, tuple)) and any(
                    isinstance(candidate, str) and candidate.strip() for candidate in item
                ):
                    return True
            if _has_typed_reference(item, keys):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_has_typed_reference(item, keys) for item in value)
    return False


def _typed_reference_values(value: Any, keys: frozenset[str]) -> list[str]:
    """Return stable scalar IDs from named reference fields only."""
    found: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in keys:
                    candidates = child if isinstance(child, (list, tuple)) else [child]
                    for candidate in candidates:
                        if isinstance(candidate, str) and candidate.strip() and candidate not in found:
                            found.append(candidate)
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return found


def _row_reference_values(row: dict[str, Any], singular: str, plural: str) -> list[str]:
    """Read explicit communication relationship IDs from envelope and payload fields."""
    keys = frozenset({singular, plural})
    return _typed_reference_values(
        {"row": row, "payload": _payload_of(row)},
        keys,
    )


def _communication_required_slot_coverage(
    *,
    request: ProjectionRequest,
    scope: _Scope,
    messages: list[CommunicationMessage],
    fact_rows: list[dict[str, Any]],
    silver_up: bool,
    silver_truncated: bool,
    canonical_up: bool,
    canonical_truncated: bool,
    journey_links: JourneyLinkRead,
    profile_links: ProfileLinksRead,
    risk_flags: RiskFlagRead,
    policy_state: ConsentPolicyRead,
) -> dict[str, dict[str, Any]]:
    """Expose all SSOT slots without promoting IDs, transport, or policy inputs to truth."""
    message_refs = _dedupe_refs(
        [ref for message in messages for ref in message.evidence_refs if isinstance(ref, EvidenceRef)]
    )
    fact_rows_with_evidence = [
        (row, evidence)
        for row in fact_rows
        if (evidence := _row_evidence(row)) is not None
    ]
    fact_refs = _dedupe_refs([evidence for _, evidence in fact_rows_with_evidence])
    all_refs = _dedupe_refs([*message_refs, *fact_refs])

    def slot(
        state: str,
        coverage: str,
        reason: str,
        refs: list[EvidenceRef] | None = None,
    ) -> dict[str, Any]:
        return {
            "state": state,
            "coverage": coverage,
            "reason": reason,
            "evidenceRefs": [ref.model_dump(mode="json", exclude_none=True) for ref in refs or []],
        }

    messages_complete = scope.bindable and silver_up and not silver_truncated
    canonical_complete = canonical_up and not canonical_truncated
    conversation_rows = [
        row for row in fact_rows if row.get("kind") in {"conversation", "provider_thread"}
    ]
    conversation_refs = _dedupe_refs(
        [ref for row in conversation_rows if (ref := _row_evidence(row)) is not None]
    )
    thread_message_refs = [
        ref
        for message in messages
        if isinstance(message.external_thread_id, str) and message.external_thread_id.strip()
        for ref in message.evidence_refs
        if isinstance(ref, EvidenceRef)
    ]
    thread_refs = _dedupe_refs([*conversation_refs, *thread_message_refs])

    participant_rows = [row for row in fact_rows if row.get("kind") == "participant_binding"]
    participant_refs = _dedupe_refs(
        [
            ref
            for row in participant_rows
            for ref in [
                *([_row_evidence(row)] if _row_evidence(row) is not None else []),
                *_trusted_participant_source_evidence(row),
            ]
        ]
    )
    message_endpoint_refs = [
        ref
        for message in messages
        if message.sender_entity_id or message.recipient_entity_id
        for ref in message.evidence_refs
        if isinstance(ref, EvidenceRef)
    ]
    participant_evidence = _dedupe_refs([*participant_refs, *message_endpoint_refs])

    campaign_rows = [
        row
        for row in fact_rows
        if _has_typed_reference(
            {"row": row, "payload": _payload_of(row)}, frozenset({"campaign_id", "campaign_ids"})
        )
    ]
    campaign_refs = _dedupe_refs(
        [ref for row in campaign_rows if (ref := _row_evidence(row)) is not None]
        + [
            ref
            for message in messages
            if message.campaign_id
            for ref in message.evidence_refs
            if isinstance(ref, EvidenceRef)
        ]
    )
    response_rows = [
        row
        for row in fact_rows
        if row.get("kind") == "communication_act"
        and str(_payload_of(row).get("act_type") or "").strip().lower()
        in {"acknowledge", "reply", "replied", "respond", "responded"}
    ]
    response_refs = _dedupe_refs(
        [ref for row in response_rows if (ref := _row_evidence(row)) is not None]
    )
    author_rows = [
        row
        for row in participant_rows
        if str(_payload_of(row).get("role") or "").strip().lower() == "author"
        and (
            str(_payload_of(row).get("entity_type") or "").strip().lower() == "agent"
            or _payload_of(row).get("agent_id")
            or row.get("agent_id")
        )
        and (
            _payload_of(row).get("entity_id")
            or _payload_of(row).get("principal_entity_id")
            or row.get("actor_id")
        )
    ]
    author_refs = _dedupe_refs(
        [
            ref
            for row in author_rows
            for ref in [
                *([_row_evidence(row)] if _row_evidence(row) is not None else []),
                *_trusted_participant_source_evidence(row),
            ]
        ]
    )
    if scope.kind == "agent" and scope.identity_resolution_state == "resolved":
        agent_message_refs = [
            ref
            for message in messages
            if message.sender_entity_id in scope.participant_identity_ids
            for ref in message.evidence_refs
            if isinstance(ref, EvidenceRef)
        ]
        author_refs = _dedupe_refs([*author_refs, *agent_message_refs])

    if conversation_refs:
        thread_slot = slot(
            "degraded",
            "partial",
            "canonical_thread_rows_available_without_complete_message_thread_composition",
            thread_refs,
        )
    elif thread_refs:
        thread_slot = slot(
            "degraded",
            "partial",
            "provider_thread_ids_observed_without_canonical_conversation_resolution",
            thread_refs,
        )
    else:
        thread_slot = slot("unknown", "unknown", "canonical_conversation_thread_join_unavailable")

    if messages_complete:
        message_slot = slot(
            "available" if messages else "empty",
            "complete",
            "tenant_scoped_message_reader_completed_for_bound_subject",
            message_refs,
        )
    elif messages:
        message_slot = slot(
            "degraded",
            "partial",
            "tenant_scoped_message_read_is_truncated_or_unavailable",
            message_refs,
        )
    else:
        message_ids_exist = any(
            _has_typed_reference(
                {"row": row, "payload": _payload_of(row)},
                frozenset({"message_id", "message_ids"}),
            )
            for row in fact_rows
        )
        message_slot = slot(
            "degraded" if message_ids_exist else "unknown",
            "partial" if message_ids_exist else "unknown",
            "canonical_message_references_exist_without_message_record_lookup"
            if message_ids_exist
            else "subject_has_no_supported_message_spine_binding",
            fact_refs if message_ids_exist else None,
        )

    trusted_roster_rows = [
        row for row in participant_rows if _trusted_participant_source_evidence(row)
    ]
    source_complete_rosters = [
        row
        for row in trusted_roster_rows
        if _payload_of(row).get("roster_completeness_state") == "complete"
        and _payload_of(row).get("roster_expected_binding_count")
        == _payload_of(row).get("roster_binding_count")
    ]
    source_incomplete_rosters = [
        row
        for row in trusted_roster_rows
        if _payload_of(row).get("roster_completeness_state") != "complete"
        or _payload_of(row).get("roster_expected_binding_count")
        != _payload_of(row).get("roster_binding_count")
    ]
    if participant_evidence and source_complete_rosters:
        participant_slot = slot(
            "degraded",
            "partial",
            "complete_provider_roster_observed_but_provider_conversation_to_canonical_conversation_membership_is_unresolved",
            participant_evidence,
        )
    elif participant_evidence and source_incomplete_rosters:
        participant_slot = slot(
            "degraded",
            "partial",
            "provider_participant_roster_is_explicitly_partial_or_has_uncovered_bindings",
            participant_evidence,
        )
    elif participant_evidence:
        participant_slot = slot(
            "degraded",
            "partial",
            "observed_message_endpoints_or_participant_bindings_do_not_establish_full_participant_roles",
            participant_evidence,
        )
    else:
        participant_slot = slot("unknown", "unknown", "participant_authority_not_joined")

    if campaign_refs:
        campaign_slot_state = (
            "available"
            if scope.kind == "campaign" and messages_complete and bool(messages)
            else "degraded"
        )
        campaign_slot = slot(
            campaign_slot_state,
            "complete" if campaign_slot_state == "available" else "partial",
            "tenant_scoped_message_campaign_reference_observed"
            if campaign_slot_state == "available"
            else "typed_campaign_references_observed_without_campaign_entity_resolution",
            campaign_refs,
        )
    else:
        campaign_slot = slot("unknown", "unknown", "communication_campaign_link_not_observed")

    journey_slot = slot(
        journey_links.state,
        "complete" if journey_links.state == "available" else (
            "unknown" if journey_links.state == "unknown" else "partial"
        ),
        journey_links.reason,
        list(journey_links.evidence_refs),
    )

    if response_refs:
        response_slot = slot(
            "degraded",
            "partial",
            "response_like_canonical_acts_observed_without_complete_response_event_linkage",
            response_refs,
        )
    else:
        response_slot = slot("unknown", "unknown", "canonical_response_event_authority_not_joined")

    if author_refs:
        author_slot = slot(
            "degraded",
            "partial",
            "observed_sender_or_author_binding_lacks_complete_actor_authority_evaluation",
            author_refs,
        )
    else:
        author_slot = slot("unknown", "unknown", "canonical_authorship_binding_not_observed")

    evidence_slot = (
        slot(
            "degraded",
            "partial",
            "message_and_fact_evidence_refs_available_source_provenance_not_fully_resolved",
            all_refs,
        )
        if all_refs
        else slot("unknown", "unknown", "communication_evidence_refs_unavailable")
    )

    return {
        "thread_summary": thread_slot,
        "message_inventory": message_slot,
        "participants": participant_slot,
        "campaign_links": campaign_slot,
        "profile_links": {
            **slot(
                profile_links.state,
                "partial" if profile_links.links else "unknown",
                profile_links.reason,
                list(profile_links.evidence_refs),
            ),
            "links": list(profile_links.links),
            # The profile record read is exact and tenant-scoped, but the
            # authority does not provide historical identity or a freshness
            # watermark for the communication-to-profile relationship.
            "temporalState": "unknown",
            "temporalReason": "profile_identity_history_not_joined",
            "freshnessState": "unknown",
            "freshnessReason": "profile_identity_authority_has_no_projection_watermark",
        },
        "journey_links": journey_slot,
        "response_events": response_slot,
        "agent_authorship": author_slot,
        "policy_state": policy_state.content,
        "risk_flags": {
            **slot(
                risk_flags.state,
                risk_flags.source_coverage_state,
                risk_flags.reason,
                list(risk_flags.evidence_refs),
            ),
            "freshnessState": risk_flags.freshness_state,
            "freshnessReason": "risk_signal_authority_has_no_current_coverage_watermark",
        },
        "evidence_trace": evidence_slot,
    }


def _exact_consent_policy_inputs(
    messages: list[CommunicationMessage], tenant_id: str
) -> dict[tuple[str, str], dict[str, Any]]:
    """Collect only recipient/purpose pairs backed by tenant-scoped message evidence."""
    inputs: dict[tuple[str, str], dict[str, Any]] = {}
    for message in messages:
        if message.tenant_id != tenant_id:
            continue
        subject_id = message.recipient_entity_id
        binding_id = message.recipient_identity_binding_id
        binding_ref = message.recipient_identity_evidence_ref
        consent = message.consent_evidence
        purpose = consent.purpose
        if (
            not subject_id
            or not binding_id
            or not isinstance(purpose, str)
            or not purpose.strip()
            or binding_ref is None
            or binding_ref.id != binding_id
            or binding_ref.type != "entity"
            or binding_ref.source != "comms_provider_identities"
            or binding_ref.uri
            != f"store://comms_provider_identities/{quote(binding_id, safe='')}"
            or not message.evidence_refs
        ):
            continue

        historical_refs: list[EvidenceRef] = []
        historical_outcome = "unknown"
        if consent.state == "recorded":
            if (
                consent.subject_entity_id != subject_id
                or consent.identity_binding_id != binding_id
                or not consent.receipt_id
            ):
                continue
            receipt_ref = next(
                (
                    ref
                    for ref in consent.evidence_refs
                    if ref.id == consent.receipt_id
                    and ref.source == "governance.consent.authority"
                    and ref.uri
                    == f"store://consent_receipts/{quote(consent.receipt_id, safe='')}"
                ),
                None,
            )
            consent_binding_ref = next(
                (
                    ref
                    for ref in consent.evidence_refs
                    if ref.id == binding_id
                    and ref.source == "comms_provider_identities"
                    and ref.uri
                    == f"store://comms_provider_identities/{quote(binding_id, safe='')}"
                ),
                None,
            )
            if receipt_ref is None or consent_binding_ref is None:
                continue
            historical_refs = [receipt_ref, consent_binding_ref]
            # The connector writes this lineage only after the server consent
            # authority returned an allowed receipt. This records that past
            # processing event; it says nothing about current consent.
            historical_outcome = "allowed"
        elif consent.state != "unknown":
            continue

        pair = (subject_id, purpose.strip())
        entry = inputs.setdefault(
            pair,
            {
                "subjectEntityId": subject_id,
                "purpose": purpose.strip(),
                "messageIds": [],
                "inputEvidenceRefs": [],
                "historicalEvidenceRefs": [],
                "historicalOutcomeAtCommunication": historical_outcome,
            },
        )
        if message.message_id not in entry["messageIds"]:
            entry["messageIds"].append(message.message_id)
        entry["inputEvidenceRefs"].extend(
            [
                ref
                for ref in message.evidence_refs
                if isinstance(ref, EvidenceRef)
            ]
        )
        entry["inputEvidenceRefs"].append(binding_ref)
        entry["historicalEvidenceRefs"].extend(historical_refs)
        if historical_outcome == "allowed":
            entry["historicalOutcomeAtCommunication"] = "allowed"

    for entry in inputs.values():
        entry["inputEvidenceRefs"] = _dedupe_refs(entry["inputEvidenceRefs"])
        entry["historicalEvidenceRefs"] = _dedupe_refs(entry["historicalEvidenceRefs"])
        entry["messageIds"].sort()
    return inputs


def _canonical_open_state_count(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    expected_state: str,
    known_states: frozenset[str],
) -> Optional[int]:
    """Count explicit canonical states only when that fact family is present and typed."""
    candidates = [row for row in rows if row.get("kind") == kind]
    if not candidates:
        return None
    states = [_payload_of(row).get("state") or row.get("state") for row in candidates]
    if any(not isinstance(state, str) or state not in known_states for state in states):
        return None
    return sum(state == expected_state for state in states)


def _source_policy_context(
    *,
    request: ProjectionRequest,
    scope: _Scope,
    messages: list[CommunicationMessage],
    rows: list[dict[str, Any]],
    silver_up: bool,
    canonical_up: bool,
    silver_truncated: bool,
    canonical_truncated: bool,
) -> dict[str, Any]:
    """Expose exact source references and stored consent receipts without
    treating either as a current policy decision.

    Campaign messages carry an explicit provider identity on the silver row.
    Episode/journey canonical facts may carry an explicit ``provider_id`` or
    ``provider_identity`` reference in their row/payload. These identifiers
    are preserved as observed references only; Source360 must still resolve
    source rights/provenance and the frame runtime owns policy evaluation.
    """
    source_refs: dict[tuple[str, str, str], dict[str, Any]] = {}
    for message in messages:
        provider = message.provider
        if not isinstance(provider, str) or not provider.strip():
            continue
        refs = [
            ref.model_dump(mode="json", exclude_none=True)
            for ref in message.evidence_refs
            if isinstance(ref, EvidenceRef)
        ]
        if not refs:
            continue
        source_refs[("silver_comms_facts", provider, message.message_id)] = {
            "providerIdentity": provider,
            "referenceSource": "silver_comms_facts.provider",
            "observedAt": message.received_at or message.occurred_at,
            "evidenceRefs": refs,
        }

    for row in rows:
        payload = _payload_of(row)
        provider = row.get("provider_identity") or row.get("provider_id")
        if not isinstance(provider, str) or not provider.strip():
            provider = payload.get("provider_identity") or payload.get("provider_id")
        if not isinstance(provider, str) or not provider.strip():
            continue
        evidence = _row_evidence(row)
        if evidence is None:
            continue
        source_refs[
            (
                "communication360_facts",
                provider,
                evidence.id,
            )
        ] = {
            "providerIdentity": provider,
            "referenceSource": "communication360_facts.provider_identity",
            "observedAt": str(row.get("occurred_at") or "") or None,
            "evidenceRefs": [evidence.model_dump(mode="json", exclude_none=True)],
        }

    consent_receipts: dict[str, dict[str, Any]] = {}
    for message in messages:
        consent = message.consent_evidence
        if consent.state != "recorded" or not consent.receipt_id:
            continue
        # CommunicationConsentEvidence validates that the server-owned receipt
        # and identity-binding evidence are both present for recorded state.
        if len(consent.evidence_refs) < 2:
            continue
        consent_receipts[consent.receipt_id] = {
            "receiptId": consent.receipt_id,
            "purpose": consent.purpose,
            "subjectEntityId": consent.subject_entity_id,
            "observedAt": message.received_at or message.occurred_at,
            "evidenceRefs": [
                ref.model_dump(mode="json", exclude_none=True)
                for ref in consent.evidence_refs
                if isinstance(ref, EvidenceRef)
            ],
        }

    source_incomplete = (scope.bindable and (not silver_up or silver_truncated)) or (
        scope.canonical_fact_bindable and (not canonical_up or canonical_truncated)
    )
    if source_incomplete:
        lineage_state = "degraded"
        consent_state = "degraded" if scope.bindable else "unknown"
        state = "degraded"
        reason = (
            REASON_SOURCE_READ_TRUNCATED
            if silver_truncated or canonical_truncated
            else REASON_SILVER_SOURCE_UNAVAILABLE
            if scope.bindable and not silver_up
            else REASON_CANONICAL_SOURCE_UNAVAILABLE
        )
    else:
        lineage_state = "observed_references" if source_refs else "unknown"
        consent_state = "recorded" if consent_receipts else "unknown"
        state = "partial" if source_refs or consent_receipts else "unknown"
        reason = (
            "source360_rights_lineage_not_composed"
            if source_refs
            else "no_exact_source_or_server_consent_reference_observed"
        )

    return {
        "state": state,
        "tenantId": request.tenantId,
        "subject": {"kind": request.subject.kind, "id": request.subject.id},
        "sourceLineage": {
            "state": lineage_state,
            "references": list(source_refs.values()),
            "authority": "source360_required_for_provider_registry_and_rights_lineage",
        },
        "historicalConsent": {
            "state": consent_state,
            "receipts": list(consent_receipts.values()),
            "reason": (
                None
                if consent_receipts
                else "consent_is_not_inferred_from_delivery_or_message_category"
            ),
        },
        "policyEvaluation": {
            "state": "unknown",
            "authority": "experience360_frame_policy_runtime",
            "reason": "policy_is_evaluated_by_the_governing_frame_runtime",
        },
        "freshness": {
            # Preserved timestamps are freshness inputs, not a freshness
            # judgment. This provider has no registered freshness window or
            # Temporal360 result to decide whether those inputs are current.
            "state": "unknown",
            "sourceTimestampsPreserved": True,
            "evaluation": "not_performed",
            "reason": "freshness_window_not_evaluated_by_communication360",
        },
        "reason": reason,
    }


def _row_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    """A reused canonical EvidenceRef for one stored fact row (or None)."""
    ref_id = row.get("fact_id") or row.get("idempotency_key") or row.get("source_event_id")
    if not ref_id:
        return None
    observed_at = str(row.get("occurred_at") or "") or None
    return EvidenceRef(
        id=str(ref_id),
        type="event",
        source=_FACT_REF_SOURCE,
        observedAt=observed_at,
        uri=f"store://communication360_facts/{ref_id}",
    )


def _trusted_participant_source_evidence(row: dict[str, Any]) -> list[EvidenceRef]:
    """Read source role/completeness evidence only from writer-shaped facts.

    Generic participant rows remain readable as observed facts, but their
    arbitrary payload evidence is not promoted into trusted provenance.
    """
    payload = _payload_of(row)
    provenance = payload.get("source_provenance")
    authentication = provenance.get("authentication") if isinstance(provenance, dict) else None
    identity = payload.get("source_identity")
    actor = payload.get("actor_attribution")
    policy = payload.get("policy")
    provider = payload.get("provider")
    if not (
        isinstance(provenance, dict)
        and isinstance(authentication, dict)
        and authentication.get("method") == "tenant_webhook_hmac"
        and authentication.get("verified") is True
        and isinstance(provider, str)
        and provider
        and provenance.get("namespace") == provider
        and provenance.get("provider_account_id") == payload.get("provider_account_id")
        and provenance.get("event_id") == row.get("source_event_id")
        and payload.get("communication_scope_kind") == "provider_conversation"
        and payload.get("provider_conversation_id") == payload.get("communication_scope")
        and isinstance(payload.get("roster_id"), str)
        and payload.get("roster_id")
        and isinstance(payload.get("binding_id"), str)
        and payload.get("binding_id")
        and isinstance(payload.get("role"), str)
        and payload.get("claim_state") == "observed"
        and isinstance(identity, dict)
        and identity.get("resolution_status") == "resolved"
        and isinstance(identity.get("identity_binding_id"), str)
        and identity.get("identity_binding_id")
        and isinstance(payload.get("entity_id"), str)
        and payload.get("entity_id")
        and isinstance(actor, dict)
        and actor.get("actor_id") == row.get("actor_id")
        and isinstance(policy, dict)
        and policy.get("ingress_consent_outcome") == "allowed"
        and policy.get("sensitive_message_fields_redacted") is True
    ):
        return []

    parsed_refs: dict[str, list[EvidenceRef]] = {
        "role_evidence_refs": [],
        "roster_completeness_evidence_refs": [],
    }
    for key in parsed_refs:
        candidates = payload.get(key)
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if (
                candidate.get("source") != provider
                or candidate.get("uri") is not None
                or not isinstance(candidate.get("id"), str)
                or not candidate["id"].strip()
                or "@" in candidate["id"]
                or any(ch.isspace() for ch in candidate["id"].strip())
                or not isinstance(candidate.get("observedAt"), str)
                or not candidate["observedAt"].strip()
            ):
                continue
            try:
                observed_at = datetime.fromisoformat(
                    candidate["observedAt"].strip().replace("Z", "+00:00")
                )
                if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                    continue
                parsed_refs[key].append(EvidenceRef.model_validate(candidate))
            except Exception:  # noqa: BLE001 - invalid source evidence remains untrusted
                continue
    roster_state = payload.get("roster_completeness_state")
    expected_count = payload.get("roster_expected_binding_count")
    binding_count = payload.get("roster_binding_count")
    if not parsed_refs["role_evidence_refs"]:
        return []
    if roster_state in {"complete", "partial"} and not parsed_refs[
        "roster_completeness_evidence_refs"
    ]:
        return []
    if roster_state == "complete" and (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count < 1
        or expected_count != binding_count
    ):
        return []
    if roster_state not in {"complete", "partial", "unknown"}:
        return []
    return _dedupe_refs(
        [
            *parsed_refs["role_evidence_refs"],
            *parsed_refs["roster_completeness_evidence_refs"],
        ]
    )


def _dedupe_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    """EvidenceRefs deduped by id, first occurrence order preserved."""
    seen: set[str] = set()
    out: list[EvidenceRef] = []
    for ref in refs:
        if ref.id in seen:
            continue
        seen.add(ref.id)
        out.append(ref)
    return out


def _message_state_value(message: CommunicationMessage) -> Optional[str]:
    return _state_value(message.communication_state)


# ─────────────────────────────────────────────────────────────────────────────
# Provider
# ─────────────────────────────────────────────────────────────────────────────


class Communication360Provider:
    """Intelligence-projection provider for ``communication360`` (read-only)."""

    projection_id = "communication360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(
        self,
        sources: Optional[Union[CommunicationSource, dict[str, CommunicationSource]]] = None,
        *,
        agent_identity_reader: Optional[AgentIdentityReader] = None,
        entity_identity_reader: Optional[EntityIdentityReader] = None,
        profile_link_reader: Optional[ProfileLinkReader] = None,
        recipient_identity_reader: Optional[RecipientIdentityReader] = None,
        source_subject_scope_reader: Optional[SourceSubjectScopeReader] = None,
        journey_reader: Optional[CurrentJourneyReader] = None,
        risk_signal_reader: Optional[RiskSignalReader] = None,
        consent_policy_reader: Optional[ConsentPolicyReader] = None,
    ) -> None:
        """Injectable sources (test seam); default = ``default_sources()``.

        ``sources`` may be a single :class:`CommunicationSource` (applied to
        both the silver message role and the canonical fact role — the shape a
        lightweight test double provides) or a ``{"silver": ..., "canonical": ...}``
        dict. No connection is opened at construction time.
        """
        if sources is None:
            resolved: dict[str, CommunicationSource] = dict(default_sources())
        elif isinstance(sources, dict):
            resolved = dict(sources)
        else:
            resolved = {"silver": sources, "canonical": sources}
        self._silver = resolved.get("silver") or resolved.get("messages")
        self._canonical = resolved.get("canonical") or resolved.get("facts")
        if self._silver is None or self._canonical is None:
            raise ProjectionError(
                "communication360 provider requires both a silver message source "
                "and a canonical fact source"
            )
        self._agent_identity = (
            agent_identity_reader
            if agent_identity_reader is not None
            else RepositoryAgentIdentityReader()
        )
        self._entity_identity = (
            entity_identity_reader
            if entity_identity_reader is not None
            else RepositoryEntityIdentityReader()
        )
        self._profile_links = profile_link_reader or RepositoryProfileLinkReader()
        self._recipient_identity = (
            recipient_identity_reader
            if recipient_identity_reader is not None
            else RepositoryRecipientIdentityReader()
        )
        self._source_subject_scope = (
            source_subject_scope_reader
            if source_subject_scope_reader is not None
            else RepositorySourceSubjectScopeReader()
        )
        self._journeys = journey_reader or RepositoryCurrentJourneyReader()
        self._risk_signals = risk_signal_reader or RepositoryRiskSignalReader()
        self._consent_policy = consent_policy_reader or RepositoryConsentPolicyReader()

    # ── IntelligenceProjectionProvider ─────────────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one read-only Communication360 projection over canonical truth."""
        tenant_id = request.tenantId
        scope = _resolve_scope(request)
        read_limit = min(
            max(request.page.limit if request.page else _DEFAULT_READ_LIMIT, 1),
            _MAX_READ_LIMIT,
        )
        if request.subject.kind == "agent":
            try:
                identity = await self._agent_identity.resolve(tenant_id, request.subject.id)
            except Exception:  # noqa: BLE001 - fail closed on identity errors
                identity = AgentIdentityRead(
                    state="unknown", reason="agent_identity_authority_unavailable"
                )
            if (
                identity.state == "resolved"
                and isinstance(identity.canonical_agent_entity_id, str)
                and identity.canonical_agent_entity_id
                and identity.evidence
            ):
                # Source/runtime references are useful only to the resolver.
                # Message and canonical fact joins use the resolved Agent entity.
                identity_ids = (identity.canonical_agent_entity_id,)
                scope = replace(
                    scope,
                    participant_entity_id=identity.canonical_agent_entity_id,
                    participant_identity_ids=identity_ids,
                    identity_resolution_state="resolved",
                    identity_evidence=identity.evidence,
                )
            else:
                scope = replace(
                    scope,
                    participant_entity_id=None,
                    participant_identity_ids=(),
                    identity_resolution_state=identity.state,
                    identity_evidence=identity.evidence,
                    bindable=False,
                    canonical_fact_bindable=False,
                    note=identity.reason or "agent_identity_unresolved",
                )
        elif request.subject.kind == "entity":
            try:
                identity = await self._entity_identity.resolve(tenant_id, request.subject.id)
            except Exception:  # noqa: BLE001 - fail closed on identity errors
                identity = EntityIdentityRead(
                    state="unknown", reason="entity_identity_authority_unavailable"
                )
            identity_evidence = tuple(
                ref
                for ref in identity.evidence
                if ref.id == request.subject.id
                and ref.type == "entity"
                and ref.source == "entity_registry"
            )
            if (
                identity.state == "resolved"
                and identity.canonical_entity_id == request.subject.id
                and identity_evidence
            ):
                scope = replace(
                    scope,
                    participant_entity_id=request.subject.id,
                    participant_identity_ids=(request.subject.id,),
                    identity_resolution_state="resolved",
                    identity_evidence=identity_evidence,
                )
            else:
                scope = replace(
                    scope,
                    participant_entity_id=None,
                    participant_identity_ids=(),
                    identity_resolution_state=identity.state,
                    identity_evidence=identity_evidence,
                    bindable=False,
                    canonical_fact_bindable=False,
                    note=identity.reason or "entity_identity_unresolved",
                )

        # Read the canonical fact store once (scope-matched below by family).
        identity_readable = (
            request.subject.kind not in {"agent", "entity"}
            or scope.identity_resolution_state == "resolved"
        )
        canonical_up, canonical_rows, canonical_truncated = (
            await self._read_canonical_rows(tenant_id, scope, limit=read_limit)
            if identity_readable
            else (True, [], False)
        )
        in_scope_rows = [r for r in canonical_rows if _row_matches_scope(r, tenant_id, scope)]
        journey_links = await self._read_journey_links(
            tenant_id,
            in_scope_rows,
            noncurrent_scope=_projection_requests_noncurrent_scope(request),
            canonical_up=canonical_up,
            canonical_truncated=canonical_truncated,
        )
        profile_links = await self._read_profile_links(
            tenant_id,
            in_scope_rows,
            noncurrent_scope=_projection_requests_noncurrent_scope(request),
            canonical_up=canonical_up,
            canonical_truncated=canonical_truncated,
        )

        # Read the message spine only when the subject binds to it.
        messages: list[CommunicationMessage] = []
        silver_up = True
        silver_truncated = False
        if scope.bindable:
            silver_up, messages, silver_truncated = await self._read_messages(
                tenant_id, scope, limit=read_limit
            )
            messages = [
                m
                for m in messages
                if str(m.tenant_id) == tenant_id and _message_matches_scope(m, scope)
            ]

        policy_state = await self._read_policy_state(
            request,
            messages,
            scope=scope,
            silver_up=silver_up,
            silver_truncated=silver_truncated,
        )
        risk_flags = await self._read_risk_flags(
            request,
            scope,
            messages=messages,
            silver_up=silver_up,
            silver_truncated=silver_truncated,
        )

        degraded_reasons: list[str] = []
        if not silver_up:
            degraded_reasons.append(REASON_SILVER_SOURCE_UNAVAILABLE)
        if not canonical_up:
            degraded_reasons.append(REASON_CANONICAL_SOURCE_UNAVAILABLE)
        if silver_truncated or canonical_truncated:
            degraded_reasons.append(REASON_SOURCE_READ_TRUNCATED)

        sections = [
            self._summary_section(
                request,
                scope,
                messages,
                silver_up,
                silver_truncated,
                in_scope_rows,
                canonical_up,
                canonical_truncated,
                context,
                journey_links,
                profile_links,
                risk_flags,
                policy_state,
            ),
            self._state_section(
                request,
                scope,
                messages,
                silver_up,
                canonical_up,
                in_scope_rows,
                silver_truncated,
                canonical_truncated,
                context,
            ),
            self._timeline_section(
                request,
                scope,
                messages,
                silver_up,
                silver_truncated,
                in_scope_rows,
                canonical_up,
                canonical_truncated,
            ),
            self._evidence_section(
                request,
                scope,
                messages,
                silver_up,
                in_scope_rows,
                canonical_up,
                silver_truncated,
                canonical_truncated,
            ),
            self._interactions_section(
                request,
                scope,
                in_scope_rows,
                canonical_up,
                canonical_truncated,
            ),
            self._outcomes_section(context),
        ]
        claims = self._build_claims(
            request,
            messages,
            in_scope_rows,
            scope,
            scope.identity_evidence,
        )
        claims.extend(self._journey_link_claims(request, journey_links))
        claims.extend(self._risk_flag_claims(request, risk_flags))
        if (
            request.subject.kind in {"agent", "entity"}
            and scope.identity_resolution_state != "resolved"
        ):
            degraded_reasons.append(scope.note or f"{request.subject.kind}_identity_unresolved")

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            generatedAt=_utc_now_iso(),
            degradedReasons=degraded_reasons,
        )

    # ── Defensive reads ────────────────────────────────────────────────────

    async def _read_policy_state(
        self,
        request: ProjectionRequest,
        messages: list[CommunicationMessage],
        *,
        scope: _Scope,
        silver_up: bool,
        silver_truncated: bool,
    ) -> ConsentPolicyRead:
        """Evaluate current consent only for exact, identity-bound recipients.

        Communication facts preserve the purpose and subject binding used at
        ingestion. The current consent decision always comes from the canonical
        server authority; a historical receipt is returned only as historical
        lineage and can never turn an unevaluated current state into an allow.
        """
        base: dict[str, Any] = {
            "coverage": "unknown",
            "reason": "no_exact_subject_linked_consent_purpose_observed",
            "evaluation": "current_server_consent_authority_for_exact_subject_purpose_pairs",
            "policyScope": "current_consent_only_for_exact_recipient_purposes",
            "currentPolicyState": "not_evaluated",
            "currentConsentState": "unknown",
            "nonConsentPolicyState": "unknown",
            "decisionEvidenceState": "not_persisted",
            "historicalDecisionCoverage": "unknown",
            "historicalDecisionCount": 0,
            "historicalDecisions": [],
            "currentDecisionCount": 0,
            "currentEvaluations": [],
            "evidenceRefs": [],
        }

        if _projection_requests_noncurrent_scope(request):
            base["reason"] = "current_consent_not_evaluated_for_historical_request"
            return ConsentPolicyRead("unknown", {"state": "unknown", **base})
        if not scope.bindable:
            base["reason"] = "message_subject_binding_unavailable_for_consent_policy"
            return ConsentPolicyRead("unknown", {"state": "unknown", **base})
        if not silver_up:
            base["coverage"] = "partial"
            base["reason"] = "communication_message_authority_unavailable_for_policy_inputs"
            return ConsentPolicyRead("degraded", {"state": "degraded", **base})

        inputs = _exact_consent_policy_inputs(messages, request.tenantId)
        if not inputs:
            if silver_truncated:
                base["coverage"] = "partial"
                base["reason"] = "communication_message_policy_inputs_truncated"
                return ConsentPolicyRead("degraded", {"state": "degraded", **base})
            base["historicalDecisionCoverage"] = "complete"
            return ConsentPolicyRead("unknown", {"state": "unknown", **base})

        pairs = sorted(inputs.items())[:_MAX_CONSENT_POLICY_READS]
        read_truncated = len(inputs) > _MAX_CONSENT_POLICY_READS
        evaluations: list[dict[str, Any]] = []
        current_refs: list[EvidenceRef] = []
        all_input_refs: list[EvidenceRef] = []
        historical_decisions: list[dict[str, Any]] = []
        authority_failed = False
        for (subject_id, purpose), evidence in pairs:
            evaluated_at = _utc_now_iso()
            all_input_refs.extend(evidence["inputEvidenceRefs"])
            all_input_refs.extend(evidence["historicalEvidenceRefs"])
            historical_decisions.append(
                {
                    "subjectEntityId": subject_id,
                    "purpose": purpose,
                    "messageIds": list(evidence["messageIds"]),
                    "outcomeAtCommunication": evidence["historicalOutcomeAtCommunication"],
                    "evidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in evidence["historicalEvidenceRefs"]
                    ],
                }
            )
            try:
                raw = await self._consent_policy.evaluate(
                    request.tenantId, subject_id, purpose
                )
            except Exception:  # noqa: BLE001 - do not leak authority details
                raw = None
                authority_failed = True

            allowed = (
                raw.get("allowed")
                if isinstance(raw, dict)
                else getattr(raw, "allowed", None)
            )
            reason_code = (
                raw.get("reason_code")
                if isinstance(raw, dict)
                else getattr(raw, "reason_code", None)
            )
            receipt_id = (
                raw.get("receipt_id")
                if isinstance(raw, dict)
                else getattr(raw, "receipt_id", None)
            )
            authority_refs: list[EvidenceRef] = []
            if allowed is True and isinstance(receipt_id, str) and receipt_id.strip():
                decision = "allowed"
                reason = None
                authority_refs.append(
                    EvidenceRef(
                        id=receipt_id,
                        type="event",
                        source="governance.consent.authority",
                        observedAt=evaluated_at,
                        uri=f"store://consent_receipts/{quote(receipt_id, safe='')}",
                    )
                )
            elif allowed is False:
                decision = "denied"
                reason = (
                    reason_code
                    if isinstance(reason_code, str) and reason_code
                    else "consent_denied"
                )
            else:
                decision = "unknown"
                reason = (
                    "consent_authority_unavailable"
                    if raw is None
                    else "consent_authority_returned_unverifiable_result"
                )
                authority_failed = True

            current_refs.extend(authority_refs)
            evaluations.append(
                {
                    "subjectEntityId": subject_id,
                    "purpose": purpose,
                    "messageIds": list(evidence["messageIds"]),
                    "decision": decision,
                    "reasonCode": reason,
                    "evaluatedAt": evaluated_at,
                    "policyDecisionEvidencePersisted": False,
                    "authorityEvidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in authority_refs
                    ],
                    "subjectEvidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in evidence["inputEvidenceRefs"]
                    ],
                }
            )

        decisions = {entry["decision"] for entry in evaluations}
        if decisions == {"allowed"}:
            current_consent_state = "allowed"
        elif decisions == {"denied"}:
            current_consent_state = "denied"
        elif decisions == {"unknown"}:
            current_consent_state = "unknown"
        elif "unknown" in decisions:
            current_consent_state = "partial"
        else:
            current_consent_state = "mixed"

        incomplete = authority_failed or read_truncated or silver_truncated
        slot_state = "degraded" if incomplete else "available"
        reason = (
            "consent_authority_unavailable_or_unverifiable_result"
            if authority_failed
            else "exact_consent_policy_inputs_truncated"
            if read_truncated or silver_truncated
            else "current_consent_evaluated_for_exact_subject_purpose_pairs_other_policy_unjoined"
        )
        all_refs = _dedupe_refs([*all_input_refs, *current_refs])
        historical_count = sum(
            item["outcomeAtCommunication"] == "allowed"
            for item in historical_decisions
        )
        content = {
            "state": slot_state,
            "coverage": "partial",
            "reason": reason,
            "evaluation": "current_server_consent_authority_for_exact_subject_purpose_pairs",
            "policyScope": "current_consent_only_for_exact_recipient_purposes",
            "currentPolicyState": "partial",
            "currentConsentState": current_consent_state,
            "nonConsentPolicyState": "unknown",
            "decisionEvidenceState": "not_persisted",
            "historicalDecisionCoverage": "partial",
            "historicalDecisionCount": historical_count,
            "historicalDecisions": historical_decisions,
            "currentDecisionCount": len(evaluations),
            "currentEvaluations": evaluations,
            "evidenceRefs": [
                ref.model_dump(mode="json", exclude_none=True) for ref in all_refs
            ],
        }
        return ConsentPolicyRead(slot_state, content)

    async def _read_risk_flags(
        self,
        request: ProjectionRequest,
        scope: _Scope,
        *,
        messages: list[CommunicationMessage],
        silver_up: bool,
        silver_truncated: bool,
    ) -> RiskFlagRead:
        """Read exact Risk360 subjects, with current-policy gates for recipient joins.

        For an entity subject, risk is read only when that same canonical entity
        is an exact, identity-bound communication recipient. The communication
        edge supplies identity context only: risk stays attached to the entity
        Risk360 names and is never propagated to the sender, campaign, or thread.
        """
        tenant_id = request.tenantId
        subject = request.subject
        if _projection_requests_noncurrent_scope(request):
            return RiskFlagRead("unknown", "risk_signal_temporal_lookup_unavailable")
        if subject.kind == "source":
            risk_subject = subject
            try:
                source_scope = await self._source_subject_scope.resolve(tenant_id, subject.id)
            except Exception:  # noqa: BLE001 - identity authority is fail-closed
                source_scope = SourceSubjectScopeRead(
                    tenant_id,
                    subject.id,
                    "degraded",
                    reason="source_identity_authority_unavailable",
                )
            if source_scope.tenant_id != tenant_id or source_scope.source_identity_id != subject.id:
                return RiskFlagRead(
                    "degraded",
                    "source_identity_scope_mismatch",
                    source_coverage_state="degraded",
                )
            if source_scope.state != "available" or not source_scope.canonical_entity_id:
                state = "degraded" if source_scope.state == "degraded" else "unknown"
                return RiskFlagRead(
                    state,
                    source_scope.reason or "source_identity_binding_unresolved",
                    source_coverage_state="degraded" if state == "degraded" else "unknown",
                )
            source_identity_refs = tuple(
                ref for ref in source_scope.evidence_refs if isinstance(ref, EvidenceRef)
            )
            if not source_identity_refs:
                return RiskFlagRead(
                    "unknown",
                    "source_identity_binding_evidence_missing",
                    source_coverage_state="unknown",
                )
            try:
                policy = await self._consent_policy.evaluate(
                    tenant_id, source_scope.canonical_entity_id, "analytics"
                )
            except Exception:  # noqa: BLE001 - consent authority is a fail-closed gate
                return RiskFlagRead(
                    "degraded",
                    "source_analytics_consent_authority_unavailable",
                    authority_refs=source_identity_refs,
                    source_coverage_state="degraded",
                )
            allowed = (
                policy.get("allowed")
                if isinstance(policy, dict)
                else getattr(policy, "allowed", None)
            )
            receipt_id = (
                policy.get("receipt_id")
                if isinstance(policy, dict)
                else getattr(policy, "receipt_id", None)
            )
            if allowed is not True or not isinstance(receipt_id, str) or not receipt_id.strip():
                return RiskFlagRead(
                    "suppressed" if allowed is False else "unknown",
                    "source_analytics_consent_not_established",
                    authority_refs=source_identity_refs,
                )
            authority_refs = _dedupe_refs(
                [
                    *source_identity_refs,
                    EvidenceRef(
                        id=receipt_id,
                        type="event",
                        source="governance.consent.authority",
                        observedAt=_utc_now_iso(),
                        uri=f"store://consent_receipts/{quote(receipt_id, safe='')}",
                    ),
                ]
            )
        elif (
            subject.kind == "agent"
            and scope.identity_resolution_state == "resolved"
            and scope.participant_entity_id
        ):
            risk_subject = ProjectionSubject(kind="agent", id=scope.participant_entity_id)
            agent_identity_refs = tuple(scope.identity_evidence)
            try:
                policy = await self._consent_policy.evaluate(
                    tenant_id, scope.participant_entity_id, "analytics"
                )
            except Exception:  # noqa: BLE001 - consent authority is a fail-closed gate
                return RiskFlagRead(
                    "degraded",
                    "agent_analytics_consent_authority_unavailable",
                    authority_refs=agent_identity_refs,
                    source_coverage_state="degraded",
                )
            allowed = (
                policy.get("allowed")
                if isinstance(policy, dict)
                else getattr(policy, "allowed", None)
            )
            receipt_id = (
                policy.get("receipt_id")
                if isinstance(policy, dict)
                else getattr(policy, "receipt_id", None)
            )
            policy_state = (
                policy.get("state")
                if isinstance(policy, dict)
                else getattr(policy, "state", None)
            )
            ambiguous = (
                policy.get("ambiguous") is True
                if isinstance(policy, dict)
                else getattr(policy, "ambiguous", None) is True
            ) or (isinstance(policy_state, str) and policy_state.strip().lower() == "ambiguous")
            # The canonical consent authority returns an affirmative receipt
            # only when the exact tenant/subject/purpose check succeeds. Any
            # denial, ambiguity, malformed result, or missing receipt blocks
            # the RiskSignal read.
            if (
                ambiguous
                or allowed is not True
                or not isinstance(receipt_id, str)
                or not receipt_id.strip()
            ):
                return RiskFlagRead(
                    "suppressed" if allowed is False else "unknown",
                    "agent_analytics_consent_not_established",
                    authority_refs=agent_identity_refs,
                )
            authority_refs = _dedupe_refs(
                [
                    *agent_identity_refs,
                    EvidenceRef(
                        id=receipt_id,
                        type="event",
                        source="governance.consent.authority",
                        observedAt=_utc_now_iso(),
                        uri=f"store://consent_receipts/{quote(receipt_id, safe='')}",
                    ),
                ]
            )
        elif (
            subject.kind == "entity"
            and scope.identity_resolution_state == "resolved"
            and scope.participant_entity_id == subject.id
        ):
            risk_subject = ProjectionSubject(kind="entity", id=subject.id)
        else:
            return RiskFlagRead(
                "unknown",
                "risk360_does_not_serve_this_communication_subject_kind_or_identity_is_unresolved",
            )

        if risk_subject.kind == "entity":
            return await self._read_recipient_risk_flags(
                request,
                scope,
                messages=messages,
                silver_up=silver_up,
                silver_truncated=silver_truncated,
            )

        try:
            rows = await self._risk_signals.signals(
                tenant_id=tenant_id,
                subject=risk_subject,
                limit=_MAX_RISK_SIGNAL_READS + 1,
            )
        except Exception:  # noqa: BLE001 - backing-source details stay private
            return RiskFlagRead(
                "degraded",
                "risk_signal_authority_unavailable",
                source_coverage_state="degraded",
            )
        if not isinstance(rows, list):
            return RiskFlagRead(
                "degraded",
                "risk_signal_authority_returned_invalid_rows",
                source_coverage_state="degraded",
            )

        signals: list[RiskSignal] = []
        invalid_rows = False
        for raw in rows[:_MAX_RISK_SIGNAL_READS]:
            if (
                not isinstance(raw, dict)
                or str(raw.get("tenant_id") or "") != tenant_id
                or str(raw.get("subject_kind") or "") != risk_subject.kind
                or str(raw.get("subject_id") or "") != risk_subject.id
            ):
                invalid_rows = True
                continue
            try:
                signal = RiskSignal(**raw)
            except Exception:  # noqa: BLE001 - skip malformed canonical record
                invalid_rows = True
                continue
            if not signal.evidence_refs:
                invalid_rows = True
                continue
            signals.append(signal)

        record_refs = [
            EvidenceRef(
                id=signal.signal_id,
                type="event",
                source="risk360/risk_signals",
                observedAt=(
                    signal.observed_at.isoformat() if signal.observed_at is not None else None
                ),
            )
            for signal in signals
        ]
        refs = _dedupe_refs(
            [*record_refs, *(ref for signal in signals for ref in signal.evidence_refs)]
        )
        refs = _dedupe_refs([*authority_refs, *refs])
        if len(rows) > _MAX_RISK_SIGNAL_READS or invalid_rows:
            return RiskFlagRead(
                "degraded",
                "risk_signal_read_truncated_or_contained_unscoped_records",
                tuple(refs),
                tuple(signals),
                tuple(authority_refs),
                "degraded",
            )
        if not signals:
            return RiskFlagRead("unknown", "no_exact_subject_risk_signal_observed")
        return RiskFlagRead(
            "available",
            "tenant_scoped_risk_signals_observed_for_exact_subject",
            tuple(refs),
            tuple(signals),
            tuple(authority_refs),
            "partial",
        )

    async def _read_recipient_risk_flags(
        self,
        request: ProjectionRequest,
        scope: _Scope,
        *,
        messages: list[CommunicationMessage],
        silver_up: bool,
        silver_truncated: bool,
    ) -> RiskFlagRead:
        """Join recipient risk only for the same resolved entity and current consent."""
        tenant_id = request.tenantId
        subject_id = request.subject.id
        base_authority_refs = tuple(
            ref
            for ref in scope.identity_evidence
            if ref.id == subject_id and ref.source == "entity_registry" and ref.type == "entity"
        )
        if scope.identity_resolution_state != "resolved" or not base_authority_refs:
            return RiskFlagRead(
                "unknown",
                "recipient_risk_requires_resolved_tenant_entity_identity",
                authority_refs=base_authority_refs,
            )
        if not silver_up:
            return RiskFlagRead(
                "degraded",
                "communication_recipient_identity_authority_unavailable",
                authority_refs=base_authority_refs,
                source_coverage_state="degraded",
            )

        candidates: dict[str, CommunicationMessage] = {}
        invalid_binding_seen = False
        for message in messages:
            if (
                message.tenant_id != tenant_id
                or message.recipient_entity_id != subject_id
                or not message.evidence_refs
            ):
                continue
            if not _has_exact_entity_binding(
                side="recipient",
                entity_id=message.recipient_entity_id,
                binding_id=message.recipient_identity_binding_id,
                evidence_ref=message.recipient_identity_evidence_ref,
                expected_entity_id=subject_id,
            ):
                invalid_binding_seen = True
                continue
            binding_id = message.recipient_identity_binding_id
            if isinstance(binding_id, str):
                candidates.setdefault(binding_id, message)
        if not candidates:
            if silver_truncated or invalid_binding_seen:
                return RiskFlagRead(
                    "degraded",
                    "communication_recipient_identity_coverage_incomplete",
                    authority_refs=base_authority_refs,
                    source_coverage_state="degraded",
                )
            return RiskFlagRead(
                "unknown",
                "exact_recipient_identity_not_observed",
                authority_refs=base_authority_refs,
            )

        candidate_items = sorted(candidates.items())
        read_truncated = len(candidate_items) > _MAX_RECIPIENT_RISK_IDENTITY_READS
        candidate_items = candidate_items[:_MAX_RECIPIENT_RISK_IDENTITY_READS]
        binding_refs: list[EvidenceRef] = []
        identity_incomplete = False
        resolved_binding_seen = False
        for binding_id, _message in candidate_items:
            try:
                binding = await self._recipient_identity.resolve(tenant_id, binding_id, subject_id)
            except Exception:  # noqa: BLE001 - identity details stay private
                binding = RecipientIdentityRead(
                    state="unknown", reason="recipient_identity_authority_unavailable"
                )
            valid_binding_refs = [
                ref
                for ref in binding.evidence
                if ref.id == binding_id
                and ref.type == "entity"
                and ref.source == "comms_provider_identities"
                and ref.uri == f"store://comms_provider_identities/{quote(binding_id, safe='')}"
            ]
            if (
                binding.state != "resolved"
                or binding.canonical_entity_id != subject_id
                or not valid_binding_refs
            ):
                identity_incomplete = True
                continue
            resolved_binding_seen = True
            binding_refs.extend(valid_binding_refs)

        if not resolved_binding_seen:
            return RiskFlagRead(
                "degraded" if identity_incomplete or read_truncated else "unknown",
                "recipient_identity_authority_unavailable_or_unresolved",
                authority_refs=base_authority_refs,
                source_coverage_state=(
                    "degraded" if identity_incomplete or read_truncated else "unknown"
                ),
            )

        try:
            policy = await self._consent_policy.evaluate(tenant_id, subject_id, "analytics")
        except Exception:  # noqa: BLE001 - consent authority is a fail-closed gate
            return RiskFlagRead(
                "degraded",
                "recipient_analytics_consent_authority_unavailable",
                authority_refs=_dedupe_refs([*base_authority_refs, *binding_refs]),
                source_coverage_state="degraded",
            )
        allowed = (
            policy.get("allowed") if isinstance(policy, dict) else getattr(policy, "allowed", None)
        )
        receipt_id = (
            policy.get("receipt_id")
            if isinstance(policy, dict)
            else getattr(policy, "receipt_id", None)
        )
        if allowed is not True or not isinstance(receipt_id, str) or not receipt_id.strip():
            return RiskFlagRead(
                "suppressed" if allowed is False else "unknown",
                "recipient_analytics_consent_not_established",
                authority_refs=_dedupe_refs([*base_authority_refs, *binding_refs]),
            )

        policy_ref = EvidenceRef(
            id=receipt_id,
            type="event",
            source="governance.consent.authority",
            observedAt=_utc_now_iso(),
            uri=f"store://consent_receipts/{quote(receipt_id, safe='')}",
        )
        authority_refs = _dedupe_refs([*base_authority_refs, *binding_refs, policy_ref])
        try:
            rows = await self._risk_signals.signals(
                tenant_id=tenant_id,
                subject=ProjectionSubject(kind="entity", id=subject_id),
                limit=_MAX_RISK_SIGNAL_READS + 1,
            )
        except Exception:  # noqa: BLE001 - backing-source details stay private
            return RiskFlagRead(
                "degraded",
                "risk_signal_authority_unavailable",
                tuple(authority_refs),
                authority_refs=tuple(authority_refs),
                source_coverage_state="degraded",
            )
        if not isinstance(rows, list):
            return RiskFlagRead(
                "degraded",
                "risk_signal_authority_returned_invalid_rows",
                tuple(authority_refs),
                authority_refs=tuple(authority_refs),
                source_coverage_state="degraded",
            )

        signals: list[RiskSignal] = []
        invalid_rows = False
        for raw in rows[:_MAX_RISK_SIGNAL_READS]:
            if (
                not isinstance(raw, dict)
                or str(raw.get("tenant_id") or "") != tenant_id
                or str(raw.get("subject_kind") or "") != "entity"
                or str(raw.get("subject_id") or "") != subject_id
            ):
                invalid_rows = True
                continue
            try:
                signal = RiskSignal(**raw)
            except Exception:  # noqa: BLE001 - malformed authority row stays degraded
                invalid_rows = True
                continue
            if not signal.evidence_refs:
                invalid_rows = True
                continue
            signals.append(signal)

        risk_record_refs = [
            EvidenceRef(
                id=signal.signal_id,
                type="event",
                source="risk360/risk_signals",
                observedAt=(
                    signal.observed_at.isoformat() if signal.observed_at is not None else None
                ),
            )
            for signal in signals
        ]
        refs = _dedupe_refs(
            [
                *authority_refs,
                *risk_record_refs,
                *(ref for signal in signals for ref in signal.evidence_refs),
            ]
        )
        incomplete = (
            len(rows) > _MAX_RISK_SIGNAL_READS
            or invalid_rows
            or read_truncated
            or identity_incomplete
            or silver_truncated
        )
        if incomplete:
            return RiskFlagRead(
                "degraded",
                "risk_signal_or_recipient_identity_coverage_incomplete",
                tuple(refs),
                tuple(signals),
                tuple(authority_refs),
                "degraded",
            )
        if not signals:
            return RiskFlagRead(
                "unknown",
                "no_exact_current_recipient_risk_signal_observed",
                tuple(refs),
                authority_refs=tuple(authority_refs),
            )
        return RiskFlagRead(
            "available",
            "exact_recipient_risk_signal_observed_under_current_analytics_consent",
            tuple(refs),
            tuple(signals),
            tuple(authority_refs),
            "partial",
        )

    def _risk_flag_claims(
        self, request: ProjectionRequest, read: RiskFlagRead
    ) -> list[ClaimEnvelope]:
        """Render risk signal records while preserving their epistemic status."""
        domain_slot_ids = _communication_slot_ids(
            request.subject.kind, {"risk_flags"}, {"evidence", "state"}
        )
        return [
            ClaimEnvelope(
                id=f"risk-signal.{signal.signal_id}",
                kind="communication_risk_signal_record",
                subject=request.subject,
                evidenceRefs=_dedupe_refs(
                    [
                        *read.authority_refs,
                        EvidenceRef(
                            id=signal.signal_id,
                            type="event",
                            source="risk360/risk_signals",
                            observedAt=(
                                signal.observed_at.isoformat()
                                if signal.observed_at is not None
                                else None
                            ),
                        ),
                        *signal.evidence_refs,
                    ]
                ),
                claims=[
                    f"Canonical risk signal {signal.signal_id} is recorded for this exact subject.",
                    f"Risk dimension: {signal.risk_dimension}; source: {signal.source}.",
                ],
                confidence=signal.confidence,
                claimState=signal.claim_state,
                domainSlotIds=domain_slot_ids,
            )
            for signal in read.signals
            if signal.evidence_refs
        ]

    async def _read_journey_links(
        self,
        tenant_id: str,
        rows: list[dict[str, Any]],
        *,
        noncurrent_scope: bool,
        canonical_up: bool,
        canonical_truncated: bool,
    ) -> JourneyLinkRead:
        """Resolve only explicit, evidence-backed journey IDs to current tenant rows."""
        refs_by_id: dict[str, list[EvidenceRef]] = {}
        invalid_reference = False
        for row in rows:
            raw_ids = _row_reference_values(row, "journey_id", "journey_ids")
            if not raw_ids:
                continue
            fact_ref = _row_evidence(row)
            if fact_ref is None:
                invalid_reference = True
                continue
            for raw_id in raw_ids:
                try:
                    journey_id = str(UUID(raw_id))
                except (ValueError, TypeError, AttributeError):
                    invalid_reference = True
                    continue
                refs = refs_by_id.setdefault(journey_id, [])
                if all(existing.id != fact_ref.id for existing in refs):
                    refs.append(fact_ref)

        source_refs = _dedupe_refs(
            [ref for refs in refs_by_id.values() for ref in refs]
            + [
                ref
                for row in rows
                if _row_reference_values(row, "journey_id", "journey_ids")
                and (ref := _row_evidence(row)) is not None
            ]
        )
        if not refs_by_id:
            if invalid_reference:
                return JourneyLinkRead(
                    "degraded", "typed_journey_reference_is_not_evidence_backed_or_canonical", tuple(source_refs)
                )
            if not canonical_up or canonical_truncated:
                return JourneyLinkRead(
                    "degraded",
                    REASON_CANONICAL_SOURCE_UNAVAILABLE
                    if not canonical_up
                    else REASON_SOURCE_READ_TRUNCATED,
                )
            return JourneyLinkRead("unknown", "communication_journey_link_not_observed")
        if noncurrent_scope:
            return JourneyLinkRead(
                "unknown", "historical_current_journey_lookup_unavailable", tuple(source_refs)
            )
        if not canonical_up or canonical_truncated:
            return JourneyLinkRead(
                "degraded",
                REASON_CANONICAL_SOURCE_UNAVAILABLE
                if not canonical_up
                else REASON_SOURCE_READ_TRUNCATED,
                tuple(source_refs),
            )

        journey_ids = list(refs_by_id)
        read_ids = journey_ids[:_MAX_JOURNEY_LINK_READS]
        truncated = len(journey_ids) > len(read_ids)
        semaphore = asyncio.Semaphore(8)

        async def read_one(journey_id: str) -> tuple[str, Optional[dict[str, Any]], bool]:
            async with semaphore:
                try:
                    row = await self._journeys.get_current(tenant_id, journey_id)
                except Exception:  # noqa: BLE001 - source details stay private
                    return journey_id, None, False
            return journey_id, row, True

        results = await asyncio.gather(*(read_one(journey_id) for journey_id in read_ids))
        links: list[tuple[str, EvidenceRef, EvidenceRef]] = []
        journey_refs: list[EvidenceRef] = []
        missing = False
        unavailable = False
        for journey_id, record, available in results:
            if not available:
                unavailable = True
                continue
            if record is None:
                missing = True
                continue
            if (
                not isinstance(record, dict)
                or str(record.get("tenant_id") or "") != tenant_id
                or str(record.get("journey_id") or "") != journey_id
                or record.get("is_current") is not True
            ):
                missing = True
                continue
            raw_version_id = record.get("journey_version_id")
            if not isinstance(raw_version_id, (str, UUID)) or not str(raw_version_id).strip():
                missing = True
                continue
            journey_version_id = str(raw_version_id)
            version_ref = EvidenceRef(
                id=journey_version_id,
                type="entity",
                source="services/api/journeys/measurement/journey_versions",
                observedAt=_state_value(record.get("computed_at")),
                uri=f"store://journey_versions/{journey_version_id}",
            )
            journey_refs.append(version_ref)
            for fact_ref in refs_by_id[journey_id]:
                links.append((journey_id, fact_ref, version_ref))

        all_refs = _dedupe_refs([*source_refs, *journey_refs])
        if unavailable or missing or invalid_reference or truncated:
            reason = (
                "current_journey_authority_unavailable"
                if unavailable
                else "explicit_journey_reference_not_resolved_to_current_tenant_record"
                if missing
                else "journey_link_read_truncated"
                if truncated
                else "one_or_more_typed_journey_references_not_canonical"
            )
            return JourneyLinkRead("degraded", reason, tuple(all_refs), tuple(links))
        return JourneyLinkRead(
            "available",
            "explicit_tenant_journey_reference_resolved_to_current_version",
            tuple(all_refs),
            tuple(links),
        )

    async def _read_profile_links(
        self,
        tenant_id: str,
        rows: list[dict[str, Any]],
        *,
        noncurrent_scope: bool,
        canonical_up: bool,
        canonical_truncated: bool,
    ) -> ProfileLinksRead:
        """Resolve direct profile IDs only when their communication fact has evidence."""
        refs_by_id: dict[str, list[EvidenceRef]] = {}
        ungrounded_ids: set[str] = set()
        overflow = False
        for row in rows:
            raw_ids = _row_reference_values(row, "profile_id", "profile_ids")
            if not raw_ids:
                continue
            fact_ref = _row_evidence(row)
            for profile_id in raw_ids:
                if profile_id not in refs_by_id and profile_id not in ungrounded_ids:
                    if len(refs_by_id) + len(ungrounded_ids) >= _MAX_PROFILE_LINK_READS:
                        overflow = True
                        continue
                if fact_ref is None:
                    ungrounded_ids.add(profile_id)
                    continue
                ungrounded_ids.discard(profile_id)
                refs = refs_by_id.setdefault(profile_id, [])
                if all(existing.id != fact_ref.id for existing in refs):
                    refs.append(fact_ref)

        source_refs = _dedupe_refs([ref for refs in refs_by_id.values() for ref in refs])
        if not canonical_up:
            return ProfileLinksRead(
                "degraded",
                "communication_profile_reference_authority_unavailable",
                tuple(source_refs),
            )

        missing_evidence_count = len(ungrounded_ids - set(refs_by_id))
        reference_ids = sorted(refs_by_id)
        if not reference_ids:
            if missing_evidence_count:
                return ProfileLinksRead(
                    "degraded", "profile_reference_evidence_missing", tuple(source_refs)
                )
            if canonical_truncated:
                return ProfileLinksRead(
                    "degraded", REASON_SOURCE_READ_TRUNCATED, tuple(source_refs)
                )
            return ProfileLinksRead(
                "unknown", "communication_profile_link_not_observed", tuple(source_refs)
            )

        if noncurrent_scope:
            links = tuple(
                {
                    "profileId": profile_id,
                    "resolutionState": "unknown",
                    "reason": "historical_profile_identity_lookup_unavailable",
                    "communicationEvidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in refs_by_id.get(profile_id, [])
                    ],
                    "identityEvidenceRefs": [],
                    "evidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in refs_by_id.get(profile_id, [])
                    ],
                    "temporalState": "unknown",
                    "freshnessState": "unknown",
                }
                for profile_id in reference_ids
            )
            incomplete = overflow or canonical_truncated or bool(missing_evidence_count)
            return ProfileLinksRead(
                "degraded" if incomplete else "unknown",
                REASON_SOURCE_READ_TRUNCATED
                if overflow or canonical_truncated
                else "profile_reference_evidence_missing"
                if missing_evidence_count
                else "historical_profile_identity_lookup_unavailable",
                tuple(source_refs),
                links,
            )

        read_ids = [profile_id for profile_id in reference_ids if profile_id in refs_by_id]
        read_ids = read_ids[:_MAX_PROFILE_LINK_READS]
        semaphore = asyncio.Semaphore(8)

        async def read_one(profile_id: str) -> tuple[str, ProfileLinkRead]:
            async with semaphore:
                try:
                    result = await self._profile_links.resolve(tenant_id, profile_id)
                except Exception:  # noqa: BLE001 - profile identity details stay private
                    result = ProfileLinkRead(
                        "degraded", reason="profile_identity_authority_unavailable"
                    )
            if not isinstance(result, ProfileLinkRead):
                result = ProfileLinkRead(
                    "degraded", reason="profile_identity_authority_invalid_response"
                )
            return profile_id, result

        results = await asyncio.gather(*(read_one(profile_id) for profile_id in read_ids))
        results_by_id = dict(results)
        links: list[dict[str, Any]] = []
        profile_refs: list[EvidenceRef] = []
        unresolved = False
        degraded = overflow or canonical_truncated or bool(missing_evidence_count)
        authority_unavailable = False

        for profile_id in reference_ids:
            communication_refs = refs_by_id.get(profile_id, [])
            read = results_by_id.get(profile_id)
            profile_evidence = [
                ref
                for ref in (read.evidence if read is not None else ())
                if read is not None
                and read.state == "resolved"
                and read.profile_id == profile_id
                and isinstance(ref, EvidenceRef)
                and ref.id == profile_id
                and ref.type == "entity"
                and ref.source == "identity.profiles"
            ]
            resolved = bool(
                read is not None
                and read.state == "resolved"
                and read.profile_id == profile_id
                and profile_evidence
            )
            reason = (
                "exact_tenant_profile_record_joined_to_typed_communication_reference"
                if resolved
                else read.reason
                if read is not None and isinstance(read.reason, str) and read.reason
                else "profile_identity_authority_read_limit_exceeded"
                if profile_id in refs_by_id and read is None
                else "profile_identity_reference_not_resolved"
            )
            if read is not None and read.state in {"degraded", "ambiguous"}:
                degraded = True
                authority_unavailable = authority_unavailable or read.state == "degraded"
            if not resolved:
                unresolved = True
            else:
                profile_refs.extend(profile_evidence)
            links.append(
                {
                    "profileId": profile_id,
                    "resolutionState": "resolved" if resolved else "unknown",
                    "reason": reason,
                    "communicationEvidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in communication_refs
                    ],
                    "identityEvidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in profile_evidence
                    ],
                    "evidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in _dedupe_refs([*communication_refs, *profile_evidence])
                    ],
                    "temporalState": "unknown",
                    "freshnessState": "unknown",
                }
            )

        all_refs = _dedupe_refs([*source_refs, *profile_refs])
        all_resolved = not unresolved and not degraded
        state = "available" if all_resolved else "degraded" if degraded else "unknown"
        reason = (
            "exact_tenant_profile_records_joined_to_evidence_backed_communication_references"
            if all_resolved
            else REASON_SOURCE_READ_TRUNCATED
            if canonical_truncated or overflow
            else "profile_reference_evidence_missing"
            if missing_evidence_count
            else "profile_identity_authority_unavailable"
            if authority_unavailable
            else "one_or_more_profile_references_lack_joinable_identity_evidence"
            if unresolved
            else "profile_identity_authority_unavailable"
        )
        return ProfileLinksRead(state, reason, tuple(all_refs), tuple(links))

    def _journey_link_claims(
        self, request: ProjectionRequest, read: JourneyLinkRead
    ) -> list[ClaimEnvelope]:
        """Ground successful joins in both the communication fact and journey version."""
        claims: list[ClaimEnvelope] = []
        domain_slot_ids = _communication_slot_ids(
            request.subject.kind, {"journey_links"}, {"evidence", "state"}
        )
        for journey_id, fact_ref, journey_ref in read.links:
            claims.append(
                ClaimEnvelope(
                    id=f"journey-link.{fact_ref.id}.{journey_id}",
                    kind="communication_journey_link",
                    subject=request.subject,
                    evidenceRefs=[fact_ref, journey_ref],
                    claims=[
                        f"Communication fact {fact_ref.id} explicitly references journey {journey_id}.",
                        f"A current journey version for {journey_id} exists in the same tenant.",
                    ],
                    confidence=1.0,
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=domain_slot_ids,
                )
            )
        return claims



    async def _read_messages(
        self, tenant_id: str, scope: _Scope, *, limit: int
    ) -> tuple[bool, list[CommunicationMessage], bool]:
        """Silver spine for the scope; (up, messages, truncated). Never raises."""
        try:
            messages = await self._silver.messages(
                tenant_id,
                campaign_id=scope.campaign_id,
                participant_entity_id=scope.participant_entity_id,
                limit=limit + 1,
            )
            rows = list(messages)
            return True, rows[:limit], len(rows) > limit
        except Exception:  # noqa: BLE001 - backing unavailable -> degrade
            return False, [], False

    async def _read_canonical_rows(
        self, tenant_id: str, scope: _Scope, *, limit: int
    ) -> tuple[bool, list[dict[str, Any]], bool]:
        """Canonical fact rows for the tenant; (up, rows, truncated). Never raises."""
        try:
            rows = await self._canonical.facts(tenant_id, limit=limit + 1)
            selected = [r for r in rows if isinstance(r, dict)]
            return True, selected[:limit], len(selected) > limit
        except Exception:  # noqa: BLE001 - backing unavailable -> degrade
            return False, [], False

    # ── Section builders ───────────────────────────────────────────────────

    def _summary_section(
        self,
        request: ProjectionRequest,
        scope: _Scope,
        messages: list[CommunicationMessage],
        silver_up: bool,
        silver_truncated: bool,
        rows: list[dict[str, Any]],
        canonical_up: bool,
        canonical_truncated: bool,
        context: ProjectionContext,
        journey_links: JourneyLinkRead,
        profile_links: ProfileLinksRead,
        risk_flags: RiskFlagRead,
        policy_state: ConsentPolicyRead,
    ) -> ProjectionSection:
        """Summary of a complete message scope or exact canonical fact scope."""
        fact_rows = _communication_fact_rows(rows)
        if not scope.bindable:
            if not scope.canonical_fact_bindable:
                state = "degraded"
                counts = None
                reasons = [scope.note or "canonical_fact_subject_binding_unavailable"]
            elif not canonical_up or canonical_truncated:
                state = "degraded"
                counts = None
                reasons = [
                    REASON_CANONICAL_SOURCE_UNAVAILABLE
                    if not canonical_up
                    else REASON_SOURCE_READ_TRUNCATED
                ]
            elif not fact_rows:
                state = "missing"
                counts = None
                reasons = [scope.note, "no_exact_scope_communication_facts_observed"]
            else:
                fact_kinds: dict[str, int] = {}
                for row in fact_rows:
                    kind = str(row.get("kind") or "unknown")
                    fact_kinds[kind] = fact_kinds.get(kind, 0) + 1
                state = "available"
                counts = {
                    "messages_total": None,
                    "communication_facts_total": len(fact_rows),
                    "communication_fact_kinds": fact_kinds,
                    "active_conversations": _canonical_open_state_count(
                        fact_rows,
                        kind="conversation",
                        expected_state="active",
                        known_states=frozenset({"active", "idle", "paused", "archived", "closed"}),
                    ),
                    "open_requests": _canonical_open_state_count(
                        fact_rows,
                        kind="request",
                        expected_state="open",
                        known_states=frozenset({"open", "resolved", "cancelled", "expired"}),
                    ),
                    "open_commitments": _canonical_open_state_count(
                        fact_rows,
                        kind="commitment",
                        expected_state="open",
                        known_states=frozenset({"open", "fulfilled", "broken", "cancelled"}),
                    ),
                }
                reasons = [scope.note]
        elif not silver_up:
            state = "degraded"
            counts = None
            reasons = [REASON_SILVER_SOURCE_UNAVAILABLE]
        elif silver_truncated:
            state = "degraded"
            counts = None
            reasons = [REASON_SOURCE_READ_TRUNCATED]
        else:
            state = "available"
            counts = self._summary_counts(
                messages,
                fact_rows if canonical_up and not canonical_truncated else [],
            )
            reasons = []
        return ProjectionSection(
            id="summary",
            state=state,  # type: ignore[arg-type]
            title="Communication summary",
            content={
                "tenantId": request.tenantId,
                "subject": {"kind": request.subject.kind, "id": request.subject.id},
                "scope": scope.as_dict(),
                "counts": counts,
                "reasons": reasons,
                "registryState": context.registryState,
                "sourceCompleteness": (
                    "partial"
                    if silver_truncated or canonical_truncated
                    else "bounded_read"
                    if scope.bindable
                    else "canonical_facts_only"
                    if scope.canonical_fact_bindable
                    else "not_read"
                ),
                "requiredSlotCoverage": _communication_required_slot_coverage(
                    request=request,
                    scope=scope,
                    messages=messages,
                    fact_rows=fact_rows,
                    silver_up=silver_up,
                    silver_truncated=silver_truncated,
                    canonical_up=canonical_up,
                    canonical_truncated=canonical_truncated,
                    journey_links=journey_links,
                    profile_links=profile_links,
                    risk_flags=risk_flags,
                    policy_state=policy_state,
                ),
            },
            warnings=reasons or None,
        )

    def _summary_counts(
        self,
        messages: list[CommunicationMessage],
        canonical_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Message counts plus explicit state counts from canonical fact rows."""
        channels: dict[str, int] = {}
        directions: dict[str, int] = {k: 0 for k in _DIRECTION_KEYS}
        states: dict[str, int] = {}
        engagement = {k: 0 for k in _ENGAGEMENT_STATES}
        for message in messages:
            channel = _state_value(message.channel) or "unclassified"
            channels[channel] = channels.get(channel, 0) + 1
            direction = _state_value(message.direction)
            if direction in directions:
                directions[direction] += 1
            else:
                directions["unclassified"] = directions.get("unclassified", 0) + 1
            state = _message_state_value(message)
            if state is not None:
                states[state] = states.get(state, 0) + 1
                if state in engagement:
                    engagement[state] += 1
        return {
            "messages_total": len(messages),
            "by_channel": channels,
            "by_direction": directions,
            "by_communication_state": states,
            "engagement": engagement,
            # These remain unknown when the canonical family is absent or a
            # state is untyped; only explicit stored states produce counts.
            "active_conversations": _canonical_open_state_count(
                canonical_rows,
                kind="conversation",
                expected_state="active",
                known_states=frozenset({"active", "idle", "paused", "archived", "closed"}),
            ),
            "open_requests": _canonical_open_state_count(
                canonical_rows,
                kind="request",
                expected_state="open",
                known_states=frozenset({"open", "resolved", "cancelled", "expired"}),
            ),
            "open_commitments": _canonical_open_state_count(
                canonical_rows,
                kind="commitment",
                expected_state="open",
                known_states=frozenset({"open", "fulfilled", "broken", "cancelled"}),
            ),
        }

    def _state_section(
        self,
        request: ProjectionRequest,
        scope: _Scope,
        messages: list[CommunicationMessage],
        silver_up: bool,
        canonical_up: bool,
        rows: list[dict[str, Any]],
        silver_truncated: bool,
        canonical_truncated: bool,
        context: ProjectionContext,
    ) -> ProjectionSection:
        """state — the six communication dimensions with typed states."""
        dimensions = [
            self._delivery_dimension(scope, messages, silver_up),
            self._engagement_dimension(scope, messages, silver_up),
            self._campaign_context_dimension(scope),
            self._information_dimension(scope, rows, canonical_up),
            self._knowledge_dimension(scope, rows, canonical_up),
            self._authority_dimension(scope, rows, canonical_up),
        ]
        for dimension in dimensions:
            name = dimension.get("dimension")
            affected = (silver_truncated and name in {"delivery", "engagement"}) or (
                canonical_truncated and name in {"information", "knowledge", "authority"}
            )
            if affected:
                dimension.update(
                    {
                        "state": "degraded",
                        "observed": None,
                        "breakdown": None,
                        "reason": REASON_SOURCE_READ_TRUNCATED,
                    }
                )
        section_state: str
        if (
            not scope.bindable
            or not silver_up
            or not canonical_up
            or silver_truncated
            or canonical_truncated
        ):
            section_state = "degraded"
        else:
            section_state = "available"
        return ProjectionSection(
            id="state",
            state=section_state,  # type: ignore[arg-type]
            title="Communication state",
            content={
                "tenantId": request.tenantId,
                "subject": {"kind": request.subject.kind, "id": request.subject.id},
                "dimensions": dimensions,
                "sourcePolicyContext": _source_policy_context(
                    request=request,
                    scope=scope,
                    messages=messages,
                    rows=rows,
                    silver_up=silver_up,
                    canonical_up=canonical_up,
                    silver_truncated=silver_truncated,
                    canonical_truncated=canonical_truncated,
                ),
                "registryState": context.registryState,
                "sourceCompleteness": (
                    "partial"
                    if silver_truncated or canonical_truncated
                    else "bounded_read"
                    if scope.bindable
                    else "canonical_facts_only"
                    if scope.canonical_fact_bindable
                    else "not_read"
                ),
            },
        )

    def _delivery_dimension(
        self, scope: _Scope, messages: list[CommunicationMessage], silver_up: bool
    ) -> dict[str, Any]:
        """delivery — the transport ladder (R4: delivery is not knowledge)."""
        if not scope.bindable:
            return self._degraded_dimension("delivery", scope.note)
        if not silver_up:
            return self._degraded_dimension("delivery", REASON_SILVER_SOURCE_UNAVAILABLE)
        by_state: dict[str, int] = {}
        for message in messages:
            state = _message_state_value(message)
            if state is not None:
                by_state[state] = by_state.get(state, 0) + 1
        return {
            "dimension": "delivery",
            "state": "available",
            "observed": len(messages),
            "breakdown": by_state,
            "reason": None,
        }

    def _engagement_dimension(
        self, scope: _Scope, messages: list[CommunicationMessage], silver_up: bool
    ) -> dict[str, Any]:
        """engagement — opened/clicked/replied signals (observed, never human intent)."""
        if not scope.bindable:
            return self._degraded_dimension("engagement", scope.note)
        if not silver_up:
            return self._degraded_dimension("engagement", REASON_SILVER_SOURCE_UNAVAILABLE)
        breakdown = {k: 0 for k in _ENGAGEMENT_STATES}
        observed = 0
        for message in messages:
            state = _message_state_value(message)
            if state in breakdown:
                breakdown[state] += 1
                observed += 1
        return {
            "dimension": "engagement",
            "state": "available",
            "observed": observed,
            "breakdown": breakdown,
            "reason": None,
        }

    def _campaign_context_dimension(self, scope: _Scope) -> dict[str, Any]:
        """campaign-context — the subject's campaign binding, never zeroed."""
        if scope.campaign_id is not None:
            return {
                "dimension": "campaign-context",
                "state": "available",
                "observed": None,
                "breakdown": {"campaignId": scope.campaign_id},
                "reason": None,
            }
        # episode/source: no Phase-4 campaign binding — not_applicable, never 0.
        return {
            "dimension": "campaign-context",
            "state": "not_applicable",
            "observed": None,
            "breakdown": None,
            "reason": scope.note or "no campaign binding for this subject scope",
        }

    def _information_dimension(
        self, scope: _Scope, rows: list[dict[str, Any]], canonical_up: bool
    ) -> dict[str, Any]:
        """information (R2) — separately-addressable content, observed only."""
        return self._fact_family_dimension(
            "information", scope, rows, canonical_up, _KINDS_INFORMATION
        )

    def _knowledge_dimension(
        self, scope: _Scope, rows: list[dict[str, Any]], canonical_up: bool
    ) -> dict[str, Any]:
        """knowledge (R4) — observed agent-side state; never granted by delivery."""
        return self._fact_family_dimension("knowledge", scope, rows, canonical_up, _KINDS_KNOWLEDGE)

    def _authority_dimension(
        self, scope: _Scope, rows: list[dict[str, Any]], canonical_up: bool
    ) -> dict[str, Any]:
        """authority — delegation-authority evaluations (Phase 5), observed only."""
        return self._fact_family_dimension("authority", scope, rows, canonical_up, _KINDS_AUTHORITY)

    def _fact_family_dimension(
        self,
        name: str,
        scope: _Scope,
        rows: list[dict[str, Any]],
        canonical_up: bool,
        kinds: frozenset[str],
    ) -> dict[str, Any]:
        """A canonical-fact dimension: available/observed | missing | degraded.

        ``missing`` (never zero) when the canonical store is reachable but holds
        no rows of this family for the scope — absent canonical objects are not
        evidence of a zero count, they are an unobserved family (Phase 5 lands
        most of these).
        """
        family = [r for r in rows if r.get("kind") in kinds]
        if not scope.canonical_fact_bindable:
            return self._degraded_dimension(
                name, scope.note or "canonical_fact_subject_binding_unavailable"
            )
        if not canonical_up:
            return self._degraded_dimension(name, REASON_CANONICAL_SOURCE_UNAVAILABLE)
        if not family:
            return {
                "dimension": name,
                "state": "missing",
                "observed": None,  # absent canonical objects are never a fabricated 0
                "breakdown": None,
                "reason": f"no {name} facts observed for this subject scope",
            }
        by_kind: dict[str, int] = {}
        for row in family:
            kind = str(row.get("kind") or "unknown")
            by_kind[kind] = by_kind.get(kind, 0) + 1
        return {
            "dimension": name,
            "state": "available",
            "observed": len(family),
            "breakdown": by_kind,
            "reason": None,
        }

    def _degraded_dimension(self, name: str, reason: Optional[str]) -> dict[str, Any]:
        return {
            "dimension": name,
            "state": "degraded",
            "observed": None,
            "breakdown": None,
            "reason": reason,
        }

    def _timeline_section(
        self,
        request: ProjectionRequest,
        scope: _Scope,
        messages: list[CommunicationMessage],
        silver_up: bool,
        silver_truncated: bool,
        rows: list[dict[str, Any]],
        canonical_up: bool,
        canonical_truncated: bool,
    ) -> ProjectionSection:
        """Timeline over joined messages or exact canonical facts, never causal."""
        if not scope.bindable:
            fact_rows = _communication_fact_rows(rows)
            entries = []
            undated_count = 0
            for row in fact_rows:
                occurred_at = row.get("occurred_at")
                if occurred_at is None or not str(occurred_at).strip():
                    undated_count += 1
                    continue
                evidence = _row_evidence(row)
                entries.append(
                    {
                        "factId": row.get("fact_id") or row.get("idempotency_key"),
                        "sourceEventId": row.get("source_event_id"),
                        "sourceEventType": row.get("source_event_type"),
                        "factKind": row.get("kind"),
                        "occurredAt": str(occurred_at),
                        "evidenceRefIds": [evidence.id] if evidence is not None else [],
                    }
                )
            entries.sort(key=lambda entry: (entry["occurredAt"], str(entry.get("factId") or "")))
            incomplete = (
                not scope.canonical_fact_bindable
                or not canonical_up
                or canonical_truncated
                or undated_count > 0
            )
            if not scope.canonical_fact_bindable:
                state = "degraded"
                warnings = [scope.note or "canonical_fact_subject_binding_unavailable"]
            elif not canonical_up:
                state = "degraded"
                warnings = [REASON_CANONICAL_SOURCE_UNAVAILABLE]
            elif canonical_truncated or undated_count:
                state = "degraded"
                warnings = [
                    REASON_SOURCE_READ_TRUNCATED
                    if canonical_truncated
                    else "canonical_communication_facts_missing_event_time"
                ]
            else:
                state = "available" if entries else "missing"
                warnings = [] if entries else ["no_exact_scope_communication_facts_observed"]
            source_completeness = (
                "not_read"
                if not scope.canonical_fact_bindable
                else "partial"
                if incomplete
                else "canonical_facts_only"
            )
            order = "occurred_at_ascending" if entries else None
        elif not silver_up:
            state = "degraded"
            entries = []
            warnings = [REASON_SILVER_SOURCE_UNAVAILABLE]
            source_completeness = "partial"
            order = None
        else:
            state = "degraded" if silver_truncated else "available"
            entries = sorted(
                (self._message_entry(m) for m in messages),
                key=lambda e: (str(e.get("occurredAt") or ""), str(e.get("messageId") or "")),
            )
            warnings = [REASON_SOURCE_READ_TRUNCATED] if silver_truncated else []
            source_completeness = "partial" if silver_truncated else "bounded_read"
            order = "occurred_at_ascending" if entries else None
        ordered = bool(entries)
        return ProjectionSection(
            id="timeline",
            state=state,  # type: ignore[arg-type]
            title="Communication timeline",
            content={
                "tenantId": request.tenantId,
                "subject": {"kind": request.subject.kind, "id": request.subject.id},
                "order": order if ordered else None,
                "orderLabeled": ordered,  # no entries -> sequence unlabeled
                "causalRelationsDeclared": [],  # no lineage field in Phase 4
                "causalNote": (
                    "causality is never inferred from timestamps alone; only "
                    "declared lineage fields can carry a causal relation"
                ),
                "entryCount": len(entries),
                "entries": entries,
                "sourceTruncated": (silver_truncated if scope.bindable else canonical_truncated),
                "sourceCompleteness": source_completeness,
            },
            warnings=warnings or None,
        )

    def _message_entry(self, message: CommunicationMessage) -> dict[str, Any]:
        return {
            "messageId": message.message_id,
            "factId": message.fact_id,
            "occurredAt": message.occurred_at,
            "communicationState": _message_state_value(message),
            "direction": _state_value(message.direction),
            "channel": _state_value(message.channel),
            "campaignId": message.campaign_id,
            "senderEntityId": (
                message.sender_entity_id if message.sender_identity_binding_id else None
            ),
            "recipientEntityId": (
                message.recipient_entity_id if message.recipient_identity_binding_id else None
            ),
            "claimState": _state_value(message.claim_state),
            "evidenceRefIds": [ref.id for ref in message.evidence_refs],
            "recipientIdentityBindingId": message.recipient_identity_binding_id,
            "recipientIdentityEvidenceRefId": (
                message.recipient_identity_evidence_ref.id
                if message.recipient_identity_evidence_ref is not None
                else None
            ),
            "senderIdentityBindingId": message.sender_identity_binding_id,
            "senderIdentityEvidenceRefId": (
                message.sender_identity_evidence_ref.id
                if message.sender_identity_evidence_ref is not None
                else None
            ),
            "consentEvidence": message.consent_evidence.model_dump(mode="json"),
        }

    def _evidence_section(
        self,
        request: ProjectionRequest,
        scope: _Scope,
        messages: list[CommunicationMessage],
        silver_up: bool,
        rows: list[dict[str, Any]],
        canonical_up: bool,
        silver_truncated: bool,
        canonical_truncated: bool,
    ) -> ProjectionSection:
        """evidence — every reused EvidenceRef grounding the sequence, deduped."""
        refs: list[EvidenceRef] = list(scope.identity_evidence)
        for message in messages:
            refs.extend(message.evidence_refs)
            if message.recipient_identity_evidence_ref is not None:
                refs.append(message.recipient_identity_evidence_ref)
            if message.sender_identity_evidence_ref is not None:
                refs.append(message.sender_identity_evidence_ref)
            refs.extend(message.consent_evidence.evidence_refs)
        for row in rows:
            ref = _row_evidence(row)
            if ref is not None:
                refs.append(ref)
        deduped = _dedupe_refs(refs)
        state = "available"
        if (
            not scope.canonical_fact_bindable
            or (scope.bindable and (not silver_up or silver_truncated))
            or not canonical_up
            or canonical_truncated
        ):
            # A partial ref set — the unavailable store's refs cannot be read.
            state = "degraded"
        elif not deduped:
            state = "empty"
        return ProjectionSection(
            id="evidence",
            state=state,  # type: ignore[arg-type]
            title="Evidence",
            content={
                "tenantId": request.tenantId,
                "subject": {"kind": request.subject.kind, "id": request.subject.id},
                "count": len(deduped),
                "evidence": [ref.model_dump(mode="json") for ref in deduped],
                "sourceTruncated": silver_truncated or canonical_truncated,
                "sourceCompleteness": (
                    "not_read"
                    if not scope.canonical_fact_bindable
                    else "partial"
                    if silver_truncated or canonical_truncated
                    else "bounded_read"
                ),
            },
        )

    def _interactions_section(
        self,
        request: ProjectionRequest,
        scope: _Scope,
        rows: list[dict[str, Any]],
        canonical_up: bool,
        canonical_truncated: bool,
    ) -> ProjectionSection:
        """interactions — tenant-bound canonical communication records."""
        if not scope.canonical_fact_bindable:
            state = "degraded"
            interactions: list[dict[str, Any]] = []
            warnings = [scope.note or "canonical_fact_subject_binding_unavailable"]
        elif not canonical_up:
            state = "degraded"
            interactions: list[dict[str, Any]] = []
            warnings = [REASON_CANONICAL_SOURCE_UNAVAILABLE]
        else:
            interactions = [
                self._interaction_row(r) for r in rows if r.get("kind") in _KINDS_INTERACTIONS
            ]
            state = (
                "degraded" if canonical_truncated else "available" if interactions else "missing"
            )
            warnings = [REASON_SOURCE_READ_TRUNCATED] if canonical_truncated else []
        return ProjectionSection(
            id="interactions",
            state=state,  # type: ignore[arg-type]
            title="Interactions",
            content={
                "tenantId": request.tenantId,
                "subject": {"kind": request.subject.kind, "id": request.subject.id},
                "scope": scope.as_dict(),
                "count": len(interactions),
                "interactions": interactions,
                "sourceTruncated": canonical_truncated,
                "sourceCompleteness": (
                    "not_read"
                    if not scope.canonical_fact_bindable
                    else "partial"
                    if canonical_truncated
                    else "bounded_read"
                ),
            },
            warnings=warnings or None,
        )

    def _interaction_row(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = _payload_of(row)
        kind = str(row.get("kind") or "unknown")
        evidence = _row_evidence(row)
        base = {
            "interactionId": row.get("fact_id") or row.get("idempotency_key"),
            "kind": kind,
            "occurredAt": row.get("occurred_at"),
            "actorId": row.get("actor_id"),
            "agentId": row.get("agent_id"),
            "sourceEventId": row.get("source_event_id"),
            "claimState": _state_value(row.get("claim_state")) or "observed",
            "evidenceRefIds": [evidence.id] if evidence is not None else [],
            # These are typed relationship references from the canonical fact
            # envelope/payload. Keep IDs only; do not expose arbitrary payloads.
            "campaignIds": _row_reference_values(row, "campaign_id", "campaign_ids"),
            "episodeIds": _row_reference_values(row, "episode_id", "episode_ids"),
            "journeyIds": _row_reference_values(row, "journey_id", "journey_ids"),
            "profileIds": _row_reference_values(row, "profile_id", "profile_ids"),
            "messageIds": _row_reference_values(row, "message_id", "message_ids"),
            "threadIds": _row_reference_values(row, "thread_id", "thread_ids"),
        }
        if kind == "communication_act":
            base["actType"] = payload.get("act_type")
            base["targetEntityId"] = payload.get("target_entity_id")
            base["objectRef"] = payload.get("object_ref")
            base["messageId"] = payload.get("message_id")
            base["conversationId"] = payload.get("conversation_id")
        elif kind == "participant_binding":
            binding_evidence_refs = _trusted_participant_source_evidence(row)
            if binding_evidence_refs:
                base["evidenceRefIds"] = [
                    ref.id
                    for ref in _dedupe_refs(
                    [
                        *([evidence] if evidence is not None else []),
                        *binding_evidence_refs,
                    ]
                    )
                ]
                base["sourceRosterState"] = payload.get("roster_completeness_state")
                base["sourceProvider"] = payload.get("provider")
                base["sourceProviderAccountId"] = payload.get("provider_account_id")
                base["providerConversationId"] = payload.get("provider_conversation_id")
            base["role"] = payload.get("role")
            base["entityId"] = payload.get("entity_id") or row.get("actor_id")
            base["entityType"] = payload.get("entity_type")
            base["communicationScope"] = payload.get("communication_scope")
            base["communicationScopeKind"] = payload.get("communication_scope_kind")
            base["principalEntityId"] = payload.get("principal_entity_id")
            base["delegationGrantId"] = payload.get("delegation_grant_id")
            base["validFrom"] = payload.get("valid_from")
            base["validTo"] = payload.get("valid_to")
        elif kind == "conversation":
            base["conversationId"] = payload.get("conversation_id") or base["interactionId"]
            base["conversationKind"] = payload.get("kind")
            base["providerThreadIds"] = payload.get("provider_thread_ids") or []
            base["messageIds"] = payload.get("message_ids") or []
            base["matterId"] = payload.get("matter_id")
            base["conversationState"] = payload.get("state")
            base["openedAt"] = payload.get("opened_at")
            base["lastActivityAt"] = payload.get("last_activity_at")
        elif kind == "provider_thread":
            base["threadId"] = payload.get("thread_id") or base["interactionId"]
            base["provider"] = payload.get("provider")
            base["providerAccountId"] = payload.get("provider_account_id")
            base["messageIds"] = payload.get("message_ids") or []
            base["firstSeenAt"] = payload.get("first_seen_at")
            base["lastSeenAt"] = payload.get("last_seen_at")
        elif kind == "matter":
            base["matterId"] = payload.get("matter_id") or base["interactionId"]
            base["matterKind"] = payload.get("kind")
            base["conversationIds"] = payload.get("conversation_ids") or []
            base["campaignIds"] = payload.get("campaign_ids") or []
            base["episodeIds"] = payload.get("episode_ids") or []
            base["createdAt"] = payload.get("created_at")
            base["updatedAt"] = payload.get("updated_at")
        elif kind == "request":
            base["requesterEntityId"] = payload.get("requester_entity_id")
            base["assigneeEntityId"] = payload.get("assignee_entity_id")
            base["requestState"] = payload.get("state")
            base["actId"] = payload.get("act_id")
            base["deadline"] = payload.get("deadline")
            base["resolvedAt"] = payload.get("resolved_at")
        elif kind == "commitment":
            base["committerEntityId"] = payload.get("committer_entity_id")
            base["beneficiaryEntityId"] = payload.get("beneficiary_entity_id")
            base["commitmentState"] = payload.get("state")
            base["actId"] = payload.get("act_id")
            base["dueAt"] = payload.get("due_at")
        elif kind == "response_expectation":
            base["expectationType"] = payload.get("expectation_type")
            base["communicationRef"] = payload.get("communication_ref")
            base["expectationState"] = payload.get("state")
            base["dueAt"] = payload.get("due_at")
        elif kind == "information":
            base["informationId"] = payload.get("information_id") or base["interactionId"]
            base["informationKind"] = payload.get("kind")
        elif kind == "information_transformation":
            source = payload.get("source_information_ref")
            derived = payload.get("derived_information_ref")
            base["transformationKind"] = payload.get("kind")
            base["sourceInformationId"] = (
                source.get("information_id") if isinstance(source, dict) else None
            )
            base["derivedInformationId"] = (
                derived.get("information_id") if isinstance(derived, dict) else None
            )
            base["agentEntityId"] = payload.get("agent_entity_id")
        elif kind == "knowledge_state":
            base["subjectEntityId"] = payload.get("subject_entity_id")
            base["knowledgeState"] = payload.get("state")
            base["knownSince"] = payload.get("known_since")
            base["observedAt"] = payload.get("observed_at")
        elif kind == "interpretation":
            base["agentEntityId"] = payload.get("agent_entity_id")
            base["informationRef"] = payload.get("information_ref")
            base["confidence"] = payload.get("confidence")
        elif kind == "context_inclusion":
            base["agentEntityId"] = payload.get("agent_entity_id")
            base["contextRef"] = payload.get("context_ref")
            base["included"] = payload.get("included")
            base["includedAt"] = payload.get("included_at")
            base["sourceObservationId"] = payload.get("source_observation_id")
        elif kind == "authority_evaluation":
            base["agentEntityId"] = payload.get("agent_entity_id")
            base["communicationScope"] = payload.get("communication_scope")
            base["communicationScopeKind"] = payload.get("communication_scope_kind")
            base["delegationGrantId"] = payload.get("delegation_grant_id")
            base["authorityDecision"] = payload.get("decision")
            base["evaluatedAt"] = payload.get("evaluated_at")
        elif kind == "provider_capability":
            base["provider"] = payload.get("provider")
            base["providerAccountId"] = payload.get("provider_account_id")
            base["capabilities"] = payload.get("capabilities") or {}
        elif kind == "communication_quality":
            base["communicationRef"] = payload.get("communication_ref")
            base["communicationScopeKind"] = payload.get("communication_scope_kind")
            base["completeness"] = payload.get("completeness")
            base["qualityState"] = payload.get("state")
            base["degradedReasons"] = payload.get("degraded_reasons") or []
        return base

    def _outcomes_section(self, context: ProjectionContext) -> ProjectionSection:
        """outcomes — degraded until outcome360 links land; never a redefinition."""
        deps = list(context.dependencyState)
        outcome_dep = next((d for d in deps if d.projectionId == "outcome360"), None)
        content: dict[str, Any] = {
            "tenantId": context.tenantId,
            "outcomeLinks": None,
            "dependencies": [
                {
                    "projectionId": d.projectionId,
                    "state": d.state,
                    "reason": d.reason,
                }
                for d in deps
            ],
        }
        if outcome_dep is None or outcome_dep.state != "available":
            state = "degraded"
            reason = (
                "outcome360 dependency is not yet available; communication-linked "
                "outcomes degrade until the outcome360 slice (and its links) lands"
            )
            warnings: Optional[list[str]] = [reason]
        else:
            # outcome360 is available, but this Phase-4 provider has no outcome-
            # link reader — no links are declared in the communication360 fact
            # store for the scope. not_applicable, never a fabricated 0.
            state = "not_applicable"
            reason = (
                "no outcome links are declared in the communication360 fact "
                "store for this scope (outcome linking is a Phase-6 surface)"
            )
            content["outcomeLinks"] = []
            warnings = [reason]
        content["reason"] = reason
        return ProjectionSection(
            id="outcomes",
            state=state,  # type: ignore[arg-type]
            title="Communication outcomes",
            content=content,
            warnings=warnings,
        )

    # ── Claims ─────────────────────────────────────────────────────────────

    def _build_claims(
        self,
        request: ProjectionRequest,
        messages: list[CommunicationMessage],
        canonical_rows: list[dict[str, Any]],
        scope: _Scope,
        identity_evidence: tuple[EvidenceRef, ...] = (),
    ) -> list[ClaimEnvelope]:
        """Build observed claims for evidenced messages and canonical facts.

        Every claim is capped at ``observed``, carries its reused EvidenceRefs,
        and never infers causality / knowledge from delivery. Claims receive
        only the exact Communications360 slots bound to their evidence family.
        A record without a reusable evidence ref is shown in its section but
        not asserted as a claim (requiresEvidence).
        """
        claims: list[ClaimEnvelope] = []
        subject = ProjectionSubject(kind=request.subject.kind, id=request.subject.id)
        for message in messages:
            refs = _dedupe_refs(
                [
                    *identity_evidence,
                    *message.evidence_refs,
                    *(
                        [message.sender_identity_evidence_ref]
                        if message.sender_identity_evidence_ref is not None
                        else []
                    ),
                    *(
                        [message.recipient_identity_evidence_ref]
                        if message.recipient_identity_evidence_ref is not None
                        else []
                    ),
                ]
            )
            if not refs:
                continue
            state = _message_state_value(message)
            state_line = (
                f"communication state: {state}"
                if state is not None
                else "communication state: unclassified"
            )
            message_slots = {"message_inventory", "evidence_trace"}
            claim_text = [
                f"message {message.message_id} observed",
                state_line,
            ]
            if request.subject.kind == "campaign" and message.campaign_id == request.subject.id:
                message_slots.add("campaign_links")
                claim_text.append(f"message {message.message_id} is linked to this campaign")
            if request.subject.kind == "entity":
                message_slots.add("communications")
                claim_text.append(
                    f"message {message.message_id} has an exact identity-bound endpoint for this entity"
                )
            is_agent_author = bool(
                request.subject.kind == "agent"
                and scope.identity_resolution_state == "resolved"
                and message.sender_entity_id in scope.participant_identity_ids
                and message.sender_identity_binding_id
                and message.sender_identity_evidence_ref is not None
            )
            if is_agent_author:
                message_slots.add("agent_authorship")
                claim_text.append("the message sender has an observed agent identity binding")
            domain_slot_ids = _communication_slot_ids(
                request.subject.kind,
                message_slots,
                {"timeline", "evidence"},
            )
            claims.append(
                ClaimEnvelope(
                    id=f"timeline.{message.message_id}",
                    kind="communication_sequence",
                    subject=subject,
                    evidenceRefs=refs,
                    claims=claim_text,
                    confidence=1.0,
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=domain_slot_ids,
                )
            )
        for row in _communication_fact_rows(canonical_rows):
            evidence = _row_evidence(row)
            if evidence is None:
                continue
            fact_id = row.get("fact_id") or row.get("idempotency_key") or row.get("source_event_id")
            if not fact_id:
                continue
            fact_kind = str(row.get("kind") or "unknown")
            domain_slot_ids = _canonical_communication_slot_ids(
                request.subject.kind,
                request.subject.id,
                row,
            )
            payload = _payload_of(row)
            claim_text = [
                f"canonical communication fact {fact_id} recorded",
                f"canonical communication fact kind: {fact_kind}",
            ]
            campaign_ids = _row_reference_values(row, "campaign_id", "campaign_ids")
            if request.subject.kind == "campaign" and request.subject.id in campaign_ids:
                claim_text.append(f"canonical communication fact references campaign {request.subject.id}")
            journey_ids = _row_reference_values(row, "journey_id", "journey_ids")
            if request.subject.kind == "journey" and request.subject.id in journey_ids:
                claim_text.append(f"canonical communication fact references journey {request.subject.id}")
            if fact_kind in {"conversation", "provider_thread"}:
                claim_text.append(f"canonical {fact_kind} record {fact_id} observed")
            if fact_kind == "participant_binding":
                claim_text.append("canonical communication participant binding observed")
                if _trusted_participant_source_evidence(row):
                    claim_text.append(
                        "provider-authenticated participant role assertion and source evidence observed"
                    )
                is_agent_author = (
                    request.subject.kind == "agent"
                    and str(payload.get("role") or "").strip().lower() == "author"
                    and (
                        str(payload.get("entity_type") or "").strip().lower() == "agent"
                        or bool(payload.get("agent_id"))
                        or bool(row.get("agent_id"))
                    )
                )
                if is_agent_author:
                    claim_text.append("canonical participant binding records agent authorship")
            if (
                fact_kind == "communication_act"
                and str(payload.get("act_type") or "").strip().lower()
                in {"acknowledge", "reply", "replied", "respond", "responded"}
            ):
                claim_text.append(
                    f"canonical response act type: {str(payload.get('act_type')).strip().lower()}"
                )
            claims.append(
                ClaimEnvelope(
                    id=f"canonical_fact.{fact_id}",
                    kind="communication_fact_observation",
                    subject=subject,
                    evidenceRefs=_dedupe_refs(
                        [
                            *scope.identity_evidence,
                            evidence,
                            *(
                                _trusted_participant_source_evidence(row)
                                if fact_kind == "participant_binding"
                                else []
                            ),
                        ]
                    ),
                    claims=claim_text,
                    confidence=1.0,
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=domain_slot_ids,
                )
            )
        return claims


def register_provider(registry: ProviderRegistry) -> None:
    """Register :class:`Communication360Provider` on a provider registry.

    Deliberately NOT called at import time: the global ``projection_registry``
    is only mutated by the runtime wiring layer, never by provider modules.
    """
    registry.register(Communication360Provider(), source="services/api/journeys/communication360")


__all__ = [
    "Communication360Provider",
    "OUTPUT_SECTIONS",
    "REASON_CANONICAL_SOURCE_UNAVAILABLE",
    "REASON_SILVER_SOURCE_UNAVAILABLE",
    "register_provider",
]
