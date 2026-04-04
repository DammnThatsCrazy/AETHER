import { cn } from '@shiki/lib/utils';
import type { ReactNode } from 'react';

interface ToggleProps {
  readonly checked?: boolean | undefined;
  readonly pressed?: boolean | undefined;
  readonly onChange?: ((checked: boolean) => void) | undefined;
  readonly onPressedChange?: (() => void) | undefined;
  readonly label?: string | undefined;
  readonly children?: ReactNode | undefined;
  readonly disabled?: boolean | undefined;
  readonly size?: string | undefined;
  readonly className?: string | undefined;
}

export function Toggle({ checked, pressed, onChange, onPressedChange, label, children, disabled, size, className }: ToggleProps) {
  const isActive = pressed ?? checked ?? false;

  // If used as a pressable toggle button (with children)
  if (children !== undefined) {
    return (
      <button
        type="button"
        role="switch"
        aria-checked={isActive}
        disabled={disabled}
        onClick={() => {
          onPressedChange?.();
          onChange?.(!isActive);
        }}
        className={cn(
          'px-2 py-1 rounded text-xs font-mono border transition-colors',
          size === 'sm' && 'px-1.5 py-0.5 text-[10px]',
          isActive
            ? 'bg-accent/20 text-accent border-accent/30'
            : 'bg-surface-raised text-text-secondary border-border-subtle hover:text-text-primary',
          disabled && 'opacity-50 cursor-not-allowed',
          className,
        )}
      >
        {children}
      </button>
    );
  }

  // Switch-style toggle
  return (
    <label className={cn('inline-flex items-center gap-2 cursor-pointer', disabled && 'opacity-50 cursor-not-allowed', className)}>
      <button
        role="switch"
        aria-checked={isActive}
        disabled={disabled}
        onClick={() => {
          onChange?.(!isActive);
          onPressedChange?.();
        }}
        className={cn(
          'relative w-8 h-4 rounded-full transition-colors',
          isActive ? 'bg-accent' : 'bg-border-default',
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-text-primary transition-transform',
            isActive && 'translate-x-4',
          )}
        />
      </button>
      {label && <span className="text-xs text-text-secondary">{label}</span>}
    </label>
  );
}
