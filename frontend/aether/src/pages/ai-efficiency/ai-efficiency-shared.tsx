import { Badge, formatCount, formatInstant, type LocaleContext, type TimeContext } from '@aether/ui';
import type { AIEfficiencyDetector, AIInvocationStatus, CostBasis } from '@aether/shared';

export const GOVERNED_PROPOSALS_COPY =
  'Proposals only — Aether never changes models, prompts, or routing automatically.';

export const UNKNOWN_COST_COPY =
  'Costs stay in their native currency and are never merged. Unknown costs are shown as unknown — never as zero.';

const DETECTOR_LABELS: Record<AIEfficiencyDetector, string> = {
  retry_waste: 'Retry waste',
  model_overqualification: 'Model overqualification',
  deterministic_replacement_candidate: 'Deterministic replacement',
  cache_opportunity: 'Cache opportunity',
  failed_workflow_concentration: 'Failed workflow concentration',
};

export function detectorLabel(detector: AIEfficiencyDetector): string {
  return DETECTOR_LABELS[detector] ?? detector;
}

export function DetectorBadge({ detector }: { readonly detector: AIEfficiencyDetector }) {
  return <Badge size="sm">{detectorLabel(detector)}</Badge>;
}

const INVOCATION_STATUS_VARIANTS: Record<AIInvocationStatus, 'success' | 'warning' | 'danger' | 'default'> = {
  succeeded: 'success',
  failed: 'danger',
  cancelled: 'default',
  timeout: 'warning',
};

export function InvocationStatusBadge({ status }: { readonly status: AIInvocationStatus }) {
  return <Badge variant={INVOCATION_STATUS_VARIANTS[status] ?? 'default'}>{status}</Badge>;
}

const SEVERITY_VARIANTS: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'default'> = {
  critical: 'danger',
  high: 'danger',
  medium: 'warning',
  low: 'info',
};

export function FindingSeverityBadge({ severity }: { readonly severity: string }) {
  return <Badge variant={SEVERITY_VARIANTS[severity] ?? 'default'}>{severity}</Badge>;
}

/**
 * Cost amount display. Deterministic (no locale): two decimals for amounts
 * of one unit or more, up to six significant decimals below one so small
 * per-invocation costs never collapse to "0.00".
 */
export function formatCostAmount(value: number): string {
  if (Math.abs(value) >= 1) return value.toFixed(2);
  return String(Number(value.toFixed(6)));
}

/**
 * Cost display in its own currency — never converted, summed, or merged
 * across currencies. Null/undefined means the cost is unknown and renders as
 * an "unknown" badge, NEVER as 0.
 */
export function CostValue({ value, currency }: {
  readonly value: number | null | undefined;
  readonly currency?: string | null | undefined;
}) {
  if (value === null || value === undefined) {
    return <Badge variant="warning" size="sm">unknown</Badge>;
  }
  return (
    <span className="font-mono">
      {currency ? `${formatCostAmount(value)} ${currency}` : formatCostAmount(value)}
    </span>
  );
}

export function CostBasisNote({ basis }: { readonly basis: CostBasis }) {
  return <span className="text-[10px] text-text-muted font-mono">basis: {basis.replace(/_/g, ' ')}</span>;
}

export function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return '—';
  return `${(rate * 100).toFixed(1)}%`;
}

export function formatQuality(score: number | null | undefined): string {
  if (score === null || score === undefined) return '—';
  return score.toFixed(2);
}

export function formatLatency(ms: number | null | undefined, locale: LocaleContext): string {
  if (ms === null || ms === undefined) return '—';
  return `${formatCount(Math.round(ms), locale)} ms`;
}

export function formatDateTime(iso: string | null | undefined, timeCtx: TimeContext): string {
  if (!iso) return '—';
  try {
    return formatInstant(iso, timeCtx);
  } catch {
    return iso;
  }
}
