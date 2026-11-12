/**
 * Agents — the tenant view of observed agents and their capability access
 * (Claude Design handoff: Aether Agents).
 *
 * Answers, in order: who is acting, what can they reach, what is authorized,
 * and what should I look at first.
 *
 * Every number on this page comes from the backend. Where the backend says a
 * count could not be computed it arrives as `null` with a `missing_inputs`
 * list, and this page renders that as **Unknown with the reason**, never as `0`,
 * `—`, or an empty cell. Where the backend says an answer is bounded
 * (`truncated` / `sampled` / `counts.scope: "scanned_window_only"`) the caveat is
 * rendered next to the number rather than the number being presented as a total.
 * Loading, error, empty and unknown are four visually distinct states.
 *
 * The page is read-only: it observes agents, reach and authorizations; it does
 * not grant or revoke anything.
 */
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Badge, DataTable, EmptyState, ErrorState, Icon, LoadingState, formatDateTime, useTimeContext,
} from '@aether/ui';
import { BrandMark } from '@aether-app/components/brand-mark';
import { ChoiceChip, Eyebrow, LinkButton, PrimaryButton, TonePill, type Tone } from '@aether-app/components/ae-ui';
import { NotEnabledOrError } from '@aether-app/components/domain-intelligence';
import {
  useAccessInventory,
  useAgentBlastRadius,
  useAgentProfile,
  useAgentProfiles,
  useCapabilityAuthorizations,
  useCapabilityCatalog,
  useCapabilityRiskFindings,
  type AgentProfileIndexEntry,
  type CapabilityAuthorization,
  type ReachedCapability,
} from '@aether-app/features/agent-access';
import {
  AccessCard,
  AuthorizedBadge,
  CountStat,
  PartialNotice,
  RiskLevelCounts,
  Section,
  UnknownNotice,
  UnknownValue,
  authorizationStateVariant,
  isUnknownCount,
  recencyOf,
  relativeTime,
  riskVariant,
  type Recency,
} from './agent-access-shared';

const DOMAIN_LABEL = 'Agent Access Intelligence';

