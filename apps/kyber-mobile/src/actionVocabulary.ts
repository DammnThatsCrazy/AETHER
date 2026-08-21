/**
 * Kyber Mobile — governed-action vocabulary (M6b).
 *
 * Pure presentational mapping for the mobile actions digest and the durable
 * command-receipt surface. No `@aether/mobile-core` import lives here, so this
 * module is unit-testable in plain Node the moment the app grows a test runner
 * (the SDK's governed-action methods are being built in parallel).
 *
 * Action classes are the capability plane's 0-5 ladder
 * (`services/kyber/access/capabilities.py`): 0 read … 5 fleet-destructive.
 * Command statuses / verification outcomes are the wire values the command plane
 * writes (`services/kyber/ops/contracts.py`) — rendered snake_case-as-typed,
 * never camelCased.
 */
import { theme } from '@aether/mobile-ui';

/** The capability-plane action-class ladder (0 read … 5 fleet destructive). */
export const actionClasses = {
  read: 0,
  annotate: 1,
  retry: 2,
  recompute: 3,
  high_impact: 4,
  fleet_destructive: 5,
} as const;

const ACTION_CLASS_LABELS: Record<number, string> = {
  [actionClasses.read]: 'read',
  [actionClasses.annotate]: 'annotate',
  [actionClasses.retry]: 'retry',
  [actionClasses.recompute]: 'recompute',
  [actionClasses.high_impact]: 'high_impact',
  [actionClasses.fleet_destructive]: 'fleet_destructive',
};

/** Presentational action-class label (unknown classes render `class N`). */
export function actionClassLabel(actionClass: number): string {
  return ACTION_CLASS_LABELS[actionClass] ?? `class ${actionClass}`;
}

/** The four digest tiers, in display order, with their headings. */
export const ACTION_TIERS = [
  { key: 'tier0', heading: 'Act now', hint: 'Critical now — needs a decision' },
  { key: 'tier1', heading: 'Needs action', hint: 'Open decisions waiting on you' },
  { key: 'tier2', heading: 'Watch', hint: 'Monitor — not urgent yet' },
  { key: 'tier3', heading: 'Informational', hint: 'Low-noise updates' },
] as const;

export type ActionTierKey = (typeof ACTION_TIERS)[number]['key'];

/** Semantic tone for a command status / verification outcome. */
export type CommandTone = 'success' | 'warning' | 'danger' | 'muted';

/** Tone a wire command status (verified / executed_unverified / denied / …). */
export function commandStatusTone(status: string): CommandTone {
  switch (status) {
    case 'verified':
      return 'success';
    case 'requested':
    case 'awaiting_approval':
    case 'approved':
    case 'dry_run_complete':
    case 'executing':
    case 'executed_unverified':
      // `executed_unverified` is an open question, not a failure — a side effect
      // may have landed, so it reads as "still needs attention", never as done.
      return 'warning';
    case 'denied':
    case 'rejected':
    case 'failed':
    case 'rolled_back':
    case 'cancelled':
      return 'danger';
    case 'expired':
      return 'muted';
    default:
      return 'muted';
  }
}

/** Tone a verification outcome (passed / failed / inconclusive / not_run). */
export function verificationOutcomeTone(outcome: string): CommandTone {
  switch (outcome) {
    case 'passed':
      return 'success';
    case 'failed':
      return 'danger';
    case 'inconclusive':
      return 'warning';
    default:
      return 'muted';
  }
}

/** Map a semantic tone to the theme palette. */
export function toneToColor(tone: CommandTone): string {
  switch (tone) {
    case 'success':
      return theme.colors.success;
    case 'warning':
      return theme.colors.warning;
    case 'danger':
      return theme.colors.danger;
    default:
      return theme.colors.muted;
  }
}

/** snake_case wire value → readable display label ("dry_run_complete" → "Dry Run Complete"). */
export function humanizeSnake(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

/** Display label for a wire command status. */
export function commandStatusLabel(status: string): string {
  return humanizeSnake(status);
}
