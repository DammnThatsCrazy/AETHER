import type { ApplicabilityReport } from '@aether/shared/exploration-contract';
import type { FilterGroup } from '@aether/shared/graph-contract';
import { chipsFromContext, operatorLabel } from '../filter-model';
import { FilterDispositionBadge } from './disposition-badge';

export interface FilterBarProps {
  readonly population: FilterGroup | null | undefined;
  /** Per-filter dispositions from the last result — makes silent drops visible. */
  readonly applicability?: ApplicabilityReport | null;
  readonly onRemove?: (index: number) => void;
  readonly onClear?: () => void;
}

/**
 * Active-filter chips. Each chip carries its applicability disposition badge
 * (applied / translated / unsupported / suppressed), so a filter the surface
 * did not honour can never masquerade as one that was applied.
 */
export function FilterBar({ population, applicability, onRemove, onClear }: FilterBarProps) {
  const chips = chipsFromContext(population, applicability);
  if (chips.length === 0) {
    return <p className="text-xs text-text-muted">No active filters.</p>;
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="filter-bar">
      {chips.map((chip) => (
        <span
          key={chip.index}
          className="inline-flex items-center gap-1.5 rounded border border-border-default bg-surface-raised px-2 py-1 text-xs"
        >
          <span className="text-text-secondary">{chip.label}</span>
          {!chip.isGroup && <span className="font-mono text-text-muted">{operatorLabel(chip.op)}</span>}
          {chip.valueText && <span className="font-mono text-text-primary">{chip.valueText}</span>}
          {chip.disposition && (
            <FilterDispositionBadge disposition={chip.disposition} reason={chip.reason} />
          )}
          {onRemove && !chip.isGroup && (
            <button
              type="button"
              onClick={() => onRemove(chip.index)}
              className="ml-0.5 text-text-muted hover:text-danger"
              aria-label={`Remove ${chip.label} filter`}
            >
              ×
            </button>
          )}
        </span>
      ))}
      {onClear && (
        <button
          type="button"
          onClick={onClear}
          className="text-xs text-text-muted underline hover:text-text-primary"
        >
          Clear all
        </button>
      )}
    </div>
  );
}