/** Never render an absent string as a number or as a confident blank. */
function text(value: unknown, fallback = 'Not recorded'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

const MUTE = { color: 'var(--ae-mute)' } as const;

/**
 * A backend timestamp shown for people: relative ("3h ago") for past
 * observations, or the full local date-time for schedules and timelines. The
 * exact instant is always on hover and in `dateTime`. An absent value keeps
 * its honest fallback; an unparseable one is shown as received.
 */
function Stamp({
  iso,
  mode = 'relative',
  fallback = 'Not recorded',
}: {
  readonly iso: string | null | undefined;
  readonly mode?: 'relative' | 'absolute';
  readonly fallback?: string;
}) {
  const timeCtx = useTimeContext();
  if (!iso) return <>{fallback}</>;
  if (Number.isNaN(Date.parse(iso))) return <>{iso}</>;
  const full = formatDateTime(iso, timeCtx);
  return (
    <time dateTime={iso} title={full}>
      {mode === 'relative' ? relativeTime(iso) : full}
    </time>
  );
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
      <dl className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
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
      {summary.summary ? <p className="text-[12px]" style={MUTE}>{summary.summary}</p> : null}
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
    <AccessCard title="Observed capabilities">
      <p className="text-[11px]" style={{ color: 'var(--ae-amber)' }}>
        Showing up to {CATALOG_PAGE_LIMIT} capabilities. This list is page-bounded and the
        catalog API does not report a total, so it is not the size of your inventory.
      </p>
      <div className="overflow-x-auto">
        <DataTable
          columns={[
            { key: 'tool', header: 'Tool', render: r => text(r.tool_name, 'Not recorded') },
            {
              key: 'provider',
              header: 'Provider',
              render: r => (
                <span className="flex items-center gap-2">
                  {r.provider ? <BrandMark token={r.provider} size={20} markSize={12} /> : null}
                  {text(r.provider, 'Not recorded')}
                </span>
              ),
            },
            {
              key: 'server',
              header: 'Server',
              render: r => <span className="ae-mono">{text(r.server_name ?? r.server_url, 'Not recorded')}</span>,
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
                  : <span className="ae-mono">{r.observation_count}</span>,
            },
            { key: 'last', header: 'Last observed', render: r => <Stamp iso={r.last_seen_at} /> },
          ]}
          data={rows}
          keyExtractor={r => r.capability_id}
        />
      </div>
    </AccessCard>
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
    <div className="flex flex-col gap-3">
      <PartialNotice title="This scan did not cover everything" reasons={boundedReasons} />

      <dl className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
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
        <span className="text-[12px]" style={MUTE}>By risk level:</span>
        {byRiskLevel.length === 0 ? (
          <span className="text-[12px]" style={MUTE}>None</span>
        ) : (
          byRiskLevel.map(([level, count]) => (
            <Badge key={level} variant={riskVariant(level)}>
              {level}: {count}
            </Badge>
          ))
        )}
        <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>
          Counts by observed level — there is deliberately no composite risk score.
        </span>
      </div>

      <AccessCard title="Findings, highest risk first">
        {rows.length === 0 ? (
          boundedReasons.length > 0 ? (
            <p className="py-6 text-center text-[12px]" style={MUTE}>
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
          <div className="overflow-x-auto">
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
                { key: 'code', header: 'Code', render: r => <span className="ae-mono">{r.finding.code}</span> },
                {
                  key: 'capability',
                  header: 'Capability',
                  render: r => <span className="ae-mono">{text(r.finding.capability_id, 'Not attributed')}</span>,
                },
                { key: 'summary', header: 'Summary', render: r => text(r.finding.summary, '') },
                {
                  key: 'evidence',
                  header: 'Evidence',
                  render: r => <span className="ae-mono text-[10px]">{text(r.finding.evidence, '')}</span>,
                },
                { key: 'source', header: 'Source', render: r => text(r.finding.source, 'unknown') },
              ]}
              data={rows}
              keyExtractor={r => r.key}
            />
          </div>
        )}
      </AccessCard>
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
      <p className="py-4 text-center text-[12px]" style={MUTE}>
        {evidenceOnly
          ? 'No capability evidence was retained for this subject. This is not a claim that it reaches nothing.'
          : 'No capabilities are within this agent’s observed reach.'}
      </p>
    );
  }
  return (
    <>
      {evidenceOnly ? (
        <p className="mb-2 text-[11px]" style={{ color: 'var(--ae-amber)' }}>
          Evidence we hold — not a complete list, and not a total.
        </p>
      ) : null}
      <div className="overflow-x-auto">
        <DataTable
          columns={[
            {
              key: 'capability',
              header: 'Capability',
              render: r => <span className="ae-mono">{r.capability_id}</span>,
            },
            { key: 'tool', header: 'Tool', render: r => text(r.tool_name, 'Not recorded') },
            { key: 'provider', header: 'Provider', render: r => text(r.provider, 'Not recorded') },
            { key: 'server', header: 'Server', render: r => <span className="ae-mono">{text(r.server_key, 'Not recorded')}</span> },
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
      </div>
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
    <AccessCard
      title="Access profile"
      aside={
        <Link className="ae-focus text-[12px] hover:underline" style={{ color: 'var(--ae-blue-ink)' }} to={`/agents/${encodeURIComponent(agentId)}`}>
          Open Agent 360
        </Link>
      }
    >
      {!known ? (
        <UnknownNotice
          title="This agent’s access profile is UNKNOWN, not empty"
          detail="Every count below is unknown because it could not be computed. An agent id we have never observed is indistinguishable from another tenant’s, by design."
          reasons={reasons}
        />
      ) : null}

      <dl className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
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

      <dl className="grid gap-3 text-[12px]" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <div>
          <dt style={MUTE}>First observed</dt>
          <dd><Stamp iso={data.observation.first_seen_at} /></dd>
        </div>
        <div>
          <dt style={MUTE}>Last observed</dt>
          <dd><Stamp iso={data.observation.last_seen_at} /></dd>
        </div>
        <div>
          <dt style={MUTE}>Providers observed</dt>
          <dd>
            {data.identity.providers_observed.length > 0
              ? data.identity.providers_observed.join(', ')
              : 'Not recorded'}
          </dd>
        </div>
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px]" style={MUTE}>Risk by observed level:</span>
        <RiskLevelCounts known={data.risk.known} byLevel={data.risk.by_latest_risk_level} />
      </div>
      {data.risk.note ? <p className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>{data.risk.note}</p> : null}

      <div>
        <Eyebrow>Reachable capabilities</Eyebrow>
        <div className="mt-1.5">
          <ReachTable capabilities={data.reach.capabilities} evidenceOnly={!known} />
        </div>
      </div>

      {data.summary ? <p className="text-[12px]" style={MUTE}>{data.summary}</p> : null}
    </AccessCard>
  );
}

