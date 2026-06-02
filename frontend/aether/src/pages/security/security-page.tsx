import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

type AnyRecord = Record<string, any>;

export function SecurityPage() {
  const [data, setData] = useState<AnyRecord>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.security.myPermissions(),
      api.security.auditEvents(),
      api.security.policies(),
      api.security.dataRetention(),
      api.security.dataRequests(),
    ])
      .then(([permissions, audit, policies, retention, requests]) =>
        setData({ permissions, audit, policies, retention, requests }))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <main className="p-6"><LoadingState lines={6} /></main>;
  if (error) return <main className="p-6"><EmptyState title="Security & Governance error" description={error} /></main>;

  const permissions = (data.permissions?.permissions ?? []) as AnyRecord[];
  const roles = (data.permissions?.roles ?? []) as string[];
  const audit = (data.audit?.items ?? []) as AnyRecord[];
  const policies = (data.policies?.items ?? []) as AnyRecord[];
  const retention = (data.retention?.items ?? []) as AnyRecord[];
  const requests = (data.requests?.items ?? []) as AnyRecord[];

  return (
    <main className="p-6 space-y-4">
      <div>
        <h1 className="text-xl font-mono font-bold">Security &amp; Governance</h1>
        <p className="text-sm text-text-secondary">
          Your permissions, security audit events, policies, and data retention for this tenant.
          Evidence is for security review — no compliance certification is claimed.
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Your permissions</CardTitle></CardHeader>
        <CardContent>
          <div className="mb-2 flex flex-wrap gap-1">{roles.map(r => <Badge key={r}>{r}</Badge>)}</div>
          {permissions.length === 0 ? <EmptyState title="No permissions resolved" /> : (
            <div className="grid gap-1 md:grid-cols-2 text-xs font-mono">
              {permissions.map(p => (
                <div key={p.permission_id} className="rounded border border-border-default px-2 py-1">
                  {p.domain}:{p.action} <span className="text-text-muted">({p.scope})</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Tenant audit events</CardTitle></CardHeader>
        <CardContent>
          {audit.length === 0 ? <EmptyState title="No audit events" description="Security-relevant events for your tenant appear here." /> : (
            <div className="space-y-1 text-sm">
              {audit.map(e => (
                <div key={e.audit_event_id} className="flex items-center justify-between rounded border border-border-default px-2 py-1">
                  <span className="font-mono text-xs">{e.event_type} · {e.action}</span>
                  <Badge variant={e.outcome === 'allowed' ? 'success' : 'danger'}>{e.outcome}</Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Policy decisions</CardTitle></CardHeader>
        <CardContent>
          {policies.length === 0 ? <EmptyState title="No policy decisions" /> : (
            <div className="space-y-1 text-sm">
              {policies.map(p => (
                <div key={p.decision_id} className="flex items-center justify-between rounded border border-border-default px-2 py-1">
                  <span className="font-mono text-xs">{p.policy_key}</span>
                  <Badge variant={p.allowed ? 'success' : 'danger'}>{p.allowed ? 'allowed' : 'blocked'}</Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Data retention settings</CardTitle></CardHeader>
        <CardContent>
          {retention.length === 0 ? <EmptyState title="No retention policies" /> : (
            <div className="grid gap-2 md:grid-cols-2">
              {retention.map(r => (
                <div key={r.policy_id} className="rounded border border-border-default p-2 text-xs">
                  <div className="font-medium">{r.resource_type}</div>
                  <div className="text-text-secondary">{r.retention_days} days · {r.delete_behavior}</div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Data request history</CardTitle></CardHeader>
        <CardContent>
          {requests.length === 0 ? <EmptyState title="No data requests" description="Export, deletion, and review requests appear here." /> : (
            <div className="space-y-1 text-sm">
              {requests.map(r => (
                <div key={r.data_request_id} className="flex items-center justify-between rounded border border-border-default px-2 py-1">
                  <span className="font-mono text-xs">{r.request_type}</span>
                  <Badge>{r.status}</Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Audit export &amp; integration security status</CardTitle></CardHeader>
        <CardContent className="text-xs text-text-secondary space-y-1">
          <p>Audit exports are permission-gated, integrity-hashed, expiring, and blocked across tenants.</p>
          <p>Integration webhooks are signed (HMAC), destination-validated, idempotent, and retry-limited. Secrets are never returned.</p>
        </CardContent>
      </Card>
    </main>
  );
}
