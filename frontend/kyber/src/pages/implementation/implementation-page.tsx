import { useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, GlyphIcon, LoadingState, SeverityBadge, StatusIndicator } from '@aether/ui';
import { useCustomerSuccessTriggers, useImplementationBlockers, useImplementationOverview, useImplementationTenants, useTenantImplementation } from '@kyber/features/onboarding';


function severityToken(severity: string): 'P0' | 'P1' | 'P2' | 'P3' | 'info' {
  if (severity === 'critical') return 'P0';
  if (severity === 'high') return 'P1';
  if (severity === 'medium') return 'P2';
  if (severity === 'low') return 'P3';
  return 'info';
}

function metric(label: string, value: unknown) {
  return <Card><CardContent className="p-4"><div className="text-[10px] uppercase tracking-wide text-text-muted">{label}</div><div className="mt-1 text-2xl font-mono text-accent">{String(value ?? 0)}</div></CardContent></Card>;
}

export function ImplementationPage() {
  const { tenantId } = useParams();
  const overview = useImplementationOverview();
  const tenants = useImplementationTenants();
  const detail = useTenantImplementation(tenantId);
  const blockers = useImplementationBlockers();
  const triggers = useCustomerSuccessTriggers();

  const selectedTenant = tenantId ?? String(tenants.data?.items?.[0]?.['tenant_id'] ?? '');
  const tableRows = useMemo(() => tenants.data?.items ?? [], [tenants.data]);

  if (overview.isLoading && tenants.isLoading && !overview.data) return <LoadingState lines={6} className="p-6" />;

  return (
    <div className="space-y-6 p-6" data-testid="kyber-implementation-dashboard">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold text-text-primary"><GlyphIcon glyph="◫" className="text-accent" /> Customer Implementation Dashboard</h1>
        <p className="text-sm text-text-muted">Olympus Labs operator view from signed tenant to SDK install, graph activation, value proof, and expansion readiness.</p>
      </div>

      <section className="grid gap-4 md:grid-cols-5" aria-label="Implementation Overview">
        {metric('Tenants', overview.data?.['count'])}
        {metric('Blocked', overview.data?.['blocked_tenants'])}
        {metric('Go-live', overview.data?.['go_live_readiness'])}
        {metric('Value', overview.data?.['value_readiness'])}
        {metric('Expansion', overview.data?.['expansion_readiness'])}
      </section>

      <Card>
        <CardHeader><CardTitle>Tenant Implementation Table</CardTitle></CardHeader>
        <CardContent>
          <DataTable
            data={tableRows}
            keyExtractor={(row) => String(row['tenant_id'])}
            columns={[
              { key: 'tenant_id', header: 'Tenant', render: (row) => String(row['tenant_id'] ?? '') },
              { key: 'package_id', header: 'Package', render: (row) => String(row['package_id'] ?? '') },
              { key: 'deployment_mode', header: 'Deployment', render: (row) => String(row['deployment_mode'] ?? '') },
              { key: 'onboarding_stage', header: 'Stage', render: (row) => <Badge>{String(row['onboarding_stage'] ?? '')}</Badge> },
              { key: 'owner_id', header: 'Owner', render: (row) => String(row['owner_id'] ?? 'unassigned') },
              { key: 'implementation_health_score', header: 'Health', render: (row) => String(row['implementation_health_score'] ?? 0) },
              { key: 'go_live_readiness_score', header: 'Go-live', render: (row) => String(row['go_live_readiness_score'] ?? 0) },
              { key: 'value_readiness_score', header: 'Value', render: (row) => String(row['value_readiness_score'] ?? 0) },
              { key: 'expansion_readiness_score', header: 'Expansion', render: (row) => String(row['expansion_readiness_score'] ?? 0) },
              { key: 'blockers', header: 'Blockers', render: (row) => String(row['blockers'] ?? 0) },
              { key: 'target_go_live_date', header: 'Target', render: (row) => String(row['target_go_live_date'] ?? '—') },
              { key: 'recommended_action', header: 'Recommended action', render: (row) => String(row['recommended_action'] ?? '') },
            ]}
            emptyMessage="No implementation plans yet"
          />
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[1fr_.8fr]">
        <Card data-testid="tenant-implementation-detail">
          <CardHeader><CardTitle>Tenant Implementation Detail {selectedTenant && <Badge size="sm">{selectedTenant}</Badge>}</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {!tenantId && <p className="text-xs text-text-muted">Open /implementation/&lt;tenant_id&gt; for a tenant-specific detail view. Showing dashboard context.</p>}
            {detail.data ? (
              <>
                <div className="grid grid-cols-4 gap-3 text-xs">
                  <div>Health: <b>{detail.data.plan.implementation_health_score}</b></div>
                  <div>SDK/Event/Graph: <b>{detail.data.plan.onboarding_stage}</b></div>
                  <div>Value: <b>{detail.data.plan.value_readiness_score}</b></div>
                  <div>Expansion: <b>{detail.data.plan.expansion_readiness_score}</b></div>
                </div>
                <div className="space-y-2">{detail.data.steps.map(s => <div key={s.step_id} className="flex items-center gap-2 rounded border border-border-default p-2 text-xs"><StatusIndicator status={s.status === 'completed' ? 'healthy' : s.status === 'blocked' ? 'unhealthy' : 'degraded'} />{s.title}<span className="ml-auto text-text-muted">{s.category}</span></div>)}</div>
                <div className="text-xs text-text-secondary">Success criteria: minimum events {detail.data.plan.success_criteria.minimum_event_volume}; go-live approved {String(detail.data.plan.success_criteria.go_live_approved)}</div>
              </>
            ) : <EmptyState title="No tenant selected" description="Select a tenant from the table or route to /implementation/:tenantId." />}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card><CardHeader><CardTitle>Blocker Board</CardTitle></CardHeader><CardContent className="space-y-2">{(blockers.data?.items ?? []).length ? blockers.data!.items.map(b => <div key={b.blocker_id} className="rounded border border-border-default p-2 text-xs"><SeverityBadge severity={severityToken(b.severity)} /> <b>{b.owner_type}</b> · {b.title}<div className="text-text-muted">{b.status} · {b.tenant_id}</div></div>) : <EmptyState title="No blockers" description="No implementation blockers are open." />}</CardContent></Card>
          <Card data-testid="customer-success-trigger-feed"><CardHeader><CardTitle>Customer Success Trigger Feed</CardTitle></CardHeader><CardContent className="space-y-2">{(triggers.data?.items ?? []).length ? triggers.data!.items.map(t => <div key={t.trigger_id} className="rounded border border-border-default p-2 text-xs"><div><SeverityBadge severity={severityToken(t.severity)} /> <b>{t.trigger_type}</b></div><p className="text-text-secondary">{t.reason}</p><p className="text-accent">{t.recommended_action}</p></div>) : <EmptyState title="No triggers" description="Customer success trigger feed is empty." />}</CardContent></Card>
        </div>
      </div>
    </div>
  );
}