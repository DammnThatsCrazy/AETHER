"""Cluster Targeting Intelligence — Pydantic mirrors of
packages/shared/targeting-intelligence.ts (camelCase wire fields, 1:1).

Non-execution invariants are enforced at the model layer: every intent and
export carries frozen ``executionByAether=False`` and
``externalExecutionRequired=True``; payloads claiming otherwise are rejected.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

TARGETING_SCHEMA_VERSION = "targeting.intelligence.v1"

TargetingIntentSource = Literal[
    "tenant_declared", "provider_observed", "suggestion_generated",
    "operator_reviewed", "system_inferred",
]
TargetingExecutionBoundary = Literal["external_execution_required", "observed_only"]
ExclusionReasonCode = Literal[
    "consent_blocked", "regulatory_or_policy", "fraud_risk", "churn_sensitive",
    "frequency_cap", "low_confidence_identity", "manual_tenant_exclusion",
    "negative_holdout", "overexposed", "provider_mapping_low_confidence",
    "operator_suppressed", "unknown",
]
HoldoutReason = Literal[
    "measurement_control", "risk_control", "tenant_manual",
    "operator_review", "model_validation",
]
# Strictest safe rule first — policy.py resolves in this order.
TargetingConflictResolution = Literal[
    "hard_consent_block", "regulatory_policy_block", "fraud_risk_exclusion",
    "tenant_manual_exclusion", "holdout_control", "inclusion",
    "similarity_reference_inclusion",
]
RuleType = Literal["include", "exclude", "reference", "holdout", "suppress"]
LeakageSeverity = Literal["info", "low", "medium", "high", "critical"]
GraphMode = Literal["neighborhood", "attribution", "decision_outcome", "evidence", "multi_source"]
SyncFreshness = Literal["live", "recent", "stale", "unknown"]

LIKELY_CAUSES = (
    "provider_ignored_exclusion", "tenant_uploaded_wrong_audience",
    "identity_resolved_after_launch", "cluster_overlap",
    "lookalike_expansion", "utm_mapping_error", "unknown",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _check_unit(value: Optional[float], name: str) -> Optional[float]:
    if value is not None and not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be within 0..1")
    return value


class EntityRef(BaseModel):
    kind: str
    id: str
    label: Optional[str] = None


class EvidenceRef(BaseModel):
    id: str
    type: str = "event"
    source: str
    observedAt: Optional[str] = None
    confidence: Optional[float] = None
    uri: Optional[str] = None

    _conf = field_validator("confidence")(lambda v: _check_unit(v, "confidence"))


class TimeRangeFilter(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class PolicyDecision(BaseModel):
    """Auditable record of one conflict-precedence resolution."""
    id: str = Field(default_factory=lambda: new_id("pol"))
    tenantId: str
    clusterId: str
    resolution: TargetingConflictResolution
    ruleApplied: str
    inputsSummary: dict[str, Any] = Field(default_factory=dict)
    decidedAt: str = Field(default_factory=utc_now_iso)


class ClusterTargetingRule(BaseModel):
    clusterId: str
    ruleType: RuleType
    reasonCode: Optional[str] = None
    confidenceScore: Optional[float] = None
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)

    _conf = field_validator("confidenceScore")(lambda v: _check_unit(v, "confidenceScore"))


class TargetingIntent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ti"))
    tenantId: str
    orgId: Optional[str] = None
    campaignId: Optional[str] = None

    source: TargetingIntentSource
    executionBoundary: TargetingExecutionBoundary = "external_execution_required"
    executionByAether: Literal[False] = False
    externalExecutionRequired: Literal[True] = True

    includeClusters: list[str] = Field(default_factory=list)
    includeEntities: Optional[list[EntityRef]] = None
    referenceClusters: Optional[list[str]] = None
    excludeClusters: list[str] = Field(default_factory=list)
    suppressEntities: Optional[list[EntityRef]] = None
    holdoutClusters: Optional[list[str]] = None

    rules: list[ClusterTargetingRule] = Field(default_factory=list)

    maxHopDepth: Literal[1, 2, 3] = 1
    graphMode: GraphMode = "neighborhood"

    minIdentityConfidence: float = 0.7
    minClusterMembershipScore: float = 0.6
    minPathConfidence: float = 0.5
    minEvidenceCoverage: float = 0.5

    createdBy: Optional[str] = None
    createdAt: str = Field(default_factory=utc_now_iso)
    updatedAt: str = Field(default_factory=utc_now_iso)

    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)
    policyDecisionIds: Optional[list[str]] = None

    @field_validator("minIdentityConfidence", "minClusterMembershipScore",
                     "minPathConfidence", "minEvidenceCoverage")
    @classmethod
    def _unit_thresholds(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("thresholds must be within 0..1")
        return v


class TargetingEligibilitySnapshot(BaseModel):
    snapshotId: str = Field(default_factory=lambda: new_id("tes"))
    tenantId: str
    campaignId: Optional[str] = None
    targetingIntentId: str

    asOf: str
    graphWatermark: Optional[str] = None

    eligibleClusters: list[str] = Field(default_factory=list)
    eligibleEntities: list[EntityRef] = Field(default_factory=list)
    excludedClusters: list[str] = Field(default_factory=list)
    suppressedEntities: list[EntityRef] = Field(default_factory=list)
    holdoutClusters: list[str] = Field(default_factory=list)

    identityConfidenceThreshold: float
    clusterMembershipThreshold: float
    pathConfidenceThreshold: float
    evidenceCoverageThreshold: float

    clusterMemberCounts: dict[str, int] = Field(default_factory=dict)
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)
    policyDecisionIds: list[str] = Field(default_factory=list)

    createdAt: str = Field(default_factory=utc_now_iso)


class ProviderMappingQuality(BaseModel):
    campaignId: Optional[str] = None
    provider: Optional[str] = None
    mappingRate: float = 0.0
    providerSyncFreshness: SyncFreshness = "unknown"
    unresolvedAliasCount: int = 0
    touchpointResolutionRate: float = 0.0
    identityResolutionRate: float = 0.0
    clusterAssignmentRate: float = 0.0
    qualityScore: float = 0.0
    blocksSuggestions: bool = True
    reasons: list[str] = Field(default_factory=list)
    computedAt: str = Field(default_factory=utc_now_iso)

    @field_validator("mappingRate", "touchpointResolutionRate", "identityResolutionRate",
                     "clusterAssignmentRate", "qualityScore")
    @classmethod
    def _unit_rates(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("rates must be within 0..1")
        return v


class TargetingObservation(BaseModel):
    observationId: str = Field(default_factory=lambda: new_id("tob"))
    tenantId: str
    campaignId: str
    targetingIntentId: Optional[str] = None
    eligibilitySnapshotId: Optional[str] = None

    sourceProvider: Optional[str] = None
    sourceCampaignRef: Optional[str] = None

    reachedClusters: list[str] = Field(default_factory=list)
    reachedEntities: list[EntityRef] = Field(default_factory=list)

    reachedIncludedClusters: list[str] = Field(default_factory=list)
    reachedReferenceClusters: list[str] = Field(default_factory=list)
    reachedExcludedClusters: list[str] = Field(default_factory=list)
    reachedHoldoutClusters: list[str] = Field(default_factory=list)

    providerMappingQuality: ProviderMappingQuality

    observedAt: str = Field(default_factory=utc_now_iso)
    computedAt: str = Field(default_factory=utc_now_iso)
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)


class ExclusionLeakageFinding(BaseModel):
    findingId: str = Field(default_factory=lambda: new_id("elf"))
    tenantId: str
    campaignId: str
    targetingIntentId: Optional[str] = None
    clusterId: str

    reasonCode: ExclusionReasonCode
    excludedEntityCount: int = 0
    reachedEntityCount: int = 0
    leakageRate: float = 0.0

    likelyCauses: list[str] = Field(default_factory=lambda: ["unknown"])
    severity: LeakageSeverity = "info"
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)
    computedAt: str = Field(default_factory=utc_now_iso)

    @field_validator("likelyCauses")
    @classmethod
    def _known_causes(cls, v: list[str]) -> list[str]:
        for cause in v:
            if cause not in LIKELY_CAUSES:
                raise ValueError(f"unknown likely cause: {cause}")
        return v

    _rate = field_validator("leakageRate")(lambda v: _check_unit(v, "leakageRate"))


class TargetingHoldout(BaseModel):
    holdoutId: str = Field(default_factory=lambda: new_id("hld"))
    tenantId: str
    campaignId: Optional[str] = None
    targetingIntentId: str
    clusterIds: list[str] = Field(default_factory=list)
    reason: HoldoutReason
    contaminated: bool = False
    contaminationRate: Optional[float] = None
    startAt: str = Field(default_factory=utc_now_iso)
    endAt: Optional[str] = None
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)

    _rate = field_validator("contaminationRate")(
        lambda v: _check_unit(v, "contaminationRate")
    )


class ClusterJourneyDelta(BaseModel):
    deltaId: str = Field(default_factory=lambda: new_id("cjd"))
    tenantId: str
    campaignId: str
    clusterId: str

    comparedToClusterIds: Optional[list[str]] = None
    holdoutClusterIds: Optional[list[str]] = None

    beforeWindow: TimeRangeFilter
    afterWindow: TimeRangeFilter

    populationStageDeltas: dict[str, float] = Field(default_factory=dict)
    commsStageDeltas: Optional[dict[str, float]] = None

    reachedCount: int = 0
    engagedCount: int = 0
    convertedCount: int = 0
    attributedCount: int = 0

    nonProgressedCount: int = 0
    progressedElsewhereCount: int = 0

    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)
    computedAt: str = Field(default_factory=utc_now_iso)


class ClusterTargetingImpact(BaseModel):
    tenantId: str
    campaignId: str
    clusterId: str

    memberCount: int = 0
    eligibleCount: int = 0
    reachedCount: int = 0
    engagedCount: int = 0
    convertedCount: int = 0
    attributedCount: int = 0

    spendUsd: Optional[float] = None
    revenueUsd: Optional[float] = None
    roas: Optional[float] = None
    ltvDelta: Optional[float] = None

    complaintRate: Optional[float] = None
    unsubscribeRate: Optional[float] = None
    churnSignalRate: Optional[float] = None
    fraudSignalRate: Optional[float] = None
    overexposureScore: Optional[float] = None

    identityConfidence: Optional[float] = None
    clusterMembershipConfidence: Optional[float] = None
    evidenceCoverage: float = 0.0

    computedAt: str = Field(default_factory=utc_now_iso)
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)


class PositiveOutcomes(BaseModel):
    conversions: int = 0
    revenue: float = 0.0
    roas: Optional[float] = None
    ltvDelta: Optional[float] = None
    journeyProgression: int = 0


class NegativeOutcomes(BaseModel):
    unsubscribes: int = 0
    complaints: int = 0
    churnSignals: int = 0
    fraudSignals: int = 0
    refunds: int = 0
    supportBurden: int = 0
    overexposureSignals: int = 0


class TargetingOutcomeSnapshot(BaseModel):
    snapshotId: str = Field(default_factory=lambda: new_id("tos"))
    tenantId: str
    campaignId: str
    targetingIntentId: Optional[str] = None
    eligibilitySnapshotId: Optional[str] = None
    observationId: Optional[str] = None

    positiveOutcomes: PositiveOutcomes = Field(default_factory=PositiveOutcomes)
    negativeOutcomes: NegativeOutcomes = Field(default_factory=NegativeOutcomes)

    clusterImpacts: list[ClusterTargetingImpact] = Field(default_factory=list)
    leakageFindings: list[ExclusionLeakageFinding] = Field(default_factory=list)
    journeyDeltas: list[ClusterJourneyDelta] = Field(default_factory=list)

    confidenceScore: float = 0.0
    evidenceCoverage: float = 0.0
    pathClassification: Optional[str] = None

    computedAt: str = Field(default_factory=utc_now_iso)
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)

    _conf = field_validator("confidenceScore")(lambda v: _check_unit(v, "confidenceScore"))


class TargetingRecommendationExportPackage(BaseModel):
    exportId: str = Field(default_factory=lambda: new_id("tex"))
    tenantId: str
    suggestionId: Optional[str] = None
    targetingIntentId: Optional[str] = None
    campaignId: Optional[str] = None

    includeClusterIds: list[str] = Field(default_factory=list)
    referenceClusterIds: list[str] = Field(default_factory=list)
    excludeClusterIds: list[str] = Field(default_factory=list)
    holdoutClusterIds: list[str] = Field(default_factory=list)

    implementationNotes: list[str] = Field(default_factory=list)
    externalExecutionRequired: Literal[True] = True
    executionByAether: Literal[False] = False

    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)
    generatedAt: str = Field(default_factory=utc_now_iso)
