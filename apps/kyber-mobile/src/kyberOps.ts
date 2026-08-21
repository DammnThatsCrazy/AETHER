/**
 * Kyber Mobile operator-plane client (M4a).
 *
 * App-local typed GET client for the EXISTING Kyber/agent operator surfaces,
 * mirroring the Aether Mobile projection pattern (`apps/aether-mobile/src/
 * projections.ts`). Reuses `@aether/mobile-core`'s `HttpClient`, which unwraps
 * the backend `{ data: ... }` envelope, so every typed method below resolves to
 * the inner data object exactly as the route returns it.
 *
 * Wire contracts are typed from the backend code, not guessed:
 *   - `services/agent/routes.py`         (health, controllers/status, review-batches)
 *   - `services/agent/worker_routes.py`  (runs, runs/stuck)
 *   - `services/agent/ops_alerts.py`     (ops/alerts)
 *   - `services/agent/briefings.py`      (briefings)
 *   - `services/kyber/ops/routes.py` + `contracts.py` (exceptions, incidents, resume-cards)
 *   - `services/kyber/devices/routes.py` + `access/contracts.py` (devices)
 *   - `services/kyber/sessions/routes.py` + `access/contracts.py` (sessions)
 *
 * READ-ONLY by construction (M2 "no offline mutation" invariant): every method
 * issues GETs only. Field names are snake_case (decision-log D6). Screens render
 * severity / kind / title / status / ids / timestamps / counts only — never raw
 * payloads, secrets, or PII beyond what the ops disclosure levels already expose.
 */
import {
  HttpClient,
  normalizeBaseUrl,
  type FetchLike,
  type HttpClientDeps,
  type MobileConfig,
} from '@aether/mobile-core';

import { auth } from './client';

// `apps/kyber-mobile/src/client.ts` exports `auth`, `crypto` and `client` but
// keeps `config` / `deviceFetch` module-local, so this module builds the same
// runtime bindings itself (identical values to client.ts) rather than
// duplicating or rewriting the client.
const config: MobileConfig = {
  apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? 'https://operator.aether.example',
  appKind: 'kyber',
  environment: process.env.EXPO_PUBLIC_ENVIRONMENT ?? 'production',
};

// The device fetch (a WHATWG Response) structurally satisfies FetchResponseLike.
const deviceFetch: FetchLike = (url, init) => fetch(url, init as RequestInit);

// ── Vocabularies (from the backend contracts) ────────────────────────────────

/** Kyber severity vocabulary (`kyber/ops/contracts.py`). */
export const kyberSeverities = ['critical', 'high', 'medium', 'low', 'info'] as const;
export type KyberSeverity = (typeof kyberSeverities)[number];

/** What the operator should do with an exception, not how bad it looks. */
export const kyberExceptionBuckets = [
  'critical_now',
  'needs_action',
  'watch',
  'informational',
] as const;
export type KyberExceptionBucket = (typeof kyberExceptionBuckets)[number];

export const kyberExceptionStatuses = [
  'open',
  'acknowledged',
  'in_progress',
  'resolved',
  'suppressed',
] as const;
export type KyberExceptionStatus = (typeof kyberExceptionStatuses)[number];

export const kyberIncidentStatuses = [
  'detected',
  'investigating',
  'identified',
  'mitigating',
  'monitoring',
  'resolved',
  'closed',
] as const;
export type KyberIncidentStatus = (typeof kyberIncidentStatuses)[number];

/** Ops-alert severity vocabulary (`services/agent/ops_alerts.py`). */
export const agentAlertSeverities = ['P0', 'P1', 'P2', 'P3', 'P4'] as const;
export type AgentAlertSeverity = (typeof agentAlertSeverities)[number];

/** Worker-run statuses (`runtime_repository.py` RUN_STATUSES). */
export const agentRunStatuses = [
  'queued',
  'running',
  'completed',
  'failed',
  'retry',
  'stale',
  'dispatch_failed',
] as const;
export type AgentRunStatus = (typeof agentRunStatuses)[number];

/** Review-batch statuses (`runtime_repository.py` REVIEW_STATUSES). */
export const reviewBatchStatuses = [
  'pending',
  'approved',
  'rejected',
  'committed',
  'quarantined',
  'rolled_back',
] as const;
export type ReviewBatchStatus = (typeof reviewBatchStatuses)[number];

/** Device trust states (`kyber/access/contracts.py`). */
export const deviceApprovalStates = ['pending', 'approved', 'suspended', 'revoked', 'expired'] as const;
export type DeviceApprovalState = (typeof deviceApprovalStates)[number];

