import { cn } from '@aether/ui';
import type { ReactNode } from 'react';

interface PanelHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  eyebrow?: string;
  className?: string;
}

export function PanelHeader({ title, subtitle, actions, eyebrow, className }: PanelHeaderProps) {
  return (
    <div className={cn('panel-header', className)}>
      <div>
        {eyebrow && <p className="label-eyebrow mb-1">{eyebrow}</p>}
        <h3 className="panel-title">{title}</h3>
        {subtitle && <p className="text-xs text-text-muted mt-0.5">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 flex-shrink-0">{actions}</div>}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  eyebrow,
  className,
}: PanelHeaderProps) {
  return (
    <div className={cn('flex items-start justify-between gap-4 mb-5', className)}>
      <div>
        {eyebrow && <p className="label-eyebrow mb-1.5">{eyebrow}</p>}
        <h1 className="text-xl font-semibold tracking-tight text-text-primary">{title}</h1>
        {subtitle && <p className="text-sm text-text-secondary mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 flex-shrink-0 pt-0.5">{actions}</div>}
    </div>
  );
}
