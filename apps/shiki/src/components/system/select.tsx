import { cn } from '@shiki/lib/utils';
import type { SelectHTMLAttributes } from 'react';

interface SelectOption {
  readonly value: string;
  readonly label: string;
}

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange'> {
  readonly options: readonly SelectOption[];
  readonly onChange: (value: string) => void;
  readonly label?: string;
}

export function Select({ options, onChange, label, className, value, ...props }: SelectProps) {
  return (
    <div className="inline-flex flex-col gap-1">
      {label && <label className="text-xs text-text-secondary">{label}</label>}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          'bg-surface-raised text-text-primary border border-border-default rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-border-focus',
          className,
        )}
        {...props}
      >
        {options.map(opt => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  );
}
