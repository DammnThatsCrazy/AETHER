import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

function useLoad(loader: () => Promise<unknown>) {
  const [data, setData] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { let alive = true; setLoading(true); loader().then(d => alive && setData(d as AnyRecord)).catch(e => alive && setError(e instanceof Error ? e.message : String(e))).finally(() => alive && setLoading(false)); return () => { alive = false; }; }, []);
  return { data, loading, error };
}

function Chips({ items }: { readonly items?: string[] }) {
  return <div className="flex flex-wrap gap-1">{(items ?? []).map(item => <Badge key={item} variant="default">{item}</Badge>)}</div>;
}

function Shell({ title, subtitle, state, children }: { readonly title: string; readonly subtitle: string; readonly state: ReturnType<typeof useLoad>; readonly children: React.ReactNode }) {
  if (state.loading) return <PageWrapper title={title}><LoadingState lines={6} /></PageWrapper>;
  if (state.error) return <PageWrapper title={title}><EmptyState title={`Unable to load ${title}`} description={state.error} /></PageWrapper>;
  return <PageWrapper title={title} subtitle={subtitle}>{children}</PageWrapper>;
}

export function PricingArchitecturePage() {
  const state = useLoad(api.admin.kyber.pricingModels);
  const model = (state.data?.items ?? [])[0] ?? {};
  return <Shell title="Pricing Architecture" subtitle="Structure-first levers with no exact dollar amounts encoded." state={state}>
    <div className="space-y-4">
      <Card><CardHeader><CardTitle>{model.name}</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p className="text-text-secondary">{model.base_platform_fee_notes}</p><Chips items={model.premium_modules} /><Chips items={model.deployment_pricing} /><Chips items={model.services_pricing} /><Chips items={model.value_based_pricing_notes} /></CardContent></Card>
      <div className="grid gap-3 lg:grid-cols-2">{(model.usage_dimensions ?? []).map((d: AnyRecord) => <Card key={d.dimension_key}><CardHeader><CardTitle>{d.label} <Badge variant={d.billable ? 'warning' : 'default'}>{d.unit}</Badge></CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><p className="text-text-secondary">{d.description}</p><div className="text-xs text-text-muted">Metering: {d.metering_source}</div><Chips items={d.included_in_tiers} /><p className="text-xs text-text-muted">{d.notes}</p></CardContent></Card>)}</div>
    </div>
  </Shell>;
}

export function GTMMaterialsPage() {
  const state = useLoad(api.admin.kyber.gtmMaterials);
  const items = state.data?.items ?? [];
  return <Shell title="GTM Materials" subtitle="Collateral by package, persona, market, and sales readiness status." state={state}>
    <div className="grid gap-3 lg:grid-cols-2">{items.map((m: AnyRecord) => <Card key={m.material_id}><CardHeader><CardTitle>{m.title} <Badge>{m.status}</Badge></CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><Badge variant="default">{m.material_type}</Badge><Badge variant="accent">{m.market}</Badge><Chips items={m.solution_package_ids} /><Chips items={m.buyer_personas} /><ul className="list-disc pl-5 text-text-secondary">{(m.content_blocks ?? []).map((b: string) => <li key={b}>{b}</li>)}</ul></CardContent></Card>)}</div>
  </Shell>;
}

export function BuyerPersonasPage() {
  const state = useLoad(api.admin.kyber.buyerPersonas);
  const items = state.data?.items ?? [];
  return <Shell title="Buyer Personas" subtitle="Pains, objections, proof needs, and mapped package collateral." state={state}>
    <div className="grid gap-3 lg:grid-cols-2">{items.map((p: AnyRecord) => <Card key={p.persona_id}><CardHeader><CardTitle>{p.title} <Badge>{p.market}</Badge></CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><Chips items={p.relevant_solution_packages} /><Section title="Pains" items={p.pains} /><Section title="Desired outcomes" items={p.desired_outcomes} /><Section title="Objections" items={p.objections} /><Section title="Proof needed" items={p.proof_needed} /><Section title="Recommended materials" items={p.recommended_collateral} /><div className="text-xs text-warning">Pricing sensitivity: {p.pricing_sensitivity}</div></CardContent></Card>)}</div>
  </Shell>;
}

export function ROICalculatorsPage() {
  const state = useLoad(api.admin.kyber.roiCalculators);
  const items = state.data?.items ?? [];
  return <Shell title="ROI Calculators" subtitle="Directional calculator definitions, assumptions, outputs, and disclaimers." state={state}>
    <div className="grid gap-3 lg:grid-cols-2">{items.map((c: AnyRecord) => <Card key={c.calculator_id}><CardHeader><CardTitle>{c.calculator_id} <Badge>{c.status}</Badge></CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><Badge variant="accent">{c.solution_package_id}</Badge><Section title="Inputs" items={c.inputs} /><Section title="Formulas" items={c.formulas} /><Section title="Outputs" items={c.outputs} /><Section title="Assumptions" items={c.assumptions} /><p className="text-xs text-warning">{c.disclaimer}</p></CardContent></Card>)}</div>
  </Shell>;
}

export function SalesReadinessPage() {
  const state = useLoad(api.admin.kyber.salesReadiness);
  const items = state.data?.items ?? [];
  return <Shell title="Sales Readiness" subtitle="Packages ready to sell and gaps in collateral, ROI, audit export, or deployment readiness." state={state}>
    <div className="mb-4 text-sm text-text-secondary">Ready packages: <b>{state.data?.ready_to_sell_count ?? 0}</b></div>
    <div className="grid gap-3 lg:grid-cols-2">{items.map((p: AnyRecord) => <Card key={p.package_id}><CardHeader><CardTitle>{p.package_name} <Badge variant={p.ready_to_sell ? 'success' : 'warning'}>{p.readiness_status}</Badge></CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><div className="grid grid-cols-3 gap-2"><div>Materials <b>{p.material_count}</b></div><div>Personas <b>{p.persona_count}</b></div><div>ROI <b>{p.roi_calculator_count}</b></div></div><Chips items={[p.missing_collateral && 'missing collateral', p.missing_roi_calculator && 'missing ROI calculator', p.missing_audit_export_support && 'missing audit export support', p.missing_deployment_readiness && 'missing deployment readiness'].filter(Boolean) as string[]} /><Section title="Recommended next sales actions" items={p.recommended_next_sales_actions} /></CardContent></Card>)}</div>
  </Shell>;
}

function Section({ title, items }: { readonly title: string; readonly items?: string[] }) {
  return <div><div className="text-xs font-mono text-text-muted">{title}</div><ul className="list-disc pl-5 text-text-secondary">{(items ?? []).map(i => <li key={i}>{i}</li>)}</ul></div>;
}
