/**
 * KYBER operator adapter — the operations plane (`/v1/kyber/ops`).
 *
 * Four surfaces behind one router: the prioritised exception queue an operator reads
 * instead of watching dashboards, the incidents those exceptions roll up into, the
 * governed command plane, and the containment switches that stop the platform.
 *
 * ── The contracts that shape every type in this file ─────────────────────────────
 *
 * **A count the server could not compute is `null`, never `0`.** Every count below is
 * `.nullable()` and never `.default(0)`. There is no `?? 0` here or at any call site:
 * "we could not read the reach" and "the reach is nothing" are different answers, and
 * only one of them lets an operator press execute.
 *
 * **`executed_unverified` is a real state, not a failure and not a success.** The
 * backend writes it before verification runs and leaves it there when a postcondition
 * fails or cannot be determined. `verification: null` likewise means "the question is
 * still open", which is why the schema keeps the key and marks it nullable rather than
 * treating an absent verification as a pass.
 *
 * **A blast radius always exists as a record.** `compute_blast_radius` never returns
 * `None`: it returns `{available: false, reason, missing_inputs}` when it could not
 * assess, so a degraded assessor produces a value that refuses rather than a falsy one
 * that gets skipped. `reachIsKnown` below is the single place that decides whether a
 * numeric reach may be rendered at all.
 *
 * **A correlation basis is either deterministic or a guess.** The backend stores the
 * basis and its confidence but does NOT ship a deterministic/heuristic flag, so
 * `basisKind` classifies here against the backend's own `CORRELATION_BASES` table
 * (`services/kyber/ops/correlation.py`). Attributing a signal on time proximity is a
 * guess and has to look like one.
 */

import { useQuery } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@kyber/lib/api';

const BASE = '/v1/kyber/ops';
const KEY = 'kyber-ops';
const STALE = 15_000;

// ── Envelope ─────────────────────────────────────────────────────────────────

const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema }).passthrough();

const buildQS = (params: Record<string, string | number | undefined>): string => {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') qs.set(key, String(value));
  }
  const rendered = qs.toString();
  return rendered ? `?${rendered}` : '';
};

/**
 * A count the server may have been unable to compute. `.nullable()` is load-bearing:
 * `.default(0)` would turn "unknown" into a confident zero before it reached a
 * component, and a confident zero is what makes an operator press execute.
 */
const count = z.number().nullable();

const jsonRecord = z.record(z.unknown());

// ── Exceptions ───────────────────────────────────────────────────────────────

const priorityTermSchema = z
  .object({
    value: z.unknown(),
    normalized: z.number().nullish(),
    weight: z.number().nullish(),
    contribution: z.number().nullish(),
  })
  .passthrough();

export type PriorityTerm = z.infer<typeof priorityTermSchema>;

/**
 * The arithmetic that produced `priority_score`, stored beside it by
 * `severity.score_exception` precisely so a ranking can be interrogated after the
 * fact. A ranking an operator cannot interrogate is one they stop trusting.
 */
const priorityInputsSchema = z
  .object({
    terms: z.record(priorityTermSchema).nullish(),
    weights: z.record(z.number()).nullish(),
    raw_subtotal: z.number().nullish(),
    max_raw_score: z.number().nullish(),
    confidence: z.number().nullish(),
    confidence_factor: z.number().nullish(),
    score: z.number().nullish(),
    dominant_terms: z.array(z.string()).nullish(),
    scale: z.string().nullish(),
    scored_at: z.string().nullish(),
  })
  .passthrough();

export type PriorityInputs = z.infer<typeof priorityInputsSchema>;

