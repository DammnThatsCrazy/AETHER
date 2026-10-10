import { useState } from 'react';
import { useParams } from 'react-router-dom';
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
import { useReliability } from '@kyber/features/reliability';

type AnyRecord = Record<string, any>;

function statusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'healthy' || status === 'meeting' || status === 'operational') return 'success';
  if (status === 'degraded' || status === 'at_risk' || status === 'delayed') return 'warning';
  if (status === 'critical' || status === 'offline' || status === 'breached') return 'danger';
  return 'default';
}

function StatusBadge({ status }: { readonly status?: string }) {
  const s = status ?? 'unknown';
  return <Badge variant={statusVariant(s)}>{s}</Badge>;
}

function Metric({ label, value }: { readonly label: string; readonly value: unknown }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? 0)}</div>
      </CardContent>
    </Card>
  );
}

const INCIDENT_LANES: { readonly key: string; readonly label: string }[] = [
  { key: 'open', label: 'Open' },
  { key: 'investigating', label: 'Investigating' },
  { key: 'mitigating', label: 'Mitigating' },
  { key: 'resolved', label: 'Resolved' },
  { key: 'postmortem_pending', label: 'Postmortem Pending' },
  { key: 'closed', label: 'Closed' },
];

export function ReliabilityPage() {
  const { incidentId } = useParams<{ incidentId?: string }>();
  const { data, loading, error } = useReliability();
  const [selectedIncident, setSelectedIncident] = useState<AnyRecord | null>(null);

  if (loading) return <PageWrapper title="Reliability Command Center"><LoadingState lines={8} /></PageWrapper>;
  if (error) {
    return (
      <PageWrapper title="Reliability Command Center">
        <ErrorState title="Unable to load reliability data" message={error} />
      </PageWrapper>
    );
  }

  const { overview, services, pipelines, queues, slos, incidents, runbooks, postmortems } = data;
  const summary = overview.service_health_summary ?? {};
  const sloStatus = overview.slo_status ?? {};

  // Honor a deep link (/reliability/incidents/:incidentId) when present, then a
  // clicked selection, then fall back to the first incident.
  const routedIncident = incidentId ? incidents.find((i) => i.incident_id === incidentId) ?? null : null;
  const detail = selectedIncident ?? routedIncident ?? incidents[0] ?? null;

  return (
    <PageWrapper
      title="Reliability Command Center"
      subtitle="Internal view of Aether services, pipelines, queues, incidents, SLOs, runbooks, and tenant impact."
    >
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="services">Services</TabsTrigger>
          <TabsTrigger value="pipelines">Pipelines</TabsTrigger>
          <TabsTrigger value="queues">Queues</TabsTrigger>
          <TabsTrigger value="incidents">Incidents</TabsTrigger>
          <TabsTrigger value="runbooks">Runbooks</TabsTrigger>
          <TabsTrigger value="slos">SLOs</TabsTrigger>
        </TabsList>

        {/* 1. Reliability Overview */}
        <TabsContent value="overview">
          <div className="grid gap-3 md:grid-cols-4">
            <Metric label="Overall status" value={overview.overall_status} />
            <Metric label="Healthy services" value={summary.healthy} />
            <Metric label="Open incidents" value={overview.open_incident_count} />
            <Metric label="Degraded pipelines" value={overview.degraded_pipeline_count} />
            <Metric label="Queue backlogs" value={overview.queue_backlog_count} />
            <Metric label="SLOs meeting" value={sloStatus.meeting} />
            <Metric label="SLOs at risk" value={sloStatus.at_risk} />
            <Metric label="Impacted tenants" value={overview.tenant_impact?.impacted_tenant_count} />
          </div>
          <Card>
            <CardHeader><CardTitle>Error Budget Status</CardTitle></CardHeader>
            <CardContent>
              <DataTable
                data={(overview.error_budget_status ?? []) as AnyRecord[]}
                keyExtractor={(r) => r.slo_id}
                columns={[
                  { key: 'slo', header: 'SLO', render: (r) => r.slo_id },
                  { key: 'service', header: 'Service', render: (r) => r.service_key },
                  { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
                  { key: 'budget', header: 'Budget remaining', render: (r) => r.error_budget_remaining ?? '—' },
                ]}
                emptyMessage="All SLOs within budget"
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* 2. Service Health Dashboard */}
        <TabsContent value="services">
          <Card>
            <CardHeader><CardTitle>Service Health</CardTitle></CardHeader>
            <CardContent>
              <DataTable
                data={services}
                keyExtractor={(r) => r.service_key}
                columns={[
                  { key: 'service', header: 'Service', render: (r) => r.label ?? r.service_key },
                  { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
                  { key: 'latency', header: 'Latency (ms)', render: (r) => r.latency_ms ?? '—' },
                  { key: 'error', header: 'Error rate', render: (r) => r.error_rate ?? '—' },
                  { key: 'heartbeat', header: 'Last heartbeat', render: (r) => r.last_heartbeat_at ?? '—' },
                  { key: 'job', header: 'Last successful job', render: (r) => r.last_successful_job_at ?? '—' },
                  { key: 'tenants', header: 'Tenant impact', render: (r) => r.affected_tenant_count ?? 0 },
                  { key: 'incidents', header: 'Open incidents', render: (r) => (r.open_incident_ids ?? []).length },
                ]}
                emptyMessage="No services registered"
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* 3. Pipeline Health Dashboard */}
        <TabsContent value="pipelines">
          <Card>
            <CardHeader><CardTitle>Pipeline Health</CardTitle></CardHeader>
            <CardContent>
              <DataTable
                data={pipelines}
                keyExtractor={(r) => r.pipeline_key}
                columns={[
                  { key: 'pipeline', header: 'Pipeline', render: (r) => r.label ?? r.pipeline_key },
                  { key: 'source', header: 'Source', render: (r) => r.source },
                  { key: 'destination', header: 'Destination', render: (r) => r.destination },
                  { key: 'throughput', header: 'Throughput/min', render: (r) => r.throughput_per_minute ?? '—' },
                  { key: 'latency', header: 'Latency (ms)', render: (r) => r.latency_ms ?? '—' },
                  { key: 'error', header: 'Error rate', render: (r) => r.error_rate ?? '—' },
                  { key: 'retry', header: 'Retries', render: (r) => r.retry_count ?? '—' },
                  { key: 'dlq', header: 'Dead-letter', render: (r) => r.dead_letter_count ?? '—' },
                  { key: 'freshness', header: 'Freshness (s)', render: (r) => r.freshness_seconds ?? '—' },
                  { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
                ]}
                emptyMessage="No pipelines registered"
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* 4. Queue/Worker Health Dashboard */}
        <TabsContent value="queues">
          <Card>
            <CardHeader><CardTitle>Queue &amp; Worker Health</CardTitle></CardHeader>
            <CardContent>
              <DataTable
                data={queues}
                keyExtractor={(r) => r.queue_key}
                columns={[
                  { key: 'queue', header: 'Queue', render: (r) => r.label ?? r.queue_key },
                  { key: 'depth', header: 'Depth', render: (r) => r.depth ?? 0 },
                  { key: 'age', header: 'Oldest msg (s)', render: (r) => r.oldest_message_age_seconds ?? '—' },
                  { key: 'workers', header: 'Workers', render: (r) => `${r.active_worker_count ?? '—'} / ${r.worker_count ?? '—'}` },
                  { key: 'retry', header: 'Retries', render: (r) => r.retry_count ?? '—' },
                  { key: 'dlq', header: 'Dead-letter', render: (r) => r.dead_letter_count ?? '—' },
                  { key: 'latency', header: 'Processing (ms)', render: (r) => r.processing_latency_ms ?? '—' },
                  { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
                ]}
                emptyMessage="No queues registered"
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* 5. Incident Board + 6. Incident Detail */}
        <TabsContent value="incidents">
          <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6 mb-4">
            {INCIDENT_LANES.map((lane) => {
              const laneItems = incidents.filter((i) => i.status === lane.key);
              return (
                <Card key={lane.key}>
                  <CardHeader><CardTitle className="text-xs">{lane.label} ({laneItems.length})</CardTitle></CardHeader>
                  <CardContent className="space-y-2">
                    {laneItems.length === 0 ? (
                      <div className="text-xs text-text-muted">None</div>
                    ) : (
                      laneItems.map((i) => (
                        <button
                          key={i.incident_id}
                          onClick={() => setSelectedIncident(i)}
                          className="block w-full rounded border border-border-default p-2 text-left text-xs hover:border-accent"
                        >
                          <div className="font-medium text-text-primary">{i.title}</div>
                          <Badge variant={statusVariant(i.severity === 'sev1' ? 'critical' : i.severity === 'sev2' ? 'degraded' : 'default')}>{i.severity}</Badge>
                        </button>
                      ))
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {detail ? (
            <Card>
              <CardHeader><CardTitle>Incident Detail — {detail.title}</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex gap-2"><Badge>{detail.severity}</Badge><StatusBadge status={detail.status} /></div>
                <div><span className="text-text-muted">Affected services: </span>{(detail.affected_services ?? []).join(', ') || '—'}</div>
                <div><span className="text-text-muted">Affected tenants: </span>{(detail.affected_tenants ?? []).join(', ') || '—'}</div>
                <div><span className="text-text-muted">Runbook: </span>{detail.runbook_id ?? '—'}</div>
                <div><span className="text-text-muted">Customer impact: </span>{detail.customer_impact ?? '—'}</div>
                <div><span className="text-text-muted">Mitigation steps:</span>
                  <ul className="ml-4 list-disc">{(detail.mitigation_steps ?? []).map((s: string, idx: number) => <li key={idx}>{s}</li>)}</ul>
                </div>
                <div><span className="text-text-muted">Timeline: </span>started {detail.started_at ?? '—'}{detail.resolved_at ? `, resolved ${detail.resolved_at}` : ''}</div>
                <div><span className="text-text-muted">Postmortem: </span>{postmortems.find((p) => p.incident_id === detail.incident_id)?.postmortem_id ?? 'none'}</div>
              </CardContent>
            </Card>
          ) : (
            <EmptyState title="No incidents" description="There are no incidents to display." />
          )}
        </TabsContent>

        {/* 7. Runbook Library */}
        <TabsContent value="runbooks">
          <div className="grid gap-3 lg:grid-cols-2">
            {runbooks.length === 0 ? (
              <EmptyState title="No runbooks" description="No operational runbooks defined." />
            ) : (
              runbooks.map((rb) => (
                <Card key={rb.runbook_id}>
                  <CardHeader><CardTitle>{rb.title} <Badge>{rb.severity_hint}</Badge></CardTitle></CardHeader>
                  <CardContent className="space-y-1 text-xs">
                    <div><span className="text-text-muted">Incident type: </span>{rb.incident_type}</div>
                    <div><span className="text-text-muted">Detection signals: </span>{(rb.detection_signals ?? []).join('; ')}</div>
                    <div><span className="text-text-muted">Diagnostic steps: </span>{(rb.diagnostic_steps ?? []).join('; ')}</div>
                    <div><span className="text-text-muted">Mitigation steps: </span>{(rb.mitigation_steps ?? []).join('; ')}</div>
                    <div><span className="text-text-muted">Escalation: </span>{(rb.escalation_paths ?? []).join(' → ')}</div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </TabsContent>

        {/* 8. SLO Dashboard */}
        <TabsContent value="slos">
          <Card>
            <CardHeader><CardTitle>Service Level Objectives</CardTitle></CardHeader>
            <CardContent>
              <DataTable
                data={slos}
                keyExtractor={(r) => r.slo_id}
                columns={[
                  { key: 'service', header: 'Service', render: (r) => r.service_key },
                  { key: 'metric', header: 'Metric', render: (r) => r.metric_key },
                  { key: 'target', header: 'Target', render: (r) => r.target },
                  { key: 'current', header: 'Current', render: (r) => r.current_value ?? '—' },
                  { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
                  { key: 'budget', header: 'Error budget', render: (r) => r.error_budget_remaining ?? '—' },
                  { key: 'window', header: 'Window', render: (r) => r.window },
                ]}
                emptyMessage="No SLOs defined"
              />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
