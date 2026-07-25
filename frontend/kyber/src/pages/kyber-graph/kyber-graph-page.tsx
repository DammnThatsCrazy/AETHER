/**
 * KYBER — Kyber Graph operator console (`/v1/kyber/graph`).
 *
 * Five surfaces, in the backend's own disclosure order: platform topology (D0),
 * fleet projections (D1), cohorts (D1), a bounded blast-radius review (D0), and
 * — only behind an active purpose-bound scope — one tenant's own graph (D3).
 *
 * ── The rules this page exists to keep ────────────────────────────────────────
 *
 * **A total is only a total when the backend says so.** The fleet and platform
 * surfaces keep returning integers when a read was partial; those integers count
 * what was READ. Whenever `totals_known` is false this page shows a partial
 * banner naming every missing input and renders "Unknown" in place of the
 * number. It never sums the rows it did get, and it never falls back to zero.
 *
 * **Stale is not healthy.** A stale projection row is marked stale next to its
 * state and its state badge is re-labelled `<state> · stale`, because a stale row
 * rendered green converts "we do not know" into "it is fine" and an operator
 * stops looking. `unknown` and `no_data` are likewise rendered distinctly from
 * `healthy` — neither is a clean bill of health.
 *
 * **Suppression is not absence.** A cohort below its minimum size comes back
 * suppressed with a reason; this page shows that reason instead of an empty
 * table, because an operator who cannot tell suppression from "no matches" reads
 * the second and closes the question.
 *
 * **A partial reach is never a complete one.** `exposure_known: false` renders as
 * Unknown plus reasons; `truncated: true` says the traversal was bounded and
 * shows the reduced confidence the backend assigned.
 *
 * **Routing is not a grant.** Reaching this URL grants nothing. Every section
 * renders the backend's own refusal — a 403 on the D3 tenant reads is an
 * expected, explainable "requires an active tenant scope", not a generic error.
 *
 * The honest-count primitives below (`CountTile`, `CountCell`, `PartialBanner`,
 * `CompleteBanner`, `UNKNOWN_LABEL`) are deliberate local equivalents of
 * `pages/agent-access/honest-counts.tsx`. That module is page-local to the agent
 * access surface and is not exported from any shared location, and importing
 * across page directories is not done in this repo — so the pattern is
 * reproduced here rather than reached for.
 */

import { useState, type ReactNode } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  FreshnessIndicator,
  Input,
  LoadingState,
  Select,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  formatCount,
  useTimeContext,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import {
  COHORT_SUPPRESSION_REASON,
  MAX_TRAVERSAL_DEPTH,
  isDenied,
  useBlastRadius,
  useCohortEvaluation,
  useDefineCohort,
  useFleetSummary,
  usePlatformGraph,
  useTenantGraph,
} from '@kyber/features/kyber-graph';
import type {
  AccessDenial,
  BlastRadius,
  BlastRadiusRequest,
  CohortEvaluation,
  FleetAggregate,
  FleetSummary,
  Guarded,
  PlatformGraph,
  PlatformNode,
  QueryState,
  TenantGraph,
  TenantGraphQuery,
} from '@kyber/features/kyber-graph';
import { cn } from '@kyber/lib/utils';

const PAGE_SUBTITLE =
  'Platform topology, fleet projections, cohorts and blast radius — read at the lowest disclosure that answers the question. Nothing here is summed across a partial read, and nothing stale is shown as current.';

// ── Honest rendering primitives (local; see the module note above) ────────────

export const UNKNOWN_LABEL = 'Unknown';

const NO_REASON_REPORTED =
  'The API reported no reason. Treat this as unknown, not as zero.';

/** Humanize a `missing_inputs` entry (`resource:reason:key=value`) for an operator. */
function describeMissingInput(entry: string): string {
  const [resource, ...rest] = entry.split(':');
  const detail = rest.join(':');
  const resourceLabel = (resource ?? entry).replace(/_/g, ' ');
  return detail ? `${resourceLabel} — ${detail.replace(/_/g, ' ')}` : resourceLabel;
}

