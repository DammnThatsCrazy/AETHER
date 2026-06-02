import { useEffect, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type Row = Record<string, any>;
const money = (v: any) => `$${Number(v ?? 0).toLocaleString()}`;
const pct = (v: any) => `${Math.round(Number(v ?? 0) * 100)}%`;

function Metric({ label, value }: { readonly label: string; readonly value: any }) {
  return <Card><CardContent className="p-4"><div className="text-xs text-text-muted font-mono">{label}</div><div className="text-2xl font-semibold text-text-primary">{value}</div></CardContent></Card>;
}

function MiniList({ title, items }: { readonly title: string; readonly items: any[] }) {
  return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">{items.length ? items.slice(0, 6).map((item, i) => <div key={item.opportunity_id ?? item.renewal_risk_id ?? i} className="rounded border border-border-subtle p-2"><div className="font-medium text-text-primary">{item.opportunity_type ?? item.primary_failure_mode}</div><div className="text-xs text-text-secondary">{item.next_step ?? item.recommended_intervention}</div></div>) : <EmptyState title="No records" description="Generate triggers to populate this feed." />}</CardContent></Card>;
}

export function CustomerSuccessPage() {
  const [overview, setOverview] = useState<Row | null>(null);
  const [accounts, setAccounts] = useState<Row[]>([]);
  const [opportunities, setOpportunities] = useState<Row[]>([]);
  const [risks, setRisks] = useState<Row[]>([]);
  const [ebr, setEbr] = useState<Row | null>(null);
  const [plan, setPlan] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const selected = accounts[0];

  async function load() {
    setLoading(true);
    try {
      const [o, a, e, r] = await Promise.all([api.admin.kyber.customerSuccessOverview(), api.admin.kyber.customerSuccessAccounts(), api.admin.kyber.expansionOpportunities(), api.admin.kyber.renewalRisks()]);
      setOverview(o as Row); setAccounts(((a as Row).items ?? []) as Row[]); setOpportunities(((e as Row).items ?? []) as Row[]); setRisks(((r as Row).items ?? []) as Row[]);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setLoading(false); }
  }

  useEffect(() => { void load(); }, []);
  useEffect(() => { if (selected?.tenant_id) { api.admin.kyber.generateEbr(selected.tenant_id).then(x => setEbr(x as Row)).catch(() => setEbr(null)); api.admin.kyber.accountPlan(selected.tenant_id).then(x => setPlan(x as Row)).catch(() => setPlan(null)); } }, [selected?.tenant_id]);

  if (loading) return <PageWrapper title="Customer Success"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Customer Success"><EmptyState title="Unable to load customer success" description={error} /></PageWrapper>;

  return <PageWrapper title="Customer Success Command Center" subtitle="Tenant health, expansion, renewal risk, EBR readiness, and account next actions." actions={<Button size="sm" onClick={() => api.admin.kyber.customerSuccessTriggersGenerate().then(load)}>Generate Triggers</Button>}>
    <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
      <Metric label="Total" value={overview?.total_customers ?? 0} /><Metric label="Active" value={overview?.active_customers ?? 0} /><Metric label="Value Proven" value={overview?.value_proven_customers ?? 0} /><Metric label="Expansion Ready" value={overview?.expansion_ready_customers ?? 0} /><Metric label="At Risk" value={overview?.at_risk_customers ?? 0} /><Metric label="Open Triggers" value={overview?.open_triggers ?? 0} /><Metric label="Renewal Risks" value={overview?.open_renewal_risks ?? 0} /><Metric label="Pipeline" value={money(overview?.estimated_expansion_pipeline)} />
    </div>

    <Card><CardHeader><CardTitle>Tenant Health Table</CardTitle></CardHeader><CardContent><DataTable data={accounts} keyExtractor={r => r.tenant_id} columns={[
      { key: 'tenant', header: 'Tenant', render: r => r.account_name ?? r.tenant_id }, { key: 'package', header: 'Package', render: r => r.package_id ?? r.plan_tier ?? '—' }, { key: 'stage', header: 'Lifecycle', render: r => <Badge>{r.lifecycle_stage}</Badge> }, { key: 'health', header: 'Health', render: r => pct(r.health_score) }, { key: 'expansion', header: 'Expansion', render: r => pct(r.expansion_score) }, { key: 'risk', header: 'Renewal Risk', render: r => pct(r.renewal_risk_score) }, { key: 'value', header: 'Observed Value', render: r => money(r.observed_value_total) }, { key: 'capture', header: 'Outcome Capture', render: r => pct(r.outcome_capture_rate) }, { key: 'playbook', header: 'Playbooks', render: r => pct(r.playbook_adoption_rate) }, { key: 'integration', header: 'Integrations', render: r => pct(r.integration_adoption_rate) }, { key: 'next', header: 'Next Action', render: r => r.next_recommended_action ?? '—' }, { key: 'owner', header: 'Owner', render: r => r.assigned_csm_id ?? r.assigned_account_exec_id ?? '—' }, { key: 'renewal', header: 'Renewal', render: r => r.renewal_date ?? '—' },
    ]} /></CardContent></Card>

    <div className="grid gap-4 xl:grid-cols-2"><MiniList title="Expansion Opportunity Feed" items={opportunities} /><MiniList title="Renewal Risk Feed" items={risks} /></div>

    <div className="grid gap-4 xl:grid-cols-2"><Card><CardHeader><CardTitle>EBR Builder</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><div>Tenant: <b>{selected?.account_name ?? selected?.tenant_id ?? '—'}</b></div><div>Value Created: <b>{money(ebr?.value_created_summary?.observed_value_total)}</b></div><div>Outcome Ledger: {ebr?.outcome_ledger_summary?.outcomes_observed ?? 0} outcomes</div><div>Playbook ROI: {pct(ebr?.playbook_roi_summary?.playbook_adoption_rate)}</div><div>Usage: {ebr?.usage_summary?.recommendations_generated ?? 0} recommendations</div><div>Integrations: {pct(ebr?.integration_summary?.integration_adoption_rate)}</div><div>Recommended modules: {(ebr?.recommended_next_modules ?? []).join(', ') || '—'}</div><div>Next 90 days: {(ebr?.next_90_day_plan ?? []).join(' • ') || '—'}</div></CardContent></Card>
    <Card><CardHeader><CardTitle>Account Plan Detail</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><div>Current package: {plan?.current_package_id ?? selected?.package_id ?? '—'}</div><div>Target package: {plan?.target_package_id ?? '—'}</div><div>ARR: {money(plan?.current_arr_estimate)} → {money(plan?.expansion_arr_estimate)}</div><div>Strategic objectives: {(plan?.strategic_objectives ?? []).join(', ') || '—'}</div><div>Success criteria: {(plan?.success_criteria ?? []).join(', ') || '—'}</div><div>Risks: {(plan?.risks ?? []).join(', ') || '—'}</div><div>Opportunities: {(plan?.opportunities ?? []).join(', ') || '—'}</div><div>Next actions: {(plan?.next_actions ?? []).length}</div></CardContent></Card></div>
  </PageWrapper>;
}