const exceptionSchema = z
  .object({
    exception_id: z.string(),
    title: z.string(),
    severity: z.string(),
    bucket: z.string(),
    status: z.string(),
    confidence: z.number().nullish(),
    affected_tenants: z.array(z.string()).nullish(),
    affected_features: z.array(z.string()).nullish(),
    affected_services: z.array(z.string()).nullish(),
    customer_visible: z.boolean().nullish(),
    security_exposure: z.boolean().nullish(),
    financial_exposure: z.boolean().nullish(),
    data_integrity_exposure: z.boolean().nullish(),
    reversible: z.boolean().nullish(),
    time_to_breach_seconds: count,
    sla_impact: z.boolean().nullish(),
    priority_score: count,
    priority_inputs: priorityInputsSchema.nullish(),
    probable_cause: z.string().nullish(),
    recommended_action: z.string().nullish(),
    incident_id: z.string().nullish(),
    signal_count: count,
    first_seen_at: z.string().nullish(),
    last_seen_at: z.string().nullish(),
    metadata: jsonRecord.nullish(),
  })
  .passthrough();

export type OperationalException = z.infer<typeof exceptionSchema>;

const exceptionQueueSchema = z
  .object({
    order: z.array(z.string()),
    buckets: z.record(z.array(exceptionSchema)),
    items: z.array(exceptionSchema),
    counts: z.record(count),
    total: count,
    status_filter: z.string().nullish(),
    generated_at: z.string().nullish(),
  })
  .passthrough();

export type ExceptionQueue = z.infer<typeof exceptionQueueSchema>;

const exceptionMutationSchema = z.object({ exception: exceptionSchema }).passthrough();

/** Bucket order is part of the contract, not a display preference. */
export const BUCKET_ORDER = [
  'critical_now',
  'needs_action',
  'watch',
  'informational',
] as const;

export const BUCKET_LABELS: Record<string, string> = {
  critical_now: 'Critical now',
  needs_action: 'Needs action',
  watch: 'Watch',
  informational: 'Informational',
};

// ── Incidents ────────────────────────────────────────────────────────────────

const signalSchema = z
  .object({
    signal_id: z.string(),
    incident_id: z.string().nullish(),
    tenant_id: z.string().nullish(),
    source: z.string(),
    signal_type: z.string(),
    error_signature: z.string().nullish(),
    service: z.string().nullish(),
    feature: z.string().nullish(),
    release_id: z.string().nullish(),
    // `null` means the signal opened its own incident on no correlation at all.
    correlation_basis: z.string().nullable(),
    correlation_confidence: z.number().nullable(),
    observed_at: z.string().nullish(),
    payload: jsonRecord.nullish(),
  })
  .passthrough();

export type IncidentSignal = z.infer<typeof signalSchema>;

const incidentSchema = z
  .object({
    incident_id: z.string(),
    title: z.string(),
    status: z.string(),
    severity: z.string(),
    priority_score: count,
    root_cause: z.string().nullish(),
    affected_tenants: z.array(z.string()).nullish(),
    affected_features: z.array(z.string()).nullish(),
    affected_services: z.array(z.string()).nullish(),
    release_id: z.string().nullish(),
    customer_visible: z.boolean().nullish(),
    revenue_exposure: z.boolean().nullish(),
    security_exposure: z.boolean().nullish(),
    data_integrity_exposure: z.boolean().nullish(),
    last_action: z.string().nullish(),
    next_action: z.string().nullish(),
    blocked_by: z.string().nullish(),
    pending_verification: z.array(z.string()).nullish(),
    signal_count: count,
    opened_at: z.string().nullish(),
    resolved_at: z.string().nullish(),
    updated_at: z.string().nullish(),
    metadata: jsonRecord.nullish(),
  })
  .passthrough();

export type Incident = z.infer<typeof incidentSchema>;

const resumeCardSchema = z
  .object({
    incident_id: z.string(),
    title: z.string(),
    status: z.string(),
    severity: z.string(),
    priority_score: count,
    last_action: z.string().nullish(),
    next_action: z.string().nullish(),
    blocked_by: z.string().nullish(),
    pending_verification: z.array(z.string()).nullish(),
    root_cause: z.string().nullish(),
    signal_count: count,
    affected_services: z.array(z.string()).nullish(),
    affected_tenants: z.array(z.string()).nullish(),
    opened_at: z.string().nullish(),
    updated_at: z.string().nullish(),
    missing_inputs: z.array(z.string()).nullish(),
  })
  .passthrough();

