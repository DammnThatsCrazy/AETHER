import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

function useRevops() {
  const [data, setData] = useState<AnyRecord>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.admin.kyber.revopsOverview(), api.admin.kyber.revopsContracts(), api.admin.kyber.revopsUsage(),
      api.admin.kyber.revopsInvoicePreviews(), api.admin.kyber.revopsValueCreated(), api.admin.kyber.revopsRevenueLeakage(),
      api.admin.kyber.revopsExpansionBillingOpportunities(),
    ]).then(([overview, contracts, usage, invoices, values, leakage, opportunities]) => setData({ overview, contracts, usage, invoices, values, leakage, opportunities }))
      .catch(e => setError(e instanceof Error ? e.message : String(e))).finally(() => setLoading(false));
  }, []);
  return { data, loading, error };
}

function Metric({ label, value }: { readonly label: string; readonly value: unknown }) {
  return <Card><CardContent><div className="text-xs text-text-muted font-mono">{label}</div><div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? 0)}</div></CardContent></Card>;
}

export function RevenueOperationsPage() {
  const { data, loading, error } = useRevops();
  if (loading) return <PageWrapper title="Revenue Operations"><LoadingState lines={8} /></PageWrapper>;
  if (error) return <PageWrapper title="Revenue Operations"><EmptyState title="Unable to load RevOps" description={error} /></PageWrapper>;
  const overview = data.overview ?? {};
  const contracts = (data.contracts?.items ?? []) as AnyRecord[];
  const usage = (data.usage?.items ?? []) as AnyRecord[];
  const invoices = (data.invoices?.items ?? []) as AnyRecord[];
  const values = (data.values?.items ?? []) as AnyRecord[];
  const leakage = (data.leakage?.items ?? []) as AnyRecord[];
  const opportunities = (data.opportunities?.items ?? []) as AnyRecord[];

  return <PageWrapper title="Revenue Operations" subtitle="Internal billing-ready contract, usage, invoice preview, leakage, and expansion intelligence.">
    <div className="grid gap-3 md:grid-cols-4">
      <Metric label="Active contracts" value={overview.active_contracts} />
      <Metric label="Usage-based tenants" value={overview.usage_based_tenants} />
      <Metric label="Enterprise contracts" value={overview.enterprise_contract_tenants} />
      <Metric label="Pilot tenants" value={overview.pilot_tenants} />
      <Metric label="Tenants with overages" value={overview.tenants_with_overages} />
      <Metric label="Estimated billable usage" value={overview.estimated_billable_usage} />
      <Metric label="Value-created total" value={overview.value_created_total} />
      <Metric label="Previews pending review" value={overview.invoice_previews_pending_review} />
    </div>

    <Card><CardHeader><CardTitle>Tenant Billing Table</CardTitle></CardHeader><CardContent><DataTable data={contracts} keyExtractor={(r) => r.contract_profile_id} columns={[
      { key: 'tenant', header: 'Tenant', render: r => r.tenant_id }, { key: 'package', header: 'Package', render: r => r.package_id ?? '—' },
      { key: 'tier', header: 'Plan tier', render: r => r.plan_tier ?? '—' }, { key: 'model', header: 'Billing model', render: r => <Badge>{r.billing_model}</Badge> },
      { key: 'period', header: 'Billing period', render: r => r.billing_period }, { key: 'status', header: 'Contract status', render: r => <Badge variant={r.contract_status === 'active' ? 'success' : 'default'}>{r.contract_status}</Badge> },
      { key: 'renewal', header: 'Renewal date', render: r => r.renewal_date ?? '—' },
      { key: 'invoice', header: 'Invoice preview status', render: r => invoices.find(i => i.tenant_id === r.tenant_id)?.status ?? '—' },
      { key: 'expansion', header: 'Expansion recommendation', render: r => opportunities.find(o => o.tenant_id === r.tenant_id)?.opportunity_type ?? '—' },
    ]} emptyMessage="No contract profiles yet" /></CardContent></Card>

    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Tenant Contract Profile</CardTitle></CardHeader><CardContent className="space-y-3">{contracts.slice(0, 4).map(c => <div key={c.contract_profile_id} className="rounded border border-border-default p-3 text-sm"><div className="font-medium">{c.tenant_id}</div><div className="text-text-secondary">{c.package_id ?? 'No package'} / {c.plan_tier ?? 'No plan'} / {c.billing_model}</div><div className="text-xs text-text-muted">{c.contract_start_date ?? '—'} → {c.contract_end_date ?? '—'} · renewal {c.renewal_date ?? '—'}</div><div className="text-xs text-text-muted">Payment terms: {c.payment_terms ?? '—'} · Internal notes: {c.internal_notes ?? '—'}</div></div>)}</CardContent></Card>
      <Card><CardHeader><CardTitle>Usage Detail</CardTitle></CardHeader><CardContent className="space-y-2">{usage.slice(0, 8).map(u => <div key={u.metering_event_id} className="flex justify-between rounded border border-border-default p-2 text-sm"><span>{u.tenant_id} · {u.event_type}</span><Badge variant={u.billable ? 'success' : 'default'}>{u.quantity}</Badge></div>)}</CardContent></Card>
      <Card><CardHeader><CardTitle>Invoice Preview</CardTitle></CardHeader><CardContent className="space-y-2">{invoices.slice(0, 5).map(i => <div key={i.invoice_preview_id} className="rounded border border-border-default p-3 text-sm"><div className="flex justify-between"><span>{i.tenant_id}</span><Badge>{i.status}</Badge></div><div className="text-xs text-text-secondary">{i.billing_period_start} → {i.billing_period_end}; {i.line_items?.length ?? 0} draft line items</div><pre className="mt-2 max-h-28 overflow-auto text-xs text-text-muted">{JSON.stringify(i.value_created_summary ?? {}, null, 2)}</pre></div>)}</CardContent></Card>
      <Card><CardHeader><CardTitle>Revenue Leakage Feed</CardTitle></CardHeader><CardContent><DataTable data={leakage} keyExtractor={(r) => r.signal_id} columns={[{ key: 'tenant', header: 'Tenant', render: r => r.tenant_id }, { key: 'type', header: 'Leakage type', render: r => r.leakage_type }, { key: 'severity', header: 'Severity', render: r => <Badge variant={r.severity === 'critical' ? 'danger' : 'default'}>{r.severity}</Badge> }, { key: 'reason', header: 'Reason', render: r => r.reason }, { key: 'action', header: 'Recommended action', render: r => r.recommended_action }]} emptyMessage="No revenue leakage signals" /></CardContent></Card>
      <Card><CardHeader><CardTitle>Value Created Events</CardTitle></CardHeader><CardContent className="space-y-2">{values.slice(0, 5).map(v => <div key={v.value_event_id} className="flex justify-between rounded border border-border-default p-2 text-sm"><span>{v.value_type} · {v.source_type}</span><Badge variant="success">{v.value_amount ?? 'tracked'}</Badge></div>)}</CardContent></Card>
      <Card><CardHeader><CardTitle>Expansion Billing Opportunities</CardTitle></CardHeader><CardContent className="space-y-2">{opportunities.slice(0, 6).map(o => <div key={o.opportunity_id} className="rounded border border-border-default p-2 text-sm"><div className="font-medium">{o.tenant_id} · {o.opportunity_type}</div><p className="text-xs text-text-secondary">{o.reason}</p></div>)}</CardContent></Card>
    </div>
  </PageWrapper>;
}
