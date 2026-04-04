import { cn } from '@shiki/lib/utils';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  readonly size?: 'sm' | 'md' | 'lg';
  readonly children: ReactNode;
}

const variantStyles: Record<string, string> = {
  primary: 'bg-accent text-text-inverse hover:bg-accent-hover',
  secondary: 'bg-surface-raised text-text-primary border border-border-default hover:border-accent/50',
  danger: 'bg-danger/20 text-danger border border-danger/30 hover:bg-danger/30',
  ghost: 'text-text-secondary hover:text-text-primary hover:bg-surface-raised',
};

const sizeStyles: Record<string, string> = {
  sm: 'px-2 py-1 text-xs',
  md: 'px-3 py-1.5 text-sm',
  lg: 'px-4 py-2 text-base',
};

export function Button({ variant = 'primary', size = 'md', className, children, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus disabled:opacity-50 disabled:pointer-events-none',
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
