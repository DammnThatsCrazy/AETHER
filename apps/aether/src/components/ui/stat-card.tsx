import { cn } from '@aether/ui';
import type { ReactNode } from 'react';

interface StatCardProps {
  label: string;
  value: string | number;
  delta?: { value: string; positive: boolean };
  sub?: string;
  accent?: 'default' | 'success' | 'warning' | 'danger' | 'insight';
  icon?: string;
  mono?: boolean;
  className?: string;
  children?: ReactNode;
}

const accentColors = {
  default: 'text-text-primary',
  success: 'text-verdant',
  warning: 'text-amber',
  danger:  'text-ember',
  insight: 'text-solar',
};

export function StatCard({ label, value, delta, sub, accent = 'default', icon, mono = true, className, children }: StatCardProps) {
  return (
    <div className={cn('panel p-4 flex flex-col gap-2', className)}>
      <div className="flex items-center justify-between">
        <span className="label-eyebrow">{label}</span>
        {icon && <span className="font-mono text-text-muted text-sm">{icon}</span>}
      </div>
      <div className="flex items-baseline gap-2.5">
        <span className={cn(
          'text-2xl font-semibold tracking-tight tabular-nums',
          mono ? 'font-mono' : 'font-sans',
          accentColors[accent],
        )}>
          {value}
        </span>
        {delta && (
          <span className={cn('text-xs font-mono', delta.positive ? 'text-verdant' : 'text-ember')}>
            {delta.positive ? '+' : ''}{delta.value}
          </span>
        )}
      </div>
      {sub && <p className="text-xs text-text-muted">{sub}</p>}
      {children}
    </div>
  );
}