// ── Per-agent authority ──────────────────────────────────────────────────────

const AUTHORITY_COLUMNS: ReadonlyArray<{ key: 'yes' | 'unknown' | 'no'; label: string; tone: Tone }> = [
  { key: 'yes', label: 'Authorized', tone: 'sage' },
  { key: 'unknown', label: 'Not determined', tone: 'mute' },
  { key: 'no', label: 'Reached, not authorized', tone: 'ember' },
];

function AgentAuthorityPanel({ agentId }: { readonly agentId: string }) {
  const profile = useAgentProfile(agentId);
  const grants = useCapabilityAuthorizations({ agent_id: agentId });
  const reach = profile.data?.reach.capabilities ?? [];
  const columns = {
    yes: reach.filter(c => c.authorized === true),
    unknown: reach.filter(c => c.authorized === null || c.authorized === undefined),
    no: reach.filter(c => c.authorized === false),
  };

  return (
    <div className="flex flex-col gap-[18px]">
      <AccessCard title="What this agent can reach, by authorization" testId="agent-authority-columns">
        {profile.error ? (
          <ErrorState message={profile.error} onRetry={profile.refetch} />
        ) : !profile.data ? (
          <LoadingState lines={3} />
        ) : reach.length === 0 ? (
          <p className="text-[12px]" style={MUTE}>
            {profile.data.profile_known
              ? 'No capabilities are within this agent’s observed reach.'
              : 'No reach evidence was retained for this agent. This is not a claim that it reaches nothing.'}
          </p>
        ) : (
          <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(200px, 100%), 1fr))' }}>
            {AUTHORITY_COLUMNS.map(col => (
              <div key={col.key} className="flex flex-col gap-1.5 rounded-[14px] px-3.5 py-3" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
                <span className="flex items-center justify-between gap-2">
                  <TonePill tone={col.tone}>{col.label}</TonePill>
                  <span className="ae-mono text-[12px]" style={MUTE}>{columns[col.key].length}</span>
                </span>
                {columns[col.key].length === 0 ? (
                  <span className="text-[12px]" style={{ color: 'var(--ae-faint)' }}>None in observed reach</span>
                ) : (
                  columns[col.key].map(c => (
                    <span key={c.capability_id} className="flex min-w-0 flex-col text-[12px] leading-tight">
                      <span className="truncate">{text(c.tool_name, c.capability_id)}</span>
                      <span className="ae-mono truncate text-[10px]" style={MUTE}>{text(c.server_key, 'server not recorded')}</span>
                    </span>
                  ))
                )}
              </div>
            ))}
          </div>
        )}
        <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>
          Not determined means the authorization read was unavailable for that capability — it is never shown as a denial.
        </span>
      </AccessCard>

      <AccessCard title="Authorizations granted to this agent">
        {grants.error ? (
          <ErrorState message={grants.error} onRetry={grants.refetch} />
        ) : !grants.data ? (
          <LoadingState lines={3} />
        ) : grants.data.items.length === 0 ? (
          <p className="text-[12px]" style={MUTE}>No explicit authorization is recorded for this agent. Observed reach is not authorization.</p>
        ) : (
          <AuthorizationRows items={grants.data.items} />
        )}
        <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>Aether reads authorizations here; it does not grant or revoke them from this page.</span>
      </AccessCard>
    </div>
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
    <AccessCard title="Blast radius">
      {!known ? (
        <UnknownNotice
          title="Exposure is UNKNOWN, not zero"
          detail="Every count below could not be computed. Do not read this as no exposure."
          reasons={reasons}
        />
      ) : null}

      <dl className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
        <CountStat testId="agent-access-stat-blast-servers-reachable" label="Servers reachable" value={counts['servers_reachable']} reasons={reasons} />
        <CountStat testId="agent-access-stat-blast-capabilities-exposed" label="Capabilities exposed" value={counts['capabilities_exposed']} reasons={reasons} />
        <CountStat testId="agent-access-stat-blast-capabilities-invoked" label="Capabilities invoked" value={counts['capabilities_invoked']} reasons={reasons} />
        <CountStat testId="agent-access-stat-blast-capabilities-authorized" label="Capabilities authorized" value={counts['capabilities_authorized']} reasons={reasons} />
        <CountStat testId="agent-access-stat-blast-capabilities-unauthorized" label="Capabilities unauthorized" value={counts['capabilities_unauthorized']} reasons={reasons} />
      </dl>

      <div>
        <Eyebrow>Servers {known ? 'reached' : 'observed (evidence)'}</Eyebrow>
        {data.servers.length === 0 ? (
          <p className="mt-1.5 text-[12px]" style={MUTE}>
            {known ? 'No servers within observed reach.' : 'No server evidence retained.'}
          </p>
        ) : (
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {data.servers.map(server => (
              <li key={server}>
                <Badge variant="default" className="font-mono">{server}</Badge>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <Eyebrow>Capabilities within reach</Eyebrow>
        <div className="mt-1.5">
          <ReachTable capabilities={data.capabilities ?? []} evidenceOnly={!known} />
        </div>
      </div>

      {data.summary ? <p className="text-[12px]" style={MUTE}>{data.summary}</p> : null}
    </AccessCard>
  );
}

// ── Per-agent lifecycle ──────────────────────────────────────────────────────

interface LifecycleEntry {
  readonly at: string;
  readonly label: string;
  readonly tone: Tone;
}

function AgentLifecyclePanel({ agent, agentId }: { readonly agent: AgentProfileIndexEntry | undefined; readonly agentId: string }) {
  const grants = useCapabilityAuthorizations({ agent_id: agentId });
  const entries: LifecycleEntry[] = [];
  if (agent?.first_seen_at) entries.push({ at: agent.first_seen_at, label: 'First observed', tone: 'sage' });
  for (const g of grants.data?.items ?? []) {
    const scope = g.capability_id ? `capability ${g.capability_id}` : g.server_ref ? `server ${g.server_ref}` : text(g.scope, 'scope not recorded');
    if (g.created_at) entries.push({ at: g.created_at, label: `Authorization recorded for ${scope}`, tone: 'blue' });
    if (g.ends_at) entries.push({ at: g.ends_at, label: `Authorization for ${scope} ends`, tone: 'amber' });
    if (g.revoked_at) entries.push({ at: g.revoked_at, label: `Authorization for ${scope} revoked`, tone: 'ember' });
  }
  if (agent?.last_seen_at) entries.push({ at: agent.last_seen_at, label: 'Last observed', tone: 'blue' });
  entries.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));

  return (
    <AccessCard title="Lifecycle" testId="agent-lifecycle">
      {grants.error ? <ErrorState message={grants.error} onRetry={grants.refetch} /> : null}
      {entries.length === 0 ? (
        <p className="text-[12px]" style={MUTE}>No lifecycle timestamps were recorded for this agent.</p>
      ) : (
        <ol className="flex flex-col">
          {entries.map((e, i) => (
            <li key={`${e.at}-${e.label}-${i}`} className="flex items-start gap-3 pb-3">
              <span className="mt-1 flex flex-col items-center">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: `var(--ae-${e.tone})` }} />
              </span>
              <span className="flex flex-col leading-tight">
                <span className="text-[13px]">{e.label}</span>
                <span className="text-[11px]" style={MUTE}><Stamp iso={e.at} mode="absolute" /></span>
              </span>
            </li>
          ))}
        </ol>
      )}
      <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>Built from observation and authorization timestamps only; agent creation and termination are not reported.</span>
    </AccessCard>
  );
}

