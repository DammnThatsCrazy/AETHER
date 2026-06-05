import { useCallback, useEffect, useState } from 'react';
import {
  Badge, Card, CardContent, CardHeader, CardTitle, DataTable,
  EmptyState, ErrorState, LoadingState, Tabs, TabsList, TabsTrigger, TabsContent,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

const VIEWS = [
  { value: 'overview', label: 'Security Overview' },
  { value: 'policies', label: 'Policy Decision Log' },
  { value: 'audit', label: 'Audit Event Explorer' },
  { value: 'isolation', label: 'Tenant Isolation' },
  { value: 'operator', label: 'Operator Access' },
  { value: 'breakglass', label: 'Break-Glass' },
  { value: 'retention', label: 'Data Retention' },
  { value: 'requests', label: 'Data Request Queue' },
  { value: 'evidence', label: 'Evidence Packs' },
] as const;

function useSecurity() {
  const [data, setData] = useState<AnyRecord>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.admin.kyber.securityOverview(),
      api.admin.kyber.securityPolicyDecisions(),
      api.admin.kyber.securityAuditEvents(),
      api.admin.kyber.securityTenantIsolation(),
      api.admin.kyber.securityOperatorAccess(),
      api.admin.kyber.securityBreakGlassList(),
      api.admin.kyber.securityDataRetention(),
      api.admin.kyber.securityDataRequests(),
      api.admin.kyber.securityEvidencePacks(),
    ])
      .then(([overview, policies, audit, isolation, operator, breakglass, retention, requests, evidence]) =>
        setData({ overview, policies, audit, isolation, operator, breakglass, retention, requests, evidence }))
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);
  return { data, loading, error, reload: load };
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

