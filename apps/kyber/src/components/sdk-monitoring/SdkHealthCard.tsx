import { Card, CardContent } from '@aether/ui';
import { AsciiStatusGlyph } from '@kyber/components/ascii';
import type { SDKHealthScore } from '@kyber/types/sdk-health';

interface SdkHealthCardProps {
  readonly score: SDKHealthScore;
  readonly className?: string;
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-400' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="w-24 text-text-muted shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-surface-subtle overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-text-secondary">{pct}%</span>
    </div>
  );
}

export function SdkHealthCard({ score, className }: SdkHealthCardProps) {
  const statusColor =
    score.status === 'healthy'
      ? 'text-green-400'
      : score.status === 'degraded'
      ? 'text-yellow-400'
      : 'text-red-400';

  return (
    <Card className={className}>
      <CardContent className="space-y-3 p-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AsciiStatusGlyph
              status={score.status as 'healthy' | 'degraded' | 'unhealthy' | 'unknown'}
              className="text-base"
            />
            <span className="text-xs font-mono text-text-secondary truncate max-w-[120px]">
              {score.sdk_id.slice(0, 12)}…
            </span>
          </div>
          <span className={`text-xl font-bold tabular-nums ${statusColor}`}>
            {score.composite.toFixed(0)}
          </span>
        </div>

        {/* Sub-score bars */}
        <div className="space-y-1.5">
          <ScoreBar label="Connectivity" value={score.connectivity} />
          <ScoreBar label="Throughput" value={score.throughput} />
          <ScoreBar label="Integrity" value={score.integrity} />
          <ScoreBar label="Auth/Consent" value={score.auth_consent} />
          <ScoreBar label="Freshness" value={score.freshness} />
        </div>

        {/* Footer */}
        <div className="text-[10px] text-text-muted pt-1 border-t border-border-subtle">
          Last heartbeat: {new Date(score.last_heartbeat_at).toLocaleTimeString()}
        </div>
      </CardContent>
    </Card>
  );
}
