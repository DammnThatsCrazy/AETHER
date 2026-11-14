"""UniversalObservationEnvelope (Envelope B) — canonical server-side
observation model. Runtime models live in ``shared.observation.envelope``;
the canonical field registry is
``packages/shared/contracts/observation-envelope-registry.json`` and the
passive TS mirror is ``packages/shared/observation-envelope.ts``.
"""

from shared.observation.envelope import (
    CREDENTIAL_CLASSES,
    IDENTIFIER_TYPES,
    SOURCE_RELATIONSHIPS,
    SOURCE_TYPES,
    TRUST_CLASSES,
    ActorContextBlock,
    AuthorityContextBlock,
    CorrelationBlock,
    ExecutionContextBlock,
    LineageBlock,
    ObservationBlock,
    PrivacyBlock,
    ProtocolContextBlock,
    ProvenanceBlock,
    QualityBlock,
    RightsReferenceBlock,
    SourceBlock,
    SubjectRef,
    TemporalBlock,
    TenancyBlock,
    UniversalObservationEnvelope,
)

__all__ = [
    "CREDENTIAL_CLASSES",
    "IDENTIFIER_TYPES",
    "SOURCE_RELATIONSHIPS",
    "SOURCE_TYPES",
    "TRUST_CLASSES",
    "ActorContextBlock",
    "AuthorityContextBlock",
    "CorrelationBlock",
    "ExecutionContextBlock",
    "LineageBlock",
    "ObservationBlock",
    "PrivacyBlock",
    "ProtocolContextBlock",
    "ProvenanceBlock",
    "QualityBlock",
    "RightsReferenceBlock",
    "SourceBlock",
    "SubjectRef",
    "TemporalBlock",
    "TenancyBlock",
    "UniversalObservationEnvelope",
]
