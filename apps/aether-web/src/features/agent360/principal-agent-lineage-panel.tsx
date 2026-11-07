import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import {
  fetchLineageAgents, fetchLineageTree, useLineageClusters, useLineageSummary,
} from './use-agent-lineage';
import type { LineageRowView, LineageTreeNodeView } from './use-agent-lineage';
import { AttributionBadge, LineageDisclosureNote, LineageStat, lineageCount } from './lineage-display';

const COHORTS: readonly { id: string; label: string; query: Record<string, string> }[] = [
  { id: 'direct', label: 'Direct', query: { relationship: 'direct' } },
  { id: 'delegated', label: 'Delegated', query: { relationship: 'indirect' } },
  { id: 'active', label: 'Active', query: { active_state: 'active' } },
  { id: 'risk', label: 'Risk flagged', query: { risk: 'flagged' } },
  { id: 'unresolved', label: 'Unresolved', query: { attribution_class: 'unresolved' } },
  { id: 'out_of_scope', label: 'Out of scope', query: { authority_status: 'out_of_scope' } },
  { id: 'revoked', label: 'Revoked', query: { authority_status: 'revoked' } },
];

function total(direct: number | null | undefined, indirect: number | null | undefined): number | null {
  return direct === null || direct === undefined || indirect === null || indirect === undefined
    ? null
    : direct + indirect;
}

function agentHref(agentId: string): string {
  return `/agents/${encodeURIComponent(agentId)}`;
}

