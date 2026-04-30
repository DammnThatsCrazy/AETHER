import { StatusIndicator, Card, CardContent } from '@kyber/components/system';
import { AsciiStatusGlyph } from '@kyber/components/ascii';
import type { HealthStatus } from '@kyber/types';

interface HealthSummaryProps {
  readonly health: HealthStatus;
  readonly label: string;
  readonly className?: string;
}

export function HealthSummary({ health, label, className }: HealthSummaryProps) {
  return (
    <Card className={className}>
      <CardContent>
        <div className="flex items-center gap-3">
          <AsciiStatusGlyph status={health.status} className="text-lg" />
          <div>
            <div className="text-xs font-medium text-text-primary">{label}</div>
            <StatusIndicator status={health.status} label={health.status.toUpperCase()} size="sm" />
            {health.message && <div className="text-[10px] text-text-muted mt-0.5">{health.message}</div>}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
