import { useState } from 'react';
import { Badge, Button } from '@aether/ui';
import type { ExportPackageRecord } from '../api';

// ── Required execution-boundary copy ───────────────────────────────────────────
// These strings are normative UX copy: Aether observes targeting, it never
// executes campaigns. Do not soften or reword them.

export const CAMPAIGN_BOUNDARY_COPY =
  'Aether does not execute this campaign. Execution happens in your external platforms.';

export const EXPORT_BOUNDARY_COPY =
  'This package is for your external platform. Aether does not execute it.';

export const EXTERNAL_EXECUTION_REQUIRED_COPY = 'External execution required';

export const NOT_CONFIGURED_TITLE = 'Targeting intelligence is not configured';
export const NOT_CONFIGURED_DESCRIPTION =
  'This workspace does not have the targeting intelligence plane enabled. Contact your administrator or Aether support to enable it.';

// ── Formatters ─────────────────────────────────────────────────────────────────

export function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return '—';
  return `${(rate * 100).toFixed(1)}%`;
}

export function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return n.toLocaleString();
}

/** Amounts always carry an explicit currency label and are never merged. */
export function formatCurrencyAmount(
  amount: number | null | undefined,
  currency: string,
): React.ReactNode {
  if (amount === null || amount === undefined) {
    return <Badge variant="warning" size="sm">unknown</Badge>;
  }
  return (
    <span className="font-mono">
      {amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {currency}
    </span>
  );
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

export function humanize(value: string): string {
  return value.replace(/_/g, ' ');
}

// ── Severity ───────────────────────────────────────────────────────────────────

export function severityVariant(severity: string): 'danger' | 'warning' | 'info' | 'default' {
  if (severity === 'critical' || severity === 'high') return 'danger';
  if (severity === 'medium') return 'warning';
  if (severity === 'low') return 'info';
  return 'default';
}

export function LeakageSeverityBadge({ severity }: { readonly severity: string }) {
  return <Badge variant={severityVariant(severity)} size="sm">{severity}</Badge>;
}

// ── Cluster chips ──────────────────────────────────────────────────────────────

export type ClusterRuleKind = 'include' | 'exclude' | 'reference' | 'holdout';

const RULE_VARIANTS: Record<ClusterRuleKind, 'success' | 'danger' | 'info' | 'warning'> = {
  include: 'success',
  exclude: 'danger',
  reference: 'info',
  holdout: 'warning',
};

export const RULE_LABELS: Record<ClusterRuleKind, string> = {
  include: 'Included clusters',
  exclude: 'Excluded clusters',
  reference: 'Reference clusters',
  holdout: 'Holdout clusters',
};

interface ClusterChipProps {
  readonly clusterId: string;
  readonly kind: ClusterRuleKind;
  /** True when observed campaign reach overlapped this cluster. */
  readonly reached?: boolean;
}

/**
 * One chip per cluster rule. The reach indicator marks observed overlap:
 * ✓ reach is expected for include/reference clusters, and marks leakage or
 * contamination for exclude/holdout clusters.
 */
export function ClusterChip({ clusterId, kind, reached }: ClusterChipProps) {
  const reachedIsViolation = kind === 'exclude' || kind === 'holdout';
  return (
    <Badge variant={RULE_VARIANTS[kind]} size="sm" className="font-mono">
      {clusterId}
      {reached !== undefined && (
        <span
          className={reached && reachedIsViolation ? 'ml-1 text-danger' : 'ml-1'}
          title={reached ? 'Observed reach overlaps this cluster' : 'No observed reach in this cluster'}
        >
          {reached ? (reachedIsViolation ? '· reached ⚠' : '· reached ✓') : '· not reached'}
        </span>
      )}
    </Badge>
  );
}

interface ClusterChipGroupProps {
  readonly kind: ClusterRuleKind;
  readonly clusterIds: string[];
  readonly reachedClusterIds?: string[];
  /** Omit reach indicators entirely (e.g. no observation yet). */
  readonly showReach?: boolean;
}

export function ClusterChipGroup({ kind, clusterIds, reachedClusterIds, showReach = true }: ClusterChipGroupProps) {
  const reachedSet = new Set(reachedClusterIds ?? []);
  return (
    <div>
      <p className="text-xs font-medium text-text-muted uppercase tracking-wide mb-1">{RULE_LABELS[kind]}</p>
      {clusterIds.length === 0 ? (
        <p className="text-xs text-text-muted">None declared</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {clusterIds.map(clusterId => (
            <ClusterChip
              key={clusterId}
              clusterId={clusterId}
              kind={kind}
              {...(showReach ? { reached: reachedSet.has(clusterId) } : {})}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Evidence chain summary ─────────────────────────────────────────────────────

export interface EvidenceChainRefs {
  readonly targetingIntentId?: string | null | undefined;
  readonly eligibilitySnapshotId?: string | null | undefined;
  readonly observationId?: string | null | undefined;
  readonly outcomeSnapshotId?: string | null | undefined;
}

const CHAIN_STAGES: ReadonlyArray<{ key: keyof EvidenceChainRefs; label: string }> = [
  { key: 'targetingIntentId', label: 'Intent' },
  { key: 'eligibilitySnapshotId', label: 'Snapshot' },
  { key: 'observationId', label: 'Observation' },
  { key: 'outcomeSnapshotId', label: 'Outcome' },
];

/** Intent → snapshot → observation → outcome provenance summary. */
export function EvidenceChainSummary({ chain }: { readonly chain: EvidenceChainRefs }) {
  return (
    <div>
      <p className="text-xs font-medium text-text-muted uppercase tracking-wide mb-1">Evidence chain</p>
      <div className="flex items-center gap-1.5 flex-wrap text-xs font-mono">
        {CHAIN_STAGES.map(({ key, label }, index) => {
          const ref = chain[key];
          return (
            <span key={key} className="flex items-center gap-1.5">
              {index > 0 && <span className="text-text-muted">→</span>}
              <span className={ref ? 'text-text-primary' : 'text-text-muted'}>
                {label}
                {ref ? `: ${String(ref)}` : ': —'}
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ── Export package detail ──────────────────────────────────────────────────────

export function ExportPackageDetail({ pkg }: { readonly pkg: ExportPackageRecord }) {
  const notes = pkg.implementationNotes ?? [];
  const [copied, setCopied] = useState(false);

  // Copyable JSON per the export UI spec: no secrets, no raw PII — the
  // package only carries cluster ids, notes, and evidence refs.
  const handleCopyJson = () => {
    const json = JSON.stringify(pkg, null, 2);
    const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : undefined;
    if (!clipboard?.writeText) return;
    clipboard.writeText(json).then(() => setCopied(true)).catch(() => undefined);
  };

  return (
    <div className="border border-border-default rounded-md px-3 py-2.5 space-y-3 bg-surface-raised">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-medium text-text-primary font-mono">{pkg.exportId}</span>
        <Badge variant="warning" size="sm">{EXTERNAL_EXECUTION_REQUIRED_COPY}</Badge>
        {pkg.generatedAt && (
          <span className="text-xs text-text-muted">{formatDateTime(pkg.generatedAt)}</span>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={handleCopyJson}
          aria-label={`Copy JSON for export ${pkg.exportId}`}
        >
          {copied ? 'Copied' : 'Copy JSON'}
        </Button>
      </div>

      <p className="text-xs text-text-secondary">{EXPORT_BOUNDARY_COPY}</p>

      <div className="space-y-2">
        <ClusterChipGroup kind="include" clusterIds={pkg.includeClusterIds ?? []} showReach={false} />
        <ClusterChipGroup kind="reference" clusterIds={pkg.referenceClusterIds ?? []} showReach={false} />
        <ClusterChipGroup kind="exclude" clusterIds={pkg.excludeClusterIds ?? []} showReach={false} />
        <ClusterChipGroup kind="holdout" clusterIds={pkg.holdoutClusterIds ?? []} showReach={false} />
      </div>

      <div>
        <p className="text-xs font-medium text-text-muted uppercase tracking-wide mb-1">Implementation notes</p>
        {notes.length === 0 ? (
          <p className="text-xs text-text-muted">No implementation notes.</p>
        ) : (
          <ul className="list-disc list-inside space-y-0.5">
            {notes.map((note, i) => (
              <li key={i} className="text-xs text-text-primary">{note}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
