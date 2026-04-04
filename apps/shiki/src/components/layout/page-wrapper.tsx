import type { ReactNode } from 'react';
import { cn } from '@shiki/lib/utils';

interface PageWrapperProps {
  readonly title: string;
  readonly subtitle?: string;
  readonly children: ReactNode;
  readonly actions?: ReactNode;
  readonly className?: string;
}

export function PageWrapper({ title, subtitle, children, actions, className }: PageWrapperProps) {
  return (
    <div className={cn('space-y-4', className)}>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-text-primary font-mono">{title}</h1>
          {subtitle && <p className="text-xs text-text-secondary mt-0.5">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}
