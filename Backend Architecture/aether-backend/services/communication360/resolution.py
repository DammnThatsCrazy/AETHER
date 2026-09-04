"""Communication360 resolution engine (Phase 6) — pure, deterministic logic.

This module resolves canonical :class:`Conversation` / :class:`Matter`
continuity over the Phase-3 frozen contracts
(``services/communication360/contracts.py``) and provides the declared-lineage
causal ordering primitive (spec §54, §57–60). It is **pure logic**: it never
imports repositories, storage, graph/edge modules, settings, or the network; it
reads only the contract objects handed to it and returns new derived objects.

Epistemic discipline (R1–R5, same as the contracts module):

- **Resolution is inference, never fact.** A ``Conversation`` / ``Matter``
  returned here is a *derived* product of the evidence passed in. Its
  ``claim_state`` is always :attr:`EpistemicStatus.INFERRED` (never
  ``VERIFIED``/``OBSERVED``/``RESOLVED``), and its ``ResolutionRecord`` carries
  a method, a 0..1 confidence, the supporting ``EvidenceRef``\\ s reused from
  the inputs, and any contradictions that surfaced.
- **Timestamps never imply causality.** ``responds_to`` / ``supersedes`` order
  comes **only** from declared lineage (:func:`order_messages_declared`,
  :func:`is_causally_ordered`). A later ``occurred_at`` is never treated as a
  cause or as an ordering edge. Timestamps are only surfaced as continuity
  *metadata* (``opened_at`` / ``last_activity_at`` envelopes); they never decide
  thread membership.
- **Provider threads do not auto-equal conversations.** A bare
  :class:`ProviderThread` with no message and no participant binding is not a
  conversation (:func:`thread_can_standalone_as_conversation`). When inputs are
  ambiguous the resolver does **not** silently pick a thread — it returns a
  conversation/matter whose resolution records low confidence and a
  contradiction naming the ambiguity.
- **Honest refusal beats fabrication.** :func:`resolve_matter` raises
  ``ValueError`` when there is nothing to bind rather than emitting an
  ungrounded ``Matter``.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, Optional

from services.communication360.contracts import (
    CommunicationMessage,
    Conversation,
    ConversationState,
    Matter,
    ParticipantBinding,
    ProviderThread,
    ResolutionRecord,
)
from services.operational_intelligence.models import EvidenceRef
from shared.contracts_models.epistemic import EpistemicStatus

# ─────────────────────────────────────────────────────────────────────────────
# Declared-lineage vocabulary (§54)
# ─────────────────────────────────────────────────────────────────────────────

LineageKind = Literal["responds_to", "supersedes"]

# Declared lineage is a mapping from the *dependent* message id (the message
# that declares the relation) to a ``(kind, prior_message_id)`` pair, e.g.
# ``{"msg_b": ("responds_to", "msg_a")}`` means ``msg_b`` declares it responds
# to ``msg_a``. Both ``responds_to`` and ``supersedes`` make the dependent
# message causally later than the prior message. A flat ``{id: kind}`` dict is
# deliberately NOT used: a causal edge has two endpoints, so the prior message
# id must be explicit. A key whose value kind is present but whose prior message
# is absent from the input set imposes no ordering on the listed messages.
Lineage = Mapping[str, tuple[LineageKind, str]]


@dataclass(frozen=True)
class _ThreadSignal:
    """Internal per-thread aggregation used by conversation resolution."""

    thread: ProviderThread
    message_ids: tuple[str, ...]
    participant_entity_ids: frozenset[str]
    subject: Optional[str] = None


def _norm(value: Optional[str]) -> Optional[str]:
    """Normalize a topic/subject for comparison; None stays None."""
    if value is None:
        return None
    normalized = " ".join(value.strip().lower().split())
    return normalized or None


def _dedup_evidence(refs: Iterable[EvidenceRef]) -> list[EvidenceRef]:
    """Dedupe EvidenceRefs by id, preserving first-seen order."""
    seen: set[str] = set()
    out: list[EvidenceRef] = []
    for ref in refs:
        if ref.id in seen:
            continue
        seen.add(ref.id)
        out.append(ref)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Declared-lineage causal ordering (§54) — never from timestamps
# ─────────────────────────────────────────────────────────────────────────────


def order_messages_declared(
    messages: list[CommunicationMessage],
    lineage: Optional[Lineage] = None,
) -> list[CommunicationMessage]:
    """Order messages by DECLARED lineage only — never by ``occurred_at``.

    Each ``lineage`` entry ``{dependent_id: (kind, prior_id)}`` states that the
    dependent message declared a ``responds_to`` / ``supersedes`` relation
    toward ``prior_id``, so ``prior_id`` is placed before the dependent message.
    A topological sort honors chains (A declared prior of B, B declared prior of
    C ⇒ A, B, C). Messages with no declared relation to any other listed message
    keep their input order (stable, deterministic). A declared cycle is
    contradictory and raises ``ValueError`` (honest refusal) instead of
    returning an arbitrary order.

    When ``lineage`` is ``None`` (or contains no edges between listed messages)
    the input order is returned unchanged — timestamps are never consulted, so a
    later ``occurred_at`` can never pull a message forward.
    """
    ordered = list(messages)
    if not lineage or not ordered:
        return ordered

    index: dict[str, int] = {}
    by_id: dict[str, CommunicationMessage] = {}
    for position, message in enumerate(ordered):
        if message.message_id in by_id:
            raise ValueError(
                f"cannot order declared lineage: duplicate message id "
                f"{message.message_id!r} in the input set"
            )
        by_id[message.message_id] = message
        index[message.message_id] = position

    # Build the declaration graph among the listed messages only. Edges that
    # reference an id outside the input set impose no relative ordering here.
    adjacency: dict[str, list[str]] = {mid: [] for mid in by_id}
    indegree: dict[str, int] = {mid: 0 for mid in by_id}
    for dependent_id, (_kind, prior_id) in lineage.items():
        if dependent_id in by_id and prior_id in by_id:
            adjacency[prior_id].append(dependent_id)
            indegree[dependent_id] += 1

    # Kahn's algorithm with a min-heap keyed by original input position so the
    # result is deterministic and preserves input order for unconstrained runs.
    ready: list[tuple[int, str]] = [
        (index[mid], mid) for mid in by_id if indegree[mid] == 0
    ]
    heapq.heapify(ready)
    resolved: list[str] = []
    while ready:
        _position, message_id = heapq.heappop(ready)
        resolved.append(message_id)
        for dependent_id in adjacency[message_id]:
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                heapq.heappush(ready, (index[dependent_id], dependent_id))

    if len(resolved) != len(by_id):
        raise ValueError(
            "cannot order declared lineage: a declared responds_to/supersedes "
            "cycle exists among the messages"
        )

    resolved_set = {mid: by_id[mid] for mid in resolved}
    return [resolved_set[mid] for mid in resolved]


def is_causally_ordered(
    a: CommunicationMessage,
    b: CommunicationMessage,
    lineage: Lineage,
) -> bool:
    """Return whether ``a`` is declared to causally precede ``b``.

    ``True`` only when a DECLARED lineage edge states that ``b`` responds to or
    supersedes ``a`` (i.e. ``lineage[b.message_id][1] == a.message_id``). Causal
    order is never inferred from timestamp proximity: two messages whose
    ``occurred_at`` values are adjacent but share no declared edge return
    ``False``. Transitive reachability is handled by
    :func:`order_messages_declared`, not by this direct-edge predicate.
    """
    entry = lineage.get(b.message_id)
    if entry is None:
        return False
    return entry[1] == a.message_id


# ─────────────────────────────────────────────────────────────────────────────
# Provider-thread standalone guard (§57) — threads are not conversations
# ─────────────────────────────────────────────────────────────────────────────


def thread_can_standalone_as_conversation(
    thread: ProviderThread,
    participants: list[ParticipantBinding],
) -> bool:
    """Return whether ``thread`` alone can stand as a Conversation.

    ``True`` only when the thread lists at least one message
    (``thread.message_ids``) AND at least one participant binding references one
    of those messages. Provider threads must NOT auto-equal conversations: a
    bare thread with no participants or messages is not a conversation, so this
    returns ``False`` (spec §17, §57).
    """
    if not thread.message_ids:
        return False
    member_ids = frozenset(thread.message_ids)
    return any(
        binding.communication_scope_kind == "message"
        and binding.communication_scope in member_ids
        for binding in participants
    )


# ─────────────────────────────────────────────────────────────────────────────
# Conversation resolution (§58)
# ─────────────────────────────────────────────────────────────────────────────


def resolve_conversation(
    *,
    tenant_id: str,
    conversation_id: str,
    provider_threads: list[ProviderThread],
    messages: list[CommunicationMessage],
    participants: list[ParticipantBinding],
    explicit_session_id: Optional[str] = None,
    shared_matter_id: Optional[str] = None,
    topic: Optional[str] = None,
    opened_at: Optional[str] = None,
    last_activity_at: Optional[str] = None,
) -> Conversation:
    """Resolve candidate threads/messages/participants into one Conversation.

    Combines participants + topic + provider threads + linked messages + shared
    Matter + explicit session id into a single derived :class:`Conversation`
    carrying a :class:`ResolutionRecord` (method, confidence, supporting
    ``EvidenceRef``\\ s reused from the message evidence, and contradictions).

    Membership is decided by declared signals only:

    * ``explicit_session_id`` → ``session_id`` (high confidence anchor);
    * ``shared_matter_id`` → ``shared_matter`` (high confidence anchor; the
      conversation is bound to that matter);
    * otherwise a shared participant across every thread plus a coherent topic →
      ``participants+topics``;
    * a single well-formed thread → ``participants+topics`` /
      ``provider_thread_continuity``.

    When the inputs are ambiguous (threads with no shared participant, no topic,
    no linkage, no matter, and no session id) the resolver does NOT silently
    pick a thread: it returns a Conversation that still carries the candidate
    thread/message ids but whose resolution records ``method="ambiguous"``, low
    confidence, and a contradiction naming the ambiguity.

    ``opened_at`` / ``last_activity_at`` are envelope metadata only: they are
    taken from the explicit parameters or derived from message/thread times.
    They never decide membership and never imply causality.
    """
    for thread in provider_threads:
        if thread.tenant_id != tenant_id:
            raise ValueError(
                f"provider thread {thread.thread_id!r} belongs to tenant "
                f"{thread.tenant_id!r}, not {tenant_id!r}"
            )
    for message in messages:
        if message.tenant_id != tenant_id:
            raise ValueError(
                f"message {message.message_id!r} belongs to tenant "
                f"{message.tenant_id!r}, not {tenant_id!r}"
            )
    for binding in participants:
        if binding.tenant_id != tenant_id:
            raise ValueError(
                f"participant binding {binding.binding_id!r} belongs to tenant "
                f"{binding.tenant_id!r}, not {tenant_id!r}"
            )

    contradictions: list[str] = []
    thread_ids = [thread.thread_id for thread in provider_threads]

    # Map each passed message to the thread that claims it (by id list or by
    # provider+external_thread_id). A message claimed by two threads is a
    # membership contradiction.
    message_ids = [message.message_id for message in messages]
    message_id_set = frozenset(message_ids)
    owner: dict[str, Optional[str]] = {}
    for message in messages:
        claimed: list[str] = []
        for thread in provider_threads:
            if message.message_id in thread.message_ids:
                claimed.append(thread.thread_id)
            elif (
                thread.provider
                and thread.external_thread_id
                and message.provider == thread.provider
                and message.external_thread_id == thread.external_thread_id
            ):
                claimed.append(thread.thread_id)
        if claimed:
            owner[message.message_id] = claimed[0]
            for extra in claimed[1:]:
                if extra != claimed[0]:
                    contradictions.append(
                        f"message {message.message_id!r} is listed under provider "
                        f"threads {claimed!r}; thread membership disagrees"
                    )
                    break
        else:
            owner[message.message_id] = None

    messages_by_thread: dict[str, list[CommunicationMessage]] = {
        thread.thread_id: [] for thread in provider_threads
    }
    for message in messages:
        thread_id = owner[message.message_id]
        if thread_id is not None:
            messages_by_thread[thread_id].append(message)

    # Participant entity sets per thread plus conversation-level entities.
    thread_entities: dict[str, set[str]] = {
        thread.thread_id: set() for thread in provider_threads
    }
    kept_bindings: list[ParticipantBinding] = []
    conversation_entities: set[str] = set()
    for binding in participants:
        if (
            binding.communication_scope_kind == "message"
            and binding.communication_scope in message_id_set
        ):
            kept_bindings.append(binding)
            conversation_entities.add(binding.entity_id)
            thread_id = owner.get(binding.communication_scope)
            if thread_id is not None:
                thread_entities[thread_id].add(binding.entity_id)
        elif (
            binding.communication_scope_kind == "conversation"
            and binding.communication_scope == conversation_id
        ):
            kept_bindings.append(binding)
            conversation_entities.add(binding.entity_id)

    signals = [
        _ThreadSignal(
            thread=thread,
            message_ids=tuple(
                message.message_id for message in messages_by_thread[thread.thread_id]
            ),
            participant_entity_ids=frozenset(thread_entities[thread.thread_id]),
            subject=_norm(thread.subject),
        )
        for thread in provider_threads
    ]

    canonical_topic = _norm(topic)

    # Topic coherence: every present thread subject agrees, and agrees with the
    # canonical topic when one is supplied.
    thread_subjects = {signal.subject for signal in signals if signal.subject}
    topic_coherent = len(thread_subjects) <= 1
    if canonical_topic is not None and len(thread_subjects) <= 1:
        subject = next(iter(thread_subjects), None)
        if subject is not None and subject != canonical_topic:
            topic_coherent = False
            conflicts = [s.thread.thread_id for s in signals if s.subject]
            contradictions.append(
                f"provider thread(s) {conflicts} subject {subject!r} conflicts "
                f"with conversation topic {canonical_topic!r}"
            )
    if len(thread_subjects) > 1:
        for signal in signals:
            if signal.subject is not None and signal.subject != canonical_topic:
                contradictions.append(
                    f"provider thread {signal.thread.thread_id!r} subject "
                    f"{signal.subject!r} conflicts with the other thread(s)"
                )

    # Shared participant = an entity bound to at least one message in EVERY
    # thread (a conversation-level binding does not tie two threads together).
    shared_entities: frozenset[str] = frozenset()
    if len(signals) == 1:
        shared_entities = signals[0].participant_entity_ids
    elif len(signals) > 1:
        shared_entities = frozenset.intersection(
            *(signal.participant_entity_ids for signal in signals)
        )

    for signal in signals:
        if not signal.message_ids or not signal.participant_entity_ids:
            contradictions.append(
                f"provider thread {signal.thread.thread_id!r} is bare (no "
                f"message and/or no participant binding) and cannot contribute "
                f"to a conversation on its own"
            )

    # Choose the resolution method + confidence.
    if explicit_session_id is not None:
        method = "session_id"
        confidence = 0.9
    elif shared_matter_id is not None:
        method = "shared_matter"
        confidence = 0.9
    elif not signals:
        if messages and conversation_entities:
            method = "participants+topics"
            confidence = 0.6
        else:
            method = "ambiguous"
            confidence = 0.1
            contradictions.append(
                "no provider thread, message, or participant binding is present "
                "to resolve into a conversation"
            )
    elif len(signals) == 1:
        signal = signals[0]
        if not signal.message_ids or not signal.participant_entity_ids:
            method = "ambiguous"
            confidence = 0.25
        elif canonical_topic is not None or signal.subject is not None:
            method = "participants+topics"
            confidence = 0.85
        else:
            method = "provider_thread_continuity"
            confidence = 0.7
    else:
        if shared_entities:
            if topic_coherent:
                method = "participants+topics"
                confidence = 0.9
            else:
                method = "participants+topics"
                confidence = 0.7
        elif topic_coherent and thread_subjects and canonical_topic is not None:
            # Same concrete topic across providers but no shared participant.
            method = "participants+topics"
            confidence = 0.55
        else:
            method = "ambiguous"
            confidence = 0.2
            contradictions.append(
                "no shared participant, topic, matter, session id, or "
                "provider-thread linkage connects provider threads "
                f"{thread_ids}; conversation membership is ambiguous"
            )

    # Conversation envelope from the resolved participant/message set.
    resolved_message_ids = message_ids
    if method == "ambiguous":
        supporting: list[EvidenceRef] = []
    else:
        source_refs = [
            ref
            for message in messages
            for ref in message.evidence_refs
        ] + [
            ref for binding in kept_bindings for ref in binding.evidence_refs
        ]
        supporting = _dedup_evidence(source_refs)

    # Surface a topic only when it is coherent: the explicit topic wins, and a
    # single unambiguous thread subject fills in when no explicit topic is given.
    conversation_topic = canonical_topic
    if conversation_topic is None and topic_coherent and thread_subjects:
        conversation_topic = next(iter(thread_subjects))

    derived_opened_at = opened_at
    if derived_opened_at is None:
        candidates = [t.first_seen_at for t in provider_threads if t.first_seen_at]
        candidates += [m.occurred_at for m in messages]
        derived_opened_at = min(candidates) if candidates else None

    derived_last_activity_at = last_activity_at
    if derived_last_activity_at is None:
        candidates = [t.last_seen_at for t in provider_threads if t.last_seen_at]
        candidates += [m.occurred_at for m in messages]
        derived_last_activity_at = max(candidates) if candidates else None

    return Conversation(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        topic=conversation_topic,
        provider_thread_ids=thread_ids,
        message_ids=resolved_message_ids,
        participant_bindings=kept_bindings,
        matter_id=shared_matter_id,
        state=ConversationState.UNKNOWN,
        resolution=ResolutionRecord(
            method=method,
            confidence=confidence,
            supporting_evidence_refs=supporting,
            contradictions=contradictions,
        ),
        opened_at=derived_opened_at,
        last_activity_at=derived_last_activity_at,
        claim_state=EpistemicStatus.INFERRED,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Matter resolution (§59)
# ─────────────────────────────────────────────────────────────────────────────


def resolve_matter(
    *,
    tenant_id: str,
    matter_id: str,
    subject: str,
    conversations: Iterable[Conversation] = (),
    campaign_ids: Iterable[str] = (),
    episode_ids: Iterable[str] = (),
    external_refs: Optional[Mapping[str, str]] = None,
) -> Matter:
    """Resolve long-lived subject continuity across channels into a Matter.

    Binds conversations + campaign/episode/external anchors to one
    :class:`Matter` (§59) with a :class:`ResolutionRecord`. A Matter requires at
    least one conversation or an explicit campaign/episode/external anchor —
    otherwise ``ValueError`` is raised (honest refusal; an ungrounded Matter is
    never fabricated). Confidence reflects the number of independent binding
    surfaces (conversations across channels plus explicit anchors); a
    conversation already bound to a different matter is a contradiction and caps
    confidence.
    """
    conversations = list(conversations)
    for conversation in conversations:
        if conversation.tenant_id != tenant_id:
            raise ValueError(
                f"conversation {conversation.conversation_id!r} belongs to "
                f"tenant {conversation.tenant_id!r}, not {tenant_id!r}"
            )

    campaign_ids = tuple(dict.fromkeys(campaign_ids))
    episode_ids = tuple(dict.fromkeys(episode_ids))
    external_refs = dict(external_refs) if external_refs is not None else {}

    if not conversations and not campaign_ids and not episode_ids and not external_refs:
        raise ValueError(
            f"cannot resolve matter {matter_id!r}: no conversation, campaign "
            f"episode, or external reference binds it"
        )

    # Distinct conversations by id, preserving order.
    seen: set[str] = set()
    distinct_conversations: list[Conversation] = []
    for conversation in conversations:
        if conversation.conversation_id not in seen:
            seen.add(conversation.conversation_id)
            distinct_conversations.append(conversation)

    contradictions: list[str] = []
    for conversation in distinct_conversations:
        if conversation.matter_id and conversation.matter_id != matter_id:
            contradictions.append(
                f"conversation {conversation.conversation_id!r} is already "
                f"bound to matter {conversation.matter_id!r}; rebinding it to "
                f"{matter_id!r} would orphan the prior binding"
            )

    facets: list[str] = []
    if distinct_conversations:
        facets.append("conversations")
    if campaign_ids:
        facets.append("campaign")
    if episode_ids:
        facets.append("episode")
    if external_refs:
        facets.append("external_ref")
    method = "+".join(facets)

    surfaces = (
        (1 if distinct_conversations else 0)
        + (1 if campaign_ids else 0)
        + (1 if episode_ids else 0)
        + (1 if external_refs else 0)
    )
    confidence = 0.4 + 0.15 * min(surfaces, 3)
    extra_conversations = max(0, len(distinct_conversations) - 1)
    confidence += 0.05 * min(extra_conversations, 3)
    confidence = round(min(0.95, confidence), 2)
    if contradictions:
        confidence = min(confidence, 0.35)

    supporting = _dedup_evidence(
        ref
        for conversation in distinct_conversations
        if conversation.resolution is not None
        for ref in conversation.resolution.supporting_evidence_refs
    )

    return Matter(
        matter_id=matter_id,
        tenant_id=tenant_id,
        subject=subject,
        conversation_ids=[
            conversation.conversation_id for conversation in distinct_conversations
        ],
        campaign_ids=list(campaign_ids),
        episode_ids=list(episode_ids),
        external_refs=external_refs,
        resolution=ResolutionRecord(
            method=method,
            confidence=confidence,
            supporting_evidence_refs=supporting,
            contradictions=contradictions,
        ),
        claim_state=EpistemicStatus.INFERRED,
    )
