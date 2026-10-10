import { Badge } from '../components/badge';
import type {
  ValueFreshness,
  ValueConfidence,
  RollupStatus,
  ValueReconciliationState,
  OwnershipRelationship,
} from './format';

// =============================================================================
// Small presentational badges for the canonical value envelope (§4.17).
//
// Each badge maps a canonical status enum to the shared `Badge` variants used
// across the value surfaces (success / warning / danger / info / default) and
// renders nothing when its input is absent — the same "absence is not zero"
// discipline the value formatters follow. These are purely presentational: no
// data fetching, no coercion, just an enum -> label + variant lookup.
// =============================================================================

type BadgeVariant = 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

interface BadgeMeta {
  readonly variant: BadgeVariant;
  readonly label: string;
}

function titleCase(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

// --- RollupStatusBadge -------------------------------------------------------

const ROLLUP_STATUS_META: Record<RollupStatus, BadgeMeta> = {
  complete: { variant: 'success', label: 'Complete' },
  partial: { variant: 'warning', label: 'Partial' },
  stale: { variant: 'warning', label: 'Stale' },
  unavailable: { variant: 'default', label: 'Unavailable' },
  conflicted: { variant: 'danger', label: 'Conflicted' },
};

interface RollupStatusBadgeProps {
  readonly status: RollupStatus | null | undefined;
  readonly className?: string | undefined;
}

/** Rollup completeness at a glance: complete / partial / stale / unavailable / conflicted. */
export function RollupStatusBadge({ status, className }: RollupStatusBadgeProps) {
  if (!status) return null;
  const meta = ROLLUP_STATUS_META[status] ?? { variant: 'default', label: titleCase(status) };
  return (
    <Badge variant={meta.variant} size="sm" className={className}>
      {meta.label}
    </Badge>
  );
}

// --- FreshnessBadge ----------------------------------------------------------

const FRESHNESS_META: Record<ValueFreshness, BadgeMeta> = {
  live: { variant: 'success', label: 'Live' },
  recent: { variant: 'info', label: 'Recent' },
  stale: { variant: 'warning', label: 'Stale' },
  expired: { variant: 'danger', label: 'Expired' },
  unavailable: { variant: 'default', label: 'Unavailable' },
};

interface FreshnessBadgeProps {
  readonly freshness: ValueFreshness | null | undefined;
  readonly className?: string | undefined;
}

/** Valuation freshness: live / recent / stale / expired / unavailable. */
export function FreshnessBadge({ freshness, className }: FreshnessBadgeProps) {
  if (!freshness) return null;
  const meta = FRESHNESS_META[freshness] ?? { variant: 'default', label: titleCase(freshness) };
  return (
    <Badge variant={meta.variant} size="sm" className={className}>
      {meta.label}
    </Badge>
  );
}

// --- ReconciliationBadge -----------------------------------------------------

const RECONCILIATION_META: Record<ValueReconciliationState, BadgeMeta> = {
  matched: { variant: 'success', label: 'Matched' },
  conflict: { variant: 'danger', label: 'Conflict' },
  stale: { variant: 'warning', label: 'Stale' },
  unreconciled: { variant: 'warning', label: 'Unreconciled' },
  sdk_only: { variant: 'info', label: 'SDK only' },
  provider_only: { variant: 'info', label: 'Provider only' },
  ignored_duplicate: { variant: 'default', label: 'Duplicate' },
  not_applicable: { variant: 'default', label: 'N/A' },
};

interface ReconciliationBadgeProps {
  readonly state: ValueReconciliationState | null | undefined;
  readonly className?: string | undefined;
}

/** Cross-source reconciliation state for a value. */
export function ReconciliationBadge({ state, className }: ReconciliationBadgeProps) {
  if (!state) return null;
  const meta = RECONCILIATION_META[state] ?? { variant: 'default', label: titleCase(state) };
  return (
    <Badge variant={meta.variant} size="sm" className={className}>
      {meta.label}
    </Badge>
  );
}

// --- OwnershipConfidenceBadge ------------------------------------------------

const CONFIDENCE_META: Record<ValueConfidence, BadgeMeta> = {
  high: { variant: 'success', label: 'High' },
  medium: { variant: 'info', label: 'Medium' },
  low: { variant: 'warning', label: 'Low' },
  unknown: { variant: 'default', label: 'Unknown' },
};

interface OwnershipConfidenceBadgeProps {
  readonly confidence: ValueConfidence | null | undefined;
  /** Optional ownership relationship prefix, e.g. "Owned · High". */
  readonly relationship?: OwnershipRelationship | null | undefined;
  readonly className?: string | undefined;
}

/** Ownership confidence (with an optional relationship prefix). */
export function OwnershipConfidenceBadge({
  confidence,
  relationship,
  className,
}: OwnershipConfidenceBadgeProps) {
  if (!confidence) return null;
  const meta = CONFIDENCE_META[confidence] ?? { variant: 'default', label: titleCase(confidence) };
  const label = relationship ? `${titleCase(relationship)} · ${meta.label}` : meta.label;
  return (
    <Badge variant={meta.variant} size="sm" className={className}>
      {label}
    </Badge>
  );
}
