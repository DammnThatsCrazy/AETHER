import { Badge } from '@aether/ui';
import type { LineageDisclosure } from './use-agent-lineage';

/** Unknown is shown as unknown. A null count never renders as 0. */
export function lineageCount(value: unknown): string {
  if (value === null || value === undefined) return 'Unknown';
  return typeof value === 'number' ? value.toLocaleString('en-US') : String(value);
}

export function LineageStat({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-md border border-border-default bg-surface-raised px-3 py-2">
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd className="mt-1 text-sm font-medium text-text-primary">{lineageCount(value)}</dd>
    </div>
  );
}

const ATTRIBUTION_VARIANT = {
  verified: 'success',
  inferred: 'info',
  suspected_cluster: 'warning',
  unresolved: 'default',
} as const;

const ATTRIBUTION_LABEL: Record<string, string> = {
  verified: 'Verified',
  inferred: 'Inferred',
  suspected_cluster: 'Suspected cluster',
  unresolved: 'Unresolved',
};

export function AttributionBadge({ value }: { value: string }) {
  const variant = ATTRIBUTION_VARIANT[value as keyof typeof ATTRIBUTION_VARIANT] ?? 'default';
  return <Badge variant={variant}>{ATTRIBUTION_LABEL[value] ?? value}</Badge>;
}

const DEGRADED_COPY: Record<string, string> = {
  partial: 'Some lineage is partial. Counts below are what could be resolved.',
  truncated: 'Some lineage was cut off by a processing limit. Counts below exclude what was not walked.',
  stale: 'This view has not been reconciled recently.',
  recomputing: 'This view is being recomputed.',
  unknown: 'No lineage has been materialized for this subject yet. That does not mean there are no agents.',
  unavailable: 'Lineage could not be read.',
};

export function LineageDisclosureNote({ disclosure }: { disclosure: LineageDisclosure }) {
  const copy = DEGRADED_COPY[disclosure.completeness];
  return (
    <div className="space-y-1">
      <p className="text-xs text-text-secondary">
        As of {disclosure.as_of ?? 'unknown'} · Completeness: {disclosure.completeness}
      </p>
      {copy && <p role="status" className="text-xs text-warning">{copy}</p>}
      {disclosure.truncation_reasons.length > 0 && (
        <p className="font-mono text-xs text-text-secondary">{disclosure.truncation_reasons.join(' · ')}</p>
      )}
    </div>
  );
}
