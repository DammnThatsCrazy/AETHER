import { useId } from 'react';
import { cn } from '../utils/cn';
import type { InputHTMLAttributes } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  readonly label?: string;
}

export function Input({ label, className, id, ...props }: InputProps) {
  // Associate the visible label with the control so it names the field.
  const generatedId = useId();
  const inputId = id ?? generatedId;
  return (
    <div className="flex flex-col gap-1">
      {label && <label htmlFor={inputId} className="text-xs text-text-secondary">{label}</label>}
      <input
        id={inputId}
        className={cn(
          'bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted',
          className,
        )}
        {...props}
      />
    </div>
  );
}
