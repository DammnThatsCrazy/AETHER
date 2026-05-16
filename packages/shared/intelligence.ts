// =============================================================================
// Aether SDK — Intelligence & Risk Profile Contracts
// Covers trust, risk, anomaly scoring, ML feature vectors, and predictions.
// Returned by GET /v1/profile/{id}/intelligence
// and GET /v1/profile/{id}/predictions
// and GET /v1/intelligence/wallet/{addr}/risk
// =============================================================================

/** A single ML model feature with optional importance weighting. */
export interface MLFeature {
  readonly feature_name: string;
  readonly value: number;
  /** Relative importance of this feature in the scoring model — 0–1 */
  readonly importance?: number;
}

/** What the model predicts the entity will do next. */
export interface PredictedNextEvent {
  readonly event_type: string;
  readonly probability: number;        // 0–1
  readonly expected_at?: string;       // ISO8601 estimate
  readonly context?: Record<string, unknown>;
}

/**
 * Full intelligence profile for any entity.
 * Returned by GET /v1/profile/{id}/intelligence.
 * All scores are 0–1. risk_level is a human-readable tier derived from risk_score.
 */
export interface IntelligenceProfile {
  readonly entity_id: string;

  // ── Core scores ──
  readonly trust_score: number;         // 0–1 — higher = more trustworthy
  readonly risk_score: number;          // 0–1 — higher = more risky
  readonly anomaly_score: number;       // 0–1 — higher = more anomalous

  // ── Risk tiering ──
  readonly risk_level?: 'low' | 'medium' | 'high' | 'critical';

  // ── Score drivers (human-readable strings) ──
  readonly risk_drivers?: string[];
  readonly trust_drivers?: string[];
  readonly anomaly_flags?: string[];
  readonly risk_flags?: string[];

  // ── Predictions ──
  readonly predicted_next?: PredictedNextEvent;

  // ── ML feature vector ──
  readonly ml_features?: MLFeature[];
  readonly models_applied?: string[];

  readonly computed_at?: string;
}

/**
 * Wallet-specific risk assessment.
 * Returned by GET /v1/intelligence/wallet/{address}/risk.
 */
export interface WalletRiskProfile {
  readonly wallet_address: string;
  readonly risk_score: number;          // 0–1
  readonly risk_level: 'low' | 'medium' | 'high' | 'critical';
  readonly risk_flags: string[];
  readonly is_sanctioned: boolean;
  readonly mixer_exposure?: boolean;
  readonly exploit_involvement?: boolean;
  readonly counterparty_risk?: number;  // 0–1 — derived from transaction graph
  readonly computed_at: string;
}
