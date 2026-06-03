import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

type AnyRecord = Record<string, any>;

const STATUS_VARIANT: Record<string, 'success' | 'warning' | 'danger' | 'default'> = {
  healthy: 'success',
  watch: 'warning',
  degraded: 'warning',
  critical: 'danger',
  unknown: 'default',
};

function statusBadge(status?: string) {
  return <Badge variant={STATUS_VARIANT[status ?? 'unknown'] ?? 'default'}>{status ?? 'unknown'}</Badge>;
}

function pct(value: unknown): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '—';
}

const DIMENSION_LABELS: Record<string, string> = {
  event_quality_score: 'Event quality',
  schema_stability_score: 'Schema stability',
  identity_resolution_score: 'Identity resolution',
  graph_quality_score: 'Graph quality',
  profile_quality_score: 'Profile 360',
  recommendation_quality_score: 'Recommendation quality',
  outcome_feedback_quality_score: 'Outcome feedback',
  playbook_quality_score: 'Playbook quality',
};

export function DataQualityPage() {
  const [data, setData] = useState<AnyRecord>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.dataQuality.overview(),
      api.dataQuality.events(),
      api.dataQuality.recommendations(),
      api.dataQuality.graph(),
    ])
      .then(([overview, events, recommendations, graph]) =>
        setData({ overview, events, recommendations, graph }))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <main className="p-6"><LoadingState lines={6} /></main>;
  if (error) return <main className="p-6"><EmptyState title="Data Quality error" description={error} /></main>;

  const score = (data.overview?.score ?? {}) as AnyRecord;
  const dimensions = (data.overview?.dimensions ?? {}) as Record<string, AnyRecord>;
  const openDrift = data.overview?.open_drift_event_count ?? 0;
  const events = (data.events ?? {}) as AnyRecord;
  const recommendations = (data.recommendations ?? {}) as AnyRecord;
  const graph = (data.graph ?? {}) as AnyRecord;

  return (
    <main className="p-6 space-y-4">
      <div>
        <h1 className="text-xl font-mono font-bold">Data Quality</h1>
        <p className="text-sm text-text-secondary">
          Intelligence quality, drift, and data health for your tenant — across events, schema,
          identity resolution, the graph, Profile 360, recommendations, outcomes, and playbooks.
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Overall intelligence quality</CardTitle></CardHeader>
        <CardContent>
          {Object.keys(score).length === 0 ? <EmptyState title="No quality score yet" /> : (
            <div className="flex items-center gap-4">
              <div className="text-2xl font-semibold text-text-primary">{pct(score.overall_intelligence_quality_score)}</div>
              {statusBadge(score.status)}
              <div className="text-xs text-text-muted">Open drift events: {openDrift}</div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Quality by dimension</CardTitle></CardHeader>
        <CardContent>
          {Object.keys(dimensions).length === 0 ? <EmptyState title="No dimensions" /> : (
            <div className="grid gap-2 md:grid-cols-2 text-xs">
              {Object.entries(dimensions).map(([field, d]) => (
                <div key={field} className="flex items-center justify-between rounded border border-border-default px-2 py-1">
                  <span className="font-mono">{DIMENSION_LABELS[field] ?? field}</span>
                  <span className="flex items-center gap-2">{pct(d.score)} {statusBadge(d.status)}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Event quality detail</CardTitle></CardHeader>
        <CardContent className="text-xs font-mono grid gap-1 md:grid-cols-2">
          <div>Volume: {events.event_volume ?? '—'}</div>
          <div>Validation failure rate: {pct(events.schema_validation_failure_rate)}</div>
          <div>Duplicate events: {events.duplicate_event_count ?? '—'}</div>
          <div>Late arriving: {events.late_arriving_event_count ?? '—'}</div>
          <div className="flex items-center gap-2">Status: {statusBadge(events.status)}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Recommendation quality detail</CardTitle></CardHeader>
        <CardContent className="text-xs font-mono grid gap-1 md:grid-cols-2">
          <div>Success rate: {pct(recommendations.success_rate)}</div>
          <div>Low-confidence rate: {pct(recommendations.low_confidence_recommendation_rate)}</div>
          <div>Suppression rate: {pct(recommendations.suppression_rate)}</div>
          <div className="flex items-center gap-2">Status: {statusBadge(recommendations.status)}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Graph quality detail</CardTitle></CardHeader>
        <CardContent className="text-xs font-mono grid gap-1 md:grid-cols-2">
          <div>Orphaned vertices: {graph.orphaned_vertices ?? '—'}</div>
          <div>Dangling edges: {graph.dangling_edges ?? '—'}</div>
          <div>Missing expected edges: {graph.missing_expected_edges ?? '—'}</div>
          <div className="flex items-center gap-2">Status: {statusBadge(graph.status)}</div>
        </CardContent>
      </Card>
    </main>
  );
}
