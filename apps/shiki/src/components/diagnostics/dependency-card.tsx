import { Card, CardContent, StatusIndicator, Badge } from '@shiki/components/system';
import type { DependencyHealth } from '@shiki/types';
import { formatDuration } from '@shiki/lib/utils';

interface DependencyCardProps {
  readonly dependency: DependencyHealth;
}

export function DependencyCard({ dependency }: DependencyCardProps) {
  return (
    <Card className="p-3">
      <CardContent>
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-text-primary">{dependency.name}</span>
          <StatusIndicator status={dependency.status.status} size="sm" />
        </div>
        <div className="space-y-1 text-[10px]">
          <div className="flex justify-between">
            <span className="text-text-muted">Type</span>
            <Badge>{dependency.type}</Badge>
          </div>
          <div className="flex justify-between">
            <span className="text-text-muted">Latency</span>
            <span className="text-text-secondary">{formatDuration(dependency.latencyMs)}</span>
          </div>
          {dependency.lastError && (
            <div className="text-danger text-[10px] mt-1 truncate">{dependency.lastError}</div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
