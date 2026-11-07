import { useState } from 'react';
import type { FormEvent } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Input, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';

type AnyRecord = Record<string, unknown>;

function record(value: unknown): AnyRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as AnyRecord : {};
}

function list(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

/** Unknown stays unknown. A null count never renders as 0. */
function count(value: unknown): string {
  if (value === null || value === undefined) return 'Unknown';
  return typeof value === 'number' ? value.toLocaleString('en-US') : String(value);
}

function attributionColor(value: unknown): 'success' | 'info' | 'warning' | 'default' {
  if (value === 'verified') return 'success';
  if (value === 'inferred') return 'info';
  if (value === 'suspected_cluster') return 'warning';
  return 'default';
}

function Metric({ label, value }: { readonly label: string; readonly value: unknown }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-xl font-semibold text-text-primary">{count(value)}</div>
      </CardContent>
    </Card>
  );
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface AgentListProps {
  readonly rows: AnyRecord[];
  readonly onSelect: (agentId: string) => void;
}

function AgentList({ rows, onSelect }: AgentListProps) {
  if (rows.length === 0) return <p className="text-xs text-text-muted">None in this set.</p>;
  return (
    <ul className="divide-y divide-border-default text-xs font-mono">
      {rows.map((row) => {
        const id = String(row.agent_entity_id);
        return (
          <li key={id} className="flex flex-wrap items-center justify-between gap-2 py-1">
            <button type="button" className="text-text-primary underline" onClick={() => onSelect(id)}>{id}</button>
            <span className="flex items-center gap-2 text-text-muted">
              depth {count(row.depth)} · {String(row.evidence_class ?? 'UNKNOWN')}
              <Badge variant={attributionColor(row.attribution_class)}>{String(row.attribution_class)}</Badge>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

const SECTIONS: readonly { key: string; title: string }[] = [
  { key: 'authority_boundary_crossings', title: 'Agents past their authority boundary' },
  { key: 'revoked_agents', title: 'Agents under revoked authority' },
  { key: 'active_agents', title: 'Still active' },
  { key: 'unresolved_agents', title: 'Unresolved' },
];

/** Move from a whole population to the relevant agents without losing provenance. */
export function AgentLineagePage() {
  const [tenantId, setTenantId] = useState('');
  const [principalId, setPrincipalId] = useState('');
  const [view, setView] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clusterId, setClusterId] = useState<string | null>(null);
  const [members, setMembers] = useState<AnyRecord[]>([]);
  const [membersCursor, setMembersCursor] = useState<string | null>(null);
  const [agent, setAgent] = useState<AnyRecord | null>(null);

  if (!isFeatureEnabled('enableExternalAgentTelemetry')) {
    return (
      <PageWrapper title="Agent Lineage">
        <EmptyState title="Agent lineage is not enabled" description="Enable external agent telemetry for this environment." />
      </PageWrapper>
    );
  }

  const investigate = (event: FormEvent) => {
    event.preventDefault();
    if (!tenantId.trim() || !principalId.trim()) return;
    setLoading(true);
    setError(null);
    setView(null);
    setClusterId(null);
    setMembers([]);
    setAgent(null);
    api.admin.kyber.agentLineageInvestigation(tenantId.trim(), principalId.trim())
      .then(data => setView(record(data)))
      .catch((caught: unknown) => setError(errorText(caught)))
      .finally(() => setLoading(false));
  };

  const loadMembers = (id: string, cursor?: string | null) => {
    setClusterId(id);
    const query: Record<string, string> = { cluster_id: id, page_size: '50' };
    if (cursor) query.cursor = cursor;
    api.admin.kyber.agentLineageAgents(tenantId.trim(), principalId.trim(), query)
      .then((data) => {
        const page = record(data);
        setMembers(previous => (cursor ? [...previous, ...list(page.items)] : list(page.items)));
        setMembersCursor((page.next_cursor as string | null) ?? null);
      })
      .catch((caught: unknown) => setError(errorText(caught)));
  };

  const openAgent = (id: string) => {
    api.admin.kyber.agentLineageAgent(tenantId.trim(), id)
      .then(data => setAgent(record(data)))
      .catch((caught: unknown) => setError(errorText(caught)));
  };

  const summary = record(view?.summary);
  const disclosure = record(summary.disclosure);
  const linkage = record(view?.linkage);
  const risk = record(view?.risk);
  const segments = record(risk.segments);
  const temporal = record(view?.spawn_acceleration);
  const clusters = list(record(view?.clusters).items);
  const node = record(agent?.node);

  return (
    <PageWrapper title="Agent Lineage">
      <div className="space-y-4">
        <p className="text-xs text-text-muted font-mono">
          A suspected cluster is not common control, and scale is not fraud. Verified, inferred and unresolved links are counted separately.
        </p>
        <form className="flex flex-wrap items-end gap-2" onSubmit={investigate}>
          <label className="text-xs font-mono text-text-muted">
            Tenant
            <Input value={tenantId} onChange={e => setTenantId(e.target.value)} aria-label="Tenant" />
          </label>
          <label className="text-xs font-mono text-text-muted">
            Principal
            <Input value={principalId} onChange={e => setPrincipalId(e.target.value)} aria-label="Principal" />
          </label>
          <Button type="submit" size="sm" disabled={loading}>Investigate</Button>
        </form>

        {loading && <LoadingState lines={6} />}
        {error && <EmptyState title="Unable to load lineage" description={error} />}

        {view && (
          <>
            <div className="text-xs font-mono text-text-muted">
              As of {String(disclosure.as_of ?? 'unknown')} · Completeness: {String(disclosure.completeness)}
              {Array.isArray(disclosure.truncation_reasons) && disclosure.truncation_reasons.length > 0
                ? ` · ${disclosure.truncation_reasons.join(' · ')}` : ''}
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              <Metric label="Verified links" value={linkage.verified_links} />
              <Metric label="Inferred links" value={linkage.inferred_links} />
              <Metric label="Probabilistic" value={linkage.probabilistic_links} />
              <Metric label="Unresolved" value={linkage.unresolved_links} />
              <Metric label="Direct" value={summary.direct_agents} />
              <Metric label="Indirect" value={summary.indirect_agents} />
              <Metric label="Active" value={summary.active_agents} />
              <Metric label="Max depth" value={summary.max_delegation_depth} />
              <Metric label="Instances" value={summary.agent_instances} />
              <Metric label="Runs" value={summary.agent_runs} />
              <Metric label="Verified effects" value={view.verified_external_effects} />
              <Metric label="Reported effects" value={view.reported_external_effects} />
            </div>

            <Card>
              <CardHeader><CardTitle>Risk assessment</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-xs font-mono">
                <div>Level: <Badge variant={risk.assessment_level === 'no_behavioral_indicators' ? 'success' : 'warning'}>{String(risk.assessment_level)}</Badge></div>
                <div>Triggered by: {Array.isArray(risk.triggered_signals) && risk.triggered_signals.length ? risk.triggered_signals.join(', ') : 'nothing behavioral'}</div>
                <div>
                  No indicators {count(segments.no_indicators)} · Unresolved {count(segments.unresolved)} · Elevated {count(segments.elevated_risk)} · Confirmed abusive {count(segments.confirmed_abusive)}
                </div>
                <div>
                  Peak spawn rate {count(temporal.spawn_rate)}/s · Baseline per window {count(temporal.baseline_agent_count)} · Acceleration {count(temporal.acceleration)}
                </div>
                <div>Tools: {Array.isArray(view.common_tools) && view.common_tools.length ? view.common_tools.join(', ') : 'none observed'}</div>
                <div>Providers: {Array.isArray(view.common_providers) && view.common_providers.length ? view.common_providers.join(', ') : 'none observed'}</div>
                <div>Wallets: {Array.isArray(view.wallets) && view.wallets.length ? view.wallets.join(', ') : 'none observed'}</div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>Dominant clusters</CardTitle></CardHeader>
              <CardContent>
                {clusters.length === 0 ? <p className="text-xs text-text-muted">No cluster has enough members to report.</p> : (
                  <ul className="divide-y divide-border-default text-xs font-mono">
                    {clusters.map((cluster) => {
                      const id = String(cluster.cluster_id);
                      const bases = list(cluster.bases).map(basis => String(basis.basis)).join(', ');
                      return (
                        <li key={id} className="flex flex-wrap items-center justify-between gap-2 py-1">
                          <button type="button" className="text-text-primary underline" onClick={() => loadMembers(id)}>
                            {count(cluster.member_count)} agents · {String(cluster.kind)} · {bases}
                          </button>
                          <span className="flex items-center gap-2">
                            {cluster.implies_common_control ? null : <span className="text-text-muted">does not establish common control</span>}
                            <Badge variant={attributionColor(cluster.attribution_class)}>{String(cluster.attribution_class)}</Badge>
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
                {clusterId && (
                  <div className="mt-3 space-y-2">
                    <AgentList rows={members} onSelect={openAgent} />
                    {membersCursor && <Button variant="ghost" size="sm" onClick={() => loadMembers(clusterId, membersCursor)}>Load more</Button>}
                  </div>
                )}
              </CardContent>
            </Card>

            {SECTIONS.map(section => (
              <Card key={section.key}>
                <CardHeader><CardTitle>{section.title}</CardTitle></CardHeader>
                <CardContent><AgentList rows={list(record(view[section.key]).items)} onSelect={openAgent} /></CardContent>
              </Card>
            ))}

            {agent && (
              <Card>
                <CardHeader><CardTitle>Evidence trail: {String(agent.agent_entity_id)}</CardTitle></CardHeader>
                <CardContent className="space-y-1 text-xs font-mono">
                  <div>Parent chain: {list(agent.ancestors).map(item => String(item.agent_entity_id)).join(' → ') || 'top of known chain'}</div>
                  <div>Principals: {list(agent.principals).map(row => `${String(row.principal_entity_id)} (${String(row.attribution_class)}, ${String(row.evidence_class)})`).join('; ') || 'none'}</div>
                  <div>Instances {count(node.agent_instance_count)} · Runs {count(node.agent_run_count)} · Sample runs: {Array.isArray(node.agent_run_sample) ? node.agent_run_sample.join(', ') : ''}</div>
                  <div>Tools: {Array.isArray(node.tool_sample) ? node.tool_sample.join(', ') : ''}</div>
                  <div>Verified effects: {Array.isArray(node.verified_effects) && node.verified_effects.length ? node.verified_effects.join(', ') : 'none verified'}</div>
                  <div>Reported effects: {Array.isArray(node.reported_effects) && node.reported_effects.length ? node.reported_effects.join(', ') : 'none reported'}</div>
                  <div>Authority: {Array.isArray(node.authority_refs) && node.authority_refs.length ? node.authority_refs.join(', ') : 'none'}</div>
                  <div>Source events: {Array.isArray(node.evidence_refs) ? node.evidence_refs.join(', ') : ''}</div>
                </CardContent>
              </Card>
            )}
          </>
        )}
      </div>
    </PageWrapper>
  );
}
