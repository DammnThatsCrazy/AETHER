import { cn } from '@shiki/lib/utils';

interface StatusIndicatorProps {
  readonly status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  readonly label?: string;
  readonly size?: 'sm' | 'md';
  readonly className?: string;
}

const statusColors: Record<string, string> = {
  healthy: 'bg-success',
  degraded: 'bg-warning',
  unhealthy: 'bg-danger',
  unknown: 'bg-text-muted',
};

const statusGlyphs: Record<string, string> = {
  healthy: '\u25CF',
  degraded: '\u25B2',
  unhealthy: '\u25A0',
  unknown: '\u25CB',
};

export function StatusIndicator({ status, label, size = 'sm', className }: StatusIndicatorProps) {
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <span
        className={cn(
          'rounded-full inline-block',
          statusColors[status],
          size === 'sm' ? 'h-2 w-2' : 'h-3 w-3',
        )}
        aria-label={status}
      />
      {label && (
        <span className={cn('font-mono', size === 'sm' ? 'text-xs' : 'text-sm', 'text-text-secondary')}>
          {label ?? statusGlyphs[status]}
        </span>
      )}
    </span>
  );
}
