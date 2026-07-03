// Canonical semantic-sentiment intelligence contracts shared by Aether, Kyber and backend API clients.

export const SEMANTIC_SENTIMENT_SCHEMA_VERSION = 'semantic-sentiment.v1' as const;
export const SEMANTIC_SENTIMENT_TAXONOMY_VERSION = 'semantic-sentiment-taxonomy.v1' as const;

export type SemanticSubjectType =
  | 'person' | 'organization' | 'account' | 'profile' | 'agent' | 'wallet'
  | 'campaign' | 'creative' | 'product' | 'service' | 'offer' | 'feature'
  | 'brand' | 'protocol' | 'token' | 'contract' | 'governance_proposal'
  | 'transaction' | 'topic' | 'narrative' | 'claim' | 'location' | 'channel'
  | 'platform' | 'workflow' | 'journey' | 'episode' | 'other';

export type SemanticStance =
  | 'strongly_supportive' | 'supportive' | 'weakly_supportive' | 'neutral'
  | 'uncertain' | 'mixed' | 'weakly_opposed' | 'opposed'
  | 'strongly_opposed' | 'not_applicable' | 'abstained';

export type SemanticIntent =
  | 'discover' | 'investigate' | 'compare' | 'evaluate' | 'purchase'
  | 'subscribe' | 'renew' | 'cancel' | 'churn' | 'return' | 'refer'
  | 'recommend' | 'share' | 'complain' | 'request_help' | 'escalate'
  | 'approve' | 'reject' | 'delegate' | 'correct' | 'negotiate' | 'vote'
  | 'transact' | 'bridge' | 'stake' | 'swap' | 'transfer' | 'govern'
  | 'claim_reward' | 'avoid' | 'monitor' | 'learn' | 'unknown';

export type SemanticSpeechAct =
  | 'statement' | 'question' | 'command' | 'request' | 'recommendation'
  | 'complaint' | 'praise' | 'criticism' | 'approval' | 'rejection'
  | 'correction' | 'warning' | 'referral' | 'comparison' | 'negotiation'
  | 'agreement' | 'disagreement' | 'escalation' | 'confirmation'
  | 'explanation' | 'delegation' | 'report' | 'unknown';

export type SemanticEmotion =
  | 'joy' | 'trust' | 'anticipation' | 'surprise' | 'sadness' | 'fear'
  | 'anger' | 'disgust' | 'neutral' | 'mixed' | 'unknown';

export type SemanticPropagationRole =
  | 'direct_transmission' | 'exposure_channel' | 'behavioral_outcome'
  | 'facilitative_context' | 'structural_context' | 'excluded';

export type SemanticCausalConfidence =
  | 'observed_sequence' | 'correlated_association' | 'probable_propagation'
  | 'high_confidence_propagation' | 'experimentally_supported';

export type SemanticObservationStatus =
  | 'pending' | 'classified' | 'partial' | 'abstained' | 'failed'
  | 'superseded' | 'deleted' | 'consent_restricted' | 'quarantined';

export interface SemanticEvidenceRef {
  readonly evidence_id: string;
  readonly source_type: string;
  readonly source_ref: string;
  readonly observed_at: string;
  readonly confidence: number;
}

export interface SemanticSubjectRef {
  readonly ref: string;
  readonly type: SemanticSubjectType;
  readonly label?: string | null;
}

export interface SemanticObservationContract {
  readonly observation_id: string;
  readonly tenant_id: string;
  readonly source_event_id: string;
  readonly source_type: string;
  readonly actor_ref: string;
  readonly actor_type: SemanticSubjectType;
  readonly primary_subject_ref: string;
  readonly subject_refs: readonly SemanticSubjectRef[];
  readonly campaign_id?: string | null;
  readonly language: string;
  readonly topics: readonly string[];
  readonly claims: readonly string[];
  readonly narrative_frames: readonly string[];
  readonly stance: SemanticStance;
  readonly intent: SemanticIntent;
  readonly speech_act: SemanticSpeechAct;
  readonly evidence_refs: readonly SemanticEvidenceRef[];
  readonly classification_confidence: number;
  readonly model_id: string;
  readonly model_version: string;
  readonly taxonomy_version: typeof SEMANTIC_SENTIMENT_TAXONOMY_VERSION;
  readonly schema_version: typeof SEMANTIC_SENTIMENT_SCHEMA_VERSION;
  readonly consent_snapshot_id?: string | null;
  readonly purposes: readonly string[];
  readonly privacy_class: string;
  readonly retention_class: string;
  readonly stable_hash: string;
  readonly idempotency_key: string;
  readonly status: SemanticObservationStatus;
  readonly abstention_reason?: string | null;
}

export interface SentimentObservationContract {
  readonly sentiment_observation_id: string;
  readonly semantic_observation_id: string;
  readonly tenant_id: string;
  readonly actor_ref: string;
  readonly target_subject_ref: string;
  readonly source_event_id: string;
  readonly valence: number;
  readonly arousal: number;
  readonly dominance?: number | null;
  readonly emotion_distribution: Partial<Record<SemanticEmotion, number>>;
  readonly intensity: number;
  readonly stance_label: SemanticStance;
  readonly uncertainty: number;
  readonly sarcasm_probability: number;
  readonly contradiction_probability: number;
  readonly explicit_or_inferred: 'explicit' | 'inferred' | 'abstained';
  readonly evidence_type: string;
  readonly model_id: string;
  readonly model_version: string;
  readonly confidence: number;
}

export interface SemanticEntityStateContract {
  readonly state_id: string;
  readonly tenant_id: string;
  readonly entity_ref: string;
  readonly entity_type: SemanticSubjectType;
  readonly subject_ref: string;
  readonly window_start: string;
  readonly window_end: string;
  readonly active_topics: readonly string[];
  readonly dominant_narratives: readonly string[];
  readonly stance_distribution: Partial<Record<SemanticStance, number>>;
  readonly intent_distribution: Partial<Record<SemanticIntent, number>>;
  readonly semantic_summary: string;
  readonly observation_count: number;
  readonly unique_source_count: number;
  readonly confidence: number;
  readonly freshness: string;
  readonly evidence_refs: readonly SemanticEvidenceRef[];
}

export interface SemanticCascadeContract {
  readonly cascade_id: string;
  readonly tenant_id: string;
  readonly subject_ref: string;
  readonly topic_ref?: string | null;
  readonly narrative_ref?: string | null;
  readonly stance: SemanticStance;
  readonly seed_observations: readonly string[];
  readonly first_observed_at: string;
  readonly last_observed_at: string;
  readonly adopting_entities: readonly string[];
  readonly rejecting_entities: readonly string[];
  readonly depth: number;
  readonly breadth: number;
  readonly velocity: number;
  readonly reproduction_rate: number;
  readonly causal_confidence: SemanticCausalConfidence;
  readonly confidence: number;
  readonly evidence_refs: readonly SemanticEvidenceRef[];
}
