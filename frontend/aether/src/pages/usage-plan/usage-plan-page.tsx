import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState, UsageBar } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

type AnyRecord = Record<string, any>;

export function UsagePlanPage() {
  const [data, setData] = useState<AnyRecord>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([api.billing.plan(), api.billing.entitlements(), api.billing.usageSummary(), api.billing.invoicePreviews(), api.billing.valueCreated()])
      .then(([plan, entitlements, summary, invoices, values]) => setData({ plan, entitlements, summary, invoices, values }))
      .catch(e => setError(e instanceof Error ? e.message : String(e))).finally(() => setLoading(false));
  }, []);
  if (loading) return <main className="p-6"><LoadingState lines={6} /></main>;
  if (error) return <main className="p-6"><EmptyState title="Unable to load Usage & Plan" description={error} /></main>;
  const plan = data.plan?.plan ?? {};
  const entitlements = (data.entitlements?.entitlements ?? []) as AnyRecord[];
  const summary = data.summary ?? {};
  const usage = summary.usage_by_dimension ?? {};
  const included = summary.included_usage_by_dimension ?? {};
  const values = (data.values?.items ?? []) as AnyRecord[];
  const dimensions = ['event_ingested', 'audit_export_generated', 'integration_delivery', 'playbook_run', 'recommendation_generated', 'outcome_observed'];
  return <main className="p-6 space-y-4"><div><h1 className="text-xl font-mono font-bold">Usage & Plan</h1><p className="text-sm text-text-secondary">Customer-safe view of your package, enabled modules, included usage, current usage, and value-created metrics.</p></div>
    <div className="grid gap-4 lg:grid-cols-3">
      <Card><CardHeader><CardTitle>Current package</CardTitle></CardHeader><CardContent className="space-y-2"><div className="text-2xl font-semibold">{plan.package_id ?? plan.plan_tier ?? 'No package assigned'}</div><Badge>{plan.billing_period ?? 'monthly'}</Badge><div className="text-sm text-text-secondary">Status: {plan.contract_status ?? 'not configured'}</div></CardContent></Card>
      <Card className="lg:col-span-2"><CardHeader><CardTitle>Enabled modules</CardTitle></CardHeader><CardContent className="flex flex-wrap gap-2">{entitlements.filter(e => e.enabled).length ? entitlements.filter(e => e.enabled).map(e => <Badge key={e.entitlement_id}>{e.feature_key}</Badge>) : <EmptyState title="No module entitlements configured" description="Contact your customer success manager for package setup." />}</CardContent></Card>
    </div>
    <Card><CardHeader><CardTitle>Included vs current usage</CardTitle></CardHeader><CardContent className="space-y-4">{dimensions.map(dim => <div key={dim}><div className="mb-1 flex justify-between text-sm"><span>{dim.replace(/_/g, ' ')}</span><span>{usage[dim] ?? 0} / {included[dim] ?? '—'}</span></div><UsageBar label={dim.replace(/_/g, ' ')} used={Number(usage[dim] ?? 0)} total={Number(included[dim] || Math.max(1, usage[dim] ?? 1))} showUpgradeCta={false} /></div>)}</CardContent></Card>
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Usage by dimension</CardTitle></CardHeader><CardContent><pre className="max-h-80 overflow-auto rounded bg-surface-sunken p-3 text-xs">{JSON.stringify(usage, null, 2)}</pre></CardContent></Card>
      <Card><CardHeader><CardTitle>Customer-facing value-created summary</CardTitle></CardHeader><CardContent className="space-y-2">{values.length ? values.map(v => <div key={v.value_event_id} className="flex justify-between rounded border border-border-default p-2 text-sm"><span>{v.value_type}</span><Badge variant="success">{v.value_amount ?? 'Tracked'}</Badge></div>) : <EmptyState title="No value-created events yet" description="Outcomes, playbooks, and integrations will populate this view when value evidence is observed." />}</CardContent></Card>
    </div>
  </main>;
}
