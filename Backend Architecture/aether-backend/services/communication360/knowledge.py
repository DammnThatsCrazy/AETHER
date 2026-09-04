"""Knowledge / interpretation / context — pure mapping from agent observations (R4).

Phase 5 of the Communication360 convergence program. This module is PURE LOGIC:
no DB, no network, no repository imports. It maps an agent-side observation
(an :class:`~services.agentic_observability.models.AgenticObservationRecord` OR
a plain dict with keys such as ``observation_id`` / ``event_name`` /
``observed_at`` / ``agent_id`` / ...) into the frozen Phase-3 knowledge records:

* :func:`context_inclusion_from_observation` → :class:`ContextInclusionRecord`
  only when the observation is an agent-side context event (``event_name`` /
  action carries an ``included_in_context`` / ``context_inclusion`` marker or an
  explicit ``included: <bool>`` flag); otherwise ``None``.
* :func:`knowledge_state_from_observation` → :class:`KnowledgeStateRecord` only
  when the observation carries a consumption marker (``ingested`` / ``parsed`` /
  ``included_in_context`` / ``used``); otherwise ``None``.
* :func:`interpretation_from_observation` → :class:`InterpretationRecord` only
  for explicit interpretation / derived-content events; ``claim_state`` is at
  most :attr:`EpistemicStatus.INFERRED`.

R4 — delivery is not knowledge
------------------------------
Message lifecycle/delivery state (``CommunicationState``) and agent-side
knowledge/interpretation/context state (:class:`AgentConsumptionState`) are two
typed state families with NO cross-ladder inference. :func:`consumption_from_delivery_state`
ALWAYS returns :attr:`AgentConsumptionState.UNKNOWN` — a ``delivered`` /
``sent`` / ``opened`` / ``received`` event carries no knowledge weight and can
never yield ``ingested`` / ``parsed`` / ``included_in_context`` / ``used``.
Every record function additionally refuses to fire on an observation whose event
semantics are a delivery/engagement marker.

Epistemic discipline (R1)
-------------------------
Records built here are observed agent-runtime facts and are capped at
:attr:`EpistemicStatus.OBSERVED`; interpretations are derived content and are
capped at :attr:`EpistemicStatus.INFERRED`. No function can emit a record whose
``claim_state`` is in the factual band (``verified`` / ``resolved`` /
``causally_supported``). A missing value stays ``None`` / typed-unknown — never
a fabricated state.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional, Union

from services.agentic_observability.models import AgenticObservationRecord
from services.communication360.contracts import (
    AgentConsumptionState,
    CommunicationState,
    ContextInclusionRecord,
    InterpretationRecord,
    KnowledgeStateRecord,
)
from services.operational_intelligence.models import EvidenceRef
from shared.contracts_models.epistemic import EpistemicStatus

# ─────────────────────────────────────────────────────────────────────────────
# Epistemic guard
# ─────────────────────────────────────────────────────────────────────────────

#: Statuses that must never appear on a record built from an observation.
FACTUAL_BAND: frozenset[EpistemicStatus] = frozenset(
    {
        EpistemicStatus.VERIFIED,
        EpistemicStatus.RESOLVED,
        EpistemicStatus.CAUSALLY_SUPPORTED,
    }
)

#: Cap for context-inclusion / knowledge-state records (observed facts).
RECORD_CLAIM_STATE_CAP: EpistemicStatus = EpistemicStatus.OBSERVED

#: Cap for interpretation records (derived content — never a fact).
INTERPRETATION_CLAIM_STATE_CAP: EpistemicStatus = EpistemicStatus.INFERRED


def _assert_capped(status: EpistemicStatus, cap: EpistemicStatus) -> None:
    """Raise unless ``status`` stays at-or-below ``cap`` on the honesty ladder."""
    if status in FACTUAL_BAND:
        raise ValueError(
            f"refusing factual claim_state {status.value!r} on an "
            "observation-derived record (R1)"
        )
    _band_index = {
        EpistemicStatus.OBSERVED: 0,
        EpistemicStatus.INFERRED: 1,
    }
    if _band_index.get(status, 0) > _band_index.get(cap, 0):
        raise ValueError(
            f"claim_state {status.value!r} exceeds cap {cap.value!r} "
            "for this record family"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Consumption ladder (R4) — strongest observed state ranks highest
# ─────────────────────────────────────────────────────────────────────────────

_LADDER_RANK: dict[AgentConsumptionState, int] = {
    AgentConsumptionState.UNOBSERVED: 0,
    AgentConsumptionState.INGESTED: 1,
    AgentConsumptionState.PARSED: 2,
    AgentConsumptionState.INCLUDED_IN_CONTEXT: 3,
    AgentConsumptionState.USED: 4,
    AgentConsumptionState.UNKNOWN: -1,
}

#: Agent-side consumption markers → ladder states. Detection is token-exact over
#: the lowercased observation text so ordinary words cannot false-positive
#: (integration must narrow this onto the registry event taxonomy).
_CONSUMPTION_STEM_MARKERS: tuple[tuple[frozenset[str], AgentConsumptionState], ...] = (
    (frozenset({"ingested", "ingest"}), AgentConsumptionState.INGESTED),
    (frozenset({"parsed", "parse"}), AgentConsumptionState.PARSED),
    (frozenset({"used", "use"}), AgentConsumptionState.USED),
)

#: Context words that mark an agent-side context inclusion event (R4).
_CONTEXT_INCLUSION_VERBS: frozenset[str] = frozenset(
    {"inclusion", "included", "include", "added", "promoted", "injected"}
)

#: Interpretation / derived-content event tokens.
_INTERPRETATION_EVENT_TOKENS: frozenset[str] = frozenset(
    {
        "interpretation",
        "interpreted",
        "interpret",
        "interpreting",
        "derived_content",
        "derivation",
        "derived",
        "synthesized",
    }
)

#: Delivery/engagement tokens. An observation whose event semantics carry one of
#: these sits on the DELIVERY ladder and can never produce a knowledge record
#: (R4). Deliberately narrow (message-transport words) so an agent *tool* named
#: e.g. ``read_file`` is not mis-classified as a delivery event.
_DELIVERY_TOKENS: frozenset[str] = frozenset(
    {
        "queued",
        "processed",
        "sent",
        "delivered",
        "delivery",
        "deferred",
        "bounced",
        "dropped",
        "opened",
        "clicked",
        "replied",
        "complained",
        "suppressed",
        "suppression",
        "unsubscribed",
        "received",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# Observation normalisation
# ─────────────────────────────────────────────────────────────────────────────


def _as_dict(obs: Union[AgenticObservationRecord, dict[str, Any]]) -> dict[str, Any]:
    """Return a plain-dict view of an observation (record or fixture dict)."""
    if isinstance(obs, AgenticObservationRecord):
        return obs.model_dump(mode="python")
    if isinstance(obs, dict):
        return dict(obs)
    raise TypeError(
        "observation must be an AgenticObservationRecord or a dict, "
        f"got {type(obs).__name__}"
    )


def _get(data: dict[str, Any], *path: str) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _scalar(data: dict[str, Any], *paths: tuple[str, ...]) -> Optional[str]:
    for path in paths:
        value = _get(data, *path)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _observation_text(data: dict[str, Any]) -> str:
    """Lowercased event/action/object text used for marker scanning."""
    parts = [
        _get(data, "event_name"),
        _get(data, "action", "name"),
        _get(data, "action", "status"),
        _get(data, "action", "outcome"),
        _get(data, "action", "intent"),
        _get(data, "object", "object_type"),
        _get(data, "object", "object_id"),
    ]
    # Dict-only scalar fields that may carry a semantic marker.
    for key in (
        "detail",
        "marker",
        "note",
        "event_type",
        "stage",
        "state",
        "consumption_state",
        "reason",
        "text",
    ):
        value = _get(data, key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(p for p in parts if isinstance(p, str)).lower()


def _tokens(text: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", text.lower()))


def _event_and_action_text(data: dict[str, Any]) -> str:
    """Event-name + action-name semantics (used for the R4 delivery guard)."""
    parts = [_get(data, "event_name"), _get(data, "action", "name")]
    return " ".join(p for p in parts if isinstance(p, str)).lower()


def _agent_entity_id(data: dict[str, Any]) -> Optional[str]:
    """Resolve the acting agent's entity id from the observation view."""
    agent_id = _scalar(
        data,
        ("agent", "agent_id"),
        ("agent", "external_agent_id"),
        ("agent_id",),
    )
    if agent_id:
        return agent_id
    if _get(data, "actor", "actor_type") == "agent":
        return _scalar(data, ("actor", "actor_id"))
    return None


