import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

function Chips({ items }: { readonly items?: string[] }) {
  return <div className="flex flex-wrap gap-1">{(items ?? []).map(item => <Badge key={item} variant="default">{item}</Badge>)}</div>;
}

export function SolutionPackagesPage() {
  const { packageId } = useParams();
  const [data, setData] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    const load = packageId ? api.admin.kyber.solutionPackage(packageId) : api.admin.kyber.solutionPackages();
    load.then(d => setData(d as AnyRecord)).catch(e => setError(e instanceof Error ? e.message : String(e))).finally(() => setLoading(false));
  }, [packageId]);

  if (loading) return <PageWrapper title="Solution Packages"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Solution Packages"><EmptyState title="Unable to load packages" description={error} /></PageWrapper>;

  if (packageId) {
    if (!data) return <PageWrapper title="Solution Packages"><EmptyState title="Package not found" /></PageWrapper>;
    const pkg = data ?? {};
    const readiness = pkg.readiness_report ?? {};
    return (
      <PageWrapper title={pkg.name ?? 'Package detail'} subtitle="Included modules, audit exports, deployment readiness, and tenant fit.">
        <div className="grid gap-4 lg:grid-cols-2">
          <Card><CardHeader><CardTitle>Package Definition</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
            <p className="text-text-secondary">{pkg.description}</p>
            <div><div className="text-xs font-mono text-text-muted">Included modules</div><Chips items={pkg.included_modules} /></div>
            <div><div className="text-xs font-mono text-text-muted">Required flags</div><Chips items={pkg.required_feature_flags} /></div>
            <div><div className="text-xs font-mono text-text-muted">Recommended integrations</div><Chips items={pkg.recommended_integrations} /></div>
            <div><div className="text-xs font-mono text-text-muted">Required audit exports</div><Chips items={pkg.required_audit_exports} /></div>
          </CardContent></Card>
          <Card><CardHeader><CardTitle>Readiness Checklist</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
            <Badge variant="default">{pkg.readiness_status}</Badge>
            {['feature_completeness','documentation_completeness','test_coverage_status','audit_export_support','access_control_status','deployment_support_status'].map(key => <div key={key} className="flex justify-between gap-3"><span className="text-text-muted">{key}</span><span>{readiness[key]}</span></div>)}
            <div className="pt-2"><div className="font-mono text-xs text-text-muted">Known gaps</div><ul className="list-disc pl-5 text-text-secondary">{(readiness.known_gaps ?? []).map((g: string) => <li key={g}>{g}</li>)}</ul></div>
          </CardContent></Card>
          <Card><CardHeader><CardTitle>Deployment modes</CardTitle></CardHeader><CardContent className="space-y-2">{(pkg.deployment_modes_detail ?? []).map((m: AnyRecord) => <div key={m.name} className="rounded border border-border-default p-3"><div className="font-medium">{m.name}</div><p className="text-xs text-text-secondary">{m.description}</p><Chips items={m.known_gaps} /></div>)}</CardContent></Card>
          <Card><CardHeader><CardTitle>Tenants matching this package</CardTitle></CardHeader><CardContent>{(pkg.tenants_matching ?? []).length ? (pkg.tenants_matching ?? []).map((t: AnyRecord) => <div key={t.tenant_id} className="flex justify-between text-sm"><span>{t.tenant_id}</span><Badge variant="success">{Math.round(t.package_fit_score * 100)}%</Badge></div>) : <EmptyState title="No active tenant demand yet" description="Kyber will show matches as tenant usage accumulates." />}</CardContent></Card>
        </div>
      </PageWrapper>
    );
  }

  const items = (data?.items ?? []) as AnyRecord[];
  return (
    <PageWrapper title="Solution Packages" subtitle="Enterprise, regulated, commercial, and government-planning packages.">
      {items.length === 0 ? <EmptyState title="No solution packages configured" /> : <div className="grid gap-4 lg:grid-cols-2">
        {items.map(pkg => <Card key={pkg.package_id}><CardHeader><CardTitle><Link to={`/packages/${pkg.package_id}`}>{pkg.name}</Link></CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
          <div className="flex flex-wrap gap-2"><Badge>{Array.isArray(pkg.market) ? pkg.market.join(' / ') : pkg.market}</Badge><Badge variant="default">{pkg.readiness_status}</Badge><Badge variant="success">tenant demand {pkg.active_tenant_demand ?? 0}</Badge></div>
          <p className="text-text-secondary">{pkg.description}</p>
          <div><div className="text-xs text-text-muted font-mono">Buyer personas</div><Chips items={pkg.buyer_personas} /></div>
          <div><div className="text-xs text-text-muted font-mono">Use cases</div><Chips items={pkg.use_cases} /></div>
          <div><div className="text-xs text-text-muted font-mono">Pricing levers</div><Chips items={pkg.pricing_levers} /></div>
          {(pkg.known_gaps ?? []).length > 0 && <div className="text-xs text-warning">{pkg.known_gaps.join(' ')}</div>}
        </CardContent></Card>)}
      </div>}
    </PageWrapper>
  );
}
