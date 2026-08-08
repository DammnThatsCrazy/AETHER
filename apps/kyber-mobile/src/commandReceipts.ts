/**
 * Kyber Mobile — durable command-receipt render view + projections (M6b).
 *
 * The SDK owns the wire shapes for the command-receipt surface
 * (`AetherMobileClient.getCommandReceipts` / `getCommandReceipt`, typed from the
 * backend contracts). This module holds the app's FLATTENED render view and the
 * pure presentational helpers on top of it — it does not re-declare the wire
 * contract (reuse-before-build; the SDK's `CommandReceiptList` / `CommandReceipt`
 * / `CommandReceiptDetail` are the source of truth).
 *
 * `verification: null` is the "not verified" answer and is never hidden — see
 * {@link receiptVerificationText}. All fields stay snake_case (decision-log D6).
 */
import type { CommandReceipt, CommandReceiptDetail } from '@aether/mobile-core';

/**
 * The receipt detail as the UI renders it. The SDK returns the command record
 * nested under `detail.command` (plus `spec` / `execution` / `verification` /
 * `verified`); this view flattens the command row and pulls the spec's
 * `capability_id` up beside the other reason/capability fields.
 * `verification` is `null` exactly when the command was never verified — the
 * honest answer — and must render as "Not verified".
 */
export interface CommandReceiptDetailView {
  command_id: string;
  command_type: string;
  status: string;
  requested_by: string;
  action_class: number;
  /** The spec capability that authorises this command type, when known. */
  capability?: string | null;
  reason: string;
  blast_radius?: Record<string, unknown> | null;
  required_approvals?: number;
  approvals?: Array<Record<string, unknown>>;
  approval_mode?: string;
  execution?: Record<string, unknown> | null;
  verification: Record<string, unknown> | null;
  /** True only when the command's status is `verified`. */
  verified: boolean;
  created_at: string;
  updated_at: string;
  generated_at?: string;
}

/** One row of the receipts list — the SDK's command record (a superset of what the row renders). */
export type CommandReceiptListRow = CommandReceipt;

/** `client.getCommandReceipts` envelope (the SDK shape). */
export type ReceiptsList = import('@aether/mobile-core').CommandReceiptList;

/**
 * Adapt the SDK's nested detail shape to the flat render view.
 *
 * The SDK returns `{ command, spec, execution, executions, verification,
 * verified, generated_at }`; the view flattens the command row and lifts the
 * spec's `capability_id` (the capability that authorises the command type) into
 * the view. This is the single SDK→view adapter for the detail screen.
 */
export function mapReceiptDetailToView(detail: CommandReceiptDetail): CommandReceiptDetailView {
  const c = detail.command;
  const specCapability = detail.spec?.['capability_id'];
  return {
    command_id: c.command_id,
    command_type: c.command_type,
    status: c.status,
    requested_by: c.requested_by,
    action_class: c.action_class,
    capability: typeof specCapability === 'string' ? specCapability : null,
    reason: c.reason,
    blast_radius: c.blast_radius,
    required_approvals: c.required_approvals,
    approvals: c.approvals,
    approval_mode: c.approval_mode,
    execution: detail.execution,
    verification: detail.verification,
    verified: detail.verified,
    created_at: c.created_at,
    updated_at: c.updated_at,
    generated_at: detail.generated_at,
  };
}

/** A readable blast-radius summary from the assessed `blast_radius` dict. */
export function blastRadiusSummary(blast?: Record<string, unknown> | null): string {
  if (blast === null || blast === undefined || typeof blast !== 'object') {
    return 'not assessed';
  }
  if (blast['available'] === false) {
    const reason = typeof blast['reason'] === 'string' ? String(blast['reason']) : '';
    return reason ? `unavailable — ${reason}` : 'unavailable';
  }
  const parts: string[] = [];
  for (const key of ['impact_score', 'priority_score', 'confidence'] as const) {
    const value = blast[key];
    if (typeof value === 'number' || typeof value === 'string') {
      parts.push(`${key.replace('_score', '')} ${value}`);
    }
  }
  return parts.length > 0 ? parts.join(' · ') : 'assessed';
}

/** Human-readable one-liner for the execution block (or "never dispatched"). */
export function executionOutcomeText(execution?: Record<string, unknown> | null): string {
  if (!execution) {
    return 'not executed — no execution record';
  }
  const parts: string[] = [];
  if (typeof execution['attempt'] === 'number') parts.push(`attempt ${execution['attempt']}`);
  if (typeof execution['completed_at'] === 'string') {
    parts.push(`completed ${execution['completed_at']}`);
  } else if (typeof execution['started_at'] === 'string') {
    parts.push(`started ${execution['started_at']}`);
  }
  if (typeof execution['rollback_status'] === 'string') parts.push(`rollback ${execution['rollback_status']}`);
  const sideEffects = Array.isArray(execution['side_effects']) ? (execution['side_effects'] as unknown[]) : [];
  if (sideEffects.length > 0) {
    parts.push(`${sideEffects.length} recorded side effect${sideEffects.length === 1 ? '' : 's'}`);
  }
  return parts.length > 0 ? parts.join(' · ') : 'execution recorded';
}

/**
 * The honest verification line for a receipt. `null` verification is rendered
 * as "Not verified" and is never omitted — an absent field is an open question,
 * not a passing one.
 */
export function receiptVerificationText(detail: CommandReceiptDetailView): string {
  if (detail.verification === null) {
    return detail.verified
      ? 'Not verified — status is verified but no verification record is attached.'
      : 'Not verified — this command’s postconditions are still an open question.';
  }
  const outcome = typeof detail.verification['outcome'] === 'string'
    ? String(detail.verification['outcome'])
    : 'unknown';
  const failure = typeof detail.verification['failure_reason'] === 'string'
    ? String(detail.verification['failure_reason'])
    : null;
  return failure ? `Verification ${outcome} — ${failure}` : `Verification ${outcome}`;
}
