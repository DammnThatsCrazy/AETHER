"""Communication360 canonical facts + provider (Phase 3).

Read-mostly + new-canonical-facts package over the shipped comms silver path
(``services/comms`` → ``silver_comms_facts``) and the ratified information /
knowledge / participant authorities (Phase 2 R1–R5). The registry row
``communication360`` remains ``in_flight`` through Phase 5; this package
implements the canonical contracts, storage, and (Phase 4) the
``Communication360Provider`` that projects over them read-only.
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

__all__ = [
    "AgentConsumptionState",
    "AuthorityEvaluation",
    "AuthorityState",
    "CapabilityState",
    "Commitment",
    "CommunicationAct",
    "CommunicationActType",
    "CommunicationContract",
    "CommunicationMessage",
    "CommunicationParticipantRole",
    "CommunicationQuality",
    "ContextInclusionRecord",
    "Conversation",
    "ConversationState",
    "Information",
    "InformationRef",
    "InformationTransformation",
    "InterpretationRecord",
    "KnowledgeStateRecord",
    "Matter",
    "MessageClaimBinding",
    "ParticipantBinding",
    "ProviderCapability",
    "ProviderThread",
    "Request",
    "ResolutionRecord",
    "ResponseExpectation",
]
