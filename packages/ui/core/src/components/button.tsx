import { cloneElement, isValidElement, type ButtonHTMLAttributes, type ReactElement, type ReactNode } from 'react';

import { cn } from '../utils/cn';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  readonly size?: 'sm' | 'md' | 'lg';
  /**
   * Render the button styling onto a single child element (a router `Link` or
   * an anchor) instead of a `<button>`. Used by public marketing CTAs so the
   * interactive surface is a real link while sharing the exact button grammar.
   */
  readonly asChild?: boolean;
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

const buttonClass = (variant: ButtonProps['variant'], size: ButtonProps['size'], className: string | undefined) =>
  cn(
    'inline-flex items-center justify-center rounded-md font-medium aether-motion-interactive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus disabled:opacity-50 disabled:pointer-events-none',
    variantStyles[variant ?? 'primary'],
    sizeStyles[size ?? 'md'],
    className,
  );

export function Button({
  variant = 'primary',
  size = 'md',
  asChild = false,
  className,
  children,
  ...props
}: ButtonProps) {
  if (asChild) {
    const child = isValidElement<{ className?: string }>(children) ? (children as ReactElement<{ className?: string }>) : undefined;
    if (child === undefined) {
      throw new Error('Button with asChild requires exactly one child element.');
    }
    return cloneElement(child, { className: buttonClass(variant, size, cn(child.props.className, className)) });
  }

  return (
    <button className={buttonClass(variant, size, className)} {...props}>
      {children}
    </button>
  );
}
