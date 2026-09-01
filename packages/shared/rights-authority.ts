// DO NOT EDIT — generated from packages/shared/contracts/rights-authority-registry.json
// Run: python scripts/generate_contracts.py

export const RIGHTS_AUTHORITY_CONTRACT_VERSION = "1.0.0";

export type RightsClass =
  | "tenant_contributed_data"
  | "tenant_confidential_intelligence"
  | "aether_computational_artifact"
  | "olympus_sourced_data"
  | "olympus_generalized_intelligence"
  | "platform_operational_data"
  | "retained_compliance_record";

export type RightsAction =
  | "ingest"
  | "store"
  | "read"
  | "graph_mutate"
  | "derive"
  | "train"
  | "evaluate"
  | "aggregate"
  | "disclose"
  | "export"
  | "retain"
  | "delete"
  | "operate_kyber";

export type RightsDecisionOutcome =
  | "allow"
  | "deny"
  | "allow_with_obligations"
  | "pending_review"
  | "unavailable";

export type RightsProfile =
  | "legacy_restricted"
  | "secure_tenant"
  | "collaborative_learning"
  | "strategic_data_exchange";

export type RightsActivationState =
  | "rights_pending"
  | "rights_review"
  | "rights_active"
  | "rights_restricted"
  | "rights_revoked";

export type RightsTransform =
  | "feature_extraction"
  | "embedding"
  | "model_evaluation"
  | "model_training"
  | "aggregation"
  | "deidentification"
  | "promote_to_olympus_generalized_graph"
  | "export"
  | "recomputation"
  | "deletion";

export const RIGHTS_CLASSES = ["tenant_contributed_data", "tenant_confidential_intelligence", "aether_computational_artifact", "olympus_sourced_data", "olympus_generalized_intelligence", "platform_operational_data", "retained_compliance_record"] as const;
export const RIGHTS_ACTIONS = ["ingest", "store", "read", "graph_mutate", "derive", "train", "evaluate", "aggregate", "disclose", "export", "retain", "delete", "operate_kyber"] as const;
export const RIGHTS_DECISION_OUTCOMES = ["allow", "deny", "allow_with_obligations", "pending_review", "unavailable"] as const;
export const RIGHTS_PROFILES = ["legacy_restricted", "secure_tenant", "collaborative_learning", "strategic_data_exchange"] as const;
export const RIGHTS_TRANSFORMS = ["feature_extraction", "embedding", "model_evaluation", "model_training", "aggregation", "deidentification", "promote_to_olympus_generalized_graph", "export", "recomputation", "deletion"] as const;
export const RIGHTS_ACTIVATION_STATES = ["rights_pending", "rights_review", "rights_active", "rights_restricted", "rights_revoked"] as const;

export interface RightsReference {
  policySetId?: string;
  envelopeId?: string;
  decisionId?: string;
  lineageSetHash?: string;
  retentionClass?: string;
}
