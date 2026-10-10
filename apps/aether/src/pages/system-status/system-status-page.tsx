import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

type Row = Record<string, any>;

function statusVariant(status?: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'healthy' || status === 'operational' || status === 'fresh') return 'success';
  if (status === 'degraded' || status === 'delayed') return 'warning';
  if (status === 'critical' || status === 'offline' || status === 'stale') return 'danger';
  return 'default';
}

function StatusRow({ label, value }: { readonly label: string; readonly value?: string }) {
  return (
    <div className="flex items-center justify-between border-b border-border-default py-2 last:border-0">
      <span className="text-sm text-text-secondary">{label}</span>
      <Badge variant={statusVariant(value)}>{value ?? 'unknown'}</Badge>
    </div>
  );
}

function IncidentCard({ incident }: { readonly incident: Row }) {
  return (
    <div className="rounded border border-border-default p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-text-primary">{incident.title}</span>
        <Badge variant={statusVariant(incident.status)}>{incident.status}</Badge>
      </div>
      {incident.customer_impact && <p className="mt-1 text-xs text-text-secondary">{incident.customer_impact}</p>}
      <div className="mt-1 text-xs text-text-muted">
        {incident.started_at ?? '—'}{incident.resolved_at ? ` → resolved ${incident.resolved_at}` : ''}
      </div>
    </div>
  );
}

export function SystemStatusPage() {
  const [overview, setOverview] = useState<Row | null>(null);
  const [incidents, setIncidents] = useState<Row>({ active: [], resolved: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.status.overview(), api.status.incidents()])
      .then(([o, i]) => {
        setOverview(o as Row);
        setIncidents((i as Row) ?? { active: [], resolved: [] });
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-6"><LoadingState lines={6} /></div>;
  if (error) return <div className="p-6"><ErrorState title="Unable to load system status" message={error} /></div>;

  const active = (incidents.active ?? []) as Row[];
  const resolved = (incidents.resolved ?? []) as Row[];

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-xl font-bold text-text-primary font-mono">System Status</h1>
        <p className="text-sm text-text-secondary">
          Current status of your Aether services and data. Shows only your own
          workspace — no internal infrastructure details.
        </p>
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-text-secondary">Overall status</span>
            <Badge variant={statusVariant(overview?.overall_status)}>{overview?.overall_status ?? 'unknown'}</Badge>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Service &amp; Data Health</CardTitle></CardHeader>
          <CardContent>
            <StatusRow label="Data freshness" value={overview?.data_freshness} />
            <StatusRow label="Recommendation freshness" value={overview?.recommendation_status} />
            <StatusRow label="Outcome capture" value={overview?.outcome_capture_status} />
            <StatusRow label="Integration status" value={overview?.integration_status} />
            <StatusRow label="Audit export status" value={overview?.audit_export_status} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Active Incidents ({active.length})</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {active.length ? active.map((i) => <IncidentCard key={i.incident_id} incident={i} />) : (
              <EmptyState title="No active incidents" description="All systems affecting your workspace are operating normally." />
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Recently Resolved Incidents ({resolved.length})</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {resolved.length ? resolved.map((i) => <IncidentCard key={i.incident_id} incident={i} />) : (
            <div className="text-sm text-text-muted">No recently resolved incidents.</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