function UnknownReason({ reasons }: { readonly reasons: readonly string[] }) {
  return (
    <div className="mt-1 text-[10px] text-text-muted font-mono leading-snug">
      {reasons.length === 0 ? (
        NO_REASON_REPORTED
      ) : (
        <ul className="space-y-0.5">
          {reasons.map(reason => (
            <li key={reason}>· {describeMissingInput(reason)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface CountTileProps {
  readonly label: string;
  readonly value: number | null | undefined;
  readonly reasons?: readonly string[] | undefined;
}

/** One count. `null`/`undefined` becomes "Unknown" plus the reason — never a zero. */
function CountTile({ label, value, reasons = [] }: CountTileProps) {
  const localeCtx = useTimeContext();
  const unknown = value === null || value === undefined;
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        {unknown ? (
          <>
            <div className="mt-1 text-2xl font-semibold text-warning font-mono">
              {UNKNOWN_LABEL}
            </div>
            <UnknownReason reasons={reasons} />
          </>
        ) : (
          <div className="mt-1 text-2xl font-semibold text-text-primary font-mono">
            {formatCount(value, localeCtx)}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** A count inside a table cell. Same rule, smaller. */
function CountCell({ value }: { readonly value: number | null | undefined }) {
  const localeCtx = useTimeContext();
  if (value === null || value === undefined) {
    return <span className="text-warning font-mono">{UNKNOWN_LABEL}</span>;
  }
  return <span className="font-mono text-text-primary">{formatCount(value, localeCtx)}</span>;
}

/** Shown whenever totals could not be computed. States plainly that this is not a total. */
function PartialBanner({
  subject,
  missingInputs,
}: {
  readonly subject: string;
  readonly missingInputs: readonly string[];
}) {
  return (
    <div
      role="status"
      className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
    >
      <div className="font-semibold font-mono">
        Partial read — {subject} totals are Unknown, not zero
      </div>
      <div className="mt-1 text-text-secondary">
        One or more inputs could not be read, so no total is shown. The rows below are
        evidence from the inputs that did answer — their sum is not a total.
      </div>
      <UnknownReason reasons={missingInputs} />
    </div>
  );
}

/** Shown when every input was readable, so the totals really are totals. */
function CompleteBanner({ summary }: { readonly summary: string }) {
  return (
    <div
      role="status"
      className="rounded border border-border-default bg-surface-raised px-3 py-2 text-xs text-text-secondary"
    >
      <span className="font-semibold font-mono text-success">Complete read</span> — {summary}
    </div>
  );
}

/**
 * Health, rendered so that no absence of knowledge can read as good news.
 *
 * `unknown` and `no_data` each get their own label and tone, distinct from
 * `healthy`; and a stale row is re-labelled `<state> · stale` so the state can
 * never be read as current.
 */
function HealthBadge({
  health,
  stale = false,
}: {
  readonly health: string | null | undefined;
  readonly stale?: boolean;
}) {
  const value = (health ?? 'unknown').toLowerCase();
  if (stale) {
    return <Badge variant="warning">{`${value} · stale`}</Badge>;
  }
  if (value === 'healthy') return <Badge variant="success">healthy</Badge>;
  if (value === 'degraded') return <Badge variant="warning">degraded</Badge>;
  if (value === 'failing') return <Badge variant="danger">failing</Badge>;
  if (value === 'no_data') return <Badge variant="info">no data</Badge>;
  if (value === 'unknown') return <Badge variant="warning">unknown</Badge>;
  return <Badge variant="default">{value}</Badge>;
}

function StaleNotice({
  ageSeconds,
  maxAgeSeconds,
}: {
  readonly ageSeconds: number | null | undefined;
  readonly maxAgeSeconds: number | null | undefined;
}) {
  return (
    <div
      role="status"
      className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
    >
      <div className="font-semibold font-mono">Stale — this is not a current answer</div>
      <div className="mt-1 text-text-secondary">
        The oldest input is{' '}
        {ageSeconds === null || ageSeconds === undefined
          ? 'of unknown age'
          : `${Math.round(ageSeconds)} seconds old`}
        {maxAgeSeconds === null || maxAgeSeconds === undefined
          ? ''
          : `, past the ${maxAgeSeconds} second freshness bound`}
        . A stale row rendered healthy converts &ldquo;we do not know&rdquo; into &ldquo;it is
        fine&rdquo;, so treat the state beside it as unverified rather than current.
      </div>
    </div>
  );
}

/** The backend refused. That is an answer with a reason, not a broken surface. */
function AccessDenialPanel({ denial }: { readonly denial: AccessDenial }) {
  return (
    <div
      role="status"
      className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
    >
      <div className="font-semibold font-mono">
        {denial.scopeRequired
          ? 'Requires an active tenant scope'
          : 'Requires a capability this session does not hold'}
      </div>
      <div className="mt-1 text-text-secondary">
        {denial.scopeRequired
          ? 'Reading a tenant’s own graph needs a live, purpose-bound access scope naming that tenant. Reaching this page is not that grant — request a scope, then retry. Nothing about this tenant is implied either way.'
          : 'The backend declined this read. This is an authorization outcome, not a failure of the surface, and no part of the answer is being withheld from you by this page.'}
      </div>
      <div className="mt-1 text-text-secondary">Backend reason: {denial.reason}</div>
      {denial.denialReason !== null && (
        <div className="mt-0.5 font-mono text-[10px] text-text-muted">
          denial_reason: {denial.denialReason}
        </div>
      )}
    </div>
  );
}

// ── Section shell ────────────────────────────────────────────────────────────

interface GuardedSectionProps<T> {
  readonly state: QueryState<Guarded<T>>;
  readonly errorTitle: string;
  readonly emptyTitle: string;
  readonly idle?: ReactNode;
  readonly children: (value: T) => ReactNode;
}

/**
 * Loading / denied / error / empty, in that order.
 *
 * Denial is checked before the error branch on purpose: a 403 already resolved
 * into an explanation, and letting the generic error banner win would replace a
 * precise, actionable statement with "Request failed".
 */
function GuardedSection<T>({
  state,
  errorTitle,
  emptyTitle,
  idle,
  children,
}: GuardedSectionProps<T>) {
  const { data, loading, error, refresh } = state;
  if (idle !== undefined && data === null && !loading && error === null) {
    return <>{idle}</>;
  }
  if (loading && data === null) return <LoadingState lines={4} />;
  if (isDenied(data)) return <AccessDenialPanel denial={data} />;
  if (error !== null) return <ErrorState title={errorTitle} message={error} onRetry={refresh} />;
  if (data === null) return <EmptyState title={emptyTitle} />;
  return <>{children(data as T)}</>;
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, ' ');
}

// ── 1. Platform topology (D0) ────────────────────────────────────────────────

function PlatformCard() {
  const state = usePlatformGraph();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Platform topology (D0)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-text-secondary">
          Services, worker roles, releases, deployments and feature surfaces. One bounded
          query per node type — never one per tenant — and no node here carries a tenant.
        </p>
        <GuardedSection<PlatformGraph>
          state={state}
          errorTitle="Unable to load platform topology"
          emptyTitle="No platform topology returned"
        >
          {graph => <PlatformBody graph={graph} />}
        </GuardedSection>
      </CardContent>
    </Card>
  );
}

interface FlatPlatformNode extends PlatformNode {
  readonly bucket: string;
}

function PlatformBody({ graph }: { readonly graph: PlatformGraph }) {
  const nodeTypes = Object.keys(graph.nodes).sort();
  const healthKeys = Object.keys(graph.by_health).sort();
  const rows: FlatPlatformNode[] = [];
  for (const nodeType of nodeTypes) {
    for (const node of graph.nodes[nodeType] ?? []) {
      rows.push({ ...node, bucket: nodeType });
    }
  }

  return (
    <>
      {graph.totals_known ? (
        <CompleteBanner
          summary={`Every platform node type answered in ${graph.queries_issued} bounded queries.`}
        />
      ) : (
        <PartialBanner subject="platform topology" missingInputs={graph.missing_inputs} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-text-muted font-mono">Platform state</span>
        <HealthBadge health={graph.state} />
        <FreshnessIndicator computedAt={graph.computed_at} />
        {graph.truncated && <Badge variant="warning">Scan truncated</Badge>}
        {!graph.available && <Badge variant="warning">Graph store unavailable</Badge>}
      </div>

      <div data-testid="platform-totals" className="grid gap-3 md:grid-cols-2">
        <CountTile
          label="Platform nodes"
          value={graph.totals_known ? (graph.node_count ?? null) : null}
          reasons={graph.missing_inputs}
        />
        <CountTile
          label="Node types answered"
          value={graph.totals_known ? nodeTypes.length : null}
          reasons={graph.missing_inputs}
        />
      </div>

      {healthKeys.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] text-text-muted font-mono">
            Health of the nodes that were read
            {graph.totals_known ? '' : ' — observed only, not a distribution over the platform'}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {healthKeys.map(key => (
              <span key={key} className="flex items-center gap-1">
                <HealthBadge health={key} />
                <CountCell value={graph.by_health[key]} />
              </span>
            ))}
          </div>
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState
          title={
            graph.totals_known
              ? 'No platform nodes in this environment'
              : 'No platform node could be read'
          }
          description={
            graph.totals_known
              ? 'The topology read completed and returned nothing. This is an empty platform, not an unread one.'
              : 'The read was incomplete, so this is not evidence that the platform is empty.'
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-border-default text-text-muted">
                <th className="py-2 px-2 text-left">Node</th>
                <th className="py-2 px-2 text-left">Type</th>
                <th className="py-2 px-2 text-left">Environment</th>
                <th className="py-2 px-2 text-left">Health</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(node => (
                <tr
                  key={`${node.bucket}:${node.node_key ?? node.display_name ?? 'unkeyed'}`}
                  className="border-b border-border-subtle"
                >
                  <td className="py-2 px-2 text-text-primary">
                    {node.display_name ?? node.node_key ?? 'unnamed node'}
                  </td>
                  <td className="py-2 px-2 text-text-secondary">
                    {node.node_type ?? node.bucket}
                  </td>
                  <td className="py-2 px-2 text-text-secondary">
                    {node.environment ?? 'all environments'}
                  </td>
                  <td className="py-2 px-2">
                    <HealthBadge health={node.health} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ── 2. Fleet (D1) ────────────────────────────────────────────────────────────

function FleetCard() {
  const state = useFleetSummary();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Fleet projections (D1)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-text-secondary">
          Precomputed aggregates, so freshness is part of the answer rather than a footnote.
          Counts and distributions only — no tenant is named at this level.
        </p>
        <GuardedSection<FleetSummary>
          state={state}
          errorTitle="Unable to load fleet projections"
          emptyTitle="No fleet summary returned"
        >
          {summary => <FleetBody summary={summary} />}
        </GuardedSection>
      </CardContent>
    </Card>
  );
}

function FleetBody({ summary }: { readonly summary: FleetSummary }) {
  const names = Object.keys(summary.projections).sort();

  return (
    <>
      {summary.totals_known ? (
        <CompleteBanner
          summary={`Every projection row was read in ${summary.queries_issued} query. Fleet state: ${summary.state}.`}
        />
      ) : (
        <PartialBanner subject="fleet" missingInputs={summary.missing_inputs} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-text-muted font-mono">Fleet state</span>
        <HealthBadge health={summary.state} stale={summary.stale} />
        <FreshnessIndicator computedAt={summary.oldest_computed_at} />
      </div>

      {summary.stale && (
        <StaleNotice
          ageSeconds={summary.oldest_row_age_seconds}
          maxAgeSeconds={summary.max_age_seconds}
        />
      )}

      {/*
        Gated on `totals_known`, not on nullness: the backend keeps returning
        integers for a partial read, and those integers count what was read.
        Presenting one as a fleet total is the exact lie this section forbids.
      */}
      <div data-testid="fleet-totals" className="grid gap-3 md:grid-cols-2">
        <CountTile
          label="Tenants in fleet"
          value={summary.totals_known ? summary.tenant_count : null}
          reasons={summary.missing_inputs}
        />
        <CountTile
          label="Projections"
          value={summary.totals_known ? summary.projection_count : null}
          reasons={summary.missing_inputs}
        />
      </div>

      {names.length === 0 ? (
        <EmptyState
          title="No fleet projection rows"
          description="The projection table returned nothing. Nothing has been projected yet, or the projector has not run — either way this is not a healthy fleet."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-border-default text-text-muted">
                <th className="py-2 px-2 text-left">Projection</th>
                <th className="py-2 px-2 text-left">State</th>
                <th className="py-2 px-2 text-left">Freshness</th>
                <th className="py-2 px-2 text-right">Rows read</th>
                <th className="py-2 px-2 text-right">Tenants read</th>
                <th className="py-2 px-2 text-left">Why unknown</th>
              </tr>
            </thead>
            <tbody>
              {names.map(name => (
                <FleetProjectionRow
                  key={name}
                  name={name}
                  aggregate={summary.projections[name] as FleetAggregate}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function FleetProjectionRow({
  name,
  aggregate,
}: {
  readonly name: string;
  readonly aggregate: FleetAggregate;
}) {
  return (
    <tr
      data-testid={`fleet-row-${name}`}
      className={cn(
        'border-b border-border-subtle',
        aggregate.stale && 'bg-warning/5',
      )}
    >
      <td className="py-2 px-2 text-text-primary">{name}</td>
      <td className="py-2 px-2">
        <HealthBadge health={aggregate.state} stale={aggregate.stale} />
      </td>
      <td className="py-2 px-2">
        {aggregate.stale ? (
          <Badge variant="warning">Stale — not current</Badge>
        ) : (
          <Badge variant="success">Current</Badge>
        )}
        <div className="mt-0.5 text-[10px] text-text-muted">
          {aggregate.oldest_computed_at === null
            ? 'oldest row has no readable timestamp'
            : `oldest row ${aggregate.oldest_computed_at}`}
        </div>
      </td>
      <td className="py-2 px-2 text-right">
        <CountCell value={aggregate.totals_known ? aggregate.row_count : null} />
      </td>
      <td className="py-2 px-2 text-right">
        <CountCell value={aggregate.totals_known ? aggregate.tenant_count : null} />
      </td>
      <td className="py-2 px-2 text-text-muted">
        {aggregate.missing_inputs.length === 0
          ? ''
          : aggregate.missing_inputs.map(describeMissingInput).join('; ')}
      </td>
    </tr>
  );
}

// ── 3. Cohorts (D1) ──────────────────────────────────────────────────────────

function CohortsCard() {
  const [name, setName] = useState('');
  const [projection, setProjection] = useState('');
  const [environment, setEnvironment] = useState('');
  const [minimumSize, setMinimumSize] = useState('3');
  const [cohortId, setCohortId] = useState<string | null>(null);
  const [lookupId, setLookupId] = useState('');

  const define = useDefineCohort();
  const evaluation = useCohortEvaluation(cohortId);

  const canDefine = name.trim() !== '';
  const parsedMinimum = Number.parseInt(minimumSize, 10);

  const onDefine = async (): Promise<void> => {
    const filters: Record<string, unknown> = {};
    if (projection.trim() !== '') filters['projection'] = projection.trim();
    if (environment.trim() !== '') filters['environment'] = environment.trim();
    const result = await define.mutate({
      name: name.trim(),
      filters,
      minimumSize: Number.isNaN(parsedMinimum) ? 3 : parsedMinimum,
    });
    if (result !== null && !isDenied(result)) {
      setCohortId(result.cohort.cohort_id);
      setLookupId(result.cohort.cohort_id);
    }
  };

  const defined = define.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cohorts (D1)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-text-secondary">
          A cohort is a saved query over fleet projections — never over tenant records. A
          cohort resolving below its minimum size is suppressed and says so, because
          suppression and absence are different answers.
        </p>

        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-text-muted font-mono">
            Cohort name (required)
            <Input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="degraded-eu-west"
            />
          </label>
          <label className="text-xs text-text-muted font-mono">
            Projection filter
            <Input
              value={projection}
              onChange={e => setProjection(e.target.value)}
              placeholder="graph_health"
            />
          </label>
          <label className="text-xs text-text-muted font-mono">
            Environment filter
            <Input
              value={environment}
              onChange={e => setEnvironment(e.target.value)}
              placeholder="production"
            />
          </label>
          <label className="text-xs text-text-muted font-mono">
            Minimum size
            <Input
              value={minimumSize}
              onChange={e => setMinimumSize(e.target.value)}
              placeholder="3"
            />
          </label>
          <Button size="sm" disabled={!canDefine || define.isLoading} onClick={() => void onDefine()}>
            Define cohort
          </Button>
        </div>

        {define.error !== null && (
          <ErrorState title="Unable to define cohort" message={define.error} />
        )}
        {isDenied(defined) && <AccessDenialPanel denial={defined} />}
        {defined !== null && !isDenied(defined) && defined.normalised && (
          <div
            role="status"
            className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
          >
            <div className="font-semibold font-mono">Definition normalised on the way in</div>
            <div className="mt-1 text-text-secondary">
              The backend stored something other than what was submitted — unsupported filter
              keys are dropped and a minimum size below the floor is raised. Stored minimum
              size: {defined.cohort.minimum_size}. Stored filters:{' '}
              {Object.keys(defined.cohort.filters).sort().join(', ') || 'none'}.
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-text-muted font-mono">
            Evaluate an existing cohort
            <Input
              value={lookupId}
              onChange={e => setLookupId(e.target.value)}
              placeholder="kco_0001"
            />
          </label>
          <Button
            size="sm"
            variant="secondary"
            disabled={lookupId.trim() === ''}
            onClick={() => setCohortId(lookupId.trim())}
          >
            Evaluate
          </Button>
        </div>

        <GuardedSection<CohortEvaluation>
          state={evaluation}
          errorTitle="Unable to evaluate cohort"
          emptyTitle="No cohort evaluation returned"
          idle={
            <EmptyState
              title="Define or name a cohort to evaluate"
              description="A cohort is evaluated over fleet projections only; it never reaches a tenant record."
            />
          }
        >
          {result => <CohortBody evaluation={result} />}
        </GuardedSection>
      </CardContent>
    </Card>
  );
}

function CohortBody({ evaluation }: { readonly evaluation: CohortEvaluation }) {
  if (evaluation.suppressed) {
    return (
      <div
        role="status"
        className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
      >
        <div className="font-semibold font-mono">
          Cohort suppressed — this is not an empty cohort
        </div>
        <div className="mt-1 text-text-secondary">
          Suppression reason:{' '}
          <span className="font-mono">{evaluation.reason ?? COHORT_SUPPRESSION_REASON}</span>. This
          cohort resolved to fewer members than its minimum size of {evaluation.minimum_size}, so
          the backend withheld the member count — at that size the count is the identification.
          Read this as &ldquo;too few to disclose&rdquo;, never as &ldquo;no tenant matched&rdquo;.
        </div>
        <UnknownReason reasons={evaluation.missing_inputs} />
      </div>
    );
  }

  const byState = evaluation.by_state ?? {};
  const stateKeys = Object.keys(byState).sort();
  const members = evaluation.members;

  return (
    <>
      {evaluation.totals_known ? (
        <CompleteBanner
          summary={`Cohort ${evaluation.name} resolved over every projection row that matched.`}
        />
      ) : (
        <PartialBanner subject="cohort" missingInputs={evaluation.missing_inputs} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-text-muted font-mono">Cohort state</span>
        <HealthBadge health={evaluation.state} stale={evaluation.stale} />
        {evaluation.stale && <Badge variant="warning">Stale — not current</Badge>}
      </div>

      <div data-testid="cohort-totals" className="grid gap-3 md:grid-cols-2">
        <CountTile
          label="Members"
          value={evaluation.totals_known ? evaluation.member_count : null}
          reasons={evaluation.missing_inputs}
        />
        <CountTile
          label="Projection rows matched"
          value={evaluation.totals_known ? (evaluation.row_count ?? null) : null}
          reasons={evaluation.missing_inputs}
        />
      </div>

      {stateKeys.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {stateKeys.map(key => (
            <span key={key} className="flex items-center gap-1">
              <HealthBadge health={key} />
              <CountCell value={byState[key]} />
            </span>
          ))}
        </div>
      )}

      {members === null ? (
        <div className="text-xs text-text-muted font-mono">
          Member identifiers are withheld: this session does not hold{' '}
          <span className="text-text-secondary">kyber.graph.fleet.read</span>. The aggregate above
          is the whole answer available at this capability.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-border-default text-text-muted">
                <th className="py-2 px-2 text-left">Member tenant</th>
              </tr>
            </thead>
            <tbody>
              {members.map(member => (
                <tr key={member} className="border-b border-border-subtle">
                  <td className="py-2 px-2 text-text-primary">{member}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ── 4. Blast radius (D0) ─────────────────────────────────────────────────────

const SUBJECT_TYPES = [
  { value: 'Service', label: 'Service' },
  { value: 'WorkerRole', label: 'Worker role' },
  { value: 'Release', label: 'Release' },
  { value: 'Deployment', label: 'Deployment' },
  { value: 'FeatureSurface', label: 'Feature surface' },
  { value: 'ModelDeployment', label: 'Model deployment' },
  { value: 'Projection', label: 'Projection' },
] as const;

function BlastRadiusCard() {
  const [subjectType, setSubjectType] = useState<string>('Service');
  const [subjectId, setSubjectId] = useState('');
  const [environment, setEnvironment] = useState('');
  const [depth, setDepth] = useState(String(MAX_TRAVERSAL_DEPTH));
  const [request, setRequest] = useState<BlastRadiusRequest | null>(null);

  const state = useBlastRadius(request);
  const canReview = subjectId.trim() !== '';

  const onReview = (): void => {
    const parsedDepth = Number.parseInt(depth, 10);
    setRequest({
      subjectType,
      subjectId: subjectId.trim(),
      environment: environment.trim() === '' ? undefined : environment.trim(),
      maxDepth: Number.isNaN(parsedDepth) ? MAX_TRAVERSAL_DEPTH : parsedDepth,
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Blast radius (D0)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-text-secondary">
          What a change to one platform subject can reach. Per subject by design — there is no
          fleet-wide rollup, because summing it would hide exactly the subjects whose inputs
          were missing.
        </p>

        <div className="flex flex-wrap items-end gap-2">
          <Select
            label="Subject type"
            value={subjectType}
            onChange={setSubjectType}
            options={SUBJECT_TYPES.map(o => ({ value: o.value, label: o.label }))}
          />
          <label className="text-xs text-text-muted font-mono">
            Subject id (required)
            <Input
              value={subjectId}
              onChange={e => setSubjectId(e.target.value)}
              placeholder="identity-worker"
            />
          </label>
          <label className="text-xs text-text-muted font-mono">
            Environment
            <Input
              value={environment}
              onChange={e => setEnvironment(e.target.value)}
              placeholder="production"
            />
          </label>
          <label className="text-xs text-text-muted font-mono">
            Max depth
            <Input value={depth} onChange={e => setDepth(e.target.value)} placeholder="3" />
          </label>
          <Button size="sm" disabled={!canReview} onClick={onReview}>
            Review
          </Button>
        </div>

        <GuardedSection<BlastRadius>
          state={state}
          errorTitle="Unable to load blast radius"
          emptyTitle="No blast radius returned"
          idle={
            <EmptyState
              title="Name a subject to review"
              description="A blast radius is only meaningful for one named platform subject."
            />
          }
        >
          {review => <BlastRadiusBody review={review} />}
        </GuardedSection>
      </CardContent>
    </Card>
  );
}

function BlastRadiusBody({ review }: { readonly review: BlastRadius }) {
  const known = review.exposure_known;
  const buckets: readonly { readonly label: string; readonly values: readonly string[] }[] = [
    { label: 'Services reached', values: review.affected_services },
    { label: 'Feature surfaces reached', values: review.affected_features },
    { label: 'Tenants reached', values: review.affected_tenants },
    { label: 'Graph domains reached', values: review.affected_graph_domains },
  ];

  return (
    <>
      {known ? (
        <CompleteBanner
          summary={`Every input for ${review.subject_type} ${review.subject_id} was readable, and the walk finished inside its budget.`}
        />
      ) : (
        <PartialBanner subject="exposure" missingInputs={review.missing_inputs} />
      )}

      {review.truncated && (
        <div
          role="status"
          className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
        >
          <div className="font-semibold font-mono">
            Traversal was bounded — this reach is a lower bound, not the reach
          </div>
          <div className="mt-1 text-text-secondary">
            The walk hit its node budget and stopped before the graph did, so nodes it never
            reached are missing from everything below. The backend lowered its confidence to{' '}
            {review.confidence.toFixed(2)} for exactly this reason; do not read the list as
            complete.
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted font-mono">
        <span>Confidence {review.confidence.toFixed(2)}</span>
        <span>Depth reached {review.traversal_depth}</span>
        {review.customer_visible ? (
          <Badge variant="warning">Customer visible</Badge>
        ) : (
          <Badge variant="default">No tenant or feature reached</Badge>
        )}
        <FreshnessIndicator computedAt={review.computed_at} />
      </div>

      {review.delegated_surface !== null && review.delegated_surface !== undefined && (
        <div className="text-xs text-text-secondary">
          This subject is owned by the agent-access plane and is answered per tenant there:{' '}
          <span className="font-mono">{review.delegated_surface}</span>.
        </div>
      )}

      {/*
        Counts only when `exposure_known`. The lists below are what the walk saw;
        their lengths are a lower bound on the reach, and presenting a lower bound
        as a count is how a partial reach reads as a complete one.
      */}
      <div data-testid="blast-totals" className="grid gap-3 md:grid-cols-4">
        {buckets.map(bucket => (
          <CountTile
            key={bucket.label}
            label={bucket.label}
            value={known ? bucket.values.length : null}
            reasons={review.missing_inputs}
          />
        ))}
      </div>

      {buckets.every(bucket => bucket.values.length === 0) ? (
        <EmptyState
          title={known ? 'Nothing within reach' : 'No reach could be established'}
          description={
            known
              ? 'The walk completed from a resolved anchor and found nothing downstream of this subject.'
              : 'The inputs needed for this review were not available, so no conclusion about reach can be drawn — this is not evidence of a safe change.'
          }
        />
      ) : (
        <div className="space-y-2">
          <div className="text-[10px] text-text-muted font-mono">
            {known
              ? 'Everything the walk reached.'
              : 'Observed so far — a lower bound on the reach, never all of it.'}
          </div>
          {buckets
            .filter(bucket => bucket.values.length > 0)
            .map(bucket => (
              <div key={bucket.label} className="text-xs">
                <div className="text-text-muted font-mono">{bucket.label}</div>
                <div className="text-text-primary font-mono break-all">
                  {bucket.values.join(', ')}
                </div>
              </div>
            ))}
        </div>
      )}
    </>
  );
}

// ── 5. One scoped tenant (D3) ────────────────────────────────────────────────

function TenantScopeCard() {
  const [tenantId, setTenantId] = useState('');
  const [vertexType, setVertexType] = useState('');
  const [query, setQuery] = useState<TenantGraphQuery | null>(null);
  const state = useTenantGraph(query);

  return (
    <Card>
      <CardHeader>
        <CardTitle>One scoped tenant (D3)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-text-secondary">
          The only path from Kyber into a tenant&rsquo;s own graph, and it requires a live,
          purpose-bound access scope naming that tenant. Reaching this page is not that grant.
        </p>

        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-text-muted font-mono">
            Tenant id (required)
            <Input
              value={tenantId}
              onChange={e => setTenantId(e.target.value)}
              placeholder="tenant_001"
            />
          </label>
          <label className="text-xs text-text-muted font-mono">
            Vertex type
            <Input
              value={vertexType}
              onChange={e => setVertexType(e.target.value)}
              placeholder="Profile"
            />
          </label>
          <Button
            size="sm"
            disabled={tenantId.trim() === ''}
            onClick={() =>
              setQuery({
                tenantId: tenantId.trim(),
                vertexType: vertexType.trim() === '' ? undefined : vertexType.trim(),
              })
            }
          >
            Read scoped graph
          </Button>
        </div>

        <GuardedSection<TenantGraph>
          state={state}
          errorTitle="Unable to read the scoped tenant graph"
          emptyTitle="No tenant graph returned"
          idle={
            <EmptyState
              title="Name the tenant your scope was granted for"
              description="A scoped read answers for exactly one tenant — the one the active scope names. Any other tenant is denied, never quietly rescoped."
            />
          }
        >
          {graph => <TenantGraphBody graph={graph} />}
        </GuardedSection>
      </CardContent>
    </Card>
  );
}

function TenantGraphBody({ graph }: { readonly graph: TenantGraph }) {
  const visible = graph.tenantVisible;
  const diagnostics = graph.operatorDiagnostics;

  return (
    <>
      {diagnostics.exposure_known ? (
        <CompleteBanner
          summary={`One page of ${visible.tenant_id}'s own graph, read inside the granted scope.`}
        />
      ) : (
        <PartialBanner subject="tenant graph" missingInputs={diagnostics.missing_inputs} />
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted font-mono">
        <Badge variant="info">{diagnostics.granted_disclosure ?? 'disclosure unreported'}</Badge>
        {diagnostics.identifiers_masked && <Badge variant="warning">Identifiers masked</Badge>}
        {visible.truncated && <Badge variant="warning">Page truncated — there is more</Badge>}
        {diagnostics.evidence_disclosure_gated && (
          <Badge variant="default">Evidence references gated</Badge>
        )}
        <FreshnessIndicator computedAt={diagnostics.computed_at} />
      </div>

      <div data-testid="tenant-totals" className="grid gap-3 md:grid-cols-2">
        <CountTile
          label="Vertices on this page"
          value={visible.vertex_count}
          reasons={diagnostics.missing_inputs}
        />
        <CountTile
          label="Evidence references"
          value={diagnostics.evidence_reference_count}
          reasons={diagnostics.missing_inputs}
        />
      </div>

      {visible.vertices.length === 0 ? (
        <EmptyState
          title="No vertices on this page"
          description="Nothing matched inside the scope. A tenant page that is empty and a tenant that could not be read are different answers — the banner above says which this is."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-border-default text-text-muted">
                <th className="py-2 px-2 text-left">Vertex</th>
                <th className="py-2 px-2 text-left">Type</th>
              </tr>
            </thead>
            <tbody>
              {visible.vertices.map((vertex, index) => (
                <tr
                  key={vertex.vertex_id ?? `vertex-${index}`}
                  className="border-b border-border-subtle"
                >
                  <td className="py-2 px-2 text-text-primary">
                    {vertex.vertex_id ?? 'unidentified vertex'}
                  </td>
                  <td className="py-2 px-2 text-text-secondary">
                    {vertex.vertex_type ?? 'untyped'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function KyberGraphPage() {
  return (
    <PageWrapper title="Kyber Graph" subtitle={PAGE_SUBTITLE}>
      <Tabs defaultValue="platform">
        <TabsList>
          <TabsTrigger value="platform">Platform</TabsTrigger>
          <TabsTrigger value="fleet">Fleet</TabsTrigger>
          <TabsTrigger value="cohorts">Cohorts</TabsTrigger>
          <TabsTrigger value="blast-radius">Blast radius</TabsTrigger>
          <TabsTrigger value="tenant">Tenant scope</TabsTrigger>
        </TabsList>

        <TabsContent value="platform">
          <PlatformCard />
        </TabsContent>
        <TabsContent value="fleet">
          <FleetCard />
        </TabsContent>
        <TabsContent value="cohorts">
          <CohortsCard />
        </TabsContent>
        <TabsContent value="blast-radius">
          <BlastRadiusCard />
        </TabsContent>
        <TabsContent value="tenant">
          <TenantScopeCard />
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
