import { useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import { useAgent360Deployments, useAgentRecentRuns, useAgentRunEvidence } from './use-agent360';
import type { AgentDeploymentRecord } from '@aether-app/features/deployments';

type ValueRecord = Record<string, unknown>;

function asRecord(value: unknown): ValueRecord {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as ValueRecord
    : {};
}

function display(value: unknown, fallback = 'Not recorded'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function EvidenceValue({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined || value === '') return null;
  return (
    <div className="flex flex-wrap justify-between gap-x-3 gap-y-1 text-xs">
      <span className="text-text-secondary">{label}</span>
      <span className="max-w-full break-all text-right font-mono text-text-primary">{display(value)}</span>
    </div>
  );
}

function ResolutionStatusBadge({ status }: { status: unknown }) {
  const variant = status === 'matched' || status === 'matched_reference'
    ? 'success'
    : status === 'unavailable'
      ? 'danger'
      : status === 'ambiguous'
        ? 'warning'
        : 'default';
  const label = status === 'matched'
    ? 'Record matched'
    : status === 'matched_reference'
      ? 'Record reference matched'
    : status === 'not_supplied'
      ? 'Reference not supplied'
      : status === 'unresolved'
        ? 'No matching record'
        : status === 'ambiguous'
          ? 'Multiple possible records'
          : status === 'unavailable'
            ? 'Lookup unavailable'
            : `Resolution: ${display(status)}`;

  return <Badge size="sm" variant={variant}>{label}</Badge>;
}

function EconomicOutcome({ outcome }: { outcome: unknown }) {
  if (outcome === null || outcome === undefined) return null;

  const result = asRecord(outcome);
  const status = result.status;
  const records = Array.isArray(result.records) ? result.records.map(asRecord) : [];
  const matchedRecords = status === 'matched' ? records : [];
  const message = status === 'matched'
    ? matchedRecords.length === 0
      ? 'The response reports a match but includes no economic record details.'
      : 'These tenant-scoped records were matched to the source event. A match does not independently verify the event claim or prove settlement finality.'
    : status === 'not_supplied'
      ? 'This source event supplied no economic reference for matching. That does not establish that no economic activity occurred.'
      : status === 'unresolved'
        ? 'No matching tenant economic record was found for the supplied reference. This does not establish that no economic activity occurred.'
        : status === 'unavailable'
          ? 'Economic record lookup is unavailable. No conclusion about a match or absence can be drawn.'
          : 'Economic record resolution was returned separately from the source-reported event details.';

  return (
    <section aria-label="Economic record resolution" className="space-y-2 rounded border border-border-subtle bg-surface-raised p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-text-primary">Economic record match</h4>
        <ResolutionStatusBadge status={status} />
      </div>
      <p className="text-[11px] text-text-secondary">{message}</p>
      {matchedRecords.length > 0 && (
        <div className="space-y-2">
          {matchedRecords.map((record, index) => (
            <div key={`${display(record.payment_intent_id, 'payment-intent')}-${display(record.settlement_event_id, String(index))}-${index}`} className="space-y-1 rounded border border-border-default p-2">
              <p className="text-[11px] font-medium text-text-primary">Matched economic record {index + 1}</p>
              <div className="grid gap-1 sm:grid-cols-2">
                <EvidenceValue label="Payment intent" value={record.payment_intent_id} />
                <EvidenceValue label="Settlement event" value={record.settlement_event_id} />
                <EvidenceValue label="Intent status" value={record.intent_status} />
                <EvidenceValue label="Settlement status" value={record.settlement_status} />
                <EvidenceValue label="Amount" value={record.amount} />
                <EvidenceValue label="Currency" value={record.currency} />
                <EvidenceValue label="Provider" value={record.provider} />
                <EvidenceValue label="Protocol" value={record.protocol} />
                <EvidenceValue label="Record authority" value={record.source_authority} />
                <EvidenceValue label="Authority event" value={record.source_topic} />
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function DelegationResolution({ resolution }: { resolution: unknown }) {
  if (resolution === null || resolution === undefined) return null;

  const result = asRecord(resolution);
  const status = result.status;
  const message = status === 'matched_reference'
    ? 'The source reference matches a canonical delegation record in this tenant. Party identity and authorization are evaluated separately below; a record match alone does not establish that the external action occurred.'
    : status === 'not_supplied'
      ? 'This source event supplied no delegation reference. That does not establish that no delegation exists.'
      : status === 'unresolved'
        ? 'No matching tenant delegation record was found. This does not establish that no delegation exists elsewhere or that none was active.'
        : status === 'ambiguous'
          ? 'More than one possible record was found, so no delegation record was selected.'
          : status === 'unavailable'
            ? 'Delegation lookup is unavailable. No conclusion about a match or absence can be drawn.'
            : 'Delegation resolution is shown separately from the source-reported claim.';

  return (
    <section aria-label="Delegation record resolution" className="space-y-2 rounded border border-border-subtle bg-surface-raised p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-text-primary">Delegation record match</h4>
        <ResolutionStatusBadge status={status} />
      </div>
      <p className="text-[11px] text-text-secondary">{message}</p>
      {status === 'matched_reference' && (
        <div className="grid gap-1 sm:grid-cols-2">
          <EvidenceValue label="Delegation record" value={result.delegation_id} />
          <EvidenceValue label="State at event time" value={result.state_at_event} />
          <EvidenceValue label="Grantor entity" value={result.grantor_entity_id} />
          <EvidenceValue label="Grantee entity" value={result.grantee_entity_id} />
          <EvidenceValue label="Deployment party identity" value={result.party_identity_status} />
          <EvidenceValue label="Record authority" value={result.source_authority} />
        </div>
      )}
    </section>
  );
}

function DelegationAuthorization({ authorization }: { authorization: unknown }) {
  if (authorization === null || authorization === undefined) return null;

  const result = asRecord(authorization);
  const status = result.status;
  const variant = status === 'within_scope'
    ? 'success'
    : status === 'out_of_scope'
      ? 'danger'
      : status === 'indeterminate'
        ? 'warning'
        : 'default';
  const label = status === 'within_scope'
    ? 'Within recorded grant scope'
    : status === 'out_of_scope'
      ? 'Outside recorded grant scope'
      : status === 'indeterminate'
        ? 'Authorization indeterminate'
        : status === 'not_supplied'
          ? 'No delegation supplied'
          : `Authorization: ${display(status)}`;
  const message = status === 'within_scope'
    ? 'The canonical grant, bound parties, reported action and event time match the recorded scope. This evaluates the source claim; it does not verify that the action occurred.'
    : status === 'out_of_scope'
      ? 'The reported action does not fit the canonical grant at the reported event time. This is a policy comparison, not proof that the external action occurred.'
      : status === 'indeterminate'
        ? 'The available canonical records or source-reported details are insufficient to determine whether the action fit the grant.'
        : 'No canonical delegation authorization evaluation is available for this event.';

  return (
    <section aria-label="Delegation authorization evaluation" className="space-y-2 rounded border border-border-subtle bg-surface-raised p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-text-primary">Delegation authorization evaluation</h4>
        <Badge size="sm" variant={variant}>{label}</Badge>
      </div>
      <p className="text-[11px] text-text-secondary">{message}</p>
      <div className="grid gap-1 sm:grid-cols-2">
        <EvidenceValue label="Reason" value={result.reason} />
        <EvidenceValue label="Grant authority" value={result.grant_scope_authority ?? result.source_authority} />
        <EvidenceValue label="Identity binding authority" value={result.binding_authority} />
        <EvidenceValue label="Delegation state at event time" value={result.time_state} />
        <EvidenceValue label="Canonical actor Agent" value={result.actor_entity_id} />
        <EvidenceValue label="Canonical target Agent" value={result.target_entity_id} />
        <EvidenceValue label="Reported action" value={result.action_type} />
        <EvidenceValue label="Reported resource" value={result.resource_ref} />
        <EvidenceValue label="Reported event time" value={result.event_time} />
      </div>
    </section>
  );
}

function ExecutionOccurrence({ occurrence }: { occurrence: unknown }) {
  if (occurrence === null || occurrence === undefined) return null;

  const result = asRecord(occurrence);
  const verified = result.verified === true;
  return (
    <section aria-label="Execution occurrence evidence" className="space-y-2 rounded border border-border-subtle bg-surface-raised p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-text-primary">Execution occurrence</h4>
        <Badge size="sm" variant={verified ? 'success' : 'warning'}>
          {verified ? 'Independently verified' : 'Source reported · unverified'}
        </Badge>
      </div>
      <p className="text-[11px] text-text-secondary">
        {verified
          ? 'A server-authoritative receipt is associated with this occurrence.'
          : 'No server-authoritative external execution receipt is available. A grant-scope match does not prove that the action ran.'}
      </p>
      <div className="grid gap-1 sm:grid-cols-2">
        <EvidenceValue label="Occurrence status" value={result.status} />
        <EvidenceValue label="Evidence reason" value={result.reason} />
      </div>
    </section>
  );
}

function MarketplaceOrigin({ deployment }: { deployment: AgentDeploymentRecord }) {
  const origin = asRecord(deployment.marketplace_origin);
  if (Object.keys(origin).length === 0) return null;

  return (
    <div className="mt-2 space-y-1 rounded border border-border-subtle bg-surface-raised p-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium text-text-primary">Marketplace origin</span>
        <Badge size="sm" variant="warning">Tenant declared</Badge>
      </div>
      <div className="grid gap-1 sm:grid-cols-2">
        <EvidenceValue label="Source namespace" value={origin.source_namespace} />
        <EvidenceValue label="Listing reference" value={origin.listing_ref} />
        <EvidenceValue label="Template" value={origin.template_ref} />
        <EvidenceValue label="Template version" value={origin.template_version} />
        <EvidenceValue label="Category" value={origin.category} />
        <EvidenceValue label="Listing URL" value={origin.listing_url} />
      </div>
      <p className="text-[11px] text-text-secondary">
        This origin record is tenant-provided. It does not by itself verify marketplace claims or resolve the reference to a canonical Agent.
      </p>
    </div>
  );
}

function Coverage({ coverage }: { coverage: Record<string, 'observed' | 'not_observed'> | undefined }) {
  const labels: Record<string, string> = {
    trigger_evidence: 'Trigger',
    policy_evaluation: 'Policy evaluation',
    delegation: 'Delegation',
    outcome: 'Outcome',
  };
  const fields = Object.entries(labels);
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-text-primary">Evidence coverage</h3>
      <div className="flex flex-wrap gap-2">
        {fields.map(([key, label]) => {
          const state = coverage?.[key] ?? 'not_observed';
          return <Badge key={key} size="sm" variant={state === 'observed' ? 'success' : 'default'}>
            {label}: {state === 'observed' ? 'observed' : 'not observed'}
          </Badge>;
        })}
      </div>
      <p className="text-[11px] text-text-secondary">
        “Not observed” means this run response contains no corresponding event; it does not prove the action or control was absent.
      </p>
    </div>
  );
}

function RunTimeline({ evidence }: { evidence: ValueRecord[] }) {
  if (evidence.length === 0) {
    return <p className="text-sm text-text-secondary">No run evidence was returned for this source reference.</p>;
  }

  return (
    <ol className="divide-y divide-border-default">
      {evidence.map((item, index) => {
        const policy = asRecord(item.policy);
        const key = display(item.source_event_id, `evidence-${index}`);
        return (
          <li key={`${key}-${index}`} className="space-y-2 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge size="sm" variant="info">{display(item.event_type, 'Agent event')}</Badge>
                <Badge size="sm" variant="warning">Source reported</Badge>
              </div>
              <time className="text-xs text-text-secondary">{display(item.occurred_at)}</time>
            </div>
            <h4 className="text-[11px] font-medium text-text-secondary">Source-reported event details</h4>
            <div className="grid gap-1 sm:grid-cols-2">
              <EvidenceValue label="Source event" value={item.source_event_id} />
              <EvidenceValue label="Task reference" value={item.task_ref} />
              <EvidenceValue label="Action" value={item.action_type ?? item.action_ref} />
              <EvidenceValue label="Trigger" value={item.trigger_type ?? item.trigger_ref} />
              <EvidenceValue label="Tool" value={item.tool_name} />
              <EvidenceValue label="Policy" value={policy.id} />
              <EvidenceValue label="Policy decision" value={policy.decision} />
              <EvidenceValue label="Reason codes" value={policy.reason_codes} />
              <EvidenceValue label="Delegation" value={item.delegation_ref} />
              <EvidenceValue label="Delegated to" value={item.delegated_to_ref} />
              <EvidenceValue label="Payment intent reference" value={item.payment_intent_ref} />
              <EvidenceValue label="Settlement reference" value={item.settlement_event_ref} />
              <EvidenceValue label="Status" value={item.status} />
              <EvidenceValue label="Outcome" value={item.outcome ?? item.outcome_ref} />
              <EvidenceValue label="Trace" value={item.trace_id} />
              <EvidenceValue label="Causation reference" value={item.causation_id} />
            </div>
            {Boolean(item.payment_intent_ref || item.settlement_event_ref || item.delegation_ref) && (
              <div className="space-y-2 border-t border-border-subtle pt-2">
                <h4 className="text-[11px] font-medium text-text-secondary">Matched records and authority lookups</h4>
                {(item.payment_intent_ref || item.settlement_event_ref)
                  ? <EconomicOutcome outcome={item.economic_outcome} />
                  : null}
                {item.delegation_ref
                  ? <DelegationResolution resolution={item.delegation_resolution} />
                  : null}
                {item.delegation_ref
                  ? <DelegationAuthorization authorization={item.delegation_authorization} />
                  : null}
                {item.delegation_ref
                  ? <ExecutionOccurrence occurrence={item.execution_occurrence} />
                  : null}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

export function AgentRunEvidence({ agentId }: { agentId: string }) {
  const deploymentQuery = useAgent360Deployments(agentId);
  const deployments = deploymentQuery.data?.deployments ?? [];
  const notConfigured = deploymentQuery.data?.notConfigured ?? false;
  const [deploymentId, setDeploymentId] = useState('');
  const [runInput, setRunInput] = useState('');
  const [requestedRunId, setRequestedRunId] = useState('');

  useEffect(() => {
    if (deployments.length === 0) {
      setDeploymentId('');
      setRunInput('');
      setRequestedRunId('');
      return;
    }
    if (!deployments.some(deployment => deployment.id === deploymentId)) {
      setDeploymentId(deployments[0]?.id ?? '');
      setRunInput('');
      setRequestedRunId('');
    }
  }, [deployments, deploymentId]);

  const evidenceQuery = useAgentRunEvidence(deploymentId, requestedRunId);
  const runsQuery = useAgentRecentRuns(deploymentId);
  const recentRuns = runsQuery.data?.runs ?? [];
  const evidence = evidenceQuery.data;
  const selectedDeployment = deployments.find(deployment => deployment.id === deploymentId);

  function submitRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRequestedRunId(runInput.trim());
  }

  return (
    <Card>
      <CardHeader><CardTitle>External agent runs and marketplace lineage</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-text-secondary">
          Deployment references and run telemetry are scoped to your authenticated tenant. Source-reported events preserve what the deployment sent; they do not reveal hidden model reasoning or independently verify its claims.
        </p>

        {deploymentQuery.isLoading && !deploymentQuery.data ? <LoadingState lines={3} /> : null}
        {deploymentQuery.error ? (
          <ErrorState title="Deployment evidence unavailable" message={deploymentQuery.error} onRetry={deploymentQuery.refetch} />
        ) : null}
        {!deploymentQuery.isLoading && !deploymentQuery.error && notConfigured ? (
          <EmptyState title="External agent telemetry is not configured" description="This tenant has no available external deployment registry." />
        ) : null}
        {!deploymentQuery.isLoading && !deploymentQuery.error && !notConfigured && deployments.length === 0 ? (
          <EmptyState title="No external deployments are linked to this Agent" description="Register a tenant-scoped deployment with this agent reference to inspect its marketplace origin and source-reported runs." />
        ) : null}

        {deployments.length > 0 && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className="min-w-[240px] flex-1 space-y-1 text-xs text-text-secondary">
                <span>Registered deployment</span>
                <select
                  aria-label="Registered deployment"
                  className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary"
                  value={deploymentId}
                  onChange={event => {
                    setDeploymentId(event.target.value);
                    setRunInput('');
                    setRequestedRunId('');
                  }}
                >
                  {deployments.map(deployment => (
                    <option key={deployment.id} value={deployment.id}>
                      {deployment.display_name} · {deployment.external_platform} · {deployment.environment}
                    </option>
                  ))}
                </select>
              </label>
              {selectedDeployment && (
                <Link className="pb-2 text-xs text-accent hover:underline" to={`/deployments/${encodeURIComponent(selectedDeployment.id)}`}>
                  Open deployment details →
                </Link>
              )}
            </div>

            {selectedDeployment && <MarketplaceOrigin deployment={selectedDeployment} />}

            {recentRuns.length > 0 && (
              <label className="block max-w-2xl space-y-1 text-xs text-text-secondary">
                <span>Recent source-reported runs</span>
                <select
                  aria-label="Recent source-reported runs"
                  className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary"
                  value=""
                  onChange={event => {
                    setRunInput(event.target.value);
                    setRequestedRunId('');
                  }}
                >
                  <option value="">Choose a run reference</option>
                  {recentRuns.map(run => (
                    <option key={run.run_id} value={run.run_id}>
                      {run.run_id} · {run.event_count ?? 0} events · {run.last_event_at ?? 'time not recorded'}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {runsQuery.data?.runs_truncated && (
              <p className="text-[11px] text-text-secondary">
                The recent run index reached its scan limit; older source references may be omitted.
              </p>
            )}
            {runsQuery.data?.source_status === 'unavailable' && (
              <p className="text-xs text-warning">
                Recent run references are temporarily unavailable. You can still enter a source run reference below.
              </p>
            )}
            {runsQuery.data?.source_status === 'empty' && (
              <p className="text-xs text-text-secondary">
                No source-reported run references are recorded for this deployment yet. You can still enter one below.
              </p>
            )}
            {runsQuery.error && (
              <p className="text-xs text-warning">
                Recent run references could not be loaded. You can still enter a source run reference below.
              </p>
            )}

            <form className="flex flex-wrap items-end gap-3 border-t border-border-default pt-3" onSubmit={submitRun}>
              <label className="min-w-[240px] flex-1 space-y-1 text-xs text-text-secondary">
                <span>Source run reference</span>
                <input
                  aria-label="Source run reference"
                  autoComplete="off"
                  className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary"
                  maxLength={256}
                  onChange={event => setRunInput(event.target.value)}
                  placeholder="Enter the run ID reported by this deployment"
                  value={runInput}
                />
              </label>
              <Button type="submit" variant="secondary" disabled={!deploymentId || !runInput.trim()}>
                Load run evidence
              </Button>
            </form>
            <p className="text-[11px] text-text-secondary">
              The run reference is opaque and must come from the source. This screen does not infer or enumerate missing run IDs.
            </p>

            {evidenceQuery.isLoading && <LoadingState lines={5} />}
            {evidenceQuery.error && (
              <ErrorState title="Run evidence unavailable" message={evidenceQuery.error} onRetry={evidenceQuery.refetch} />
            )}
            {evidence && !evidenceQuery.isLoading && (
              <section aria-label="Run evidence results" className="space-y-4 border-t border-border-default pt-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="space-y-1">
                    <h3 className="text-sm font-medium text-text-primary">Run evidence timeline</h3>
                    <p className="font-mono text-[11px] text-text-secondary">{evidence.run_id}</p>
                  </div>
                  <Badge variant={evidence.source_status === 'available' ? 'success' : evidence.source_status === 'unavailable' ? 'danger' : 'default'}>
                    {evidence.source_status === 'available' ? `${evidence.evidence_count ?? evidence.evidence?.length ?? 0} source events` : evidence.source_status}
                  </Badge>
                </div>
                {evidence.evidence_truncated && (
                  <p className="text-xs text-warning">The response reached its evidence limit; this timeline may be incomplete.</p>
                )}
                {evidence.source_status === 'unavailable' ? (
                  <p role="status" className="text-xs text-warning">
                    Evidence coverage is unavailable because the source evidence could not be loaded.
                  </p>
                ) : (
                  <Coverage coverage={evidence.coverage} />
                )}
                <RunTimeline evidence={evidence.evidence ?? []} />
                <p className="rounded border border-border-subtle bg-surface-raised p-3 text-xs text-text-secondary">
                  {evidence.explanation_boundary ?? 'Observed references establish sequence and attribution only; they do not establish hidden reasoning or independently verify source claims.'}
                </p>
              </section>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