export const deviceRiskStates = ['ok', 'suspect', 'blocked'] as const;
export type DeviceRiskState = (typeof deviceRiskStates)[number];

/** Workforce session states (`kyber/access/contracts.py`). */
export const sessionStatuses = [
  'restricted',
  'active',
  'risk_limited',
  'revoked',
  'expired',
  'locked',
] as const;
export type SessionStatus = (typeof sessionStatuses)[number];

export const authenticationStrengths = [
  'none',
  'identity_only',
  'device_bound',
  'stepped_up',
] as const;
export type AuthenticationStrength = (typeof authenticationStrengths)[number];

// ── Agent runtime: health / controllers / runs / reviews / alerts ────────────

/** Durable kill-switch state (`runtime_repository.get_kill_switch`). */
export interface KillSwitchState {
  tenant_id: string;
  enabled: boolean;
  reason: string;
  updated_at: string | null;
  updated_by: string | null;
}

/** One controller's aggregate health row (`runtime_repository.controller_status`). */
export interface AgentControllerStatus {
  tenant_id: string;
  controller: string;
  worker_id: string | null;
  status: 'healthy' | 'degraded' | 'stale' | 'unknown' | string;
  queue_depth: number;
  worker_count: number;
  workers: Array<{
    worker_id: string | null;
    status: string;
    queue_depth: number;
    updated_at: string;
    stale: boolean;
  }>;
  metadata: Record<string, unknown>;
  updated_at: string;
}

/** Point-in-time worker run counts folded into `/v1/agent/health`. */
export interface AgentRunCounts {
  queued: number;
  running: number;
  completed: number;
  failed: number;
  retry: number;
  stale: number;
  dispatch_failed: number;
  stuck: number;
}

/** GET /v1/agent/health — aggregate controller health, queue depth, run counts. */
export interface AgentHealth {
  kill_switch: KillSwitchState;
  controllers: AgentControllerStatus[];
  queues: Array<{ name: string; depth: number }>;
  objectives: { active: number; blocked: number; failed: number; total: number };
  review: { awaiting_review: number };
  /** Additive one-person-ops key. */
  queue_depth: number;
  runs: AgentRunCounts;
  workers: { count: number; stale: number; stale_after_seconds: number };
}

/** GET /v1/agent/controllers/status. */
export interface AgentControllersStatus {
  controllers: AgentControllerStatus[];
  total: number;
}

/** One compressed operator alert (`services/agent/ops_alerts.py`). */
export interface AgentOpsAlert {
  alert_id: string;
  tenant_id: string;
  severity: AgentAlertSeverity | string;
  kind: string;
  /** Backend-sanitized message (never a raw payload). */
  message: string;
  dedupe_key: string;
  status: 'open' | 'resolved' | string;
  count: number;
  request_id: string;
  created_at: string;
  last_seen_at: string;
  updated_at: string;
  /** Best-effort notification routing outcome; may be absent. */
  notification?: {
    routed: boolean;
    reason?: string;
    channels?: Array<{ channel_type: string; success: boolean }>;
  } | null;
  compressed?: boolean;
}

/** GET /v1/agent/ops/alerts. */
export interface AgentOpsAlerts {
  alerts: AgentOpsAlert[];
  total: number;
}

/** One durable worker run row (`runtime_repository` record_dispatch/start/…). */
export interface AgentRun {
  run_id: string;
  tenant_id: string;
  objective_id: string;
  controller: string;
  queue: string;
  status: AgentRunStatus | string;
  attempt: number;
  idempotency_key?: string;
  created_at: string;
  updated_at: string;
  heartbeat_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
  failed_at?: string | null;
  stale_at?: string | null;
  worker_id?: string;
  /** Sanitized failure text (null until the run fails). */
  error: string | null;
  output?: Record<string, unknown> | null;
}

/** GET /v1/agent/runs and GET /v1/agent/runs/stuck (worker_routes.py). */
export interface AgentRuns {
  runs: AgentRun[];
  total: number;
}

/** One review batch (`runtime_repository.create_review_batch`). */
export interface AgentReviewBatch {
  batch_id: string;
  tenant_id: string;
  objective_id: string;
  status: ReviewBatchStatus | string;
  mutation_ids: string[];
  created_at: string;
  updated_at: string;
  reviewed_by: string | null;
  review_notes: string | null;
}

/** GET /v1/agent/review-batches. */
export interface AgentReviewBatches {
  batches: AgentReviewBatch[];
  total: number;
}

// ── Agent briefings ──────────────────────────────────────────────────────────

/** Redacted stuck-run row embedded in a briefing's sections. */
export interface BriefingStuckRun {
  run_id?: string;
  objective_id?: string;
  controller?: string;
  status?: string;
  heartbeat_at?: string;
}

