import { cn } from '../utils/cn';
import type { ReactNode } from 'react';
import { Icon, type IconName } from './icon';

interface EmptyStateProps {
  readonly title: string;
  readonly description?: string;
  readonly icon?: string;
  readonly action?: ReactNode;
  readonly className?: string;
}

const emptyStateIcons: Readonly<Record<string, IconName>> = {
  '✓': 'circle-check',
  '✔': 'circle-check',
  '⚠': 'triangle-alert',
  '✉': 'messages-square',
};

export function EmptyState({ title, description, icon, action, className }: EmptyStateProps) {
  const iconName = icon ? (emptyStateIcons[icon] ?? 'circle-help') : 'circle-help';
  return (
    <div className={cn('flex flex-col items-center justify-center py-12 text-center', className)}>
      <Icon name={iconName} size="xl" decorative className="mb-3 text-text-muted" />
      <div className="text-sm font-medium text-text-secondary">{title}</div>
      {description && <div className="text-xs text-text-muted mt-1 max-w-xs">{description}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
