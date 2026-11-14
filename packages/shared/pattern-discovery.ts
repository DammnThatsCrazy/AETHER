// =============================================================================
// Pattern Discovery & Unstructured Evidence Intelligence — frontend-safe
// contracts for /v1/intelligence/patterns, /v1/kyber/patterns and the
// Profile 360 / Agent 360 / Risk 360 pattern sections.
//
// Canonical home: services/api/intelligence/pattern_discovery/contracts.py.
// Hand-authored twin; parity of every vocabulary below is asserted by
// tests/unit/test_pattern_discovery_contract_parity.py.
//
// Every discovered pattern is an inferred candidate: confidence is capped per
// kind, only a reviewer verdict leaves the funnel, and promotion produces
// attributed (never verified) Risk360 signals.
// =============================================================================

export const PATTERN_KINDS = [
  'sequence',
  'shared_attribute_cluster',
  'behavioral_cohort',
  'temporal_burst',
  'lockstep',
  'behavioral_outlier',
  'novel_motif',
  'schema_drift',
  'segment_shift',
  'agent_spawn_anomaly',
  'agent_tool_signature',
  'agent_interaction_cluster',
  'traffic_anomaly',
  'cross_domain',
] as const;
export type PatternKind = (typeof PATTERN_KINDS)[number];

/** Confidence ceiling per kind (no detector output can exceed it). */
export const PATTERN_CONFIDENCE_CAPS: Readonly<Record<PatternKind, number>> = {
  sequence: 0.75,
  shared_attribute_cluster: 0.75,
  behavioral_cohort: 0.7,
  temporal_burst: 0.7,
  lockstep: 0.75,
  behavioral_outlier: 0.65,
  novel_motif: 0.7,
  schema_drift: 0.9,
  segment_shift: 0.7,
  agent_spawn_anomaly: 0.7,
  agent_tool_signature: 0.75,
  agent_interaction_cluster: 0.75,
  traffic_anomaly: 0.6,
  cross_domain: 0.85,
};

export const PATTERN_STATUSES = [
  'candidate',
  'needs_review',
  'confirmed_valid',
  'confirmed_malicious',
  'benign',
  'duplicate',
  'unresolved',
  'promoted',
  'deprecated',
] as const;
export type PatternStatus = (typeof PATTERN_STATUSES)[number];

export const PATTERN_VERDICTS = ['valid', 'malicious', 'benign', 'duplicate', 'unresolved'] as const;
export type PatternVerdict = (typeof PATTERN_VERDICTS)[number];

/** Status a verdict moves a pattern to. */
export const PATTERN_VERDICT_STATUS: Readonly<Record<PatternVerdict, PatternStatus>> = {
  valid: 'confirmed_valid',
  malicious: 'confirmed_malicious',
  benign: 'benign',
  duplicate: 'duplicate',
  unresolved: 'unresolved',
};

export type PatternSeverity = 'low' | 'medium' | 'high' | 'critical';
export type PatternPriority = 'high' | 'normal' | 'low';
export type PatternSurface = 'profile360' | 'agent360' | 'risk360';

export interface PatternEntityRef {
  kind: string;
  id: string;
  /** `kind:id`, e.g. `user:123`, `agent:abc`, `wallet:0x…`. */
  key: string;
}

export interface PatternEvidenceItem {
  type: string;
  /** `observed` restates a recorded fact; every statistical judgement is `inferred`. */
  basis: 'observed' | 'inferred';
  /** A weight, not a probability. */
  strength: number;
  detail: Record<string, unknown>;
  source_event_refs: string[];
}

export interface CompetingExplanation {
  id: string;
  note: string;
}

export interface DiscoveredPatternSummary {
  pattern_id: string;
  kind: PatternKind;
  title: string;
  summary?: string;
  status: PatternStatus;
  priority?: PatternPriority;
  severity?: PatternSeverity;
  severity_score?: number;
  confidence: number;
  confidence_cap?: number;
  novelty?: number;
  affected_entity_count: number;
  risk_categories: string[];
  first_observed_at?: string | null;
  last_observed_at?: string | null;
  version?: number;
  times_observed?: number;
  suppressed_by_feedback?: boolean;
  claim_state?: 'inferred';
}

