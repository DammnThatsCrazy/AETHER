export interface SuggestionFiltersValue {
  status?: string;
  priority?: string;
  tenant_id?: string;
}

export interface SuggestionFiltersProps {
  readonly filters: SuggestionFiltersValue;
  onChange: (f: SuggestionFiltersValue) => void;
}

const STATUS_OPTIONS = [
  'all',
  'detected',
  'oriented',
  'suggested',
  'review_required',
  'approved',
  'rejected',
  'suppressed',
  'executing',
  'executed',
  'delivered',
  'measured',
  'learned',
  'closed',
  'expired',
  'failed',
];

const PRIORITY_OPTIONS = ['all', 'P0', 'P1', 'P2', 'P3', 'info'];

const selectClass =
  'rounded border border-border-default bg-surface-default px-2 py-1 text-xs font-mono text-text-primary focus:outline-none focus:ring-1 focus:ring-brand-default';

export function SuggestionFilters({ filters, onChange }: SuggestionFiltersProps) {
  const update = (key: keyof SuggestionFiltersValue, value: string) => {
    const next: SuggestionFiltersValue = { ...filters };
    if (value === 'all' || value === '') {
      delete next[key];
    } else {
      next[key] = value;
    }
    onChange(next);
  };

  return (
    <div className="flex flex-wrap items-center gap-2 pb-3">
      <select
        className={selectClass}
        value={filters.status ?? 'all'}
        onChange={(e) => update('status', e.target.value)}
      >
        {STATUS_OPTIONS.map((s) => (
          <option key={s} value={s}>{s === 'all' ? 'All statuses' : s}</option>
        ))}
      </select>

      <select
        className={selectClass}
        value={filters.priority ?? 'all'}
        onChange={(e) => update('priority', e.target.value)}
      >
        {PRIORITY_OPTIONS.map((p) => (
          <option key={p} value={p}>{p === 'all' ? 'All priorities' : p}</option>
        ))}
      </select>

      <input
        type="text"
        placeholder="Tenant ID"
        className={selectClass}
        value={filters.tenant_id ?? ''}
        onChange={(e) => update('tenant_id', e.target.value)}
      />
    </div>
  );
}
