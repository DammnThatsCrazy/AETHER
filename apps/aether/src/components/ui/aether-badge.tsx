import { cn } from '@aether/ui';

type Variant = 'default' | 'info' | 'success' | 'warning' | 'danger' | 'insight' | 'accent';
type Shape = 'pill' | 'square';
type Size = 'sm' | 'md';

interface AetherBadgeProps {
  variant?: Variant;
  shape?: Shape;
  size?: Size;
  mono?: boolean;
  children: React.ReactNode;
  className?: string;
}

const variantStyles: Record<Variant, string> = {
  default:  'bg-surface-overlay text-text-secondary border-border-default',
  info:     'bg-accent/10 text-steel border border-accent/25',
  success:  'bg-verdant/10 text-verdant border-verdant/25',
  warning:  'bg-amber/10 text-amber border-amber/25',
  danger:   'bg-ember/10 text-ember border-ember/25',
  insight:  'bg-solar/10 text-solar border-solar/25',
  accent:   'bg-signal/10 text-signal border-signal/25',
};

const sizeStyles: Record<Size, string> = {
  sm: 'px-1.5 py-px text-2xs',
  md: 'px-2 py-0.5 text-xs',
};

export function AetherBadge({
  variant = 'default',
  shape = 'pill',
  size = 'sm',
  mono = false,
  children,
  className,
}: AetherBadgeProps) {
  return (
    <span
      className={cn(
        'badge-base font-medium border',
        variantStyles[variant],
        sizeStyles[size],
        shape === 'pill' ? 'rounded-pill' : 'rounded',
        mono && 'font-mono',
        className,
      )}
    >
      {children}
    </span>
  );
}
