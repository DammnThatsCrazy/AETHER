/**
 * Agent Access — the tenant view of agent capability access.
 *
 * Answers, in order: what can my agents reach, what is authorized, and what
 * should I look at first.
 *
 * Every number on this page comes from the backend. Where the backend says a
 * count could not be computed it arrives as `null` with a `missing_inputs`
 * list, and this page renders that as **Unknown with the reason**, never as `0`,
 * `—`, or an empty cell. Where the backend says an answer is bounded
 * (`truncated` / `sampled` / `counts.scope: "scanned_window_only"`) the caveat is
 * rendered next to the number rather than the number being presented as a total.
 * Loading, error, empty and unknown are four visually distinct states.
 */
import { useState } from 'react';
import {
  Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState,
  ErrorState, LoadingState,
} from '@aether/ui';
import { NotEnabledOrError } from '@aether-app/components/domain-intelligence';
import {
  useAccessInventory,
  useAgentBlastRadius,
  useAgentProfile,
  useAgentProfiles,
  useCapabilityAuthorizations,
  useCapabilityCatalog,
  useCapabilityRiskFindings,
  type CapabilityAuthorization,
  type ReachedCapability,
} from '@aether-app/features/agent-access';
import {
  AuthorizedBadge,
  CountStat,
  PartialNotice,
  RiskLevelCounts,
  Section,
  UnknownNotice,
  UnknownValue,
  authorizationStateVariant,
  isUnknownCount,
  riskVariant,
} from './agent-access-shared';

const DOMAIN_LABEL = 'Agent Access Intelligence';