/** Redacted alert row embedded in a briefing's sections. */
export interface BriefingAlert {
  alert_id?: string;
  severity?: string;
  kind?: string;
  count?: number;
  last_seen_at?: string;
}

/** The `sections` map a briefing carries (services/agent/briefings.py). */
export interface BriefingSections {
  objectives: Record<string, number>;
  runs: Record<string, number>;
  stuck_runs: BriefingStuckRun[];
  review: { pending_batches: number };
  staged_mutations: Record<string, number>;
  kill_switch: { enabled: boolean; reason: string };
  alerts: BriefingAlert[];
  attention: string[];
}

/** One durable operator briefing (services/agent/briefings.py). */
export interface AgentBriefing {
  briefing_id: string;
  tenant_id: string;
  type: 'run_complete' | 'alert' | 'handoff' | 'daily' | string;
  status: string;
  generated_by: string;
  request_id: string;
  /** Operator-facing summary string — the redacted digest. */
  summary: string;
  sections: BriefingSections;
  created_at: string;
  updated_at: string;
}

/** GET /v1/agent/briefings. */
export interface AgentBriefings {
  briefings: AgentBriefing[];
  total: number;
}

// ── Kyber ops plane: exceptions / incidents / resume cards ───────────────────

/** One thing that needs a decision (kyber/ops/contracts.OperationalException). */
export interface KyberException {
  exception_id: string;
  title: string;
  severity: KyberSeverity | string;
  bucket: KyberExceptionBucket | string;
  status: KyberExceptionStatus | string;
  confidence: number;
  affected_tenants: string[];
  affected_features: string[];
  affected_services: string[];
  customer_visible: boolean;
  security_exposure: boolean;
  financial_exposure: boolean;
  data_integrity_exposure: boolean;
  reversible: boolean;
  time_to_breach_seconds: number | null;
  sla_impact: boolean;
  priority_score: number;
  priority_inputs: Record<string, unknown>;
  probable_cause: string | null;
  recommended_action: string | null;
  incident_id: string | null;
  dedupe_key: string | null;
  signal_count: number;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

/** GET /v1/kyber/ops/exceptions — the operator queue (`exception_service.queue`). */
export interface KyberExceptionQueue {
  order: string[];
  buckets: Record<string, KyberException[]>;
  items: KyberException[];
  counts: Record<string, number>;
  total: number;
  status_filter: string | null;
  generated_at: string;
}

/** A correlated failure with an owner-visible next action (contracts.Incident). */
export interface KyberIncident {
  incident_id: string;
  title: string;
  status: KyberIncidentStatus | string;
  severity: KyberSeverity | string;
  priority_score: number;
  root_cause: string | null;
  affected_tenants: string[];
  affected_features: string[];
  affected_services: string[];
  release_id: string | null;
  customer_visible: boolean;
  revenue_exposure: boolean;
  security_exposure: boolean;
  data_integrity_exposure: boolean;
  last_action: string | null;
  next_action: string | null;
  blocked_by: string | null;
  pending_verification: string[];
  operator_notes: Array<Record<string, unknown>>;
  signal_count: number;
  opened_at: string;
  resolved_at: string | null;
  closed_at: string | null;
  updated_at: string;
  metadata: Record<string, unknown>;
}

/** GET /v1/kyber/ops/incidents. */
export interface KyberIncidents {
  incidents: KyberIncident[];
  count: number;
  status_filter: string | null;
  generated_at: string;
}

/** What a returning operator needs to resume an incident (`correlation.resume_card`). */
export interface KyberResumeCard {
  incident_id: string;
  title: string;
  status: KyberIncidentStatus | string;
  severity: KyberSeverity | string;
  priority_score: number;
  last_action: string | null;
  next_action: string | null;
  blocked_by: string | null;
  pending_verification: string[];
  root_cause: string | null;
  signal_count: number;
  affected_services: string[];
  affected_tenants: string[];
  opened_at: string;
  updated_at: string;
  missing_inputs: string[];
}

/** GET /v1/kyber/ops/incidents/resume-cards. */
export interface KyberResumeCards {
  cards: KyberResumeCard[];
  count: number;
  generated_at: string;
}

// ── Kyber account plane: devices / sessions ──────────────────────────────────

/** Public projection of a trusted device (`devices/routes._device_view`). */
export interface KyberDevice {
  device_id: string;
  operator_id: string;
  display_name: string;
  platform_family: string | null;
  browser_family: string | null;
  approval_state: DeviceApprovalState | string;
  risk_state: DeviceRiskState | string;
  requested_at: string | null;
  approved_at: string | null;
  approved_by: string | null;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  revocation_reason: string | null;
  risk_signals: unknown[];
}

/** GET /v1/kyber/devices. */
export interface KyberDevices {
  operator_id: string;
  devices: KyberDevice[];
}

/** Body-safe session representation (`sessions/routes._session_body`). */
export interface KyberSession {
  session_id: string;
  operator_id: string;
  device_id: string | null;
  status: SessionStatus | string;
  authentication_strength: AuthenticationStrength | string;
  authentication_methods: string[];
  environment: string;
  presence_expires_at: string | null;
  authority_expires_at: string | null;
  idle_expires_at: string | null;
  created_at: string;
  last_seen_at: string | null;
  rotated_at: string | null;
  revoked_at: string | null;
  risk_state: DeviceRiskState | string;
}

// ── Typed read-only client ───────────────────────────────────────────────────

const deps: HttpClientDeps = { fetch: deviceFetch, auth };

/** Typed GET client for the Kyber operator-plane surfaces. */
export class KyberOpsClient {
  private readonly http: HttpClient;