function Section({ title, children }: { readonly title: string; readonly children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function SecurityPage() {
  const { data, loading, error } = useSecurity();
  const [tab, setTab] = useState<string>('overview');

  if (loading) {
    return <PageWrapper title="Security & Governance Command Center"><LoadingState lines={8} /></PageWrapper>;
  }
  if (error) {
    return (
      <PageWrapper title="Security & Governance Command Center">
        <ErrorState title="Unable to load security data" message={error} />
      </PageWrapper>
    );
  }

  const overview = data.overview ?? {};
  const policies = (data.policies?.items ?? []) as AnyRecord[];
  const audit = (data.audit?.items ?? []) as AnyRecord[];
  const isolation = data.isolation ?? {};
  const operator = data.operator ?? {};
  const breakglass = (data.breakglass?.items ?? []) as AnyRecord[];
  const retention = (data.retention?.items ?? []) as AnyRecord[];
  const requests = (data.requests?.items ?? []) as AnyRecord[];
  const evidence = (data.evidence?.items ?? []) as AnyRecord[];

  return (
    <PageWrapper
      title="Security & Governance Command Center"
      subtitle="Access control, policy enforcement, audit ledger, tenant isolation, operator access, retention, and security-review evidence. Not a compliance certification."
    >
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          {VIEWS.map(v => <TabsTrigger key={v.value} value={v.value}>{v.label}</TabsTrigger>)}
        </TabsList>

        <TabsContent value="overview">
          <div className="grid gap-3 md:grid-cols-4">
            <Metric label="Audit events" value={overview.audit_events_total} />
            <Metric label="Policy decisions" value={overview.policy_decisions_total} />
            <Metric label="Policy blocks" value={overview.policy_blocks_total} />
            <Metric label="Active break-glass" value={overview.active_break_glass} />
            <Metric label="Tenant isolation" value={overview.tenant_isolation_status} />
            <Metric label="Roles configured" value={overview.roles_configured} />
          </div>
          <div className="mt-3">
            <Section title="Disclaimer">
              <p className="text-xs text-text-secondary">{overview.disclaimer ?? 'Security-review evidence only; no compliance certification is claimed.'}</p>
            </Section>
          </div>
        </TabsContent>

        <TabsContent value="policies">
          <Section title="Policy Decision Log">
            {policies.length === 0 ? <EmptyState title="No policy decisions yet" /> : (
              <DataTable
                data={policies}
                keyExtractor={(r: AnyRecord) => r.decision_id}
                columns={[
                  { key: 'policy_key', header: 'Policy', render: (r: AnyRecord) => r.policy_key },
                  { key: 'action', header: 'Action', render: (r: AnyRecord) => r.action },
                  { key: 'allowed', header: 'Result', render: (r: AnyRecord) => <Badge variant={r.allowed ? 'success' : 'danger'}>{r.allowed ? 'allowed' : 'blocked'}</Badge> },
                  { key: 'tenant_id', header: 'Tenant', render: (r: AnyRecord) => r.tenant_id ?? '—' },
                  { key: 'reason', header: 'Reason', render: (r: AnyRecord) => r.reason },
                ]}
              />
            )}
          </Section>
        </TabsContent>

        <TabsContent value="audit">
          <Section title="Audit Event Explorer">
            {audit.length === 0 ? <EmptyState title="No audit events yet" /> : (
              <DataTable
                data={audit}
                keyExtractor={(r: AnyRecord) => r.audit_event_id}
                columns={[
                  { key: 'event_type', header: 'Event', render: (r: AnyRecord) => r.event_type },
                  { key: 'action', header: 'Action', render: (r: AnyRecord) => r.action },
                  { key: 'outcome', header: 'Outcome', render: (r: AnyRecord) => <Badge variant={r.outcome === 'allowed' ? 'success' : 'danger'}>{r.outcome}</Badge> },
                  { key: 'tenant_id', header: 'Tenant', render: (r: AnyRecord) => r.tenant_id ?? '—' },
                  { key: 'created_at', header: 'When', render: (r: AnyRecord) => r.created_at },
                ]}
              />
            )}
          </Section>
        </TabsContent>

        <TabsContent value="isolation">
          <Section title="Tenant Isolation Dashboard">
            <div className="mb-2 text-sm">Overall: <Badge variant={isolation.overall_status === 'pass' ? 'success' : 'danger'}>{isolation.overall_status ?? 'unknown'}</Badge></div>
            {(isolation.checks ?? []).length === 0 ? <EmptyState title="No isolation checks recorded" /> : (
              <DataTable
                data={isolation.checks ?? []}
                keyExtractor={(r: AnyRecord) => r.check}
                columns={[
                  { key: 'check', header: 'Check', render: (r: AnyRecord) => r.check },
                  { key: 'status', header: 'Status', render: (r: AnyRecord) => <Badge variant={r.status === 'pass' ? 'success' : r.status === 'warn' ? 'warning' : 'danger'}>{r.status}</Badge> },
                  { key: 'records_scanned', header: 'Scanned', render: (r: AnyRecord) => r.records_scanned },
                  { key: 'missing_tenant_id', header: 'Missing tenant_id', render: (r: AnyRecord) => r.missing_tenant_id },
                ]}
              />
            )}
          </Section>
        </TabsContent>

        <TabsContent value="operator">
          <Section title="Operator Access Dashboard">
            <pre className="text-xs text-text-secondary overflow-auto">{JSON.stringify(operator.operator_roles ?? {}, null, 2)}</pre>
          </Section>
        </TabsContent>

        <TabsContent value="breakglass">
          <Section title="Break-Glass Access Board">
            {breakglass.length === 0 ? <EmptyState title="No break-glass requests" /> : (
              <DataTable
                data={breakglass}
                keyExtractor={(r: AnyRecord) => r.request_id}
                columns={[
                  { key: 'tenant_id', header: 'Tenant', render: (r: AnyRecord) => r.tenant_id },
                  { key: 'requested_by', header: 'Requested by', render: (r: AnyRecord) => r.requested_by },
                  { key: 'reason', header: 'Reason', render: (r: AnyRecord) => r.reason },
                  { key: 'status', header: 'Status', render: (r: AnyRecord) => <Badge>{r.status}</Badge> },
                  { key: 'expires_at', header: 'Expires', render: (r: AnyRecord) => r.expires_at ?? '—' },
                ]}
              />
            )}
          </Section>
        </TabsContent>

        <TabsContent value="retention">
          <Section title="Data Retention Dashboard">
            {retention.length === 0 ? <EmptyState title="No retention policies" /> : (
              <DataTable
                data={retention}
                keyExtractor={(r: AnyRecord) => r.policy_id}
                columns={[
                  { key: 'resource_type', header: 'Resource', render: (r: AnyRecord) => r.resource_type },
                  { key: 'retention_days', header: 'Retention (days)', render: (r: AnyRecord) => r.retention_days },
                  { key: 'delete_behavior', header: 'Delete behavior', render: (r: AnyRecord) => r.delete_behavior },
                  { key: 'enabled', header: 'Enabled', render: (r: AnyRecord) => <Badge variant={r.enabled ? 'success' : 'default'}>{String(r.enabled)}</Badge> },
                ]}
              />
            )}
          </Section>
        </TabsContent>

        <TabsContent value="requests">
          <Section title="Data Request Queue">
            {requests.length === 0 ? <EmptyState title="No data requests" /> : (
              <DataTable
                data={requests}
                keyExtractor={(r: AnyRecord) => r.data_request_id}
                columns={[
                  { key: 'request_type', header: 'Type', render: (r: AnyRecord) => r.request_type },
                  { key: 'tenant_id', header: 'Tenant', render: (r: AnyRecord) => r.tenant_id },
                  { key: 'status', header: 'Status', render: (r: AnyRecord) => <Badge>{r.status}</Badge> },
                  { key: 'requested_by', header: 'Requested by', render: (r: AnyRecord) => r.requested_by },
                ]}
              />
            )}
          </Section>
        </TabsContent>

        <TabsContent value="evidence">
          <Section title="Governance Evidence Packs">
            {evidence.length === 0 ? <EmptyState title="No evidence packs generated" /> : (
              <DataTable
                data={evidence}
                keyExtractor={(r: AnyRecord) => r.evidence_pack_id}
                columns={[
                  { key: 'pack_type', header: 'Pack type', render: (r: AnyRecord) => r.pack_type },
                  { key: 'status', header: 'Status', render: (r: AnyRecord) => <Badge variant={r.status === 'generated' ? 'success' : 'default'}>{r.status}</Badge> },
                  { key: 'known_gaps', header: 'Known gaps', render: (r: AnyRecord) => (r.known_gaps ?? []).length },
                  { key: 'generated_at', header: 'Generated', render: (r: AnyRecord) => r.generated_at ?? '—' },
                ]}
              />
            )}
          </Section>
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
