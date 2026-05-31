import { useState } from 'react';
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  LoadingState,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  TerminalSeparator,
} from '@aether/ui';
import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';
import { cn } from '@kyber/lib/utils';

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function fmtUsd(val: unknown): string {
  const n = typeof val === 'number' ? val : parseFloat(String(val ?? ''));
  if (!n || isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2 }).format(n);
}

function fmtPct(v: unknown): string {
  const n = typeof v === 'number' ? v : parseFloat(String(v ?? ''));
  if (isNaN(n)) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

interface AgentProfileProps {
  readonly agentId: string;
}

function OperatorTab({ agentId }: { agentId: string }) {
  const { data, isLoading } = useQuery({
    key: `agent:trust:${agentId}`,
    fetcher: () => api.agent.agentTrust(agentId),
    enabled: !!agentId,
  });

  if (isLoading) return <LoadingState lines={5} className="pt-2" />;
  if (!data) return <EmptyState title="Operator data unavailable" description="Agent operator metadata could not be loaded." />;

  const d = asRec(data);
  const owner = asRec(d.owner ?? d.operator);
  const delegationScope = Array.isArray(d.delegation_scope) ? d.delegation_scope as string[] : [];
  const authChain = Array.isArray(d.authorization_chain) ? d.authorization_chain as unknown[] : [];

  return (
    <div className="space-y-4 pt-2">
      <div className="grid grid-cols-2 gap-3">
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="text-[10px] uppercase text-text-muted font-mono">Owner entity</div>
            <div className="text-sm font-mono text-accent">{String(owner.display_name ?? owner.id ?? '—')}</div>
            {Boolean(owner.type) && <Badge size="sm">{String(owner.type)}</Badge>}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="text-[10px] uppercase text-text-muted font-mono">Deploying entity</div>
            <div className="text-sm font-mono text-text-primary">{String(d.deployed_by ?? d.deployer ?? '—')}</div>
            {Boolean(d.deploy_ts) && <div className="text-[10px] text-text-muted font-mono">{String(d.deploy_ts)}</div>}
          </CardContent>
        </Card>
      </div>

      {delegationScope.length > 0 && (
        <>
          <TerminalSeparator label="delegation scope" />
          <div className="flex flex-wrap gap-2">
            {delegationScope.map(scope => <Badge key={scope}>{scope}</Badge>)}
          </div>
        </>
      )}

      {authChain.length > 0 && (
        <>
          <TerminalSeparator label="authorization chain" />
          <div className="font-mono text-xs space-y-1">
            {authChain.map((link, i) => {
              const l = asRec(link);
              return (
                <div key={i} className="flex items-center gap-2">
                  {i > 0 && <span className="text-text-muted">↳</span>}
                  <span className={cn('px-2 py-0.5 rounded border', i === 0 ? 'border-accent/40 text-accent' : 'border-border-subtle text-text-secondary')}>
                    {String(l.label ?? l.name ?? l.id ?? `link-${i}`)}
                  </span>
                  {Boolean(l.role) && <span className="text-text-muted">{String(l.role)}</span>}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function ExecutionTab({ agentId }: { agentId: string }) {
  const { data, isLoading } = useQuery({
    key: `agent:graph:${agentId}:all`,
    fetcher: () => api.agent.agentGraph(agentId, 'all'),
    enabled: !!agentId,
  });

  if (isLoading) return <LoadingState lines={5} className="pt-2" />;

  const d = asRec(data);
  const stats = asRec(d.stats ?? d.execution_stats ?? {});
  const runCount = stats.run_count ?? stats.total_runs ?? d.run_count ?? 0;
  const successRate = stats.success_rate ?? d.success_rate;
  const errorRate = stats.error_rate ?? d.error_rate;
  const spendingToDate = stats.spending_to_date ?? d.spending_to_date ?? d.total_spend;
  const lastActive = String(stats.last_active ?? d.last_active_at ?? d.updated_at ?? '—');

  const metricCards = [
    { label: 'Run count', value: String(runCount) },
    { label: 'Success rate', value: fmtPct(successRate) },
    { label: 'Error rate', value: fmtPct(errorRate) },
    { label: 'Spend to date', value: fmtUsd(spendingToDate) },
  ];

  return (
    <div className="space-y-4 pt-2">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {metricCards.map(m => (
          <Card key={m.label}>
            <CardContent className="p-4 text-center">
              <div className="text-[10px] uppercase text-text-muted font-mono">{m.label}</div>
              <div className="text-lg font-semibold font-mono text-text-primary mt-1">{m.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="text-xs text-text-muted font-mono">Last active: <span className="text-text-secondary">{lastActive}</span></div>
    </div>
  );
}

function PolicyTab({ agentId }: { agentId: string }) {
  const { data, isLoading } = useQuery({
    key: `agent:trust:${agentId}`,
    fetcher: () => api.agent.agentTrust(agentId),
    enabled: !!agentId,
  });

  if (isLoading) return <LoadingState lines={5} className="pt-2" />;

  const d = asRec(data);
  const capabilities = Array.isArray(d.authorized_capabilities) ? d.authorized_capabilities as string[] : [];
  const spendingLimits = asRec(d.spending_limits ?? d.limits ?? {});
  const policyLog = Array.isArray(d.policy_log) ? d.policy_log as unknown[] : [];

  return (
    <div className="space-y-4 pt-2">
      {capabilities.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Authorized capabilities</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {capabilities.map(cap => <Badge key={cap} variant="success">{cap}</Badge>)}
            </div>
          </CardContent>
        </Card>
      )}

      {Object.keys(spendingLimits).length > 0 && (
        <Card>
          <CardHeader><CardTitle>Spending limits</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {Object.entries(spendingLimits).map(([period, limit]) => (
                <div key={period} className="flex items-center justify-between text-xs font-mono">
                  <span className="text-text-muted capitalize">{period}</span>
                  <span className="text-text-primary">{fmtUsd(limit)}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {policyLog.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Policy log</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {policyLog.map((entry, i) => {
                const e = asRec(entry);
                return (
                  <div key={i} className="text-xs font-mono border border-border-subtle rounded px-2 py-1.5 flex items-center gap-3">
                    <span className="text-text-muted">{String(e.ts ?? e.timestamp ?? '—')}</span>
                    <span className="text-text-secondary">{String(e.action ?? e.event ?? e.type ?? '—')}</span>
                    {Boolean(e.actor) && <span className="text-text-muted">by {String(e.actor)}</span>}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {capabilities.length === 0 && Object.keys(spendingLimits).length === 0 && policyLog.length === 0 && (
        <EmptyState title="No policy data" description="No policy configuration has been loaded for this agent." />
      )}
    </div>
  );
}

function EconomicTab({ agentId }: { agentId: string }) {
  const { data, isLoading } = useQuery({
    key: `agent:x402:${agentId}`,
    fetcher: () => api.graph.agentX402(agentId),
    enabled: !!agentId,
  });

  if (isLoading) return <LoadingState lines={5} className="pt-2" />;

  const d = asRec(data);
  const attributed = d.revenue_attributed ?? d.attributed_revenue ?? d.revenue;
  const costs = d.total_costs ?? d.costs ?? d.spend;
  const pays = Array.isArray(d.pays) ? d.pays as unknown[] : [];
  const consumes = Array.isArray(d.consumes) ? d.consumes as unknown[] : [];

  return (
    <div className="space-y-4 pt-2">
      <div className="grid grid-cols-2 gap-3">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-[10px] uppercase text-text-muted font-mono">Revenue attributed</div>
            <div className="text-xl font-semibold font-mono text-success mt-1">{fmtUsd(attributed)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-[10px] uppercase text-text-muted font-mono">Total costs</div>
            <div className="text-xl font-semibold font-mono text-warning mt-1">{fmtUsd(costs)}</div>
          </CardContent>
        </Card>
      </div>

      {pays.length > 0 && (
        <>
          <TerminalSeparator label="PAYS edges" />
          <div className="space-y-1.5">
            {pays.map((p, i) => {
              const pr = asRec(p);
              return (
                <div key={i} className="text-xs font-mono flex items-center gap-3 border border-border-subtle rounded px-2 py-1.5">
                  <Badge size="sm" variant="success">PAYS</Badge>
                  <span className="text-text-secondary">{String(pr.to ?? pr.target ?? pr.recipient ?? '—')}</span>
                  <span className="text-text-muted ml-auto">{fmtUsd(pr.amount)}</span>
                </div>
              );
            })}
          </div>
        </>
      )}

      {consumes.length > 0 && (
        <>
          <TerminalSeparator label="CONSUMES edges" />
          <div className="space-y-1.5">
            {consumes.map((c, i) => {
              const cr = asRec(c);
              return (
                <div key={i} className="text-xs font-mono flex items-center gap-3 border border-border-subtle rounded px-2 py-1.5">
                  <Badge size="sm" variant="warning">CONSUMES</Badge>
                  <span className="text-text-secondary">{String(cr.resource ?? cr.service ?? cr.type ?? '—')}</span>
                  <span className="text-text-muted ml-auto">{String(cr.quantity ?? cr.units ?? '—')}</span>
                </div>
              );
            })}
          </div>
        </>
      )}

      {!attributed && !costs && pays.length === 0 && consumes.length === 0 && (
        <EmptyState title="No economic data" description="No economic activity has been recorded for this agent." />
      )}
    </div>
  );
}

export function AgentProfile({ agentId }: AgentProfileProps) {
  const [activeTab, setActiveTab] = useState<'operator' | 'execution' | 'policy' | 'economic'>('operator');

  return (
    <Tabs value={activeTab} onValueChange={v => setActiveTab(v as typeof activeTab)}>
      <TabsList>
        <TabsTrigger value="operator">Operator</TabsTrigger>
        <TabsTrigger value="execution">Execution</TabsTrigger>
        <TabsTrigger value="policy">Policy</TabsTrigger>
        <TabsTrigger value="economic">Economic</TabsTrigger>
      </TabsList>
      <TabsContent value="operator"><OperatorTab agentId={agentId} /></TabsContent>
      <TabsContent value="execution"><ExecutionTab agentId={agentId} /></TabsContent>
      <TabsContent value="policy"><PolicyTab agentId={agentId} /></TabsContent>
      <TabsContent value="economic"><EconomicTab agentId={agentId} /></TabsContent>
    </Tabs>
  );
}
