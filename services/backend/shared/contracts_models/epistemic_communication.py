"""Communication / agent-observation vocabularies → EpistemicStatus (Python).

Phase 2 of the Communication360 convergence program. The generic claim-state
authority is :class:`~shared.contracts_models.epistemic.EpistemicStatus` (the
single consolidated vocabulary this repository renders claims against). This
module reconciles the *communication-domain* observation vocabularies onto that
authority so a claim built from a raw comms / agent-observation fact can never
silently escalate past what the fact supports.

No-silent-escalation invariant (communication form)
---------------------------------------------------
A message / delivery / engagement fact is an *observation about the message
event itself*: at most :attr:`EpistemicStatus.OBSERVED`. It never grants
epistemic weight about what the recipient *knew* (delivery ≠ knowledge), who
the *author* was (sender ≠ author ≠ principal), or whether a *human* took an
action an agent performed (machine-classified engagement is never human
engagement). A recipient-knowledge, author-intent, or authority claim is a
structurally different object (the information/knowledge + role-matrix layer
this program models in Phase 3/5) and must be backed by its own observation —
it can never be derived from a delivery or agent-action state alone.

Consolidation
-------------
Keys are fragment values kept as literal strings (this shared package never
imports services/generated modules at runtime); values are canonical
:class:`EpistemicStatus` members.

* ``COMMUNICATION_STATE_TO_EPISTEMIC`` ← ``CommunicationState``
  (``services/comms/contracts.py``) — provider-normalized lifecycle state of a
  communication fact.
* ``ACTION_STATUS_TO_EPISTEMIC``        ← ``ActionStatus``
  (``services/agentic_observability/models.py``) — observed outcome of an agent
  action.

The parity test ``tests/contracts/test_epistemic_communication_parity.py``
imports the source enums directly and asserts each table covers its vocabulary
exactly (literal keys cannot drift from their sources) and that no table value
sits in the factual band above ``observed``.
"""

from __future__ import annotations

from typing import Final

from shared.contracts_models.epistemic import EpistemicStatus

# ── Communication-domain vocabulary → EpistemicStatus mapping tables ─────────
#
# All keys are the frozen values of the source vocabulary named in the
# comment. Totality is enforced by tests/contracts/test_epistemic_communication_parity.py.

# CommunicationState (services/comms/contracts.py) — normalized lifecycle state
# of a communication fact. Every member is an observation about the MESSAGE
# EVENT (transport outcome, engagement signal, or consent/policy state). None
# attests to what the recipient knew or who authored the content; a fact that a
# message was sent/delivered/opened/clicked/replied is therefore at most
# ``observed``, and no member maps to the factual band (verified / resolved /
# causally_supported).
COMMUNICATION_STATE_TO_EPISTEMIC: dict[str, EpistemicStatus] = {
    # Transport lifecycle — observed message-event outcomes, never recipient
    # knowledge. "received"/"opened"/"clicked"/"replied" attest to the transport
    # or engagement signal, not to comprehension or intent.
    "queued": EpistemicStatus.OBSERVED,  # accepted by the transport, not yet sent
    "processed": EpistemicStatus.OBSERVED,  # transport processed the send
    "sent": EpistemicStatus.OBSERVED,  # handed to the transport (≠ delivered, ≠ read)
    "delivered": EpistemicStatus.OBSERVED,  # reached the inbox (≠ known)
    "deferred": EpistemicStatus.OBSERVED,  # transport retrying (observed delay)
    "bounced": EpistemicStatus.OBSERVED,  # non-delivery observed (recipient address)
    "dropped": EpistemicStatus.OBSERVED,  # suppressed/aborted by policy mid-flight
    "opened": EpistemicStatus.OBSERVED,  # engagement signal (≠ read ≠ knew)
    "clicked": EpistemicStatus.OBSERVED,  # engagement signal (≠ human; machine click excluded elsewhere)
    "replied": EpistemicStatus.OBSERVED,  # outbound/inbound reply observed (≠ authored by the human)
    "complained": EpistemicStatus.OBSERVED,  # recipient complaint observed
    "received": EpistemicStatus.OBSERVED,  # recipient-side delivery observed (≠ read ≠ knew)
    "observed": EpistemicStatus.OBSERVED,  # raw observation captured directly
    # Consent / preference state — an observed preference change, and a
    # suppression that exists because policy withheld the message.
    "unsubscribed": EpistemicStatus.OBSERVED,  # observed recipient preference change
    "suppressed": EpistemicStatus.UNAVAILABLE,  # withheld by consent/policy — not knowledge
}

# ActionStatus (services/agentic_observability/models.py) — observed outcome of
# an agent action. ``*_observed`` members attest that the AGENT action and its
# outcome were observed; they never attest to the principal's intent or
# authority (an agent "succeeded" at sending is not "the human wrote it", and a
# denial is not a silent success).
ACTION_STATUS_TO_EPISTEMIC: dict[str, EpistemicStatus] = {
    "observed": EpistemicStatus.OBSERVED,  # agent action observed in flight
    "succeeded_observed": EpistemicStatus.OBSERVED,  # action outcome observed as success — about the agent
    "failed_observed": EpistemicStatus.OBSERVED,  # action outcome observed as failure
    "denied_observed": EpistemicStatus.OBSERVED,  # denial observed (authorization denied — never silent)
    "unknown": EpistemicStatus.UNKNOWN,  # outcome genuinely not observed
}

__all__ = [
    "COMMUNICATION_STATE_TO_EPISTEMIC",
    "ACTION_STATUS_TO_EPISTEMIC",
]