def _context_ref(data: dict[str, Any]) -> Optional[str]:
    return _scalar(
        data,
        ("context_ref",),
        ("correlation", "session_id"),
        ("runtime", "instance_id"),
        ("object", "object_id"),
    )


def _is_delivery_event(data: dict[str, Any]) -> bool:
    """Whether the observation's event semantics sit on the delivery ladder.

    Uses event_name + action name only (the *event* semantics), never object
    payload words, so an observation about a delivered message that merely names
    the object is not mis-classified as a delivery event.
    """
    event_tokens = _tokens(_event_and_action_text(data))
    return bool(event_tokens & _DELIVERY_TOKENS)


def _explicit_included(data: dict[str, Any]) -> Optional[bool]:
    """An explicit ``included`` boolean marker on a dict-only observation."""
    for value in (
        _get(data, "included"),
        _get(data, "context", "included"),
        _get(data, "object", "included"),
        _get(data, "observation", "included"),
    ):
        if isinstance(value, bool):
            return value
    return None


def _context_inclusion_indicated(tokens: set[str]) -> bool:
    """Whether the token set marks an agent-side context inclusion event.

    Requires the word ``context`` together with one of the context-inclusion
    verbs (``included_in_context`` tokenizes to ``included`` + ``in`` +
    ``context``; ``context_inclusion`` to ``context`` + ``inclusion``; ...). A
    bare ``context`` word (e.g. an object type) never fires on its own.
    """
    if "context" not in tokens:
        return False
    return bool(tokens & _CONTEXT_INCLUSION_VERBS)


