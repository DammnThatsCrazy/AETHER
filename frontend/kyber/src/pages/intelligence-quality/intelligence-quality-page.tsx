import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useIntelligenceQuality } from '@kyber/features/intelligence-quality';

type AnyRecord = Record<string, any>;

function statusVariant(status?: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'healthy') return 'success';
  if (status === 'watch' || status === 'degraded') return 'warning';
  if (status === 'critical') return 'danger';
  return 'default';
}

function severityVariant(sev?: string): 'success' | 'warning' | 'danger' | 'default' {
  if (sev === 'critical' || sev === 'high') return 'danger';
  if (sev === 'medium') return 'warning';
  return 'default';
}

function StatusBadge({ status }: { readonly status?: string }) {
  return <Badge variant={statusVariant(status)}>{status ?? 'unknown'}</Badge>;
}

function pct(v: unknown): string {
  return typeof v === 'number' ? `${Math.round(v * 100)}%` : '—';
}

function Metric({ label, value }: { readonly label: string; readonly value: unknown }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? '—')}</div>
      </CardContent>
    </Card>
  );
}

export function IntelligenceQualityPage() {
  const { data, loading, error } = useIntelligenceQuality();

  if (loading) return <PageWrapper title="Intelligence Quality"><LoadingState lines={8} /></PageWrapper>;
  if (error) {
    return (
      <PageWrapper title="Intelligence Quality">
        <ErrorState title="Unable to load intelligence quality data" message={error} />
      </PageWrapper>
    );
  }

  const { overview, tenants, driftEvents, contamination, recommendations, graph, identity } = data;
  const score = (overview.score ?? {}) as AnyRecord;
  const dimensions = (overview.dimensions ?? {}) as Record<string, AnyRecord>;

  return (
    <PageWrapper
      title="Intelligence Quality"
      subtitle="Aggregate data-quality, drift detection, and graph-intelligence reliability across all tenants. No raw tenant-private payloads are shown."
    >
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="tenants">Tenants</TabsTrigger>
          <TabsTrigger value="drift">Drift Events</TabsTrigger>
          <TabsTrigger value="contamination">Contamination</TabsTrigger>
          <TabsTrigger value="dimensions">Dimensions</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid gap-3 md:grid-cols-4">
            <Metric label="Overall quality" value={pct(score.overall_intelligence_quality_score)} />
            <Metric label="Status" value={score.status} />
            <Metric label="Open drift events" value={overview.open_drift_event_count} />
            <Metric label="Tenants tracked" value={tenants.length} />
          </div>
        </TabsContent>

        <TabsContent value="tenants">
          <Card>
            <CardHeader><CardTitle>Per-tenant intelligence quality (aggregate)</CardTitle></CardHeader>
            <CardContent>
              <DataTable
                data={tenants}
                keyExtractor={(r) => r.tenant_id}
                columns={[
                  { key: 'tenant', header: 'Tenant', render: (r) => r.tenant_id },
                  { key: 'score', header: 'Overall quality', render: (r) => pct(r.overall_intelligence_quality_score) },
                  { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
                ]}
                emptyMessage="No tenants tracked"
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="drift">
          <Card>
            <CardHeader><CardTitle>Drift Events</CardTitle></CardHeader>
            <CardContent>
              <DataTable
                data={driftEvents}
                keyExtractor={(r) => r.drift_event_id}
                columns={[
                  { key: 'type', header: 'Type', render: (r) => r.drift_type },
                  { key: 'severity', header: 'Severity', render: (r) => <Badge variant={severityVariant(r.severity)}>{r.severity}</Badge> },
                  { key: 'reason', header: 'Reason', render: (r) => r.reason },
                  { key: 'status', header: 'Status', render: (r) => <Badge>{r.status}</Badge> },
                ]}
                emptyMessage="No drift events"
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="contamination">
          <Card>
            <CardHeader><CardTitle>Tenant Data Contamination</CardTitle></CardHeader>
            <CardContent className="text-xs font-mono grid gap-1 md:grid-cols-2">
              <div>Contamination score: {pct((contamination.report ?? {}).contamination_score)}</div>
              <div className="flex items-center gap-2">Status: <StatusBadge status={(contamination.report ?? {}).status} /></div>
              <div>Records missing tenant_id: {(contamination.report ?? {}).records_missing_tenant_id ?? '—'}</div>
              <div>Cross-tenant identifiers: {(contamination.report ?? {}).cross_tenant_identifiers ?? '—'}</div>
              <div className="md:col-span-2 text-text-muted">
                Critical contamination signals escalate into Security &amp; Governance audit. Escalated events: {(contamination.drift_events ?? []).length}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="dimensions">
          <div className="grid gap-3 md:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Quality by dimension</CardTitle></CardHeader>
              <CardContent>
                {Object.keys(dimensions).length === 0 ? <EmptyState title="No dimensions" /> : (
                  <div className="grid gap-1 text-xs">
                    {Object.entries(dimensions).map(([field, d]) => (
                      <div key={field} className="flex items-center justify-between rounded border border-border-default px-2 py-1">
                        <span className="font-mono">{field}</span>
                        <span className="flex items-center gap-2">{pct(d.score)} <StatusBadge status={d.status} /></span>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Detail</CardTitle></CardHeader>
              <CardContent className="text-xs font-mono space-y-1">
                <div>Recommendation success rate: {pct(recommendations.success_rate)}</div>
                <div>Graph orphaned vertices: {graph.orphaned_vertices ?? '—'}</div>
                <div>Identity unresolved rate: {pct(identity.unresolved_entity_rate)}</div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
