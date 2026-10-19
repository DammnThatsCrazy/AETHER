"""Communication360 intelligence-projection provider (Phase 4).

``communication360`` is an intelligence projection over canonical Aether
communication truth — never a competing system of record (ADR-010). This
provider projects the *communication + information-flow* domain for a subject
of kind ``campaign`` / ``episode`` / ``source`` from the Phase-2/3 canonical
surface: the shipped message spine (``services/api/journeys/comms`` silver path, read
through :class:`SilverCommsSource`) and the Phase-3 canonical-authority fact
store (``services/api/journeys/communication360`` :class:`CanonicalFactSource`).

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
``interactions`` ``{count, interactions}`` — communication_act /
              participant_binding facts bound to the subject scope.
``outcomes``  ``{outcomeLinks | None, dependencies, reason}`` — degraded until
              the outcome360 slice (and its links) lands; never a redefinition
              of Outcome.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol, Union

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
    {"agent", "campaign", "episode", "journey", "source"}
)

# Typed degraded-reason codes surfaced on ``result.degradedReasons`` (short
# strings only — NEVER an exception body / secret detail). Provider-side only:
# sibling-dependency degradation is section-level, mirroring Economic360.
REASON_SILVER_SOURCE_UNAVAILABLE = "silver_source_unavailable"
REASON_CANONICAL_SOURCE_UNAVAILABLE = "canonical_source_unavailable"
REASON_SOURCE_READ_TRUNCATED = "communication_source_read_truncated"
_DEFAULT_READ_LIMIT = 100
_MAX_READ_LIMIT = 500

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

# Canonical fact ``kind`` discriminators each state dimension / section reads.
_KINDS_INFORMATION = frozenset({"information", "information_transformation"})
_KINDS_KNOWLEDGE = frozenset({"knowledge_state", "context_inclusion", "interpretation"})
_KINDS_AUTHORITY = frozenset({"authority_evaluation"})
_KINDS_INTERACTIONS = frozenset({"communication_act", "participant_binding"})

# Engagement states are a strict subset of the delivery ladder.
_ENGAGEMENT_STATES: tuple[str, ...] = ("opened", "clicked", "replied")
_DIRECTION_KEYS: tuple[str, ...] = (
    "outbound",
    "inbound",
    "internal",
    "system_generated",
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
        "campaign": {"campaign_id"},
        "episode": {"episode_id"},
        "journey": {"journey_id"},
        "source": {"source_id", "source_namespace", "provider_id"},
    }.get(scope.kind, set())
    reference_ids = scope.participant_identity_ids if scope.kind == "agent" else (scope.id,)
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
            if key in keys and not isinstance(item, (dict, list)) and str(item or "") == reference:
                return True
            if _payload_has_exact_reference(item, keys, reference):
                return True
    elif isinstance(value, list):
        return any(_payload_has_exact_reference(item, keys, reference) for item in value)
    return False


def _message_matches_scope(message: CommunicationMessage, scope: _Scope) -> bool:
    if scope.kind == "campaign":
        return str(message.campaign_id or "") == scope.id
    if scope.kind == "agent":
        return bool(
            set(scope.participant_identity_ids)
            & {message.sender_entity_id, message.recipient_entity_id}
        )
    return False


def _communication_slot_ids() -> list[str]:
    """Catalog slots whose declared authority and section binding cover messages."""
    result: set[str] = set()
    relevant_sections = {"evidence", "interactions", "timeline"}
    for surface in PRODUCT_360_SURFACE_DEFINITIONS.values():
        if not isinstance(surface, dict):
            continue
        for slot in surface.get("domainSlots", []):
            if not isinstance(slot, dict):
                continue
            authorities = set(slot.get("canonicalAuthorityRefs", []))
            if not authorities.intersection({"communication_facts", "campaign_touchpoints"}):
                continue
            for binding in slot.get("projectionBindings", []):
                if (
                    not isinstance(binding, dict)
                    or binding.get("projectionId") != "communication360"
                ):
                    continue
                if not set(binding.get("sectionIds", [])).intersection(relevant_sections):
                    continue
                slot_id = slot.get("id")
                if isinstance(slot_id, str):
                    result.add(slot_id)
    return sorted(result)


def _communication_fact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep canonical communication families for non-message subject timelines."""
    kinds = _KINDS_INFORMATION | _KINDS_KNOWLEDGE | _KINDS_AUTHORITY | _KINDS_INTERACTIONS
    return [row for row in rows if row.get("kind") in kinds]


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

        # Read the canonical fact store once (scope-matched below by family).
        identity_readable = (
            request.subject.kind != "agent" or scope.identity_resolution_state == "resolved"
        )
        canonical_up, canonical_rows, canonical_truncated = (
            await self._read_canonical_rows(tenant_id, scope, limit=read_limit)
            if identity_readable
            else (True, [], False)
        )
        in_scope_rows = [r for r in canonical_rows if _row_matches_scope(r, tenant_id, scope)]

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
        claims = self._build_claims(request, messages, scope.identity_evidence)
        if request.subject.kind == "agent" and scope.identity_resolution_state != "resolved":
            degraded_reasons.append(scope.note or "agent_identity_unresolved")

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
    ) -> ProjectionSection:
        """Summary of a complete message scope or exact canonical fact scope."""
        if not scope.bindable:
            fact_rows = _communication_fact_rows(rows)
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
            counts = self._summary_counts(messages)
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
            },
            warnings=reasons or None,
        )

    def _summary_counts(self, messages: list[CommunicationMessage]) -> dict[str, Any]:
        """Fully-enumerated real counts over the reachable message spine."""
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
            # Honest absence — conversation resolution (Phase 6) and the
            # request/commitment surface (Phase 5) land later; never a 0.
            "active_conversations": None,
            "open_requests": None,
            "open_commitments": None,
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
        """interactions — participant/act rows bound to the subject scope."""
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
        base = {
            "interactionId": row.get("fact_id") or row.get("idempotency_key"),
            "kind": kind,
            "occurredAt": row.get("occurred_at"),
            "actorId": row.get("actor_id"),
            "agentId": row.get("agent_id"),
            "sourceEventId": row.get("source_event_id"),
            "claimState": _state_value(row.get("claim_state")) or "observed",
        }
        if kind == "communication_act":
            base["actType"] = payload.get("act_type")
            base["targetEntityId"] = payload.get("target_entity_id")
            base["objectRef"] = payload.get("object_ref")
        elif kind == "participant_binding":
            base["role"] = payload.get("role")
            base["entityId"] = payload.get("entity_id") or row.get("actor_id")
            base["communicationScope"] = payload.get("communication_scope")
            base["principalEntityId"] = payload.get("principal_entity_id")
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
        identity_evidence: tuple[EvidenceRef, ...] = (),
    ) -> list[ClaimEnvelope]:
        """One observed claim per evidenced message in the timeline.

        Every claim is capped at ``observed`` (message facts never escalate to
        ``verified``), carries its reused EvidenceRefs, and never infers
        causality / knowledge from delivery. A message that carries no evidence
        ref is shown in the timeline but not asserted as a claim (requiresEvidence).
        """
        claims: list[ClaimEnvelope] = []
        subject = ProjectionSubject(kind=request.subject.kind, id=request.subject.id)
        for message in messages:
            refs = _dedupe_refs([*identity_evidence, *message.evidence_refs])
            if not refs:
                continue
            state = _message_state_value(message)
            state_line = (
                f"communication state: {state}"
                if state is not None
                else "communication state: unclassified"
            )
            claims.append(
                ClaimEnvelope(
                    id=f"timeline.{message.message_id}",
                    kind="communication_sequence",
                    subject=subject,
                    evidenceRefs=refs,
                    claims=[
                        f"message {message.message_id} observed",
                        state_line,
                    ],
                    confidence=1.0,
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=_communication_slot_ids(),
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
