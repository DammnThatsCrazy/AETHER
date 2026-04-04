import type { Severity } from '@shiki/types';
import { Badge } from './badge';

const severityVariantMap: Record<Severity, 'danger' | 'warning' | 'info' | 'accent' | 'default'> = {
  P0: 'danger',
  P1: 'warning',
  P2: 'info',
  P3: 'accent',
  info: 'default',
};

interface SeverityBadgeProps {
  readonly severity: Severity;
  readonly className?: string | undefined;
}

export function SeverityBadge({ severity, className }: SeverityBadgeProps) {
  return (
    <Badge variant={severityVariantMap[severity]} className={className}>
      {severity}
    </Badge>
  );
}