// ── Agent directory (list view) ──────────────────────────────────────────────

const RECENCY_FILTERS: ReadonlyArray<{ key: 'all' | Recency; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'today', label: 'Seen today' },
  { key: 'week', label: 'Seen this week' },
  { key: 'quiet', label: 'Quiet' },
];

const RECENCY_TONE: Record<Recency, Tone> = { today: 'sage', week: 'blue', quiet: 'mute', unknown: 'mute' };
const RECENCY_LABEL: Record<Recency, string> = { today: 'seen today', week: 'this week', quiet: 'quiet', unknown: 'not observed' };

function countText(value: number | null | undefined): string {
  return isUnknownCount(value) ? 'Unknown' : String(value);
}

function AgentDirectory({
  query,
  selectedId,
  onSelect,
  onOpen,
}: {
  readonly query: string;
  readonly selectedId: string;
  readonly onSelect: (id: string) => void;
  readonly onOpen: (id: string) => void;
}) {
  const profiles = useAgentProfiles();
  const [filter, setFilter] = useState<'all' | Recency>('all');
  const items = useMemo(() => profiles.data?.items ?? [], [profiles.data]);
  const now = Date.now();

  const filtered = items.filter(a => {
    const matchesQuery = !query || a.agent_id.toLowerCase().includes(query.toLowerCase())
      || a.providers_observed.some(p => p.toLowerCase().includes(query.toLowerCase()));
    const matchesFilter = filter === 'all' || recencyOf(a.last_seen_at, now) === filter;
    return matchesQuery && matchesFilter;
  });
  const groups = useMemo(() => {
    const byProvider = new Map<string, AgentProfileIndexEntry[]>();
    for (const agent of filtered) {
      const provider = agent.providers_observed[0] ?? '';
      byProvider.set(provider, [...(byProvider.get(provider) ?? []), agent]);
    }
    return [...byProvider.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [filtered]);

  if (profiles.isLoading && !profiles.data) return <LoadingState lines={4} />;
  if (profiles.error) return <ErrorState message={profiles.error} onRetry={profiles.refetch} />;
  const data = profiles.data;
  if (!data) return <LoadingState lines={4} />;

  if (data.items.length === 0) {
    return (
      <EmptyState
        title="No agents observed"
        description="No agent has been observed with a capability installation yet. An agent absent from this list is one we have not observed — not one without access."
      />
    );
  }

  const boundedReasons: string[] = [];
  if (data.truncated || data.complete === false || data.counts?.scope === 'scanned_window_only') {
    boundedReasons.push(
      'The agent scan hit its limit — this list covers the scanned window only, not every observed agent.',
    );
  }

  // Resolve within the visible results so the summary never describes an agent the filters hide.
  const selected = filtered.find(a => a.agent_id === selectedId) ?? filtered[0];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter agents by last observed">
          {RECENCY_FILTERS.map(f => (
            <ChoiceChip key={f.key} size="sm" selected={filter === f.key} onClick={() => setFilter(f.key)}>{f.label}</ChoiceChip>
          ))}
        </div>
        <span className="text-[12px]" style={MUTE}>
          <span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{countText(data.counts?.agents_observed)}</span> agents in this list
          {data.counts?.scope === 'scanned_window_only' ? ' · scanned window only' : ''}
        </span>
      </div>
      <PartialNotice title="This agent list is bounded" reasons={boundedReasons} />

      <div className="grid gap-[18px]" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(320px, 100%), 1fr))' }}>
        <AccessCard title="Agent network" aside={<span className="text-[11px]" style={MUTE}>grouped by observed provider</span>} testId="agent-network">
          {filtered.length === 0 ? (
            <p className="text-[12px]" style={MUTE}>No agents match.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {groups.map(([provider, agents]) => (
                <div key={provider || 'none'} className="flex flex-col">
                  <span className="flex items-center gap-2 px-1 py-1 text-[12px]">
                    {provider ? <BrandMark token={provider} size={20} markSize={12} /> : <Icon name="circle-help" decorative size="sm" />}
                    <span>{provider || 'Provider not recorded'}</span>
                    <span className="ae-mono" style={{ color: 'var(--ae-faint)' }}>{agents.length}</span>
                  </span>
                  <div className="ml-[18px] flex flex-col border-l pl-2" style={{ borderColor: 'var(--ae-edge)' }}>
                    {agents.map(agent => {
                      const recency = recencyOf(agent.last_seen_at, now);
                      const isSel = selected?.agent_id === agent.agent_id;
                      return (
                        <button
                          key={agent.agent_id}
                          type="button"
                          aria-pressed={isSel}
                          onClick={() => onSelect(agent.agent_id)}
                          onDoubleClick={() => onOpen(agent.agent_id)}
                          className="ae-focus flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-[var(--ae-glass-card)]"
                          style={{ background: isSel ? 'var(--ae-blue-tint)' : undefined }}
                          data-testid={`agent-row-${agent.agent_id}`}
                        >
                          <span style={{ color: 'var(--ae-sage)' }}><Icon name="bot" decorative size="sm" /></span>
                          <span className="ae-mono min-w-0 flex-1 truncate">{agent.agent_id}</span>
                          <TonePill tone={RECENCY_TONE[recency]}>{RECENCY_LABEL[recency]}</TonePill>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </AccessCard>

        {selected ? (
          <AccessCard title={<span className="ae-mono">{selected.agent_id}</span>} aside={<TonePill tone={RECENCY_TONE[recencyOf(selected.last_seen_at, now)]}>{RECENCY_LABEL[recencyOf(selected.last_seen_at, now)]}</TonePill>} testId="agent-summary">
            <span className="text-[12px]" style={MUTE}>
              {selected.providers_observed.length ? `via ${selected.providers_observed.join(', ')}` : 'provider not recorded'}
            </span>
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: 'Servers', value: selected.servers_observed },
                { label: 'Capabilities', value: selected.capabilities_on_installations },
                { label: 'Observations', value: selected.observations_recorded },
              ].map(k => (
                <div key={k.label} className="flex flex-col gap-0.5 rounded-[12px] px-3 py-2" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
                  {isUnknownCount(k.value) ? <UnknownValue /> : <span className="ae-mono text-[18px]">{k.value}</span>}
                  <span className="text-[11px]" style={MUTE}>{k.label}</span>
                </div>
              ))}
            </div>
            {selected.servers.length > 0 && (
              <ul className="flex flex-wrap gap-1.5">
                {selected.servers.slice(0, 6).map(s => (
                  <li key={s}><Badge variant="default" className="font-mono">{s}</Badge></li>
                ))}
              </ul>
            )}
            <span className="text-[12px]" style={MUTE}>
              Last observed {relativeTime(selected.last_seen_at, now)} · first observed {relativeTime(selected.first_seen_at, now)}
            </span>
            <div className="flex flex-wrap items-center gap-3">
              <PrimaryButton onClick={() => onOpen(selected.agent_id)} data-testid="agent-open">Open agent →</PrimaryButton>
              <Link className="ae-focus text-[12px] hover:underline" style={{ color: 'var(--ae-blue-ink)' }} to={`/agents/${encodeURIComponent(selected.agent_id)}`}>
                Agent 360 →
              </Link>
            </div>
          </AccessCard>
        ) : null}
      </div>

      {data.note ? <p className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>{data.note}</p> : null}
    </div>
  );
}

// ── Open agent view ──────────────────────────────────────────────────────────

const AGENT_TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'authority', label: 'Authority' },
  { key: 'exposure', label: 'Exposure' },
  { key: 'lifecycle', label: 'Lifecycle' },
] as const;
type AgentTab = (typeof AGENT_TABS)[number]['key'];

function AgentOpenView({
  agentId,
  tab,
  onTab,
  onBack,
}: {
  readonly agentId: string;
  readonly tab: AgentTab;
  readonly onTab: (tab: AgentTab) => void;
  readonly onBack: () => void;
}) {
  const profiles = useAgentProfiles();
  const agent = profiles.data?.items.find(a => a.agent_id === agentId);
  const recency = recencyOf(agent?.last_seen_at);

  return (
    <div className="ae-rise flex flex-col gap-[18px]" data-testid="agent-open-view">
      <span className="flex items-center gap-1 text-[13px]" style={MUTE}>
        <LinkButton onClick={onBack} tone="mute" className="text-[13px]">Agents</LinkButton>
        <span>/</span>
        <span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{agentId}</span>
      </span>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-full" style={{ background: 'var(--ae-sage-tint)', color: 'var(--ae-sage)' }}>
            <Icon name="bot" decorative size="md" />
          </span>
          <span className="flex flex-col leading-tight">
            <span className="ae-mono text-[22px] font-medium">{agentId}</span>
            <span className="text-[13px]" style={MUTE}>
              {agent ? `${RECENCY_LABEL[recency]} · ${agent.providers_observed.length ? `via ${agent.providers_observed.join(', ')}` : 'provider not recorded'}` : 'observed agent'}
            </span>
          </span>
        </span>
        <Link className="ae-card ae-focus rounded-full px-3 py-1.5 text-[12px]" to={`/agents/${encodeURIComponent(agentId)}`}>
          Agent 360 →
        </Link>
      </div>
      <div className="ae-scroll-none -mx-1 flex gap-1.5 overflow-x-auto px-1" role="group" aria-label="Agent views">
        {AGENT_TABS.map(t => (
          <ChoiceChip key={t.key} selected={tab === t.key} onClick={() => onTab(t.key)} data-testid={`agent-tab-${t.key}`}>{t.label}</ChoiceChip>
        ))}
      </div>
      <div className="ae-rise" key={tab}>
        {tab === 'overview' && <AgentProfilePanel agentId={agentId} />}
        {tab === 'authority' && <AgentAuthorityPanel agentId={agentId} />}
        {tab === 'exposure' && <BlastRadiusPanel agentId={agentId} />}
        {tab === 'lifecycle' && <AgentLifecyclePanel agent={agent} agentId={agentId} />}
      </div>
    </div>
  );
}

// ── Authorizations ───────────────────────────────────────────────────────────

function AuthorizationRows({ items }: { readonly items: readonly CapabilityAuthorization[] }) {
  const rows = items.map((authorization: CapabilityAuthorization, index: number) => ({
    authorization,
    key: authorization.authorization_id ?? `authorization-${index}`,
  }));
  return (
    <div className="overflow-x-auto">
      <DataTable
        columns={[
          {
            key: 'agent',
            header: 'Agent',
            render: r => <span className="ae-mono">{text(r.authorization.agent_id, 'Not recorded')}</span>,
          },
          {
            key: 'scope',
            header: 'Scope',
            render: r => (
              <span className="ae-mono">
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
          { key: 'starts', header: 'Starts', render: r => <Stamp iso={r.authorization.starts_at} mode="absolute" fallback="Immediately" /> },
          { key: 'ends', header: 'Ends', render: r => <Stamp iso={r.authorization.ends_at} mode="absolute" fallback="No end date" /> },
        ]}
        data={rows}
        keyExtractor={r => r.key}
      />
    </div>
  );
}

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

  return (
    <AccessCard title="Capability authorizations">
      <AuthorizationRows items={data.items} />
    </AccessCard>
  );
}

// ── Tenant-wide access (findings, inventory, authorizations) ────────────────

const TENANT_TABS = [
  { key: 'findings', label: 'Findings' },
  { key: 'inventory', label: 'Inventory' },
  { key: 'authorizations', label: 'Authorizations' },
] as const;
type TenantTab = (typeof TENANT_TABS)[number]['key'];

/**
 * Everything about the tenant's agent access that is not about one agent:
 * scan and drift findings, the observed inventory and explicit
 * authorizations. Reached from the list ("All findings"), so the list itself
 * stays the directory and the selected agent, as in the design.
 */
function TenantAccessView({
  summary,
  tab,
  onTab,
  onBack,
}: {
  readonly summary: ReturnType<typeof useAccessInventory>['data'];
  readonly tab: TenantTab;
  readonly onTab: (tab: TenantTab) => void;
  readonly onBack: () => void;
}) {
  return (
    <div className="ae-rise flex min-w-0 flex-col gap-[18px]" data-testid="agent-access-all">
      <span className="flex items-center gap-1 text-[13px]" style={MUTE}>
        <LinkButton onClick={onBack} tone="mute" className="text-[13px]">Agents</LinkButton>
        <span>/</span>
        <span style={{ color: 'var(--ae-ink)' }}>All findings</span>
      </span>
      <div className="flex max-w-[640px] flex-col gap-1">
        <h1 className="text-[28px] font-medium leading-tight tracking-[-0.56px]">All findings</h1>
        <p className="text-[14px]" style={MUTE}>
          Tenant-wide scan findings, the observed inventory and explicit authorizations. Observed reach is not
          authorization, and anything that could not be computed reads as “Unknown”, never as zero.
        </p>
      </div>
      <div className="ae-scroll-none -mx-1 flex gap-1.5 overflow-x-auto px-1" role="group" aria-label="Tenant access views">
        {TENANT_TABS.map(t => (
          <ChoiceChip key={t.key} selected={tab === t.key} onClick={() => onTab(t.key)} data-testid={`agent-access-tab-${t.key}`}>{t.label}</ChoiceChip>
        ))}
      </div>
      <div className="ae-rise min-w-0" key={tab}>
        {tab === 'findings' && (
          <Section id="agent-access-findings" title="What to look at first" description="Scan and drift findings, highest risk first.">
            <FindingsSection />
          </Section>
        )}
        {tab === 'inventory' && (
          <Section id="agent-access-inventory" title="Inventory" description="What your agents can reach, as observed.">
            {summary ? <InventorySummary summary={summary} /> : <LoadingState lines={3} />}
          </Section>
        )}
        {tab === 'authorizations' && (
          <Section id="agent-access-authorizations" title="What is authorized" description="Explicit capability authorizations. Observed reach is not authorization.">
            <AuthorizationsSection />
          </Section>
        )}
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

function isAgentTab(value: string | null): value is AgentTab {
  return AGENT_TABS.some(t => t.key === value);
}

function isTenantTab(value: string | null): value is TenantTab {
  return TENANT_TABS.some(t => t.key === value);
}

export function AgentAccessPage() {
  const inventory = useAccessInventory();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState('');
  const agentId = params.get('agent') ?? '';
  const view = params.get('view');
  const open = view === 'agent' && agentId !== '';
  const rawTab = params.get('tab');
  const tab: AgentTab = isAgentTab(rawTab) ? rawTab : 'overview';
  const tenantTab: TenantTab = isTenantTab(rawTab) ? rawTab : 'findings';

  const update = (next: Record<string, string | null>) => {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) merged.delete(k);
      else merged.set(k, v);
    }
    setParams(merged);
  };

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
  const counts = summary?.summary_known ? summary.counts : null;
  const totalsUnknown = summary?.summary_known === false;

  if (open) {
    return (
      <AgentOpenView
        agentId={agentId}
        tab={tab}
        onTab={next => update({ tab: next })}
        onBack={() => update({ view: null, tab: null })}
      />
    );
  }

  if (view === 'all') {
    return (
      <TenantAccessView
        summary={summary}
        tab={tenantTab}
        onTab={next => update({ tab: next })}
        onBack={() => update({ view: null, tab: null })}
      />
    );
  }

  const openAll = (next: TenantTab = 'findings') => update({ view: 'all', tab: next });

  return (
    <div className="ae-rise flex min-w-0 flex-col gap-[18px]" data-testid="aether-agents">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex max-w-[640px] flex-col gap-1">
          <h1 className="text-[32px] font-medium leading-tight tracking-[-0.64px]">Agents</h1>
          <p className="text-[14px]" style={MUTE}>
            Who is acting, what they can reach, and within what authority. Everything here is derived
            from observation — it is not a proof of total reach, and anything that could not be
            computed reads as “Unknown”, never as zero.
          </p>
        </div>
        <div className="flex w-full flex-col items-stretch gap-2 sm:w-auto sm:items-end">
          <input
            type="search"
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="Search agents"
            aria-label="Search agents"
            className="ae-focus w-full rounded-full px-4 py-2 text-[13px] outline-none sm:w-auto sm:min-w-[220px]"
            style={{ border: '1px solid var(--ae-edge)', background: 'var(--ae-glass-card)', color: 'var(--ae-ink)' }}
          />
          <span className="flex flex-wrap items-center gap-x-3.5 gap-y-1 text-[12px] sm:justify-end" style={MUTE} data-testid="agents-counters">
            {counts ? (
              <>
                <span><span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{countText(counts.agents)}</span> agents</span>
                <span><span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{countText(counts.authorizations_active)}</span> active authorizations</span>
                <span><span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{countText(counts.capabilities)}</span> capabilities</span>
              </>
            ) : null}
            {totalsUnknown ? (
              <button type="button" onClick={() => openAll('inventory')} className="ae-focus" data-testid="agents-totals-unknown">
                <TonePill tone="amber">Totals unknown, not zero</TonePill>
              </button>
            ) : null}
            {!nothingObserved ? (
              <LinkButton onClick={() => openAll()} className="text-[12px]">All findings →</LinkButton>
            ) : null}
          </span>
        </div>
      </header>

      {nothingObserved ? (
        <EmptyState
          title="No capability access observed yet"
          description="No agent, server, or capability has been observed for this tenant. That is an absence of observation, not evidence that your agents reach nothing."
        />
      ) : (
        <section aria-label="Who is acting" className="flex min-w-0 flex-col gap-3" id="agent-access-agents">
          <AgentDirectory
            query={query}
            selectedId={agentId}
            onSelect={id => update({ agent: id })}
            onOpen={id => update({ agent: id, view: 'agent', tab: 'overview' })}
          />
        </section>
      )}
    </div>
  );
}
