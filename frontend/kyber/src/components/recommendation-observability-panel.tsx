import { Card, CardContent, CardHeader, Badge } from '@aether/ui';
import { useRecommendationObservability } from '@kyber/features/recommendation-observability';

const badgeVariant = { healthy: 'success', warning: 'warning', critical: 'danger' } as const;

export function RecommendationObservabilityPanel() {
  const { enabled, metrics, isLoading, error } = useRecommendationObservability();
  if (!enabled) return null;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-text-primary font-medium">Recommendation OODA observability</h2>
            <p className="text-xs text-text-secondary mt-1">Backend aggregate health only; tenant-private intelligence stays isolated.</p>
          </div>
          <Badge variant="info">Kyber</Badge>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? <p className="text-sm text-text-secondary">Loading backend observability…</p> : null}
        {error ? <p className="text-sm text-danger">Backend observability unavailable.</p> : null}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {metrics.map((metric) => (
            <div key={metric.label} className="rounded-lg border border-border-subtle p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-text-primary">{metric.label}</span>
                <Badge variant={badgeVariant[metric.status]}>{metric.status}</Badge>
              </div>
              <p className="mt-2 text-xs text-text-secondary">{metric.value}</p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
