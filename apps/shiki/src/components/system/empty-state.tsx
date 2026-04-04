import { cn } from '@shiki/lib/utils';
import type { ReactNode } from 'react';

interface EmptyStateProps {
  readonly title: string;
  readonly description?: string;
  readonly icon?: string;
  readonly action?: ReactNode;
  readonly className?: string;
}

export function EmptyState({ title, description, icon = '\u2205', action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center py-12 text-center', className)}>
      <div className="text-3xl text-text-muted mb-3 font-mono">{icon}</div>
      <div className="text-sm font-medium text-text-secondary">{title}</div>
      {description && <div className="text-xs text-text-muted mt-1 max-w-xs">{description}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
