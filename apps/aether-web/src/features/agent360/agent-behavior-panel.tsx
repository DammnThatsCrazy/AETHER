import {
  Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import { useAgentBehavior } from './use-agent360';

type ValueRecord = Record<string, unknown>;

function asRecord(value: unknown): ValueRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as ValueRecord : {};
}

function asList(value: unknown): ValueRecord[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function rate(value: unknown): string {
  const env = asRecord(value);
  if (env.value === null || env.value === undefined) {
    return env.n ? `Not enough evidence (n=${String(env.n)})` : 'Not measured';
  }
  const interval = Array.isArray(env.interval) ? ` (95% interval ${env.interval.join('–')}, n=${String(env.n)})` : '';
  return `${Math.round(Number(env.value) * 100)}%${interval}`;
}

const STATE_VARIANT = { available: 'success', partial: 'warning', unavailable: 'default' } as const;

/** Agent360 behavior: what the agent usually does, the evidence, and what Aether cannot see. */
export function AgentBehaviorPanel({ agentRef }: { agentRef: string }) {
  const query = useAgentBehavior(agentRef);
  const model = query.data;
  const sections = model?.sections ?? null;
  const behavior = asRecord(sections?.behavior?.data);
  const usual = asRecord(behavior.what_it_usually_does);
  const features = asRecord(behavior.features);
  const decisions = asList(sections?.decisions?.data);
  const observability = asRecord(sections?.observability?.data);
  const blind = Array.isArray(observability.what_aether_cannot_see) ? observability.what_aether_cannot_see as string[] : [];
  const state = sections?.behavior?.state ?? 'unavailable';

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Behavior</CardTitle>
          {model && <Badge variant={STATE_VARIANT[state]}>{state}</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-text-secondary">
          Rebuilt from the agent&apos;s reported activity. Agent references are reported by their deployments;
          rates are shown only with enough evidence, and preferences only where alternatives were observed.
        </p>
        {query.isLoading && !model && <LoadingState lines={4} />}
        {query.error && <ErrorState title="Behavior unavailable" message={query.error} onRetry={query.refetch} />}
        {model && !sections && (
          <EmptyState title="Behavior could not be read" description="The behavior source was unavailable for this request." />
        )}
        {sections && state === 'unavailable' && (
          <EmptyState title="No behavior observed yet" description={sections.behavior?.reason ?? 'No facts for this agent.'} />
        )}
        {sections && state !== 'unavailable' && (
          <>
            {model?.source_truncated && (
              <p role="alert" className="text-xs text-warning">Only the most recent 1,000 facts were read; older behavior is not included.</p>
            )}
            <dl className="grid gap-2 text-xs sm:grid-cols-2">
              <div><dt className="text-text-secondary">Usual outcome</dt><dd className="text-text-primary">{String(usual.usual_disposition ?? 'Not determined')}</dd></div>
              <div><dt className="text-text-secondary">Tool success</dt><dd className="text-text-primary">{rate(features.tool_success_rate)}</dd></div>
              <div><dt className="text-text-secondary">Authority denials</dt><dd className="text-text-primary">{rate(features.authority_denial_rate)}</dd></div>
              <div><dt className="text-text-secondary">Failures resolved</dt><dd className="text-text-primary">{rate(features.failure_resolution_rate)}</dd></div>
            </dl>
            <div>
              <h4 className="text-xs font-medium text-text-primary">Most-used tools</h4>
              <ul className="text-xs text-text-secondary">
                {asList(usual.top_tools).map(tool => (
                  <li key={String(tool.tool)}>{String(tool.tool)} — {String(tool.invocations)} calls</li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="text-xs font-medium text-text-primary">Recent decisions</h4>
              {decisions.length ? (
                <ul className="divide-y divide-border-default text-xs">
                  {decisions.slice(0, 10).map(decision => (
                    <li className="grid gap-1 py-1 sm:grid-cols-3" key={String(decision.decision_id)}>
                      <span className="font-mono">{String(decision.decision_id)}</span>
                      <span>{String(decision.disposition)}</span>
                      <span className="text-text-secondary">{String(decision.status)}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-xs text-text-secondary">{sections.decisions?.reason ?? 'No decisions reconstructed.'}</p>}
            </div>
          </>
        )}
        {sections && (
          <div>
            <h4 className="text-xs font-medium text-text-primary">What Aether cannot see</h4>
            <p className="text-xs text-text-secondary">{blind.length ? blind.join(', ') : 'Nothing listed.'}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
