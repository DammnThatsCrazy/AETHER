"""Communication360 canonical facts + provider (Phases 3–6).

Read-only ``sequence_360`` package over the shipped comms silver path
(``services/comms`` → ``silver_comms_facts``) and the ratified information /
knowledge / participant authorities (Phase 2 R1–R5). The registry row
``communication360`` is a read-only projection that never owns canonical truth;
this package implements the canonical contracts, typed JSONB storage, source
readers, the ``Communication360Provider`` that projects over them, and the
fidelity / knowledge / authority / resolution engines.

Modules:

* :mod:`~services.communication360.contracts` — canonical comms / information /
  transfer contracts (Phase 3, every fact ``claim_state``-capped observed);
* :mod:`~services.communication360.repository` — typed JSONB fact store
  (``communication360_facts``, idempotent upsert, in-memory fallback);
* :mod:`~services.communication360.registry` — seeded vocab dimensions
  (participant role / act / conversation / consumption / authority / capability);
* :mod:`~services.communication360.reader` — ``SilverCommsSource`` +
  ``CanonicalFactSource`` typed read-overs;
* :mod:`~services.communication360.provider` — the ``Communication360Provider``
  (``projection_id="communication360"``, read-only) + ``register_provider``;
* :mod:`~services.communication360.resolution` — conversation / matter
  resolution over declared lineage (never timestamp-inferred);
* :mod:`~services.communication360.fidelity` — information-fidelity engine
  (§71 metrics);
* :mod:`~services.communication360.knowledge` — knowledge / interpretation /
  context-inclusion mapping (R4, observed-capped);
* :mod:`~services.communication360.authority` — delegation-outcome →
  authority-state evaluation;
* :mod:`~services.communication360.routes` — the read-only ``/v1/communication360``
  FastAPI router (all GET, tenant-scoped, ``communication360.read``-gated).

The blueprint is ``docs/blueprints/communication360.md``; the program ledger is
``docs/plans/COMMUNICATION_360_PHASES.md``.
"""

from services.communication360.contracts import (  # noqa: F401
    AgentConsumptionState,
    AuthorityEvaluation,
    AuthorityState,
    CapabilityState,
    Commitment,
    CommunicationAct,
    CommunicationActType,
    CommunicationContract,
    CommunicationMessage,
    CommunicationParticipantRole,
    CommunicationQuality,
    ContextInclusionRecord,
    Conversation,
    ConversationState,
    Information,
    InformationRef,
    InformationTransformation,
    InterpretationRecord,
    KnowledgeStateRecord,
    Matter,
    MessageClaimBinding,
    ParticipantBinding,
    ProviderCapability,
    ProviderThread,
    Request,
    ResolutionRecord,
    ResponseExpectation,
)

from services.communication360.provider import (  # noqa: F401
    Communication360Provider,
    register_provider,
)
from services.communication360.routes import (  # noqa: F401
    EXPLORE_CAPABILITY,
    PROJECTION_ID,
    READ_CAPABILITY,
    create_router,
    router,
)

__all__ = [
    "AgentConsumptionState",
    "AuthorityEvaluation",
    "AuthorityState",
    "CapabilityState",
    "Commitment",
    "Communication360Provider",
    "CommunicationAct",
    "CommunicationActType",
    "CommunicationContract",
    "CommunicationMessage",
    "CommunicationParticipantRole",
    "CommunicationQuality",
    "ContextInclusionRecord",
    "Conversation",
    "ConversationState",
    "EXPLORE_CAPABILITY",
    "Information",
    "InformationRef",
    "InformationTransformation",
    "InterpretationRecord",
    "KnowledgeStateRecord",
    "Matter",
    "MessageClaimBinding",
    "PROJECTION_ID",
    "ParticipantBinding",
    "ProviderCapability",
    "ProviderThread",
    "READ_CAPABILITY",
    "Request",
    "ResolutionRecord",
    "ResponseExpectation",
    "create_router",
    "register_provider",
    "router",
]