def _consumption_match(tokens: set[str]) -> Optional[AgentConsumptionState]:
    matched = [
        state
        for required, state in _CONSUMPTION_STEM_MARKERS
        if required & tokens  # any-of semantics for stem synonyms
    ]
    if _context_inclusion_indicated(tokens):
        matched.append(AgentConsumptionState.INCLUDED_IN_CONTEXT)
    if not matched:
        return None
    # Prefer the strongest OBSERVED consumption state actually indicated.
    return max(matched, key=lambda state: _LADDER_RANK[state])


def _is_context_inclusion_event(tokens: set[str]) -> bool:
    return _context_inclusion_indicated(tokens)


def _is_interpretation_event(tokens: set[str]) -> bool:
    return bool(tokens & _INTERPRETATION_EVENT_TOKENS)


def _observation_evidence(data: dict[str, Any], observed_at: str) -> list[EvidenceRef]:
    obs_id = _scalar(data, ("observation_id",))
    if not obs_id:
        return []
    return [
        EvidenceRef(
            id=obs_id,
            type="event",
            source="agentic_observability",
            observedAt=observed_at or None,
        )
    ]


def _record_id(data: dict[str, Any], kind: str) -> str:
    base = _scalar(data, ("observation_id",)) or str(uuid.uuid4())
    return f"{base}:{kind}"


def _object_information_id(data: dict[str, Any]) -> Optional[str]:
    return _scalar(data, ("object", "object_id"), ("information_id",))


def _object_kind(data: dict[str, Any]) -> Optional[str]:
    return _scalar(data, ("object", "object_type"))


# ─────────────────────────────────────────────────────────────────────────────
# R4 hard guard — delivery state can never carry knowledge weight
# ─────────────────────────────────────────────────────────────────────────────


def consumption_from_delivery_state(
    communication_state: Union[CommunicationState, str],
) -> AgentConsumptionState:
    """Map a message lifecycle/delivery state onto the consumption ladder (R4).

    This is the hard cross-ladder guard: a delivery/engagement state is an
    observation about the MESSAGE EVENT, never about what an agent knew or used.
    It ALWAYS returns :attr:`AgentConsumptionState.UNKNOWN` — a ``delivered`` /
    ``sent`` / ``opened`` event can never yield ``ingested`` / ``parsed`` /
    ``included_in_context`` / ``used``.
    """
    # Deliberately ignores the specific state value: every CommunicationState
    # member lives on the delivery ladder and none attests to knowledge.
    _ = communication_state
    return AgentConsumptionState.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# Record mappings
# ─────────────────────────────────────────────────────────────────────────────


