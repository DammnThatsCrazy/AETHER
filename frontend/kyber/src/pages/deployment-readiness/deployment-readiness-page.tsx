import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;
function List({ title, items }: { readonly title: string; readonly items?: string[] }) { return <div><div className="text-xs font-mono text-text-muted">{title}</div><ul className="list-disc pl-5 text-sm text-text-secondary">{(items ?? []).map(i => <li key={i}>{i}</li>)}</ul></div>; }

export function DeploymentReadinessPage() {
  const [readiness, setReadiness] = useState<AnyRecord | null>(null);
  const [health, setHealth] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { Promise.all([api.admin.kyber.deploymentReadiness(), api.admin.kyber.auditExportHealth()]).then(([r,h]) => { setReadiness(r as AnyRecord); setHealth(h as AnyRecord); }).catch(e => setError(e instanceof Error ? e.message : String(e))).finally(() => setLoading(false)); }, []);
  if (loading) return <PageWrapper title="Deployment Readiness"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Deployment Readiness"><EmptyState title="Unable to load readiness" description={error} /></PageWrapper>;
  return <PageWrapper title="Deployment Readiness" subtitle="Supportable deployment modes, controls, documentation, and audit export health.">
    <Card><CardHeader><CardTitle>Audit Export Health</CardTitle></CardHeader><CardContent className="grid gap-3 md:grid-cols-5 text-sm"><div>Volume <b>{health?.export_volume ?? 'Unavailable'}</b></div><div>Success <b>{health?.export_success ?? 'Unavailable'}</b></div><div>Failure <b>{health?.export_failure ?? 'Unavailable'}</b></div><div>Expired <b>{health?.stale_or_expired_exports ?? 'Unavailable'}</b></div><div>Tenants <b>{health?.tenants_requesting_exports ? health.tenants_requesting_exports.length : 'Unavailable'}</b></div></CardContent></Card>
    {(readiness?.items ?? []).length === 0 ? <EmptyState title="No deployment readiness records" /> : <div className="grid gap-4 lg:grid-cols-2">{(readiness?.items ?? []).map((mode: AnyRecord) => <Card key={mode.name}><CardHeader><CardTitle>{mode.name} <Badge variant="default">{mode.readiness_status}</Badge></CardTitle></CardHeader><CardContent className="space-y-3"><p className="text-sm text-text-secondary">{mode.description}</p><List title="Required controls" items={mode.required_controls} /><List title="Supported features" items={mode.supported_features} /><List title="Unsupported features" items={mode.unsupported_features} /><List title="Known gaps" items={mode.known_gaps} /></CardContent></Card>)}</div>}
  </PageWrapper>;
}
