import { Link, useParams } from 'react-router-dom';
import {
  Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState,
  LoadingState,
} from '@aether/ui';
import { useAgent360 } from '@aether-app/features/agent360';

type RecordValue = Record<string, unknown>;

function record(value: unknown): RecordValue {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as RecordValue
    : {};
}

function list(value: unknown): RecordValue[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function display(value: unknown, fallback = 'Not recorded'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function Stat({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-md border border-border-default bg-surface-raised px-3 py-2">
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd className="mt-1 text-sm font-medium text-text-primary">{display(value)}</dd>
    </div>
  );
}

export function Agent360Page() {
  const { agentId = '' } = useParams();
  const query = useAgent360(agentId);

  if (query.isLoading && !query.data) return <LoadingState lines={8} />;
  if (query.error) return <ErrorState title="Agent 360 unavailable" message={query.error} onRetry={query.refetch} />;
  if (!query.data) return <EmptyState title="Agent profile unavailable" description="No tenant-scoped Agent 360 record was returned." />;

  const profile = record(query.data);
  const identity = record(profile.identity);
  const ownership = record(profile.ownership);
  const authorization = record(profile.authorization);
  const tasks = record(profile.task_history);
  const delegation = record(profile.delegation);
  const subagents = record(profile.subagent_graph);
  const payments = record(profile.x402_flows);
  const trust = record(profile.trust);
  const outcomes = record(profile.outcomes);
  const executions = list(tasks.recent_executions);
  const intents = list(payments.recent_intents);
  const settlements = list(payments.recent_settlements);
  const delegations = list(delegation.active_delegations);

  return (
    <main className="mx-auto max-w-6xl space-y-5 p-6">
      <div className="space-y-2">
        <Link className="text-xs text-text-secondary hover:text-text-primary" to="/agent-access">← Agent access</Link>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-text-secondary">Agent 360</p>
            <h1 className="text-2xl font-semibold text-text-primary">{display(identity.name, agentId)}</h1>
            <p className="font-mono text-xs text-text-secondary">{agentId}</p>
          </div>
          <Badge variant="default">Tenant scoped</Badge>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>Identity and authority</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Model" value={identity.model} />
            <Stat label="Status" value={identity.status} />
            <Stat label="Owner entity" value={ownership.owner_entity_id} />
            <Stat label="Policy version" value={ownership.policy_version} />
            <Stat label="Risk tolerance" value={authorization.risk_tolerance} />
            <Stat label="Active delegations" value={delegation.active_delegation_count} />
            <Stat label="Subagents" value={subagents.subagent_count} />
            <Stat label="Registered" value={identity.registered_at} />
          </dl>
          <p className="text-xs text-text-secondary">
            A missing field means the source record did not provide it. Delegation records describe authority; they do not prove a payment settled.
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Execution outcomes</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <dl className="grid grid-cols-3 gap-3">
              <Stat label="Executions" value={outcomes.execution_count} />
              <Stat label="Completed" value={outcomes.succeeded_count} />
              <Stat label="Failed" value={outcomes.failed_count} />
            </dl>
            {executions.length ? <ul className="divide-y divide-border-default">
              {executions.map((execution, index) => (
                <li className="flex flex-wrap justify-between gap-2 py-2 text-xs" key={display(execution.execution_id, String(index))}>
                  <span className="font-mono text-text-primary">{display(execution.execution_id)}</span>
                  <span className="text-text-secondary">{display(execution.status)} · {display(execution.ended_at || execution.started_at)}</span>
                </li>
              ))}
            </ul> : <p className="text-sm text-text-secondary">No execution records are available.</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Economic evidence</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <dl className="grid grid-cols-2 gap-3">
              <Stat label="Payment intents" value={payments.payment_intent_count} />
              <Stat label="Settlement records" value={payments.settlement_event_count} />
              <Stat label="Successful settlements" value={trust.successful_settlements} />
              <Stat label="Failed settlements" value={trust.failed_settlements} />
              <Stat label="Settlement reliability" value={trust.settlement_reliability == null ? null : `${Math.round(Number(trust.settlement_reliability) * 100)}%`} />
              <Stat label="Spend by currency" value={payments.spend_by_currency} />
            </dl>
            <p className="text-xs text-text-secondary">Only existing payment and settlement records contribute here. An executor's completed status is not counted as settled value.</p>
            {[...intents, ...settlements].length ? <ul className="divide-y divide-border-default">
              {[...intents, ...settlements].slice(0, 8).map((item, index) => (
                <li className="flex flex-wrap justify-between gap-2 py-2 text-xs" key={display(item.intent_id || item.settlement_event_id, String(index))}>
                  <span className="text-text-primary">{display(item.provider, display(item.type, 'Payment evidence'))}</span>
                  <span className="text-text-secondary">{display(item.status)} · {display(item.amount)} {display(item.currency, '')}</span>
                </li>
              ))}
            </ul> : <p className="text-sm text-text-secondary">No payment or settlement evidence is available.</p>}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Active delegation evidence</CardTitle></CardHeader>
        <CardContent>
          {delegations.length ? <ul className="divide-y divide-border-default">
            {delegations.map((item, index) => (
              <li className="grid gap-1 py-2 text-xs sm:grid-cols-3" key={display(item.delegation_id, String(index))}>
                <span className="font-mono text-text-primary">{display(item.delegation_id)}</span>
                <span className="text-text-secondary">Grantee: {display(item.grantee_entity_id)}</span>
                <span className="text-text-secondary">Scope: {display(item.scope)}</span>
              </li>
            ))}
          </ul> : <p className="text-sm text-text-secondary">No active delegation records are available.</p>}
        </CardContent>
      </Card>
    </main>
  );
}