export interface PatternReviewEntry {
  reviewer_id?: string;
  decision: string;
  reason?: string;
  previous_status?: PatternStatus;
  at?: string;
  [extra: string]: unknown;
}

export interface PatternPromotion {
  promoted_by: string;
  promoted_at: string;
  reason: string;
  from_status: PatternStatus;
  verdict: 'valid' | 'malicious';
  evidence_fingerprint: string;
  risk_signals: Array<{
    entity: string;
    status: 'written' | 'unresolved_subject' | 'consent_withheld' | 'failed';
    subject_kind?: string;
    subject_id?: string;
    signal_ids?: string[];
    reason_code?: string;
  }>;
  risk_projection?: 'written' | 'no_resolvable_subjects' | 'disabled';
  graph_projection?: { status: string; vertex_id?: string; edges?: number };
}

export interface DiscoveredPatternDetail extends DiscoveredPatternSummary {
  signature: Record<string, unknown>;
  signature_hash: string;
  family: string;
  evidence: PatternEvidenceItem[];
  evidence_fingerprint: string;
  competing_explanations: CompetingExplanation[];
  affected_entities: PatternEntityRef[];
  review_history: PatternReviewEntry[];
  promotion: PatternPromotion | null;
  duplicate_of: string | null;
  member_pattern_ids: string[];
  similar_patterns?: DiscoveredPatternSummary[];
  members?: DiscoveredPatternSummary[];
}

export interface PatternReviewRequest {
  verdict: PatternVerdict;
  /** At least 10 characters; recorded and used to calibrate detectors. */
  reason: string;
  duplicate_of?: string;
}

export interface PatternDiscoveryRunRequest {
  window_hours?: number;
  max_events?: number;
  kinds?: PatternKind[];
  include_store?: boolean;
}

/** Shared envelope of the three 360 pattern sections. */
export interface PatternSectionBase {
  entity: string;
  surface: PatternSurface;
  advisory: true;
  claim_state: 'inferred';
  withheld: boolean;
  reason_code?: string | null;
  counts: { total: number; open: number; reviewed: number; promoted: number };
}

export interface CoImplicatedEntity {
  entity: string;
  shared_patterns: number;
}

export interface ProfilePatternSection extends PatternSectionBase {
  surface: 'profile360';
  emerging_patterns: DiscoveredPatternSummary[];
  similar_profiles: CoImplicatedEntity[];
  behavioral_cohorts: DiscoveredPatternSummary[];
  unresolved_identity_overlaps: DiscoveredPatternSummary[];
  contradictory_evidence: DiscoveredPatternSummary[];
  baseline_changes: DiscoveredPatternSummary[];
}

export interface AgentPatternSection extends PatternSectionBase {
  surface: 'agent360';
  novel_delegation_motifs: DiscoveredPatternSummary[];
  tool_call_signatures: DiscoveredPatternSummary[];
  spawning_anomalies: DiscoveredPatternSummary[];
  shared_infrastructure: DiscoveredPatternSummary[];
  shared_infrastructure_agents: CoImplicatedEntity[];
  cross_principal_behavior: DiscoveredPatternSummary[];
  agent_interactions: DiscoveredPatternSummary[];
  principals: CoImplicatedEntity[];
}

export interface RiskPatternFinding extends DiscoveredPatternSummary {
  evidence_coverage: { items: number; observed: number; inferred: number; event_refs: number };
  review_status: PatternStatus;
  risk_signals: PatternPromotion['risk_signals'];
}

export interface RiskPatternSection extends PatternSectionBase {
  surface: 'risk360';
  pattern_findings: RiskPatternFinding[];
  campaigns: DiscoveredPatternSummary[];
  emerging_clusters: DiscoveredPatternSummary[];
  graph_motifs: DiscoveredPatternSummary[];
  temporal_anomalies: DiscoveredPatternSummary[];
  risk_category_counts: Record<string, number>;
  max_novelty: number;
  max_confidence: number;
}
