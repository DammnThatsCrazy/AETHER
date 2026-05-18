import { cn } from '@aether/ui';

interface LiveIndicatorProps {
  label?: string;
  className?: string;
}

export function LiveIndicator({ label = 'Live', className }: LiveIndicatorProps) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-verdant text-xs font-medium', className)}>
      <span className="live-dot" />
      {label}
    </span>
  );
}

export function PulsingDot({ color = 'verdant', className }: { color?: string; className?: string }) {
  return (
    <span className={cn(
      'w-2 h-2 rounded-pill animate-pulse-live inline-block',
      color === 'verdant' && 'bg-verdant',
      color === 'amber'   && 'bg-amber',
      color === 'ember'   && 'bg-ember',
      className,
    )} />
  );
}