function CohortList({ principalId, query }: { principalId: string; query: Record<string, string> }) {
  const [rows, setRows] = useState<LineageRowView[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const queryKey = JSON.stringify(query);

  useEffect(() => {
    let cancelled = false;
    setRows([]);
    setCursor(null);
    setLoading(true);
    setFailed(false);
    fetchLineageAgents(principalId, JSON.parse(queryKey) as Record<string, string>)
      .then(page => {
        if (cancelled) return;
        setRows(page.items);
        setCursor(page.next_cursor ?? null);
      })
      .catch(() => { if (!cancelled) setFailed(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [principalId, queryKey]);

  const loadMore = () => {
    setLoading(true);
    fetchLineageAgents(principalId, query, cursor)
      .then(page => {
        setRows(previous => [...previous, ...page.items]);
        setCursor(page.next_cursor ?? null);
      })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
  };

  if (failed) return <p role="alert" className="text-xs text-warning">This cohort could not be read.</p>;
  if (loading && rows.length === 0) return <LoadingState lines={3} />;
  if (rows.length === 0) return <p className="text-xs text-text-secondary">No agents in this cohort.</p>;
  return (
    <div className="space-y-2">
      <ul className="divide-y divide-border-default text-xs">
        {rows.map(row => (
          <li className="flex flex-wrap items-center justify-between gap-2 py-1" key={row.agent_entity_id}>
            <Link className="font-mono text-text-primary hover:underline" to={agentHref(row.agent_entity_id)}>{row.agent_entity_id}</Link>
            <span className="flex items-center gap-2 text-text-secondary">
              depth {lineageCount(row.depth)} · {row.active_state ?? 'unknown'}
              <AttributionBadge value={row.attribution_class} />
            </span>
          </li>
        ))}
      </ul>
      {cursor && <Button variant="ghost" size="sm" disabled={loading} onClick={loadMore}>Load more</Button>}
    </div>
  );
}

function TreeBranch({ principalId, parent }: { principalId: string; parent: string | null }) {
  const [nodes, setNodes] = useState<LineageTreeNodeView[] | null>(null);
  const [more, setMore] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    fetchLineageTree(principalId, parent)
      .then(page => {
        if (cancelled) return;
        setNodes(page.items);
        setMore(Boolean(page.next_cursor));
      })
      .catch(() => { if (!cancelled) setNodes([]); });
    return () => { cancelled = true; };
  }, [principalId, parent]);

  if (nodes === null) return <LoadingState lines={2} />;
  if (nodes.length === 0) return <p className="text-xs text-text-secondary">No resolved branch at this level.</p>;
  return (
    <ul className="space-y-1 border-l border-border-default pl-3 text-xs">
      {nodes.map(node => (
        <li key={node.agent_entity_id}>
          <div className="flex flex-wrap items-center gap-2">
            <Link className="font-mono text-text-primary hover:underline" to={agentHref(node.agent_entity_id)}>{node.agent_entity_id}</Link>
            {node.attribution_class && <AttributionBadge value={node.attribution_class} />}
            {node.lineage_status && node.lineage_status !== 'complete' && <Badge variant="warning">{node.lineage_status}</Badge>}
            {Boolean(node.descendant_count) && (
              <Button
                variant="ghost"
                size="sm"
                aria-expanded={Boolean(expanded[node.agent_entity_id])}
                onClick={() => setExpanded(state => ({ ...state, [node.agent_entity_id]: !state[node.agent_entity_id] }))}
              >
                [{lineageCount(node.descendant_count)} descendants]
              </Button>
            )}
          </div>
          {expanded[node.agent_entity_id] && <TreeBranch principalId={principalId} parent={node.agent_entity_id} />}
        </li>
      ))}
      {more && <li className="text-text-secondary">More at this level. Open a cohort to page through them.</li>}
    </ul>
  );
}

/** Profile360 agent activity: summary and cohorts first, never a full agent list. */
export function PrincipalAgentLineagePanel({ principalId }: { principalId: string }) {
  const summary = useLineageSummary(principalId);
  const clusters = useLineageClusters(principalId);
  const [cohort, setCohort] = useState<string | null>(null);
  const data = summary.data;
  const selected = COHORTS.find(item => item.id === cohort);

  return (
    <Card data-testid="profile-agent-lineage">
      <CardHeader><CardTitle>Agents acting for this profile</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-text-secondary">
          Agents and this profile stay separate identities. Each link shows how strong its evidence is, and a shared cluster does not establish common control.
        </p>
        {summary.isLoading && !data && <LoadingState lines={4} />}
        {summary.error && <ErrorState title="Agent lineage unavailable" message={summary.error} onRetry={summary.refetch} />}
        {data && (
          <>
            <LineageDisclosureNote disclosure={data.disclosure} />
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <LineageStat label="Agents" value={total(data.direct_agents, data.indirect_agents)} />
              <LineageStat label="Active" value={data.active_agents} />
              <LineageStat label="Direct" value={data.direct_agents} />
              <LineageStat label="Indirect" value={data.indirect_agents} />
              <LineageStat label="Instances" value={data.agent_instances} />
              <LineageStat label="Runs" value={data.agent_runs} />
              <LineageStat label="Risk flagged" value={data.risk_flagged_agents} />
              <LineageStat label="Unresolved" value={data.unresolved_agents} />
              <LineageStat label="Probabilistic" value={data.probabilistic_agents} />
              <LineageStat label="Max delegation depth" value={data.max_delegation_depth} />
              <LineageStat label="Verified links" value={data.verified_links} />
              <LineageStat label="Inferred links" value={data.inferred_links} />
              <LineageStat label="Revoked" value={data.revoked_agents} />
              <LineageStat label="Out of scope" value={data.out_of_scope_agents} />
              <LineageStat label="Tools used" value={data.tools_used} />
            </dl>
            <div className="space-y-2">
              <h4 className="text-xs font-medium text-text-primary">Browse by cohort</h4>
              <div className="flex flex-wrap gap-2">
                {COHORTS.map(item => (
                  <Button
                    key={item.id}
                    variant={cohort === item.id ? 'secondary' : 'ghost'}
                    size="sm"
                    aria-pressed={cohort === item.id}
                    onClick={() => setCohort(cohort === item.id ? null : item.id)}
                  >
                    {item.label}
                  </Button>
                ))}
              </div>
              {selected && <CohortList principalId={principalId} query={selected.query} />}
            </div>
            <div className="space-y-2">
              <h4 className="text-xs font-medium text-text-primary">Delegation tree</h4>
              <TreeBranch principalId={principalId} parent={null} />
            </div>
            <div className="space-y-2">
              <h4 className="text-xs font-medium text-text-primary">Largest groups</h4>
              {clusters.data?.items.length ? (
                <ul className="divide-y divide-border-default text-xs">
                  {clusters.data.items.map(cluster => (
                    <li className="flex flex-wrap items-center justify-between gap-2 py-1" key={cluster.cluster_id}>
                      <span className="text-text-primary">
                        {lineageCount(cluster.member_count)} agents · grouped by {cluster.bases.map(basis => basis.basis.replace(/_/g, ' ')).join(', ')}
                      </span>
                      <AttributionBadge value={cluster.attribution_class} />
                    </li>
                  ))}
                </ul>
              ) : <EmptyState title="No groups" description="No group has enough members to report." />}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
