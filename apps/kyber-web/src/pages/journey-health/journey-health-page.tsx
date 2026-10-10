import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useJourneyHealth } from '@kyber/features/journey-health';

type Row = Record<string, unknown>;

function Metric({ label, value }: { readonly label: string; readonly value: unknown }) {
  return <Card><CardContent><div className="text-xs text-text-muted font-mono">{label}</div><div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? 0)}</div></CardContent></Card>;
}

export function JourneyHealthPage() {
  const { data, loading, error } = useJourneyHealth();
  if (loading) return <PageWrapper title="Journey Health"><LoadingState lines={8} /></PageWrapper>;
  if (error) return <PageWrapper title="Journey Health"><ErrorState title="Unable to load journey health" message={error} /></PageWrapper>;

  const overview = data.overview as Row;
  const sdkParity = data.sdkParity as Row;
  const platforms = Object.entries((sdkParity.platforms as Record<string, number> | undefined) ?? {}).map(([platform, count]) => ({ platform, count }));
  const confidence = overview.confidence_distribution as Record<string, number> | undefined ?? {};
  const dropped = (((data.droppedEvents as Row).items as Row[] | undefined) ?? []);

  return (
    <PageWrapper title="Journey Health" subtitle="Internal cross-tenant continuity, stitching confidence, SDK parity, and dropped-event diagnostics.">
      <div className="grid gap-4 md:grid-cols-4">
        <Metric label="Journey events" value={overview.journey_event_count} />
        <Metric label="Stitches" value={overview.stitches_created_total ?? overview.journey_count} />
        <Metric label="Handoffs" value={overview.handoff_count} />
        <Metric label="Low confidence" value={overview.low_confidence_count} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Confidence distribution</CardTitle></CardHeader>
          <CardContent className="flex gap-3">
            <Badge variant="success">High {confidence.high ?? 0}</Badge>
            <Badge variant="warning">Medium {confidence.medium ?? 0}</Badge>
            <Badge variant="danger">Low {confidence.low ?? 0}</Badge>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Safeguards</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm text-text-secondary">
            <div>Handoff success rate: {String(overview.handoff_success_rate ?? 0)}</div>
            <div>Over-link warnings: {String(overview.overlink_warnings ?? 0)}</div>
            <div>Ambiguous clusters: {String(overview.ambiguous_clusters ?? 0)}</div>
            <div>Schema drift warnings: {((overview.schema_drift_warnings as unknown[]) ?? []).length}</div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>SDK parity by platform</CardTitle></CardHeader>
          <CardContent>
            <DataTable data={platforms} keyExtractor={(r) => r.platform} columns={[
              { key: 'platform', header: 'Platform / SDK', render: r => r.platform },
              { key: 'count', header: 'Journey events', render: r => r.count },
            ]} emptyMessage="No SDK journey emissions yet" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Dropped journey events</CardTitle></CardHeader>
          <CardContent>
            {dropped.length === 0 ? <EmptyState title="No dropped journey events" description="No invalid journey lifecycle events have been recorded." /> : (
              <DataTable data={dropped} keyExtractor={(r) => String(r.id ?? r.event_id ?? r.reason ?? 'dropped')} columns={[
                { key: 'tenant', header: 'Tenant', render: r => String(r.tenant_id ?? '—') },
                { key: 'event', header: 'Event', render: r => String(r.event_type ?? '—') },
                { key: 'reason', header: 'Reason', render: r => String(r.reason ?? '—') },
              ]} />
            )}
          </CardContent>
        </Card>
      </div>
    </PageWrapper>
  );
}
