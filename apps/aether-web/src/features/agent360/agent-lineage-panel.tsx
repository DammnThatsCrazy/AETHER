import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import { fetchAgentDescendants, useAgentLineageDetail } from './use-agent-lineage';
import { AttributionBadge, LineageDisclosureNote, LineageStat } from './lineage-display';

type ValueRecord = Record<string, unknown>;

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function RefList({ title, values, empty }: { title: string; values: string[]; empty: string }) {
  return (
    <div>
      <h4 className="text-xs font-medium text-text-primary">{title}</h4>
      {values.length
        ? <p className="break-all font-mono text-xs text-text-secondary">{values.join(', ')}</p>
        : <p className="text-xs text-text-secondary">{empty}</p>}
    </div>
  );
}

/** Agent360 lineage: where this agent sits, who it answers to, and what it produced. */
export function AgentLineagePanel({ agentId }: { agentId: string }) {
  const query = useAgentLineageDetail(agentId);
  const [children, setChildren] = useState<ValueRecord[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [opened, setOpened] = useState(false);
  const [listFailed, setListFailed] = useState(false);
  const detail = query.data;
  const node = detail?.node ?? null;
  const counts = detail?.counts ?? {};

  const load = (next?: string | null) => {
    setOpened(true);
    fetchAgentDescendants(agentId, next)
      .then(page => {
        setChildren(previous => (next ? [...previous, ...page.items] : page.items));
        setCursor(page.next_cursor ?? null);
      })
      .catch(() => setListFailed(true));
  };

  return (
    <Card data-testid="agent-lineage">
      <CardHeader><CardTitle>Delegation lineage</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {query.isLoading && !detail && <LoadingState lines={4} />}
        {query.error && <ErrorState title="Lineage unavailable" message={query.error} onRetry={query.refetch} />}
        {detail && <LineageDisclosureNote disclosure={detail.disclosure} />}
        {detail && !node && (
          <EmptyState title="Not in the lineage projection yet" description="This does not mean the agent has no parent or descendants." />
        )}
        {detail && node && (
          <>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <LineageStat label="Direct children" value={counts.direct_child_count} />
              <LineageStat label="All descendants" value={counts.recursive_descendant_count} />
              <LineageStat label="Active descendants" value={counts.active_descendant_count} />
              <LineageStat label="Risk-flagged descendants" value={counts.risk_descendant_count} />
              <LineageStat label="Deepest level below" value={counts.max_descendant_depth} />
              <LineageStat label="Instances" value={node.agent_instance_count} />
              <LineageStat label="Runs" value={node.agent_run_count} />
              <LineageStat label="Depth" value={node.depth} />
            </dl>
            {node.lineage_status !== 'complete' && <Badge variant="warning">{String(node.lineage_status)}</Badge>}
            <div>
              <h4 className="text-xs font-medium text-text-primary">Principals</h4>
              {detail.principals.length ? (
                <ul className="divide-y divide-border-default text-xs">
                  {detail.principals.map(row => (
                    <li className="flex flex-wrap items-center justify-between gap-2 py-1" key={row.principal_entity_id}>
                      <span className="font-mono text-text-primary">{row.principal_entity_id}</span>
                      <span className="flex items-center gap-2 text-text-secondary">
                        {row.relationship_type} · {row.evidence_class}
                        {row.authority_resolution_status ? ` · authority ${row.authority_resolution_status}` : ''}
                        <AttributionBadge value={row.attribution_class} />
                      </span>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-xs text-text-secondary">No principal is linked.</p>}
            </div>
            <div>
              <h4 className="text-xs font-medium text-text-primary">Parent chain</h4>
              {detail.ancestors.length ? (
                <ol className="text-xs">
                  {detail.ancestors.map(ancestor => {
                    const id = String(ancestor.agent_entity_id);
                    return <li key={id}><Link className="font-mono text-text-primary hover:underline" to={`/agents/${encodeURIComponent(id)}`}>{id}</Link></li>;
                  })}
                </ol>
              ) : <p className="text-xs text-text-secondary">This agent is at the top of its known chain.</p>}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <RefList title="Definitions" values={strings(node.agent_definition_ids)} empty="Not reported." />
              <RefList title="Deployments" values={strings(node.agent_deployment_ids)} empty="Not reported." />
              <RefList title="Authority" values={strings(node.authority_refs)} empty="No authority reference." />
              <RefList title="Tools" values={strings(node.tool_sample)} empty="None observed." />
              <RefList title="Services" values={strings(node.service_sample)} empty="None observed." />
              <RefList title="Verified effects" values={strings(node.verified_effects)} empty="None verified." />
              <RefList title="Reported effects" values={strings(node.reported_effects)} empty="None reported." />
              <RefList title="Outcomes" values={strings(node.outcome_refs)} empty="None recorded." />
              <RefList title="Evidence" values={strings(node.evidence_refs)} empty="No evidence sample." />
            </div>
            <p className="text-xs text-text-secondary">
              A delegation reference does not prove the action happened, and a receipt does not prove it settled. Reported effects stay separate from verified ones.
            </p>
            <div className="space-y-2">
              {!opened && Boolean(counts.recursive_descendant_count) && (
                <Button variant="ghost" size="sm" onClick={() => load()}>Show descendants</Button>
              )}
              {listFailed && <p role="alert" className="text-xs text-warning">Descendants could not be read.</p>}
              {children.length > 0 && (
                <ul className="divide-y divide-border-default text-xs">
                  {children.map(child => {
                    const id = String(child.agent_entity_id);
                    return (
                      <li className="flex flex-wrap justify-between gap-2 py-1" key={id}>
                        <Link className="font-mono text-text-primary hover:underline" to={`/agents/${encodeURIComponent(id)}`}>{id}</Link>
                        <span className="text-text-secondary">depth {String(child.depth)}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
              {cursor && <Button variant="ghost" size="sm" onClick={() => load(cursor)}>Load more</Button>}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