export type ResumeCard = z.infer<typeof resumeCardSchema>;

const correlationRecordSchema = z
  .object({
    signal_id: z.string().nullish(),
    basis: z.string().nullable(),
    confidence: z.number().nullable(),
    attached_at: z.string().nullish(),
  })
  .passthrough();

export type CorrelationRecord = z.infer<typeof correlationRecordSchema>;

const weakLinkSchema = z
  .object({
    incident_id: z.string(),
    basis: z.string().nullish(),
    confidence: z.number().nullish(),
    note: z.string().nullish(),
  })
  .passthrough();

export type WeakLink = z.infer<typeof weakLinkSchema>;

const incidentListSchema = z
  .object({
    incidents: z.array(incidentSchema),
    count: count,
    status_filter: z.string().nullish(),
    generated_at: z.string().nullish(),
  })
  .passthrough();

export type IncidentList = z.infer<typeof incidentListSchema>;

const resumeCardListSchema = z
  .object({
    cards: z.array(resumeCardSchema),
    count: count,
    generated_at: z.string().nullish(),
  })
  .passthrough();

export type ResumeCardList = z.infer<typeof resumeCardListSchema>;

const incidentDetailSchema = z
  .object({
    found: z.boolean(),
    incident: incidentSchema.nullable(),
    resume_card: resumeCardSchema.nullish(),
    timeline: z.array(signalSchema).nullish(),
    correlations: z.array(correlationRecordSchema).nullish(),
    weak_links: z.array(weakLinkSchema).nullish(),
    commands: z.array(jsonRecord).nullish(),
    generated_at: z.string().nullish(),
  })
  .passthrough();

export type IncidentDetail = z.infer<typeof incidentDetailSchema>;

const incidentMutationSchema = z
  .object({ incident: incidentSchema, resume_card: resumeCardSchema.nullish() })
  .passthrough();

// ── Correlation basis: deterministic evidence vs. a guess ────────────────────

/**
 * The backend's basis vocabulary (`services/kyber/ops/correlation.py`).
 *
 * `release_id` is the same deployment and `explicit` is a caller naming the incident
 * outright — neither infers anything. Everything else is a similarity or a coincidence.
 * `founding_signal` is not a correlation at all: it is the signal that opened the
 * incident, and recording it as evidence would claim an evaluation that never happened.
 *
 * The backend ships the basis and its confidence but no deterministic flag, so this
 * mapping lives here and is the only place it lives.
 */
export const DETERMINISTIC_BASES: readonly string[] = ['release_id', 'explicit'];
export const FOUNDING_BASES: readonly string[] = ['founding_signal'];

export type BasisKind = 'deterministic' | 'heuristic' | 'founding' | 'none';

export function basisKind(basis: string | null | undefined): BasisKind {
  if (basis === null || basis === undefined || basis === '') return 'none';
  if (FOUNDING_BASES.includes(basis)) return 'founding';
  if (DETERMINISTIC_BASES.includes(basis)) return 'deterministic';
  return 'heuristic';
}

export const BASIS_LABELS: Record<string, string> = {
  release_id: 'Same release',
  service_window: 'Same service, overlapping window',
  error_signature: 'Similar error signature',
  graph_dependency: 'Graph dependency',
  time_proximity: 'Time proximity',
  explicit: 'Named by the caller',
  founding_signal: 'Opened this incident',
};

// ── Commands ─────────────────────────────────────────────────────────────────

const commandSpecSchema = z
  .object({
    command_type: z.string(),
    title: z.string(),
    capability_id: z.string(),
    action_class: z.number(),
    handler: z.string(),
    verification_checks: z.array(z.string()).nullish(),
    requires_dry_run: z.boolean().nullish(),
    requires_rollback_plan: z.boolean().nullish(),
    tenant_scoped: z.boolean().nullish(),
    containment_scope: z.string().nullish(),
    description: z.string().nullish(),
  })
  .passthrough();

