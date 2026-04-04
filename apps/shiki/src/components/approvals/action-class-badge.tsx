import { Badge } from '@shiki/components/system';
import type { ActionClass } from '@shiki/types';

const CLASS_LABELS: Record<ActionClass, { label: string; variant: 'default' | 'success' | 'info' | 'warning' | 'danger' | 'accent' }> = {
  0: { label: 'C0 Read', variant: 'default' },
  1: { label: 'C1 Safe', variant: 'success' },
  2: { label: 'C2 Enrich', variant: 'info' },
  3: { label: 'C3 Ops', variant: 'warning' },
  4: { label: 'C4 Graph', variant: 'accent' },
  5: { label: 'C5 Critical', variant: 'danger' },
};

interface ActionClassBadgeProps {
  readonly actionClass: ActionClass;
  readonly className?: string;
}

export function ActionClassBadge({ actionClass, className }: ActionClassBadgeProps) {
  const { label, variant } = CLASS_LABELS[actionClass];
  return <Badge variant={variant} className={className}>{label}</Badge>;
}
