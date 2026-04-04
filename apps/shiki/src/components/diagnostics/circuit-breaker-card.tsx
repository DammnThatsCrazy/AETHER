import { Card, CardContent, Badge } from '@shiki/components/system';
import type { CircuitBreakerState } from '@shiki/types';
import { formatRelativeTime } from '@shiki/lib/utils';

const STATE_VARIANT: Record<string, 'success' | 'danger' | 'warning'> = {
  closed: 'success',
  open: 'danger',
  'half-open': 'warning',
};

interface CircuitBreakerCardProps {
  readonly breaker: CircuitBreakerState;
}

export function CircuitBreakerCard({ breaker }: CircuitBreakerCardProps) {
  return (
    <Card className="p-3">
      <CardContent>
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-text-primary">{breaker.name}</span>
          <Badge variant={STATE_VARIANT[breaker.state] ?? 'default'}>{breaker.state}</Badge>
        </div>
        <div className="space-y-1 text-[10px]">
          <div className="flex justify-between">
            <span className="text-text-muted">Failures</span>
            <span className="text-text-secondary">{breaker.failureCount}</span>
          </div>
          {breaker.lastFailure && (
            <div className="flex justify-between">
              <span className="text-text-muted">Last failure</span>
              <span className="text-text-secondary">{formatRelativeTime(breaker.lastFailure)}</span>
            </div>
          )}
          {breaker.nextRetry && (
            <div className="flex justify-between">
              <span className="text-text-muted">Next retry</span>
              <span className="text-text-secondary">{formatRelativeTime(breaker.nextRetry)}</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
