import { Card, CardContent, Badge, useTimeContext, useNow, formatRelative } from '@aether/ui';
import type { CircuitBreakerState } from '@kyber/types';

const STATE_VARIANT: Record<string, 'success' | 'danger' | 'warning'> = {
  closed: 'success',
  open: 'danger',
  'half-open': 'warning',
};

interface CircuitBreakerCardProps {
  readonly breaker: CircuitBreakerState;
}

export function CircuitBreakerCard({ breaker }: CircuitBreakerCardProps) {
  const timeCtx = useTimeContext();
  const now = useNow();
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
              <span className="text-text-secondary">{formatRelative(breaker.lastFailure, timeCtx, now)}</span>
            </div>
          )}
          {breaker.nextRetry && (
            <div className="flex justify-between">
              <span className="text-text-muted">Next retry</span>
              <span className="text-text-secondary">{formatRelative(breaker.nextRetry, timeCtx, now)}</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
