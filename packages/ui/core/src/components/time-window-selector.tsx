import { cn } from '../utils/cn';

export type TimeWindow = '30d' | '60d' | '90d' | 'lifetime';

const OPTIONS: { value: TimeWindow; label: string }[] = [
  { value: '30d', label: '30d' },
  { value: '60d', label: '60d' },
  { value: '90d', label: '90d' },
  { value: 'lifetime', label: 'All time' },
];

interface TimeWindowSelectorProps {
  value: TimeWindow;
  onChange: (window: TimeWindow) => void;
  className?: string;
}

export function TimeWindowSelector({ value, onChange, className }: TimeWindowSelectorProps) {
  return (
    <div className={cn('flex gap-1 font-mono text-xs', className)}>
      {OPTIONS.map(opt => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={cn(
            'px-2 py-0.5 rounded border transition-colors',
            value === opt.value
              ? 'bg-accent/20 text-accent border-accent/40'
              : 'text-text-muted border-transparent hover:text-text-secondary hover:border-border-default',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