export type CommandSpec = z.infer<typeof commandSpecSchema>;

const commandSpecListSchema = z
  .object({
    types: z.array(commandSpecSchema),
    count: count,
    generated_at: z.string().nullish(),
  })
  .passthrough();

export type CommandSpecList = z.infer<typeof commandSpecListSchema>;

/**
 * The record of what an action would reach — or of the assessment that could not be
 * made. `available: false` is not an empty reach; see `reachIsKnown`.
 */
const blastRadiusSchema = z
  .object({
    available: z.boolean(),
    reason: z.string().nullish(),
    missing_inputs: z.array(z.string()).nullish(),
    exposure_known: z.boolean().nullish(),
    subject_type: z.string().nullish(),
    subject_id: z.string().nullish(),
    environment: z.string().nullish(),
    scope: z.string().nullish(),
    affected_services: z.array(z.string()).nullish(),
    affected_features: z.array(z.string()).nullish(),
    affected_tenants: z.array(z.string()).nullish(),
    affected_graph_domains: z.array(z.string()).nullish(),
    customer_visible: z.boolean().nullish(),
    traversal_depth: count,
    truncated: z.boolean().nullish(),
    confidence: z.number().nullish(),
    evidence_references: z.array(z.string()).nullish(),
    summary: z.string().nullish(),
    source: z.string().nullish(),
    computed_at: z.string().nullish(),
  })
  .passthrough();

export type BlastRadius = z.infer<typeof blastRadiusSchema>;

/**
 * Whether a numeric reach may be rendered at all.
 *
 * Both conditions matter. `available: false` means the assessor was not reachable;
 * `exposure_known: false` means it ran but an input was missing or a budget bound. In
 * either case the reach is unknown, and an unknown reach must never be drawn as a
 * small one.
 */
export function reachIsKnown(radius: BlastRadius | null | undefined): boolean {
  if (radius === null || radius === undefined) return false;
  if (radius.available !== true) return false;
  return radius.exposure_known === true;
}

/** Why the reach is unknown, in the backend's own words. Never invented here. */
export function reachMissingInputs(radius: BlastRadius | null | undefined): readonly string[] {
  if (radius === null || radius === undefined) return [];
  const missing = radius.missing_inputs ?? [];
  if (missing.length > 0) return missing;
  return radius.reason ? [radius.reason] : [];
}

const approvalSchema = z
  .object({
    approver_id: z.string(),
    role_template_ids: z.array(z.string()).nullish(),
    approved_at: z.string().nullish(),
  })
  .passthrough();

export type CommandApproval = z.infer<typeof approvalSchema>;

const commandSchema = z
  .object({
    command_id: z.string(),
    command_type: z.string(),
    status: z.string(),
    requested_by: z.string(),
    session_id: z.string().nullish(),
    device_id: z.string().nullish(),
    environment: z.string().nullish(),
    tenant_ids: z.array(z.string()).nullish(),
    resource_ids: z.array(z.string()).nullish(),
    reason: z.string(),
    action_class: count,
    dry_run: z.boolean().nullish(),
    idempotency_key: z.string().nullish(),
    blast_radius: blastRadiusSchema.nullish(),
    rollback_plan: z.string().nullish(),
    verification_plan: z.array(z.string()).nullish(),
    required_approvals: count,
    approvals: z.array(approvalSchema).nullish(),
    approval_mode: z.string().nullish(),
    step_up_verified: z.boolean().nullish(),
    incident_id: z.string().nullish(),
    created_at: z.string().nullish(),
    updated_at: z.string().nullish(),
    metadata: jsonRecord.nullish(),
  })
  .passthrough();

export type CommandRequest = z.infer<typeof commandSchema>;

const executionSchema = z
  .object({
    execution_id: z.string(),
    command_id: z.string().nullish(),
    attempt: count,
    started_at: z.string().nullish(),
    completed_at: z.string().nullish(),
    result: jsonRecord.nullish(),
    error: z.string().nullish(),
    side_effects: z.array(z.string()).nullish(),
    rollback_status: z.string().nullish(),
  })
  .passthrough();

