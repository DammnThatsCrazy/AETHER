"""Communication-domain vocabularies reconcile onto EpistemicStatus.

Phase 2 of the Communication360 convergence program:
``shared/contracts_models/epistemic_communication.py`` maps the
communication-domain observation vocabularies (``CommunicationState``,
``ActionStatus``) onto the consolidated ``EpistemicStatus`` authority. This
test fails if:

* any mapping table drifts from its live source vocabulary (totality), or
* any table value escalates past ``observed`` into the factual band
  (``verified`` / ``resolved`` / ``causally_supported``) — a delivery or
  agent-action fact must never license a recipient-knowledge or author-intent
  claim, and
* the mapping module starts importing its source enums at runtime (keys are
  literals; the shared package stays service-free).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from shared.contracts_models.epistemic_communication import (  # noqa: E402
    ACTION_STATUS_TO_EPISTEMIC,
    COMMUNICATION_STATE_TO_EPISTEMIC,
)
from services.agentic_observability.models import ActionStatus  # noqa: E402
from services.comms.contracts import CommunicationState  # noqa: E402

MODULE_PATH = (
    BACKEND / "shared" / "contracts_models" / "epistemic_communication.py"
)

# A message-event / agent-action fact is an observation about the event itself.
# It may never escalate into the factual band above ``observed`` — those bands
# require their own evidence-grounded record (verified identity link, held-out
# experiment, independent corroboration), which a delivery or agent-action state
# can never supply.
_FACTUAL_ABOVE_OBSERVED = {
    EpistemicStatus.VERIFIED,
    EpistemicStatus.RESOLVED,
    EpistemicStatus.CAUSALLY_SUPPORTED,
}

_MAPPING_TABLES = (
    (COMMUNICATION_STATE_TO_EPISTEMIC, CommunicationState),
    (ACTION_STATUS_TO_EPISTEMIC, ActionStatus),
)


def test_mapping_tables_cover_their_source_vocabularies():
    """Every CommunicationState / ActionStatus value has a canonical status."""
    for table, source_enum in _MAPPING_TABLES:
        source_values = {m.value for m in source_enum}
        assert set(table) == source_values, (
            f"{table.__name__} keys drifted from {source_enum.__name__}: "
            f"extra={set(table) - source_values}, "
            f"missing={source_values - set(table)}"
        )


def test_mapping_values_are_canonical_members():
    for table, _ in _MAPPING_TABLES:
        for source_value, status in table.items():
            assert isinstance(status, EpistemicStatus), (
                f"{table.__name__}[{source_value!r}] is not an EpistemicStatus member"
            )


def test_no_communication_fact_escalates_into_the_factual_band():
    """Delivery / agent-action facts are at most observed — never a factual
    declaration about recipient knowledge, author intent, or human action."""
    for table, source_enum in _MAPPING_TABLES:
        escalated = set(table.values()) & _FACTUAL_ABOVE_OBSERVED
        assert not escalated, (
            f"{table.__name__} escalates into the factual band: {escalated}"
        )


def test_message_state_facts_are_event_observations_only():
    """Every CommunicationState maps to observed (a message-event observation)
    or unavailable (withheld by consent/policy) — the suspicion band is never
    implied by a lifecycle state, and knowledge is never implied at all."""
    assert set(COMMUNICATION_STATE_TO_EPISTEMIC.values()) <= {
        EpistemicStatus.OBSERVED,
        EpistemicStatus.UNAVAILABLE,
    }, (
        "a CommunicationState mapping implies more than the message event supports"
    )


def test_action_status_observed_never_implies_principal_authority():
    """`succeeded_observed` / `failed_observed` attest to the agent action, not
    the principal — none may map to a factual band member."""
    assert ACTION_STATUS_TO_EPISTEMIC["succeeded_observed"] is EpistemicStatus.OBSERVED
    assert ACTION_STATUS_TO_EPISTEMIC["denied_observed"] is EpistemicStatus.OBSERVED
    assert ACTION_STATUS_TO_EPISTEMIC["unknown"] is EpistemicStatus.UNKNOWN


def test_mapping_module_stays_service_free():
    """Keys are literals; the shared module must never import its source enums."""
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import services" not in text, "epistemic_communication imports services"
    assert "from services" not in text, "epistemic_communication imports services"
