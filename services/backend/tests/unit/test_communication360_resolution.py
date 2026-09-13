"""Unit tests for the Communication360 resolution engine (Phase 6, pure logic).

Bootstrap mirrors ``tests/unit/test_intelligence_projection_contracts.py``
(sys.path at BACKEND_ROOT, AETHER_ENV=local, JWT_SECRET=test-secret). These
tests exercise only the deterministic pure functions in
``services/communication360/resolution.py`` — no DB, no repositories, no graph.

Coverage:

* conversation resolution over two provider threads sharing participants +
  topic -> one Conversation with a high-confidence ``ResolutionRecord`` and
  reused supporting evidence;
* ambiguity: two threads with disjoint participants/topics and no session id ->
  low-confidence resolution with a contradiction (never a silent thread pick);
* ``thread_can_standalone_as_conversation`` is False for an empty /
  no-participant thread;
* matter resolution binds conversations + a campaign anchor, and raises
  ``ValueError`` (honest refusal) when there is nothing to bind;
* declared-lineage causal ordering: ``responds_to``/``supersedes`` order
  messages regardless of ``occurred_at``; messages with no declared lineage
  keep input order; timestamp proximity never implies causality.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.communication360.contracts import (  # noqa: E402
    CommunicationMessage,
    CommunicationParticipantRole,
    Conversation,
    ParticipantBinding,
    ProviderThread,
)
from services.communication360.resolution import (  # noqa: E402
    is_causally_ordered,
    order_messages_declared,
    resolve_conversation,
    resolve_matter,
    thread_can_standalone_as_conversation,
)
from services.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402


# ---------------------------------------------------------------------------
# Deterministic fixture helpers
# ---------------------------------------------------------------------------

TENANT = "tenant_comms"


def _ev(evidence_id: str, source: str = "svc/comms") -> EvidenceRef:
    return EvidenceRef(
        id=evidence_id,
        type="event",
        source=source,
        observedAt="2026-09-01T10:00:00Z",
    )


def _message(
    message_id: str,
    *,
    provider: str,
    external_thread_id: str,
    occurred_at: str,
    subject: str | None = None,
    evidence: tuple[EvidenceRef, ...] = (),
) -> CommunicationMessage:
    return CommunicationMessage(
        message_id=message_id,
        tenant_id=TENANT,
        provider=provider,
        external_thread_id=external_thread_id,
        subject=subject,
        occurred_at=occurred_at,
        claim_state=EpistemicStatus.OBSERVED,
        evidence_refs=list(evidence),
    )


def _thread(
    thread_id: str,
    *,
    provider: str,
    external_thread_id: str,
    message_ids: list[str],
    subject: str | None,
) -> ProviderThread:
    return ProviderThread(
        thread_id=thread_id,
        tenant_id=TENANT,
        provider=provider,
        external_thread_id=external_thread_id,
        subject=subject,
        message_ids=message_ids,
        first_seen_at="2026-09-01T09:00:00Z",
        last_seen_at="2026-09-01T11:00:00Z",
    )


def _binding(
    binding_id: str,
    *,
    message_id: str,
    entity_id: str,
    role: CommunicationParticipantRole,
) -> ParticipantBinding:
    return ParticipantBinding(
        binding_id=binding_id,
        tenant_id=TENANT,
        communication_scope=message_id,
        communication_scope_kind="message",
        entity_id=entity_id,
        role=role,
        valid_from="2026-09-01T00:00:00Z",
        claim_state=EpistemicStatus.OBSERVED,
        evidence_refs=[],
    )


# ---------------------------------------------------------------------------
# Conversation resolution — happy path
# ---------------------------------------------------------------------------

def test_conversation_resolution_happy_path_two_threads_shared_participants_and_topic() -> None:
    """Shared participants + topic across two provider threads -> one Conversation."""
    # Gmail thread: the customer email trail around the renewal.
    gmail_msgs = [
        _message(
            "msg_g1",
            provider="gmail",
            external_thread_id="gmail-1",
            occurred_at="2026-09-01T10:00:00Z",
            subject="2026 enterprise renewal",
            evidence=(_ev("ev_g1"), _ev("ev_g2")),
        ),
        _message(
            "msg_g2",
            provider="gmail",
            external_thread_id="gmail-1",
            occurred_at="2026-09-01T10:05:00Z",
            subject="2026 enterprise renewal",
            evidence=(_ev("ev_g3"),),
        ),
    ]
    # Slack thread: the same renewal discussion on Slack.
    slack_msgs = [
        _message(
            "msg_s1",
            provider="slack",
            external_thread_id="slack-7",
            occurred_at="2026-09-01T10:10:00Z",
            subject="2026 enterprise renewal",
            evidence=(_ev("ev_s1"),),
        ),
    ]
    gmail_thread = _thread(
        "thr_gmail",
        provider="gmail",
        external_thread_id="gmail-1",
        message_ids=["msg_g1", "msg_g2"],
        subject="2026 enterprise renewal",
    )
    slack_thread = _thread(
        "thr_slack",
        provider="slack",
        external_thread_id="slack-7",
        message_ids=["msg_s1"],
        subject="2026 enterprise renewal",
    )
    # The customer participates in both channels; two different agents act per channel.
    bindings = [
        _binding(
            "bnd_g1",
            message_id="msg_g1",
            entity_id="ent_customer",
            role=CommunicationParticipantRole.BENEFICIARY,
        ),
        _binding(
            "bnd_g2",
            message_id="msg_g2",
            entity_id="ent_agent_gmail",
            role=CommunicationParticipantRole.AUTHOR,
        ),
        _binding(
            "bnd_s1",
            message_id="msg_s1",
            entity_id="ent_customer",
            role=CommunicationParticipantRole.BENEFICIARY,
        ),
        _binding(
            "bnd_s2",
            message_id="msg_s1",
            entity_id="ent_agent_slack",
            role=CommunicationParticipantRole.AUTHOR,
        ),
    ]

    conversation = resolve_conversation(
        tenant_id=TENANT,
        conversation_id="conv_renewal_1",
        provider_threads=[gmail_thread, slack_thread],
        messages=[*gmail_msgs, *slack_msgs],
        participants=bindings,
    )

    assert isinstance(conversation, Conversation)
    assert conversation.conversation_id == "conv_renewal_1"
    assert conversation.tenant_id == TENANT
    assert conversation.provider_thread_ids == ["thr_gmail", "thr_slack"]
    assert set(conversation.message_ids) == {"msg_g1", "msg_g2", "msg_s1"}
    assert set(pb.communication_scope for pb in conversation.participant_bindings) == {
        "msg_g1",
        "msg_g2",
        "msg_s1",
    }
    assert conversation.topic == "2026 enterprise renewal"
    assert conversation.matter_id is None

    resolution = conversation.resolution
    assert resolution is not None
    assert resolution.method == "participants+topics"
    assert 0.8 <= resolution.confidence <= 1.0
    # Supporting evidence refs reused from the message evidence.
    assert len(resolution.supporting_evidence_refs) >= 3
    evidence_ids = {ref.id for ref in resolution.supporting_evidence_refs}
    assert {"ev_g1", "ev_g3", "ev_s1"} <= evidence_ids
    assert resolution.contradictions == []
    # Derived product, never a verified/observed fact.
    assert conversation.claim_state is EpistemicStatus.INFERRED
    # Envelope metadata is derived from thread + message windows (continuity,
    # never causality): earliest first_seen / latest last_seen across inputs.
    assert conversation.opened_at == "2026-09-01T09:00:00Z"
    assert conversation.last_activity_at == "2026-09-01T11:00:00Z"


# ---------------------------------------------------------------------------
# Conversation resolution — ambiguity
# ---------------------------------------------------------------------------

def test_conversation_resolution_ambiguous_disjoint_threads_never_silently_picks() -> None:
    """Disjoint participants/topics with no session id -> low-confidence + contradiction."""
    msg_a = _message(
        "msg_a1",
        provider="gmail",
        external_thread_id="gmail-a",
        occurred_at="2026-09-01T10:00:00Z",
        subject="2026 enterprise renewal",
    )
    msg_b = _message(
        "msg_b1",
        provider="slack",
        external_thread_id="slack-b",
        occurred_at="2026-09-02T09:00:00Z",
        subject="hiring onboarding docs",
    )
    thread_a = _thread(
        "thr_a",
        provider="gmail",
        external_thread_id="gmail-a",
        message_ids=["msg_a1"],
        subject="2026 enterprise renewal",
    )
    thread_b = _thread(
        "thr_b",
        provider="slack",
        external_thread_id="slack-b",
        message_ids=["msg_b1"],
        subject="hiring onboarding docs",
    )
    bindings = [
        _binding(
            "bnd_a",
            message_id="msg_a1",
            entity_id="ent_customer_a",
            role=CommunicationParticipantRole.BENEFICIARY,
        ),
        _binding(
            "bnd_b",
            message_id="msg_b1",
            entity_id="ent_customer_b",
            role=CommunicationParticipantRole.BENEFICIARY,
        ),
    ]

    conversation = resolve_conversation(
        tenant_id=TENANT,
        conversation_id="conv_ambig",
        provider_threads=[thread_a, thread_b],
        messages=[msg_a, msg_b],
        participants=bindings,
    )

    resolution = conversation.resolution
    assert resolution is not None
    assert resolution.method == "ambiguous"
    assert resolution.confidence < 0.5
    # The ambiguity is named — never a silent thread pick.
    assert resolution.contradictions
    joined = " | ".join(resolution.contradictions)
    assert "ambiguous" in joined
    assert "no shared participant" in joined
    # Both candidate threads are still surfaced (combined-but-flagged), not one dropped.
    assert conversation.provider_thread_ids == ["thr_a", "thr_b"]
    assert set(conversation.message_ids) == {"msg_a1", "msg_b1"}
    assert conversation.claim_state is EpistemicStatus.INFERRED


def test_conversation_resolution_session_id_anchor_is_high_confidence() -> None:
    """An explicit session id anchors otherwise-disjoint threads into one conversation."""
    msg_a = _message(
        "msg_a1",
        provider="gmail",
        external_thread_id="gmail-a",
        occurred_at="2026-09-01T10:00:00Z",
        subject="offboarding",
    )
    msg_b = _message(
        "msg_b1",
        provider="slack",
        external_thread_id="slack-b",
        occurred_at="2026-09-02T09:00:00Z",
        subject="access audit",
    )
    thread_a = _thread(
        "thr_a",
        provider="gmail",
        external_thread_id="gmail-a",
        message_ids=["msg_a1"],
        subject="offboarding",
    )
    thread_b = _thread(
        "thr_b",
        provider="slack",
        external_thread_id="slack-b",
        message_ids=["msg_b1"],
        subject="access audit",
    )
    bindings = [
        _binding(
            "bnd_a",
            message_id="msg_a1",
            entity_id="ent_user",
            role=CommunicationParticipantRole.PRINCIPAL,
        ),
        _binding(
            "bnd_b",
            message_id="msg_b1",
            entity_id="ent_sec_agent",
            role=CommunicationParticipantRole.AUTHOR,
        ),
    ]

    conversation = resolve_conversation(
        tenant_id=TENANT,
        conversation_id="conv_session_1",
        provider_threads=[thread_a, thread_b],
        messages=[msg_a, msg_b],
        participants=bindings,
        explicit_session_id="session_offboarding_1",
    )

    assert conversation.resolution is not None
    assert conversation.resolution.method == "session_id"
    assert conversation.resolution.confidence >= 0.8
    assert conversation.matter_id is None


def test_conversation_resolution_shared_matter_sets_matter_id() -> None:
    """A shared matter anchors the conversation and binds it to that matter."""
    msg = _message(
        "msg_m1",
        provider="intercom",
        external_thread_id="case-99",
        occurred_at="2026-09-01T10:00:00Z",
        subject="vendor procurement",
    )
    thread = _thread(
        "thr_case",
        provider="intercom",
        external_thread_id="case-99",
        message_ids=["msg_m1"],
        subject="vendor procurement",
    )
    binding = _binding(
        "bnd_m",
        message_id="msg_m1",
        entity_id="ent_procurement",
        role=CommunicationParticipantRole.ACCOUNTABLE_PARTY,
    )

    conversation = resolve_conversation(
        tenant_id=TENANT,
        conversation_id="conv_matter_1",
        provider_threads=[thread],
        messages=[msg],
        participants=[binding],
        shared_matter_id="matter_procurement_1",
    )

    assert conversation.resolution is not None
    assert conversation.resolution.method == "shared_matter"
    assert conversation.resolution.confidence >= 0.8
    assert conversation.matter_id == "matter_procurement_1"


# ---------------------------------------------------------------------------
# Provider threads do not auto-equal conversations (§57)
# ---------------------------------------------------------------------------

def test_thread_can_standalone_false_for_empty_thread() -> None:
    thread = _thread(
        "thr_empty",
        provider="gmail",
        external_thread_id="gmail-empty",
        message_ids=[],
        subject=None,
    )
    assert thread_can_standalone_as_conversation(thread, participants=[]) is False


def test_thread_can_standalone_false_for_no_participant() -> None:
    thread = _thread(
        "thr_nop",
        provider="gmail",
        external_thread_id="gmail-nop",
        message_ids=["msg_nop"],
        subject=None,
    )
    # Messages present but no participant binding to them -> not a conversation.
    assert thread_can_standalone_as_conversation(thread, participants=[]) is False


def test_thread_can_standalone_true_with_message_and_participant() -> None:
    msg = _message(
        "msg_ok",
        provider="slack",
        external_thread_id="slack-ok",
        occurred_at="2026-09-01T10:00:00Z",
    )
    thread = _thread(
        "thr_ok",
        provider="slack",
        external_thread_id="slack-ok",
        message_ids=["msg_ok"],
        subject=None,
    )
    binding = _binding(
        "bnd_ok",
        message_id="msg_ok",
        entity_id="ent_customer",
        role=CommunicationParticipantRole.BENEFICIARY,
    )
    assert thread_can_standalone_as_conversation(thread, participants=[binding]) is True


def test_bare_thread_resolves_to_ambiguous_conversation() -> None:
    # A bare provider thread is surfaced with a low-confidence ambiguous
    # resolution and a named contradiction, never auto-elevated to a conversation.
    thread = _thread(
        "thr_bare",
        provider="gmail",
        external_thread_id="gmail-bare",
        message_ids=[],
        subject="unrelated",
    )
    conversation = resolve_conversation(
        tenant_id=TENANT,
        conversation_id="conv_bare",
        provider_threads=[thread],
        messages=[],
        participants=[],
    )
    assert conversation.resolution is not None
    assert conversation.resolution.method == "ambiguous"
    assert conversation.resolution.confidence < 0.5
    assert any("bare" in c for c in conversation.resolution.contradictions)


# ---------------------------------------------------------------------------
# Matter resolution (§59)
# ---------------------------------------------------------------------------

def _renewal_conversation(conversation_id: str) -> Conversation:
    return resolve_conversation(
        tenant_id=TENANT,
        conversation_id=conversation_id,
        provider_threads=[
            _thread(
                f"thr_{conversation_id}",
                provider="gmail",
                external_thread_id=f"gmail-{conversation_id}",
                message_ids=[f"msg_{conversation_id}"],
                subject="2026 enterprise renewal",
            )
        ],
        messages=[
            _message(
                f"msg_{conversation_id}",
                provider="gmail",
                external_thread_id=f"gmail-{conversation_id}",
                occurred_at=f"2026-09-01T10:00:00Z",
                subject="2026 enterprise renewal",
                evidence=(_ev(f"ev_{conversation_id}"),),
            )
        ],
        participants=[
            _binding(
                f"bnd_{conversation_id}",
                message_id=f"msg_{conversation_id}",
                entity_id="ent_customer",
                role=CommunicationParticipantRole.BENEFICIARY,
            )
        ],
    )


def test_matter_resolution_binds_conversations_and_campaign_anchor() -> None:
    conv_email = _renewal_conversation("conv_mail")
    conv_slack = _renewal_conversation("conv_chan")

    matter = resolve_matter(
        tenant_id=TENANT,
        matter_id="matter_renewal_2026",
        subject="2026 Enterprise Renewal",
        conversations=[conv_email, conv_slack],
        campaign_ids=["camp_renewal_2026"],
    )

    assert matter.matter_id == "matter_renewal_2026"
    assert matter.subject == "2026 Enterprise Renewal"
    assert matter.conversation_ids == ["conv_mail", "conv_chan"]
    assert matter.campaign_ids == ["camp_renewal_2026"]
    assert matter.episode_ids == []
    assert matter.external_refs == {}
    assert matter.resolution is not None
    assert matter.resolution.method == "conversations+campaign"
    assert matter.resolution.confidence >= 0.7
    # Evidence bubbles up from the resolved conversations.
    assert {ref.id for ref in matter.resolution.supporting_evidence_refs} >= {
        "ev_conv_mail",
        "ev_conv_chan",
    }
    assert matter.claim_state is EpistemicStatus.INFERRED


def test_matter_resolution_accepts_anchor_only_and_external_refs() -> None:
    matter = resolve_matter(
        tenant_id=TENANT,
        matter_id="matter_anchor",
        subject="Support Issue 4412",
        campaign_ids=["camp_support"],
        external_refs={"zendesk_ticket": "ticket-4412"},
    )
    assert matter.conversation_ids == []
    assert matter.campaign_ids == ["camp_support"]
    assert matter.external_refs == {"zendesk_ticket": "ticket-4412"}
    assert matter.resolution is not None
    assert matter.resolution.method == "campaign+external_ref"
    assert matter.claim_state is EpistemicStatus.INFERRED


def test_matter_resolution_refuses_to_bind_nothing() -> None:
    with pytest.raises(ValueError):
        resolve_matter(
            tenant_id=TENANT,
            matter_id="matter_phantom",
            subject="Unmoored subject",
            conversations=[],
        )


# ---------------------------------------------------------------------------
# Declared-lineage causal ordering (§54) — never from timestamps
# ---------------------------------------------------------------------------

def test_order_messages_declared_orders_by_lineage_not_occurred_at() -> None:
    # msg_b declares responds_to msg_a, but msg_b's timestamp is EARLIER than
    # msg_a's. Declared lineage must win; occurred_at must be ignored.
    msg_a = _message(
        "msg_a",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-02T12:00:00Z",
    )
    msg_b = _message(
        "msg_b",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-01T08:00:00Z",
    )
    lineage = {"msg_b": ("responds_to", "msg_a")}

    ordered = order_messages_declared([msg_b, msg_a], lineage=lineage)
    assert [m.message_id for m in ordered] == ["msg_a", "msg_b"]

    # Reverse the input order: the answer is identical (deterministic).
    ordered_reversed_input = order_messages_declared([msg_a, msg_b], lineage=lineage)
    assert [m.message_id for m in ordered_reversed_input] == ["msg_a", "msg_b"]


def test_order_messages_declared_handles_supersedes_chain() -> None:
    # original -> revision (supersedes) -> reply (responds_to revision).
    original = _message(
        "msg_orig",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-03T09:00:00Z",
    )
    revision = _message(
        "msg_rev",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-01T09:05:00Z",
    )
    reply = _message(
        "msg_reply",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-08-30T07:00:00Z",
    )
    lineage = {
        "msg_rev": ("supersedes", "msg_orig"),
        "msg_reply": ("responds_to", "msg_rev"),
    }
    ordered = order_messages_declared([reply, revision, original], lineage=lineage)
    assert [m.message_id for m in ordered] == ["msg_orig", "msg_rev", "msg_reply"]


def test_order_messages_declared_no_lineage_keeps_input_order() -> None:
    # No declared lineage -> exact input order is preserved regardless of
    # occurred_at ordering (never reordered by timestamp).
    early = _message(
        "msg_early",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-01T08:00:00Z",
    )
    later = _message(
        "msg_later",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-05T20:00:00Z",
    )
    inputs = [later, early]  # deliberately not time-ordered
    ordered = order_messages_declared(inputs)
    assert ordered == inputs
    assert [m.message_id for m in ordered] == ["msg_later", "msg_early"]


def test_order_messages_declared_ignores_lineage_outside_input_set() -> None:
    # Declared relations to messages NOT in the set impose no reordering.
    msg_x = _message(
        "msg_x",
        provider="slack",
        external_thread_id="slack-1",
        occurred_at="2026-09-05T20:00:00Z",
    )
    msg_y = _message(
        "msg_y",
        provider="slack",
        external_thread_id="slack-1",
        occurred_at="2026-09-01T08:00:00Z",
    )
    lineage = {
        "msg_x": ("responds_to", "msg_unknown_outside"),
        "msg_y": ("supersedes", "msg_other_outside"),
    }
    assert [m.message_id for m in order_messages_declared([msg_x, msg_y], lineage)] == [
        "msg_x",
        "msg_y",
    ]


def test_order_messages_declared_raises_on_declared_cycle() -> None:
    msg_p = _message(
        "msg_p",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-01T08:00:00Z",
    )
    msg_q = _message(
        "msg_q",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-01T09:00:00Z",
    )
    lineage = {
        "msg_p": ("responds_to", "msg_q"),
        "msg_q": ("responds_to", "msg_p"),
    }
    with pytest.raises(ValueError):
        order_messages_declared([msg_p, msg_q], lineage=lineage)


def test_is_causally_ordered_true_only_for_declared_edge() -> None:
    msg_a = _message(
        "msg_a",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-01T08:00:00Z",
    )
    msg_b = _message(
        "msg_b",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-01T09:00:00Z",
    )
    lineage = {"msg_b": ("responds_to", "msg_a")}

    assert is_causally_ordered(msg_a, msg_b, lineage) is True
    assert is_causally_ordered(msg_b, msg_a, lineage) is False


def test_timestamp_proximity_never_implies_causality() -> None:
    # Two messages with adjacent timestamps but NO declared edge are NOT
    # causally ordered, and stay in input order.
    first = _message(
        "msg_t1",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-01T10:00:00Z",
    )
    second = _message(
        "msg_t2",
        provider="gmail",
        external_thread_id="gmail-1",
        occurred_at="2026-09-01T10:00:01Z",  # one second later — still no cause
    )
    empty_lineage: dict[str, tuple[str, str]] = {}

    assert is_causally_ordered(first, second, empty_lineage) is False
    assert is_causally_ordered(second, first, empty_lineage) is False
    assert [m.message_id for m in order_messages_declared([second, first])] == [
        "msg_t2",
        "msg_t1",
    ]