export type CommandExecution = z.infer<typeof executionSchema>;

const verificationCheckSchema = z
  .object({
    check: z.string(),
    outcome: z.string(),
    detail: z.string().nullish(),
    evidence: jsonRecord.nullish(),
    checked_at: z.string().nullish(),
  })
  .passthrough();

export type VerificationCheck = z.infer<typeof verificationCheckSchema>;

const verificationSchema = z
  .object({
    verification_id: z.string(),
    command_id: z.string().nullish(),
    outcome: z.string(),
    checks: z.array(verificationCheckSchema).nullish(),
    customer_visible_parity: z.boolean().nullish(),
    mirror_digest_before: z.string().nullish(),
    mirror_digest_after: z.string().nullish(),
    failure_reason: z.string().nullish(),
    started_at: z.string().nullish(),
    completed_at: z.string().nullish(),
  })
  .passthrough();

export type CommandVerification = z.infer<typeof verificationSchema>;

/**
 * `verification` stays on this shape even when it is `null`. An absent field reads as
 * a question nobody asked; the whole point of `executed_unverified` is that the
 * question was asked and is still open.
 */
const commandDetailSchema = z
  .object({
    command: commandSchema,
    spec: commandSpecSchema.nullable(),
    execution: executionSchema.nullable(),
    executions: z.array(executionSchema).nullish(),
    verification: verificationSchema.nullable(),
    verified: z.boolean(),
    generated_at: z.string().nullish(),
  })
  .passthrough();

export type CommandDetail = z.infer<typeof commandDetailSchema>;

const commandListSchema = z
  .object({
    commands: z.array(commandSchema),
    count: count,
    status_filter: z.string().nullish(),
  })
  .passthrough();

export type CommandList = z.infer<typeof commandListSchema>;

const commandRequestResultSchema = z
  .object({
    command: commandSchema,
    spec: commandSpecSchema.nullish(),
    approval_gaps: z.array(z.string()).nullish(),
    executable: z.boolean().nullish(),
  })
  .passthrough();

export type CommandRequestResult = z.infer<typeof commandRequestResultSchema>;

const dryRunPlanSchema = z
  .object({
    command_id: z.string().nullish(),
    command_type: z.string().nullish(),
    handler: z.string(),
    handler_is_async: z.boolean().nullish(),
    receiver: z.string().nullish(),
    positional_arguments: z.array(z.unknown()).nullish(),
    keyword_arguments: jsonRecord.nullish(),
    bound_parameters: z.unknown().nullish(),
    follow_up: z.array(z.string()).nullish(),
    containment_target: z
      .object({
        scope: z.string().nullish(),
        target: z.string().nullish(),
        control: z.string().nullish(),
      })
      .passthrough()
      .nullable(),
    verification_plan: z.array(z.string()).nullish(),
    planned_at: z.string().nullish(),
  })
  .passthrough();

export type DryRunPlan = z.infer<typeof dryRunPlanSchema>;

const dryRunResultSchema = z.object({ plan: dryRunPlanSchema }).passthrough();

const approveResultSchema = z
  .object({ command: commandSchema, approval_gaps: z.array(z.string()).nullish() })
  .passthrough();

export type ApproveResult = z.infer<typeof approveResultSchema>;

/** Human copy for each gate `approval_policy.approval_gaps` can name. */
export const APPROVAL_GAP_LABELS: Record<string, string> = {
  fresh_step_up: 'Fresh step-up — a class 4/5 command needs a live step-up grant',
  dry_run: 'Dry run — this command type may not execute until one has run',
  rollback_plan: 'Rollback plan — this command type may not execute without one',
  blast_radius_review: 'Blast-radius review — the assessed reach has not been reviewed',
  founder_authority: 'Founder authority — solo mode requires it for a high-impact class',
  verification_plan: 'Verification plan — solo mode requires declared postconditions',
  typed_confirmation: 'Typed confirmation — the command type must be typed back verbatim',
  second_approver: 'Second approver — a different qualified operator must approve',
};

