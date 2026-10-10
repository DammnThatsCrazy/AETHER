import { getFilterField } from '../registry';

export interface FacetBucket {
  readonly value: string;
  readonly label?: string | undefined;
  /** null means the bucket was suppressed (cohort below minimum / policy). */
  readonly count: number | null;
}

export interface FacetGroup {
  readonly field: string;
  readonly buckets: readonly FacetBucket[];
}

export interface FacetPanelProps {
  readonly facets: readonly FacetGroup[];
  /** Selecting a bucket adds the corresponding equality filter. */
  readonly onSelect?: ((field: string, value: string) => void) | undefined;
}

/** The registry-declared cohort minimum for a field, if any. */
export function cohortMinimumFor(field: string): number | undefined {
  return getFilterField(field)?.minimumCohortSize;
}

/**
 * Facet breakdown. A bucket whose count was withheld for cohort-minimum /
 * consent reasons renders an explicit suppression notice (with the registry's
 * minimum cohort size) — never a blank or a misleading zero.
 */
export function FacetPanel({ facets, onSelect }: FacetPanelProps) {
  if (facets.length === 0) {
    return <p className="text-xs text-text-muted">No facets available.</p>;
  }
  return (
    <div className="flex flex-col gap-3" data-testid="facet-panel">
      {facets.map((facet) => {
        const def = getFilterField(facet.field);
        const min = def?.minimumCohortSize;
        return (
          <div key={facet.field}>
            <p className="mb-1 text-xs font-medium text-text-secondary">{def?.label ?? facet.field}</p>
            <ul className="flex flex-col gap-0.5">
              {facet.buckets.map((bucket) => {
                const suppressed = bucket.count === null;
                return (
                  <li key={bucket.value} className="flex items-center justify-between gap-2 text-xs">
                    {onSelect && !suppressed ? (
                      <button
                        type="button"
                        onClick={() => onSelect(facet.field, bucket.value)}
                        className="text-left text-text-primary hover:text-accent"
                      >
                        {bucket.label ?? bucket.value}
                      </button>
                    ) : (
                      <span className="text-text-primary">{bucket.label ?? bucket.value}</span>
                    )}
                    {suppressed ? (
                      <span
                        className="text-[10px] text-warning"
                        title={min ? `Cohort below the minimum of ${min}` : 'Withheld by policy'}
                      >
                        suppressed{min ? ` (cohort < ${min})` : ''}
                      </span>
                    ) : (
                      <span className="font-mono text-text-muted">{bucket.count}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