def context_inclusion_from_observation(
    obs: Union[AgenticObservationRecord, dict[str, Any]],
) -> Optional[ContextInclusionRecord]:
    """Build a :class:`ContextInclusionRecord` from an agent-side context event.

    Returns a record ONLY when the observation is an agent-side context event:
    its text carries an ``included_in_context`` / ``context_inclusion`` marker
    or it carries an explicit ``included: <bool>`` flag. Delivery/engagement
    observations (R4) and observations without a resolvable agent + tenant
    return ``None``.
    """
    data = _as_dict(obs)
    tokens = _tokens(_observation_text(data))
    explicit_included = _explicit_included(data)
    is_context_event = _is_context_inclusion_event(tokens)

    if not is_context_event and explicit_included is None:
        return None
    if _is_delivery_event(data):
        # A delivery observation never grants a context-inclusion fact (R4).
        return None

    agent_entity_id = _agent_entity_id(data)
    tenant_id = _scalar(data, ("tenant_id",))
    observed_at = _scalar(data, ("observed_at",))
    if not agent_entity_id or not tenant_id:
        return None

    included = explicit_included if explicit_included is not None else True

    record = ContextInclusionRecord(
        record_id=_record_id(data, "context_inclusion"),
        tenant_id=tenant_id,
        agent_entity_id=agent_entity_id,
        context_ref=_context_ref(data),
        included=included,
        included_at=observed_at,
        source_observation_id=_scalar(data, ("observation_id",)),
        claim_state=RECORD_CLAIM_STATE_CAP,
        confidence=1.0,
        evidence_refs=_observation_evidence(data, observed_at or ""),
    )
    _assert_capped(record.claim_state, RECORD_CLAIM_STATE_CAP)
    return record


def knowledge_state_from_observation(
    obs: Union[AgenticObservationRecord, dict[str, Any]],
) -> Optional[KnowledgeStateRecord]:
    """Map an observed consumption marker onto a :class:`KnowledgeStateRecord`.

    ``ingested`` / ``parsed`` / ``included_in_context`` / ``used`` markers
    become the corresponding :class:`AgentConsumptionState`; when several are
    indicated the strongest observed state wins. Returns ``None`` when the
    observation carries no consumption marker, when it is a delivery/engagement
    observation (R4), or when the agent + tenant cannot be resolved.
    """
    data = _as_dict(obs)
    if _is_delivery_event(data):
        return None

    tokens = _tokens(_observation_text(data))
    state = _consumption_match(tokens)
    if state is None:
        return None

    agent_entity_id = _agent_entity_id(data)
    tenant_id = _scalar(data, ("tenant_id",))
    observed_at = _scalar(data, ("observed_at",))
    if not agent_entity_id or not tenant_id:
        return None

    information_id = _object_information_id(data)
    object_kind = _object_kind(data)

    record = KnowledgeStateRecord(
        record_id=_record_id(data, "knowledge_state"),
        tenant_id=tenant_id,
        subject_entity_id=agent_entity_id,
        information_ref=(
            None
            if not information_id or not object_kind
            else {
                "information_id": information_id,
                "kind": object_kind,
                "tenant_id": tenant_id,
            }
        ),
        state=state,
        known_since=observed_at,
        observed_at=observed_at,
        claim_state=RECORD_CLAIM_STATE_CAP,
        confidence=1.0,
        evidence_refs=_observation_evidence(data, observed_at or ""),
    )
    _assert_capped(record.claim_state, RECORD_CLAIM_STATE_CAP)
    return record


def interpretation_from_observation(
    obs: Union[AgenticObservationRecord, dict[str, Any]],
) -> Optional[InterpretationRecord]:
    """Build an :class:`InterpretationRecord` for an interpretation event.

    Fires ONLY on explicit interpretation / derived-content events; the record
    ``claim_state`` is capped at :attr:`EpistemicStatus.INFERRED` (an agent's
    interpretation is derived content, never a silent factual claim).
    """
    data = _as_dict(obs)
    tokens = _tokens(_observation_text(data))
    if not _is_interpretation_event(tokens):
        return None
    if _is_delivery_event(data):
        return None

    agent_entity_id = _agent_entity_id(data)
    tenant_id = _scalar(data, ("tenant_id",))
    if not agent_entity_id or not tenant_id:
        return None

    information_id = _object_information_id(data)
    object_kind = _object_kind(data)
    text = _scalar(
        data,
        ("text",),
        ("action", "outcome"),
        ("interpretation",),
    )

    record = InterpretationRecord(
        record_id=_record_id(data, "interpretation"),
        tenant_id=tenant_id,
        agent_entity_id=agent_entity_id,
        information_ref=(
            None
            if not information_id or not object_kind
            else {
                "information_id": information_id,
                "kind": object_kind,
                "tenant_id": tenant_id,
            }
        ),
        text=text,
        claim_state=INTERPRETATION_CLAIM_STATE_CAP,
        confidence=1.0,
        evidence_refs=[],
    )
    _assert_capped(record.claim_state, INTERPRETATION_CLAIM_STATE_CAP)
    return record


__all__ = [
    "AgentConsumptionState",
    "FACTUAL_BAND",
    "RECORD_CLAIM_STATE_CAP",
    "INTERPRETATION_CLAIM_STATE_CAP",
    "consumption_from_delivery_state",
    "context_inclusion_from_observation",
    "interpretation_from_observation",
    "knowledge_state_from_observation",
]