/**
 * Command statuses that are not success, however the call returned.
 *
 * `executed_unverified` is deliberately in here. It is the honest answer between "the
 * call returned" and "the system is in the state we wanted", and drawing it as success
 * is the single most damaging thing this surface can do.
 */
export const UNVERIFIED_STATUS = 'executed_unverified';
export const VERIFIED_STATUS = 'verified';

// ── Containment ──────────────────────────────────────────────────────────────

const switchSchema = z
  .object({
    switch_id: z.string(),
    scope: z.string(),
    target: z.string().nullish(),
    control: z.string(),
    active: z.boolean(),
    reason: z.string().nullish(),
    activated_by: z.string().nullish(),
    activated_at: z.string().nullish(),
    deactivated_by: z.string().nullish(),
    deactivated_at: z.string().nullish(),
    blast_radius: blastRadiusSchema.nullish(),
    metadata: jsonRecord.nullish(),
  })
  .passthrough();

export type ContainmentSwitch = z.infer<typeof switchSchema>;

/**
 * `preserved_in_safe_mode` is on the response deliberately: safe mode does NOT stop
 * ingestion, and an operator who assumes it did will read a quiet pipeline as a
 * contained incident.
 */
const containmentStateSchema = z
  .object({
    safe_mode: z.boolean(),
    active_count: count,
    switches: z.array(switchSchema),
    preserved_in_safe_mode: z.array(z.string()).nullish(),
  })
  .passthrough();

export type ContainmentState = z.infer<typeof containmentStateSchema>;

const activateResultSchema = z.object({ switch: switchSchema }).passthrough();

const deactivateResultSchema = z
  .object({ released: z.boolean(), switch: switchSchema.nullable() })
  .passthrough();

const safeModeResultSchema = z
  .object({
    safe_mode: z.boolean().nullish(),
    switches: z.array(switchSchema).nullish(),
    released: z.array(switchSchema).nullish(),
    state: containmentStateSchema,
  })
  .passthrough();

export type SafeModeResult = z.infer<typeof safeModeResultSchema>;

// ── Step-up: an expected, explainable state, not a failure ───────────────────

/**
 * A class 4/5 command denied for want of a live step-up grant comes back as a 403
 * whose detail is "A fresh step-up is required" and whose `denial_reason` is
 * `step_up_required`. That is an expected answer with a next action attached, and
 * rendering it as a generic error tells the operator nothing they can act on.
 */
export function isStepUpRequired(message: string | null | undefined): boolean {
  if (!message) return false;
  return /step[-_\s]?up/i.test(message);
}

// ── Fetchers ─────────────────────────────────────────────────────────────────

export interface ExceptionQueueQuery {
  readonly bucket?: string | undefined;
  readonly status?: string | undefined;
  readonly limit?: number | undefined;
}

export function fetchExceptionQueue(query: ExceptionQueueQuery = {}): Promise<ExceptionQueue> {
  return restClient
    .get(
      `${BASE}/exceptions${buildQS({
        bucket: query.bucket,
        status: query.status,
        limit: query.limit,
      })}`,
      wrap(exceptionQueueSchema),
    )
    .then(response => response.data);
}

export function acknowledgeException(exceptionId: string): Promise<OperationalException> {
  return restClient
    .post(
      `${BASE}/exceptions/${encodeURIComponent(exceptionId)}/acknowledge`,
      wrap(exceptionMutationSchema),
      {},
    )
    .then(response => response.data.exception);
}

export function resolveException(
  exceptionId: string,
  note?: string,
): Promise<OperationalException> {
  return restClient
    .post(
      `${BASE}/exceptions/${encodeURIComponent(exceptionId)}/resolve`,
      wrap(exceptionMutationSchema),
      note === undefined || note === '' ? {} : { note },
    )
    .then(response => response.data.exception);
}