/** Never render an absent string as a number or as a confident blank. */
function text(value: unknown, fallback = 'Not recorded'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

// ── Inventory summary ────────────────────────────────────────────────────────

function InventorySummary({
  summary,
}: {
  readonly summary: NonNullable<ReturnType<typeof useAccessInventory>['data']>;
}) {
  const known = summary.summary_known;
  const reasons = known ? [] : summary.missing_inputs;
  const counts = summary.counts;
  const boundedReasons: string[] = [];
  if (known && summary.complete === false) {
    boundedReasons.push('One or more bounded reads were hit; these totals cover the scanned window only.');
  }

  return (
    <>
      {!known ? (
        <UnknownNotice
          title="Access totals are UNKNOWN, not zero"
          detail="One or more required inputs could not be read, so no total below is stated. Do not read this as an absence of access."
          reasons={reasons}
        />
      ) : null}
      <PartialNotice title="These totals are bounded" reasons={boundedReasons} />
      <dl className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
        <CountStat label="Agents observed" value={counts.agents} reasons={reasons} />
        <CountStat label="Servers observed" value={counts.servers} reasons={reasons} />
        <CountStat label="Capabilities observed" value={counts.capabilities} reasons={reasons} />
        <CountStat
          label="Agent to capability reach"
          value={counts.edges_authorized_for}
          reasons={reasons}
          hint="Observed reach relations, not a proof of total reach."
        />
        <CountStat label="Active authorizations" value={counts.authorizations_active} reasons={reasons} />
      </dl>
      {summary.summary ? (
        <p className="text-xs text-text-secondary">{summary.summary}</p>
      ) : null}
      <ObservedCapabilities />
    </>
  );
}

const CATALOG_PAGE_LIMIT = 100;

/**
 * The observed capabilities themselves. `GET /v1/capability-catalog` returns
 * `count = len(page)` and carries no truncation flag, so the page count is
 * never presented as an inventory total — the headline total above comes from
 * the graph summary, which does disclose its bounds.
 */
function ObservedCapabilities() {
  const catalog = useCapabilityCatalog({ limit: CATALOG_PAGE_LIMIT });

  if (catalog.isLoading && !catalog.data) return <LoadingState lines={3} />;
  if (catalog.error) return <ErrorState message={catalog.error} onRetry={catalog.refetch} />;
  const rows = catalog.data?.items;
  if (!rows) return <LoadingState lines={3} />;

  if (rows.length === 0) {
    return (
      <EmptyState
        title="No capabilities in this page"
        description="No observed capability was returned for this page of the catalog."
      />
    );
  }

  return (
    <Card>
      <CardHeader><CardTitle>Observed capabilities</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        <p className="text-[11px] text-warning">
          Showing up to {CATALOG_PAGE_LIMIT} capabilities. This list is page-bounded and the
          catalog API does not report a total, so it is not the size of your inventory.
        </p>
        <DataTable
          columns={[
            { key: 'tool', header: 'Tool', render: r => text(r.tool_name, 'Not recorded') },
            { key: 'provider', header: 'Provider', render: r => text(r.provider, 'Not recorded') },
            {
              key: 'server',
              header: 'Server',
              render: r => (
                <span className="font-mono">
                  {text(r.server_name ?? r.server_url, 'Not recorded')}
                </span>
              ),
            },
            { key: 'kind', header: 'Kind', render: r => text(r.capability_kind, 'unknown') },
            {
              key: 'risk',
              header: 'Latest risk',
              render: r =>
                r.latest_risk_level === null || r.latest_risk_level === undefined ? (
                  <UnknownValue />
                ) : (
                  <Badge variant={riskVariant(r.latest_risk_level)}>{r.latest_risk_level}</Badge>
                ),
            },
            {
              key: 'observations',
              header: 'Observations',
              render: r =>
                isUnknownCount(r.observation_count)
                  ? <UnknownValue />
                  : <span>{r.observation_count}</span>,
            },
            { key: 'last', header: 'Last observed', render: r => text(r.last_seen_at) },
          ]}
          data={rows}
          keyExtractor={r => r.capability_id}
        />
      </CardContent>
    </Card>
  );
}

// ── Findings ─────────────────────────────────────────────────────────────────

function FindingsSection() {
  const findings = useCapabilityRiskFindings();

  if (findings.isLoading && !findings.data) return <LoadingState lines={4} />;
  if (findings.error) {
    return <ErrorState message={findings.error} onRetry={findings.refetch} />;
  }
  const data = findings.data;
  if (!data) return <LoadingState lines={4} />;

  const scope = data.counts.scope;
  const totalPartial =
    scope === 'all_matching_findings'
      ? undefined
      : scope === 'scanned_window_only'
        ? 'scanned window only'
        : 'scope not stated';

  const coverage = data.coverage;
  const boundedReasons: string[] = [];
  if (coverage?.catalog_truncated) {
    boundedReasons.push(
      'The capability catalog scan hit its limit — capabilities beyond the scanned window were not examined.',
    );
  } else if (coverage?.sampled) {
    boundedReasons.push('Findings were computed over a bounded sample of the inventory, not all of it.');
  }
  if (coverage?.declarations_truncated) {
    boundedReasons.push(
      'The declaration read hit its limit — identity drift could not be detected for every capability.',
    );
  }

  const rows = data.items.map((finding, index) => ({ finding, key: `${index}-${finding.code}` }));
  const byRiskLevel = Object.entries(data.counts.by_risk_level).sort((a, b) => a[0].localeCompare(b[0]));
  const identity = data.identity;

  return (
    <div className="space-y-3">
      <PartialNotice title="This scan did not cover everything" reasons={boundedReasons} />

      <dl className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <CountStat
          label="Findings"
          value={data.counts.total}
          partialReason={totalPartial}
          hint={totalPartial ? undefined : 'Covers every matching finding, not just this page.'}
        />
        <CountStat
          label="Declared capabilities"
          value={identity?.declared}
          hint="Capabilities whose observed identity matches a declaration."
        />
        <CountStat
          label="Drifted capabilities"
          value={identity?.drifted}
          hint={
            identity?.drift_detection_complete === false
              ? undefined
              : 'Observed identity no longer matches the declaration.'
          }
          partialReason={identity?.drift_detection_complete === false ? 'declaration read truncated' : undefined}
        />
        <CountStat
          label="Undeclared capabilities"
          value={identity?.observed_only}
          hint="Observed but never declared. Normal, and deliberately not a finding."
        />
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-text-secondary">By risk level:</span>
        {byRiskLevel.length === 0 ? (
          <span className="text-xs text-text-muted">None</span>
        ) : (
          byRiskLevel.map(([level, count]) => (
            <Badge key={level} variant={riskVariant(level)}>
              {level}: {count}
            </Badge>
          ))
        )}
        <span className="text-[11px] text-text-muted">
          Counts by observed level — there is deliberately no composite risk score.
        </span>
      </div>

      <Card>
        <CardHeader><CardTitle>Findings, highest risk first</CardTitle></CardHeader>
        <CardContent>
          {rows.length === 0 ? (
            boundedReasons.length > 0 ? (
              <p className="text-xs text-text-secondary py-6 text-center">
                No findings in the scanned window. The scan did not cover the whole inventory,
                so this is not a clean bill of health.
              </p>
            ) : (
              <EmptyState
                title="No risk findings"
                description="Every observed capability was examined and none produced a finding."
              />
            )
          ) : (
            <DataTable
              columns={[
                {
                  key: 'risk',
                  header: 'Risk',
                  render: r => (
                    <Badge variant={riskVariant(text(r.finding.risk_level, 'unknown'))}>
                      {text(r.finding.risk_level, 'unknown')}
                    </Badge>
                  ),
                },
                { key: 'code', header: 'Code', render: r => <span className="font-mono">{r.finding.code}</span> },
                {
                  key: 'capability',
                  header: 'Capability',
                  render: r => <span className="font-mono">{text(r.finding.capability_id, 'Not attributed')}</span>,
                },
                { key: 'summary', header: 'Summary', render: r => text(r.finding.summary, '') },
                {
                  key: 'evidence',
                  header: 'Evidence',
                  render: r => <span className="font-mono text-[10px]">{text(r.finding.evidence, '')}</span>,
                },
                { key: 'source', header: 'Source', render: r => text(r.finding.source, 'unknown') },
              ]}
              data={rows}
              keyExtractor={r => r.key}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Reach table (shared by profile + blast radius) ───────────────────────────

function ReachTable({
  capabilities,
  evidenceOnly,
}: {
  readonly capabilities: readonly ReachedCapability[];
  /** True when the enclosing answer is unknown: this list is evidence, not a total. */
  readonly evidenceOnly: boolean;
}) {
  if (capabilities.length === 0) {
    return (
      <p className="text-xs text-text-muted py-4 text-center">
        {evidenceOnly
          ? 'No capability evidence was retained for this subject. This is not a claim that it reaches nothing.'
          : 'No capabilities are within this agent’s observed reach.'}
      </p>
    );
  }
  return (
    <>
      {evidenceOnly ? (
        <p className="text-[11px] text-warning mb-2">
          Evidence we hold — not a complete list, and not a total.
        </p>
      ) : null}
      <DataTable
        columns={[
          {
            key: 'capability',
            header: 'Capability',
            render: r => <span className="font-mono">{r.capability_id}</span>,
          },
          { key: 'tool', header: 'Tool', render: r => text(r.tool_name, 'Not recorded') },
          { key: 'provider', header: 'Provider', render: r => text(r.provider, 'Not recorded') },
          { key: 'server', header: 'Server', render: r => <span className="font-mono">{text(r.server_key, 'Not recorded')}</span> },
          {
            key: 'basis',
            header: 'Basis',
            render: r => (
              <Badge variant={r.basis === 'invoked' ? 'info' : 'default'}>
                {r.basis === 'invoked' ? 'observed invoked' : 'server reachable'}
              </Badge>
            ),
          },
          {
            key: 'risk',
            header: 'Risk',
            render: r =>
              r.latest_risk_level === null || r.latest_risk_level === undefined ? (
                <UnknownValue />
              ) : (
                <Badge variant={riskVariant(r.latest_risk_level)}>{r.latest_risk_level}</Badge>
              ),
          },
          {
            key: 'authorized',
            header: 'Authorized',
            render: r => <AuthorizedBadge authorized={r.authorized} />,
          },
        ]}
        data={capabilities}
        keyExtractor={r => r.capability_id}
      />
    </>
  );
}

// ── Per-agent profile ────────────────────────────────────────────────────────

function AgentProfilePanel({ agentId }: { readonly agentId: string }) {
  const profile = useAgentProfile(agentId);

  if (profile.isLoading && !profile.data) return <LoadingState lines={4} />;
  if (profile.error) return <ErrorState message={profile.error} onRetry={profile.refetch} />;
  const data = profile.data;
  if (!data) return <LoadingState lines={4} />;

  const known = data.profile_known;
  const reasons = known ? [] : data.missing_inputs;
  const counts = data.counts;

  return (
    <Card>
      <CardHeader><CardTitle>Access profile</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {!known ? (
          <UnknownNotice
            title="This agent’s access profile is UNKNOWN, not empty"
            detail="Every count below is unknown because it could not be computed. An agent id we have never observed is indistinguishable from another tenant’s, by design."
            reasons={reasons}
          />
        ) : null}

        <dl className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <CountStat testId="agent-access-stat-profile-servers-observed" label="Servers observed" value={counts['servers_observed']} reasons={reasons} />
          <CountStat testId="agent-access-stat-profile-capabilities-reachable" label="Capabilities reachable" value={counts['capabilities_reachable']} reasons={reasons} />
          <CountStat testId="agent-access-stat-profile-capabilities-invoked" label="Capabilities invoked" value={counts['capabilities_invoked']} reasons={reasons} />
          <CountStat testId="agent-access-stat-profile-capabilities-authorized" label="Capabilities authorized" value={counts['capabilities_authorized']} reasons={reasons} />
          <CountStat testId="agent-access-stat-profile-capabilities-unauthorized" label="Capabilities unauthorized" value={counts['capabilities_unauthorized']} reasons={reasons} />
          <CountStat
            testId="agent-access-stat-profile-observations-recorded"
            label="Observations recorded"
            value={data.observation.observations_recorded}
            reasons={reasons}
            hint="Bounded-window observation count, not an exactly-once total."
          />
        </dl>

        <dl className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
          <div>
            <dt className="text-text-secondary">First observed</dt>
            <dd className="text-text-primary font-mono">{text(data.observation.first_seen_at)}</dd>
          </div>
          <div>
            <dt className="text-text-secondary">Last observed</dt>
            <dd className="text-text-primary font-mono">{text(data.observation.last_seen_at)}</dd>
          </div>
          <div>
            <dt className="text-text-secondary">Providers observed</dt>
            <dd className="text-text-primary">
              {data.identity.providers_observed.length > 0
                ? data.identity.providers_observed.join(', ')
                : 'Not recorded'}
            </dd>
          </div>
        </dl>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-text-secondary">Risk by observed level:</span>
          <RiskLevelCounts known={data.risk.known} byLevel={data.risk.by_latest_risk_level} />
        </div>
        {data.risk.note ? <p className="text-[11px] text-text-muted">{data.risk.note}</p> : null}

        <div>
          <h3 className="text-xs font-semibold text-text-secondary mb-1">Reachable capabilities</h3>
          <ReachTable capabilities={data.reach.capabilities} evidenceOnly={!known} />
        </div>

        {data.summary ? <p className="text-xs text-text-secondary">{data.summary}</p> : null}
      </CardContent>
    </Card>
  );
}

// ── Per-agent blast radius ───────────────────────────────────────────────────

function BlastRadiusPanel({ agentId }: { readonly agentId: string }) {
  const blast = useAgentBlastRadius(agentId);

  if (blast.isLoading && !blast.data) return <LoadingState lines={4} />;
  if (blast.error) return <ErrorState message={blast.error} onRetry={blast.refetch} />;
  const data = blast.data;
  if (!data) return <LoadingState lines={4} />;

  const known = data.exposure_known;
  const reasons = known ? [] : data.missing_inputs;
  const counts = data.counts;

  return (
    <Card>
      <CardHeader><CardTitle>Blast radius</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {!known ? (
          <UnknownNotice
            title="Exposure is UNKNOWN, not zero"
            detail="Every count below could not be computed. Do not read this as no exposure."
            reasons={reasons}
          />
        ) : null}

        <dl className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <CountStat testId="agent-access-stat-blast-servers-reachable" label="Servers reachable" value={counts['servers_reachable']} reasons={reasons} />
          <CountStat testId="agent-access-stat-blast-capabilities-exposed" label="Capabilities exposed" value={counts['capabilities_exposed']} reasons={reasons} />
          <CountStat testId="agent-access-stat-blast-capabilities-invoked" label="Capabilities invoked" value={counts['capabilities_invoked']} reasons={reasons} />
          <CountStat testId="agent-access-stat-blast-capabilities-authorized" label="Capabilities authorized" value={counts['capabilities_authorized']} reasons={reasons} />
          <CountStat testId="agent-access-stat-blast-capabilities-unauthorized" label="Capabilities unauthorized" value={counts['capabilities_unauthorized']} reasons={reasons} />
        </dl>

        <div>
          <h3 className="text-xs font-semibold text-text-secondary mb-1">
            Servers {known ? 'reached' : 'observed (evidence)'}
          </h3>
          {data.servers.length === 0 ? (
            <p className="text-xs text-text-muted">
              {known ? 'No servers within observed reach.' : 'No server evidence retained.'}
            </p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {data.servers.map(server => (
                <li key={server}>
                  <Badge variant="default" className="font-mono">{server}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h3 className="text-xs font-semibold text-text-secondary mb-1">Capabilities within reach</h3>
          <ReachTable capabilities={data.capabilities ?? []} evidenceOnly={!known} />
        </div>

        {data.summary ? <p className="text-xs text-text-secondary">{data.summary}</p> : null}
      </CardContent>
    </Card>
  );
}

// ── Drill-down ───────────────────────────────────────────────────────────────

function AgentDrillDown() {
  const profiles = useAgentProfiles();
  const [selectedAgentId, setSelectedAgentId] = useState('');

  if (profiles.isLoading && !profiles.data) return <LoadingState lines={4} />;
  if (profiles.error) return <ErrorState message={profiles.error} onRetry={profiles.refetch} />;
  const data = profiles.data;
  if (!data) return <LoadingState lines={4} />;

  const boundedReasons: string[] = [];
  if (data.truncated || data.complete === false || data.counts?.scope === 'scanned_window_only') {
    boundedReasons.push(
      'The agent scan hit its limit — this list covers the scanned window only, not every observed agent.',
    );
  }

  if (data.items.length === 0) {
    return (
      <EmptyState
        title="No agents observed"
        description="No agent has been observed with a capability installation yet. An agent absent from this list is one we have not observed — not one without access."
      />
    );
  }

  return (
    <div className="space-y-3">
      <PartialNotice title="This agent list is bounded" reasons={boundedReasons} />

      <dl className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <CountStat
          label="Agents in this list"
          value={data.counts?.agents_observed}
          partialReason={data.counts?.scope === 'scanned_window_only' ? 'scanned window only' : undefined}
          hint="An agent absent from this list is one we have not observed, not one without access."
        />
      </dl>

      <div className="flex flex-col gap-1 max-w-md">
        <label htmlFor="agent-access-agent-select" className="text-xs text-text-secondary">
          Agent to inspect
        </label>
        <select
          id="agent-access-agent-select"
          value={selectedAgentId}
          onChange={event => setSelectedAgentId(event.target.value)}
          className="bg-surface-raised text-text-primary border border-border-default rounded px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-border-focus"
        >
          <option value="">Select an observed agent…</option>
          {data.items.map(agent => (
            <option key={agent.agent_id} value={agent.agent_id}>
              {agent.agent_id}
            </option>
          ))}
        </select>
      </div>

      <Card>
        <CardHeader><CardTitle>Observed agents</CardTitle></CardHeader>
        <CardContent>
          <DataTable
            columns={[
              { key: 'agent', header: 'Agent', render: r => <span className="font-mono">{r.agent_id}</span> },
              {
                key: 'servers',
                header: 'Servers',
                render: r => (isUnknownCount(r.servers_observed) ? <UnknownValue /> : <span>{r.servers_observed}</span>),
              },
              {
                key: 'capabilities',
                header: 'Capabilities on installations',
                render: r =>
                  isUnknownCount(r.capabilities_on_installations)
                    ? <UnknownValue />
                    : <span>{r.capabilities_on_installations}</span>,
              },
              {
                key: 'observations',
                header: 'Observations',
                render: r =>
                  isUnknownCount(r.observations_recorded)
                    ? <UnknownValue />
                    : <span>{r.observations_recorded}</span>,
              },
              { key: 'first', header: 'First observed', render: r => text(r.first_seen_at) },
              { key: 'last', header: 'Last observed', render: r => text(r.last_seen_at) },
            ]}
            data={data.items}
            keyExtractor={r => r.agent_id}
            onRowClick={r => setSelectedAgentId(r.agent_id)}
          />
        </CardContent>
      </Card>

      {data.note ? <p className="text-[11px] text-text-muted">{data.note}</p> : null}

      {selectedAgentId ? (
        <div className="space-y-3">
          <AgentProfilePanel agentId={selectedAgentId} />
          <BlastRadiusPanel agentId={selectedAgentId} />
        </div>
      ) : (
        <p className="text-xs text-text-secondary">
          Select an agent to see its observed profile and blast radius.
        </p>
      )}
    </div>
  );
}

// ── Authorizations ───────────────────────────────────────────────────────────

function AuthorizationsSection() {
  const authorizations = useCapabilityAuthorizations();

  if (authorizations.isLoading && !authorizations.data) return <LoadingState lines={3} />;
  if (authorizations.error) {
    return <ErrorState message={authorizations.error} onRetry={authorizations.refetch} />;
  }
  const data = authorizations.data;
  if (!data) return <LoadingState lines={3} />;

  if (data.items.length === 0) {
    return (
      <EmptyState
        title="No capability authorizations"
        description="Nothing has been explicitly authorized for this tenant. Observed reach above is not authorization."
      />
    );
  }

  const rows = data.items.map((authorization: CapabilityAuthorization, index: number) => ({
    authorization,
    key: authorization.authorization_id ?? `authorization-${index}`,
  }));

  return (
    <Card>
      <CardHeader><CardTitle>Capability authorizations</CardTitle></CardHeader>
      <CardContent>
        <DataTable
          columns={[
            {
              key: 'agent',
              header: 'Agent',
              render: r => <span className="font-mono">{text(r.authorization.agent_id, 'Not recorded')}</span>,
            },
            {
              key: 'scope',
              header: 'Scope',
              render: r => (
                <span className="font-mono">
                  {r.authorization.capability_id
                    ? `capability: ${r.authorization.capability_id}`
                    : r.authorization.server_ref
                      ? `server: ${r.authorization.server_ref}`
                      : text(r.authorization.scope, 'Not recorded')}
                </span>
              ),
            },
            {
              key: 'state',
              header: 'State',
              render: r =>
                r.authorization.state
                  ? (
                    <Badge variant={authorizationStateVariant(r.authorization.state)}>
                      {r.authorization.state}
                    </Badge>
                  )
                  : <UnknownValue />,
            },
            { key: 'starts', header: 'Starts', render: r => text(r.authorization.starts_at, 'Immediately') },
            { key: 'ends', header: 'Ends', render: r => text(r.authorization.ends_at, 'No end date') },
          ]}
          data={rows}
          keyExtractor={r => r.key}
        />
      </CardContent>
    </Card>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function AgentAccessPage() {
  const inventory = useAccessInventory();

  if (inventory.isLoading && !inventory.data) return <LoadingState lines={6} className="p-8" />;
  if (inventory.error) {
    return (
      <div className="p-8">
        <NotEnabledOrError
          error={inventory.error}
          domainLabel={DOMAIN_LABEL}
          onRetry={inventory.refetch}
        />
      </div>
    );
  }

  const summary = inventory.data;
  // A tenant with nothing observed is a REAL empty state — but only when the
  // backend was actually able to compute that. `summary_known: false` is unknown,
  // and must never fall through to this branch.
  const nothingObserved = summary?.summary_known === true && summary.observed_any === false;

  return (
    <div className="p-6 space-y-8">
      <header>
        <h1 className="text-xl font-semibold text-text-primary">Agent Access</h1>
        <p className="text-sm text-text-secondary mt-1">
          What your agents have been observed reaching, what is authorized, and what to look at
          first. Everything here is derived from observation — it is not a proof of total reach,
          and anything that could not be computed reads as “Unknown”, never as zero.
        </p>
      </header>

      {nothingObserved ? (
        <EmptyState
          title="No capability access observed yet"
          description="No agent, server, or capability has been observed for this tenant. That is an absence of observation, not evidence that your agents reach nothing."
        />
      ) : (
        <>
          <Section
            id="agent-access-inventory"
            title="Inventory"
            description="What your agents can reach, as observed."
          >
            {summary ? <InventorySummary summary={summary} /> : <LoadingState lines={3} />}
          </Section>

          <Section
            id="agent-access-findings"
            title="What to look at first"
            description="Scan and drift findings, highest risk first."
          >
            <FindingsSection />
          </Section>

          <Section
            id="agent-access-authorizations"
            title="What is authorized"
            description="Explicit capability authorizations. Observed reach is not authorization."
          >
            <AuthorizationsSection />
          </Section>

          <Section
            id="agent-access-agents"
            title="Per-agent access"
            description="Select an observed agent for its profile and blast radius."
          >
            <AgentDrillDown />
          </Section>
        </>
      )}
    </div>
  );
}
