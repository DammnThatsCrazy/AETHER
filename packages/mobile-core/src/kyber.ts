/**
 * Typed wire contracts for the Kyber mobile surfaces (D6, snake_case).
 *
 * These shapes mirror the backend routers the SDK calls — step-up, mobile action
 * digest, proof keys, and command receipts. The types are locked to the backend
 * contracts; keep field names and nullability in sync with the server models
 * when either side changes.
 */

/** One actionable item surfaced by the mobile actions digest. */
export interface MobileActionItem {
  kind: 'exception' | 'command';
  id: string;
  title: string;
  severity: string;
  status: string;
  action_class: number;
  available_action: string;
  capability_id: string;
  requires_step_up: boolean;
  priority_score: number;
  signal_count: number;
  last_seen_at: string | null;
}

/** Triage digest of open actions, split by tier. */
export interface MobileActionsDigest {
  tiers: {
    tier0: MobileActionItem[];
    tier1: MobileActionItem[];
    tier2: MobileActionItem[];
    tier3: MobileActionItem[];
  };
  counts: Record<'tier0' | 'tier1' | 'tier2' | 'tier3', number>;
  step_up_required: boolean;
  step_up: {
    fresh: boolean;
    grant_id: string | null;
    expires_at: string | null;
  };
  generated_at: string;
}

/** An operator session as reported by the backend (no token, no digest). */
export interface KyberSession {
  session_id: string;
  operator_id: string;
  device_id: string | null;
  status: string;
  authentication_strength: string;
  authentication_methods: string[];
  environment: string;
  presence_expires_at: string | null;
  authority_expires_at: string | null;
  idle_expires_at: string | null;
  created_at: string;
  last_seen_at: string | null;
  rotated_at: string | null;
  revoked_at: string | null;
  risk_state: string;
}

/** `GET /v1/kyber/auth/session` — the session plus its live step-up grant state. */
export type KyberSessionView = KyberSession & {
  step_up?: {
    fresh: boolean;
    grant_id: string | null;
    expires_at: string | null;
  } | null;
};

/** `POST /v1/kyber/auth/step-up/options` — the issued authenticator challenge. */
export interface StepUpOptions {
  challenge_id: string;
  challenge: string;
  device_id: string;
  capability_id: string | null;
}

/** Body of `POST /v1/kyber/auth/step-up/verify`. */
export interface StepUpVerifyInput {
  challenge_id: string;
  signature: string;
  capability_id?: string;
  reason?: string;
  ttl_minutes?: number;
}

/** Result of a successful step-up verification: an elevation grant. */
export interface StepUpGrant {
  grant_id: string;
  capability_id: string;
  expires_at: string;
  session: KyberSession | null;
}

/** Body of `POST /v1/kyber/mobile/proof-keys` (algorithm defaults to `ES256`). */
export interface ProofKeyRegisterInput {
  device_id: string;
  /** base64url-encoded DER SPKI ECDSA P-256 public key. */
  public_key: string;
  algorithm?: 'ES256';
  /** Informational label; carried in audit metadata, not persisted on the row. */
  label?: string | null;
}

/** Full proof-key record echoed by register/revoke responses. */
export interface MobileProofKey {
  proof_key_id: string;
  device_id: string;
  operator_id: string;
  algorithm: string;
  public_key: string;
  created_at: string;
  last_verified_at: string | null;
  revoked_at: string | null;
}

/** Redacted inventory projection — never echoes public-key material. */
export interface MobileProofKeyListEntry {
  proof_key_id: string;
  device_id: string;
  operator_id: string;
  algorithm: string;
  created_at: string;
  last_verified_at: string | null;
}

/** A governed command receipt (`/v1/kyber/ops/commands`). */
export interface CommandReceipt {
  command_id: string;
  command_type: string;
  status: string;
  requested_by: string;
  session_id: string | null;
  device_id: string | null;
  environment: string;
  tenant_ids: string[];
  resource_ids: string[];
  reason: string;
  action_class: number;
  dry_run: boolean;
  idempotency_key: string;
  blast_radius: Record<string, unknown> | null;
  rollback_plan: string | null;
  verification_plan: string[];
  required_approvals: number;
  approvals: Record<string, unknown>[];
  approval_mode: string;
  step_up_verified: boolean;
  policy_decision_id: string | null;
  incident_id: string | null;
  scheduled_for: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

/** `GET /v1/kyber/ops/commands` — a filtered page of command receipts. */
export interface CommandReceiptList {
  commands: CommandReceipt[];
  count: number;
  status_filter: string;
}

/**
 * `GET /v1/kyber/ops/commands/{id}` — one command with execution + verification.
 *
 * `verification: null` is a REAL answer meaning "not verified" — it must be
 * rendered as such, never treated as a missing/omitted field. That is the
 * difference between a question nobody asked and one that is still open.
 */
export interface CommandReceiptDetail {
  command: CommandReceipt;
  spec: Record<string, unknown> | null;
  execution: Record<string, unknown> | null;
  executions: Record<string, unknown>[];
  verification: Record<string, unknown> | null;
  verified: boolean;
  generated_at: string;
}