/** The reason is mandatory server-side. Suppression without one is refused. */
export function suppressException(
  exceptionId: string,
  reason: string,
): Promise<OperationalException> {
  return restClient
    .post(
      `${BASE}/exceptions/${encodeURIComponent(exceptionId)}/suppress`,
      wrap(exceptionMutationSchema),
      { reason },
    )
    .then(response => response.data.exception);
}

export function fetchIncidents(status?: string): Promise<IncidentList> {
  return restClient
    .get(`${BASE}/incidents${buildQS({ status })}`, wrap(incidentListSchema))
    .then(response => response.data);
}

export function fetchResumeCards(): Promise<ResumeCardList> {
  return restClient
    .get(`${BASE}/incidents/resume-cards`, wrap(resumeCardListSchema))
    .then(response => response.data);
}

export function fetchIncident(incidentId: string): Promise<IncidentDetail> {
  return restClient
    .get(`${BASE}/incidents/${encodeURIComponent(incidentId)}`, wrap(incidentDetailSchema))
    .then(response => response.data);
}

export interface IncidentUpdate {
  readonly status?: string | undefined;
  readonly severity?: string | undefined;
  readonly root_cause?: string | undefined;
  readonly last_action?: string | undefined;
  readonly next_action?: string | undefined;
  readonly blocked_by?: string | undefined;
  readonly pending_verification?: readonly string[] | undefined;
  readonly note?: string | undefined;
}

export function updateIncident(incidentId: string, update: IncidentUpdate): Promise<Incident> {
  return restClient
    .patch(
      `${BASE}/incidents/${encodeURIComponent(incidentId)}`,
      wrap(incidentMutationSchema),
      update,
    )
    .then(response => response.data.incident);
}

export function resolveIncident(incidentId: string, rootCause?: string): Promise<Incident> {
  return restClient
    .post(
      `${BASE}/incidents/${encodeURIComponent(incidentId)}/resolve`,
      wrap(incidentMutationSchema),
      rootCause === undefined || rootCause === '' ? {} : { root_cause: rootCause },
    )
    .then(response => response.data.incident);
}

export function fetchCommandTypes(): Promise<CommandSpecList> {
  return restClient
    .get(`${BASE}/commands/types`, wrap(commandSpecListSchema))
    .then(response => response.data);
}

export function fetchCommands(status?: string, commandType?: string): Promise<CommandList> {
  return restClient
    .get(
      `${BASE}/commands${buildQS({ status, command_type: commandType })}`,
      wrap(commandListSchema),
    )
    .then(response => response.data);
}

export function fetchCommand(commandId: string): Promise<CommandDetail> {
  return restClient
    .get(`${BASE}/commands/${encodeURIComponent(commandId)}`, wrap(commandDetailSchema))
    .then(response => response.data);
}

export interface CommandRequestInput {
  readonly command_type: string;
  readonly reason: string;
  readonly idempotency_key: string;
  readonly tenant_ids?: readonly string[] | undefined;
  readonly resource_ids?: readonly string[] | undefined;
  readonly rollback_plan?: string | undefined;
  readonly typed_confirmation?: string | undefined;
  readonly approval_mode?: string | undefined;
  readonly incident_id?: string | undefined;
}

export function requestCommand(input: CommandRequestInput): Promise<CommandRequestResult> {
  return restClient
    .post(`${BASE}/commands`, wrap(commandRequestResultSchema), input)
    .then(response => response.data);
}

export function dryRunCommand(commandId: string): Promise<DryRunPlan> {
  return restClient
    .post(
      `${BASE}/commands/${encodeURIComponent(commandId)}/dry-run`,
      wrap(dryRunResultSchema),
      {},
    )
    .then(response => response.data.plan);
}

export function approveCommand(commandId: string): Promise<ApproveResult> {
  return restClient
    .post(
      `${BASE}/commands/${encodeURIComponent(commandId)}/approve`,
      wrap(approveResultSchema),
      {},
    )
    .then(response => response.data);
}

