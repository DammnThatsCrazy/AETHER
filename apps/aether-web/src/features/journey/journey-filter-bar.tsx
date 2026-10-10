import type { FC } from 'react';
import type { ActivityFamily } from './use-unified-journey';

const FAMILIES: { value: ActivityFamily; label: string }[] = [
  { value: 'web2', label: 'Web' },
  { value: 'web3', label: 'Web3' },
  { value: 'campaign', label: 'Campaign' },
  { value: 'commerce', label: 'Commerce' },
  { value: 'agent', label: 'Agent' },
  { value: 'x402', label: 'x402' },
  { value: 'outcome', label: 'Outcome' },
];

interface Props {
  family: ActivityFamily | undefined;
  after: string;
  before: string;
  onFamilyChange: (f: ActivityFamily | undefined) => void;
  onAfterChange: (v: string) => void;
  onBeforeChange: (v: string) => void;
  onClear: () => void;
}

export const JourneyFilterBar: FC<Props> = ({
  family, after, before, onFamilyChange, onAfterChange, onBeforeChange, onClear,
}) => {
  const hasFilters = family !== undefined || after !== '' || before !== '';

  return (
    <div className="flex items-center gap-3 flex-wrap" role="search" aria-label="Journey filters">
      <div className="flex gap-1" role="group" aria-label="Activity family">
        {FAMILIES.map(f => (
          <button
            key={f.value}
            onClick={() => onFamilyChange(family === f.value ? undefined : f.value)}
            aria-pressed={family === f.value}
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
              family === f.value
                ? 'bg-accent text-white border-accent'
                : 'bg-surface-secondary border-border text-text-muted hover:text-text'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <label htmlFor="journey-after" className="text-xs text-text-muted">After</label>
        <input
          id="journey-after"
          type="date"
          value={after}
          onChange={e => onAfterChange(e.target.value)}
          className="text-xs bg-surface-secondary border border-border rounded px-2 py-1"
          aria-label="Filter steps after date"
        />
        <label htmlFor="journey-before" className="text-xs text-text-muted">Before</label>
        <input
          id="journey-before"
          type="date"
          value={before}
          onChange={e => onBeforeChange(e.target.value)}
          className="text-xs bg-surface-secondary border border-border rounded px-2 py-1"
          aria-label="Filter steps before date"
        />
      </div>

      {hasFilters && (
        <button
          onClick={onClear}
          className="text-xs text-text-muted hover:text-text underline focus-visible:outline-2 focus-visible:outline-accent rounded"
          aria-label="Clear all journey filters"
        >
          Clear
        </button>
      )}
    </div>
  );
};