  constructor() {
    this.http = new HttpClient(normalizeBaseUrl(config.apiBaseUrl), deps);
  }

  // ── Pulse tab ──────────────────────────────────────────────────────────────

  /** GET /v1/agent/health — controller health, queue depths, run counts. */
  getHealth(): Promise<AgentHealth> {
    return this.http.request<AgentHealth>('GET', '/v1/agent/health');
  }

  /** GET /v1/agent/ops/alerts — compressed operator alerts. */
  getOpsAlerts(): Promise<AgentOpsAlerts> {
    return this.http.request<AgentOpsAlerts>('GET', '/v1/agent/ops/alerts');
  }

  /** GET /v1/agent/controllers/status — per-controller health rows. */
  getControllersStatus(): Promise<AgentControllersStatus> {
    return this.http.request<AgentControllersStatus>('GET', '/v1/agent/controllers/status');
  }

  // ── Exceptions tab ─────────────────────────────────────────────────────────

  /** GET /v1/kyber/ops/exceptions — the prioritised operator queue (open). */
  getExceptions(): Promise<KyberExceptionQueue> {
    return this.http.request<KyberExceptionQueue>('GET', '/v1/kyber/ops/exceptions?status=open&limit=100');
  }

  // ── Incidents tab ──────────────────────────────────────────────────────────

  /** GET /v1/kyber/ops/incidents — open incidents, worst-priority first. */
  getIncidents(): Promise<KyberIncidents> {
    return this.http.request<KyberIncidents>('GET', '/v1/kyber/ops/incidents?status=open&limit=100');
  }

  /** GET /v1/kyber/ops/incidents/resume-cards — what to pick back up. */
  getResumeCards(): Promise<KyberResumeCards> {
    return this.http.request<KyberResumeCards>('GET', '/v1/kyber/ops/incidents/resume-cards?limit=50');
  }

  // ── Runs tab ───────────────────────────────────────────────────────────────

  /** GET /v1/agent/runs — recent durable worker runs. */
  getRuns(): Promise<AgentRuns> {
    return this.http.request<AgentRuns>('GET', '/v1/agent/runs?limit=100');
  }

  /** GET /v1/agent/runs/stuck — runs past their stale threshold. */
  getStuckRuns(): Promise<AgentRuns> {
    return this.http.request<AgentRuns>('GET', '/v1/agent/runs/stuck');
  }

  // ── Reviews tab ────────────────────────────────────────────────────────────

  /** GET /v1/agent/review-batches — staged-mutation review queue. */
  getReviewBatches(): Promise<AgentReviewBatches> {
    return this.http.request<AgentReviewBatches>('GET', '/v1/agent/review-batches');
  }

  // ── Briefings tab ──────────────────────────────────────────────────────────

  /** GET /v1/agent/briefings — recent durable operator briefings. */
  getBriefings(): Promise<AgentBriefings> {
    return this.http.request<AgentBriefings>('GET', '/v1/agent/briefings?limit=50');
  }

  // ── Account tab (read-only devices + sessions) ─────────────────────────────

  /** GET /v1/kyber/devices — the caller's trusted devices. */
  getDevices(): Promise<KyberDevices> {
    return this.http.request<KyberDevices>('GET', '/v1/kyber/devices');
  }

  /** GET /v1/kyber/auth/sessions — the caller's sessions (inner data is a list). */
  getSessions(): Promise<KyberSession[]> {
    return this.http.request<KyberSession[]>('GET', '/v1/kyber/auth/sessions');
  }
}

/** Shared instance bound to the app's config + auth. */
export const kyberOps = new KyberOpsClient();