export function executeCommand(commandId: string): Promise<CommandDetail> {
  return restClient
    .post(
      `${BASE}/commands/${encodeURIComponent(commandId)}/execute`,
      wrap(commandDetailSchema),
      {},
    )
    .then(response => response.data);
}

export function fetchContainment(): Promise<ContainmentState> {
  return restClient
    .get(`${BASE}/containment`, wrap(containmentStateSchema))
    .then(response => response.data);
}

export interface ContainmentInput {
  readonly scope: string;
  readonly control: string;
  readonly target?: string | undefined;
  readonly reason: string;
}

export function activateContainment(input: ContainmentInput): Promise<ContainmentSwitch> {
  return restClient
    .post(`${BASE}/containment/activate`, wrap(activateResultSchema), input)
    .then(response => response.data.switch);
}

export function deactivateContainment(
  input: ContainmentInput,
): Promise<{ released: boolean; switch: ContainmentSwitch | null }> {
  return restClient
    .post(`${BASE}/containment/deactivate`, wrap(deactivateResultSchema), input)
    .then(response => ({ released: response.data.released, switch: response.data.switch }));
}

export function activateSafeMode(reason: string): Promise<SafeModeResult> {
  return restClient
    .post(`${BASE}/containment/safe-mode`, wrap(safeModeResultSchema), { reason })
    .then(response => response.data);
}

export function releaseSafeMode(reason: string): Promise<SafeModeResult> {
  return restClient
    .delete(`${BASE}/containment/safe-mode${buildQS({ reason })}`, wrap(safeModeResultSchema))
    .then(response => response.data);
}

// ── Hooks ────────────────────────────────────────────────────────────────────

export interface QueryState<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
}

export function useExceptionQueue(query: ExceptionQueueQuery = {}): QueryState<ExceptionQueue> {
  const { data, isLoading, error, refetch } = useQuery<ExceptionQueue>({
    key: `${KEY}:exceptions:${query.bucket ?? 'all'}:${query.status ?? 'open'}`,
    fetcher: () => fetchExceptionQueue(query),
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

export function useIncidents(status?: string): QueryState<IncidentList> {
  const { data, isLoading, error, refetch } = useQuery<IncidentList>({
    key: `${KEY}:incidents:${status ?? 'open'}`,
    fetcher: () => fetchIncidents(status),
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

export function useResumeCards(): QueryState<ResumeCardList> {
  const { data, isLoading, error, refetch } = useQuery<ResumeCardList>({
    key: `${KEY}:resume-cards`,
    fetcher: fetchResumeCards,
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Disabled until an incident is named — there is nothing to read without one. */
export function useIncident(incidentId: string | null): QueryState<IncidentDetail> {
  const { data, isLoading, error, refetch } = useQuery<IncidentDetail>({
    key: `${KEY}:incident:${incidentId ?? 'none'}`,
    fetcher: () => fetchIncident(incidentId as string),
    staleTime: STALE,
    enabled: incidentId !== null && incidentId !== '',
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

export function useCommandTypes(): QueryState<CommandSpecList> {
  const { data, isLoading, error, refetch } = useQuery<CommandSpecList>({
    key: `${KEY}:command-types`,
    fetcher: fetchCommandTypes,
    staleTime: 60_000,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

export function useCommands(status?: string): QueryState<CommandList> {
  const { data, isLoading, error, refetch } = useQuery<CommandList>({
    key: `${KEY}:commands:${status ?? 'open'}`,
    fetcher: () => fetchCommands(status),
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

export function useCommand(commandId: string | null): QueryState<CommandDetail> {
  const { data, isLoading, error, refetch } = useQuery<CommandDetail>({
    key: `${KEY}:command:${commandId ?? 'none'}`,
    fetcher: () => fetchCommand(commandId as string),
    staleTime: STALE,
    enabled: commandId !== null && commandId !== '',
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

export function useContainment(): QueryState<ContainmentState> {
  const { data, isLoading, error, refetch } = useQuery<ContainmentState>({
    key: `${KEY}:containment`,
    fetcher: fetchContainment,
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}
