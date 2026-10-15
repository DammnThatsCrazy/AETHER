/**
 * Kyber — Ingestion control plane (WS-E 2/3/4, blueprint Gate G).
 *
 * Operator surface over the Kyber ingestion observability + replay endpoints
 * plus the SDK capability manifest and the (previously phantom) pipeline-health
 * endpoint. It renders only what the backend reports:
 *
 *   · a pipeline-health banner (GET /v1/health/pipeline),
 *   · the ingestion funnel (per-stage buckets + rollup),
 *   · the Observation Inspector (one observation's RAW→…→METRICS/FINDINGS trace),
 *   · recent observation traces,
 *   · the SDK fleet view (mounts the pre-built SdkFleetMonitor — not rebuilt),
 *   · the SDK version-compatibility tier manifest,
 *   · replay-service status.
 *
 * Honest disabled states: while AETHER_INGESTION_OBSERVABILITY_ENABLED is OFF the
 * observability surfaces report `enabled: false` / empty and the page renders
 * that state; the SDK tier manifest and replay status are read regardless and
 * carry their own `enabled`/`mode` fields. Routing to this page is not a grant —
 * the /v1/kyber/* endpoints are Kyber-operator-only and gate every request.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api/endpoints';
import { SdkFleetMonitor } from '@kyber/components/sdk-monitoring';
import type {
  FunnelRollup,
  FunnelSnapshot,
  FunnelStageBucket,
  ObservabilityStatus,
  ObservationTrace,
  PipelineHealth,
  RecentTracesResponse,
  ReplayStatus,
  SdkVersionTiersEnvelope,
  SdkVersionTiersPayload,
  StageDisposition,
  TraceResponse,
  TraceSpan,
} from './types';

const DISPOSITION_VARIANT: Record<StageDisposition, 'success' | 'info' | 'warning' | 'danger' | 'default'> = {
  accepted: 'success',
  duplicate: 'info',
  rejected: 'danger',
  degraded: 'warning',
  observed: 'default',
};

function settledValue<T>(result: PromiseSettledResult<unknown>): T | undefined {
  return result.status === 'fulfilled' ? (result.value as T) : undefined;
}

function settledReason(result: PromiseSettledResult<unknown>): string | undefined {
  return result.status === 'rejected'
    ? result.reason instanceof Error
      ? result.reason.message
      : String(result.reason)
    : undefined;
}

/** Whether the FunnelSnapshot or ObservabilityStatus body says telemetry is OFF. */
function disabledExplainer(enabled: boolean | undefined, enabledKey: string): string {
  return enabled === false
    ? `${enabledKey} is OFF — this process recorded no ingestion telemetry. Flip AETHER_INGESTION_OBSERVABILITY_ENABLED and restart to begin recording.`
    : 'Telemetry flag is ON but no observations have been recorded yet by this process.';
}

interface OpsState {
  status: ObservabilityStatus | undefined;
  pipeline: PipelineHealth | undefined;
  funnel: FunnelSnapshot | undefined;
  recent: readonly ObservationTrace[] | undefined;
  replay: ReplayStatus | undefined;
  tiers: SdkVersionTiersPayload | undefined;
  failed: readonly string[];
}

function dispositionChips(stage: FunnelStageBucket) {
  const entries = Object.entries(stage.by_status) as Array<[StageDisposition, number]>;
  if (entries.length === 0) return <span className="text-xs text-text-muted">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([status, count]) => (
        <span
          key={status}
          className="inline-flex items-center gap-1 rounded border border-border-subtle px-1.5 py-0.5 text-[10px] font-mono"
        >
          <Badge variant={DISPOSITION_VARIANT[status]} size="sm">
            {status}
          </Badge>
          <span className="tabular-nums text-text-secondary">{count}</span>
        </span>
      ))}
    </div>
  );
}

function RollupGrid({ rollup }: { readonly rollup: FunnelRollup }) {
  const cells: Array<{ label: string; value: number; color: string }> = [
    { label: 'Received', value: rollup.received, color: 'text-text-primary' },
    { label: 'Accepted', value: rollup.accepted, color: 'text-green-600' },
    { label: 'Duplicates', value: rollup.duplicates, color: 'text-text-secondary' },
    { label: 'Rejected', value: rollup.rejected, color: 'text-red-500' },
    { label: 'Degraded', value: rollup.degraded, color: 'text-yellow-600' },
  ];
  return (
    <div className="flex flex-wrap items-center gap-2">
      {cells.map((cell) => (
        <div
          key={cell.label}
          className="flex flex-col items-start rounded border border-border-subtle px-3 py-2"
        >
          <span className={`text-xl font-bold tabular-nums ${cell.color}`}>{cell.value}</span>
          <span className="text-[10px] uppercase tracking-wide text-text-muted">{cell.label}</span>
        </div>
      ))}
    </div>
  );
}

function StatusBanner({ pipeline }: { readonly pipeline: PipelineHealth | undefined }) {
  if (!pipeline) return null;
  const meta =
    pipeline.status === 'healthy'
      ? { label: 'Pipeline healthy', tone: 'border-green-600/40 bg-green-600/10 text-green-700' }
      : pipeline.status === 'degraded'
        ? { label: 'Pipeline degraded', tone: 'border-yellow-600/40 bg-yellow-600/10 text-yellow-700' }
        : { label: 'Pipeline observability disabled', tone: 'border-border-subtle bg-surface-sunken text-text-muted' };
  return (
    <div role="status" aria-label={`Pipeline status ${pipeline.status}`} className={`flex flex-wrap items-center gap-3 rounded-md border px-4 py-3 ${meta.tone}`}>
      <span className="text-sm font-medium">{meta.label}</span>
      <Badge variant={pipeline.status === 'healthy' ? 'success' : pipeline.status === 'degraded' ? 'warning' : 'default'} className="font-mono uppercase">
        {pipeline.status}
      </Badge>
      {pipeline.enabled ? (
        <span className="text-[11px] text-text-muted">
          probe <span className="font-mono">{pipeline.probe}</span> · recorded {pipeline.timestamp}
        </span>
      ) : (
        <span className="text-[11px] text-text-muted">AETHER_INGESTION_OBSERVABILITY_ENABLED is OFF — zeroed counters below are honest, not healthy.</span>
      )}
    </div>
  );
}

function FunnelTable({ funnel }: { readonly funnel: FunnelSnapshot | undefined }) {
  if (!funnel) {
    return (
      <EmptyState
        title="No funnel telemetry"
        description="The funnel endpoint did not return a snapshot. Retry or check the operator endpoint."
      />
    );
  }
  return (
    <div className="space-y-4">
      <RollupGrid rollup={funnel.rollup} />
      <div className="overflow-x-auto rounded-md border border-border-subtle">
        <table className="w-full text-left text-xs">
          <caption className="sr-only">Per-stage ingestion funnel counts</caption>
          <thead className="bg-surface-sunken text-[10px] uppercase tracking-wide text-text-muted">
            <tr>
              <th className="px-3 py-2">Stage</th>
              <th className="px-3 py-2">Coverage</th>
              <th className="px-3 py-2 text-right">Total</th>
              <th className="px-3 py-2">Dispositions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle">
            {funnel.stages.map((stage) => (
              <tr key={stage.stage}>
                <td className="px-3 py-2">
                  <span className="font-mono text-text-primary">{stage.display}</span>
                  <span className="ml-2 text-[10px] text-text-muted">{stage.stage}</span>
                </td>
                <td className="px-3 py-2">
                  <Badge variant={stage.monitored ? 'success' : 'default'} size="sm">
                    {stage.monitored ? 'MONITORED' : 'DECLARED'}
                  </Badge>
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{stage.total}</td>
                <td className="px-3 py-2">{dispositionChips(stage)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-text-muted">
        MONITORED stages are recorded by this build (RECEIVED / VALIDATED / BRONZE in the API
        process; NORMALIZED / PROJECTIONS in the workers). DECLARED stages complete the blueprint
        ladder but are not instrumented server-side. RAW is client-side and never observed.
      </p>
    </div>
  );
}

function SpanStatusDot({ status }: { readonly status: string }) {
  const tone =
    status === 'accepted'
      ? 'bg-green-600'
      : status === 'rejected'
        ? 'bg-red-500'
        : status === 'degraded'
          ? 'bg-yellow-600'
          : 'bg-text-muted';
  return <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${tone}`} />;
}

function TraceLadder({ trace, isSearching }: { readonly trace: ObservationTrace | null | undefined; readonly isSearching: boolean }) {
  if (isSearching) {
    return <div className="py-2 text-xs text-text-muted">Inspecting…</div>;
  }
  if (trace === undefined) {
    return null;
  }
  if (trace === null) {
    return (
      <EmptyState
        title="No observation trace"
        description="The ledger has no trace for this event_id under this tenant_id. When AETHER_INGESTION_OBSERVABILITY_ENABLED is OFF no instrumentation runs; when ON, the trace key is tenant_id:event_id and both must match an observed event."
      />
    );
  }
  const step = (index: number) => (
    <div className="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-border-subtle bg-surface-sunken font-mono text-[10px] text-text-muted">
      {index + 1}
    </div>
  );
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono text-text-primary">{trace.event_id}</span>
        <Badge variant="default" size="sm">
          {trace.event_type || 'unknown type'}
        </Badge>
        <Badge variant="accent" size="sm">
          path: {trace.path}
        </Badge>
        {trace.complete ? <Badge variant={trace.outcome === 'accepted' ? 'success' : 'danger'} size="sm">outcome: {trace.outcome ?? 'complete'}</Badge> : null}
        <span className="text-[10px] text-text-muted">started {trace.started_at}</span>
      </div>
      <ol className="space-y-0">
        {trace.spans.map((span: TraceSpan, index: number) => (
          <li key={`${span.stage}-${index}`} className="relative flex gap-3 pb-3">
            {index < trace.spans.length - 1 ? (
              <span aria-hidden className="absolute left-3 top-6 h-[calc(100%-1.25rem)] w-px bg-border-subtle" />
            ) : null}
            {step(index)}
            <div className="min-w-0 flex-1 rounded-md border border-border-subtle px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <SpanStatusDot status={span.status} />
                <span className="font-mono text-xs text-text-primary">{span.display}</span>
                <Badge variant={DISPOSITION_VARIANT[span.status as StageDisposition] ?? 'default'} size="sm">
                  {span.status}
                </Badge>
                <span className="ml-auto text-[10px] text-text-muted">{new Date(span.at_ms).toISOString()}</span>
              </div>
              {span.detail ? <div className="mt-1 font-mono text-[10px] text-text-secondary">{span.detail}</div> : null}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function RecentTracesTable({
  traces,
  onInspect,
}: {
  readonly traces: readonly ObservationTrace[] | undefined;
  readonly onInspect: (trace: ObservationTrace) => void;
}) {
  if (!traces || traces.length === 0) {
    return (
      <EmptyState
        title="No recent observation traces"
        description="Recent traces appear here as the ingestion funnel records them while AETHER_INGESTION_OBSERVABILITY_ENABLED is ON."
      />
    );
  }
  return (
    <div className="overflow-x-auto rounded-md border border-border-subtle">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Recent observation traces</caption>
        <thead className="bg-surface-sunken text-[10px] uppercase tracking-wide text-text-muted">
          <tr>
            <th className="px-3 py-2">Event</th>
            <th className="px-3 py-2">Type</th>
            <th className="px-3 py-2">Path</th>
            <th className="px-3 py-2">Outcome</th>
            <th className="px-3 py-2">Started</th>
            <th className="px-3 py-2 text-right">Inspect</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-subtle">
          {traces.map((trace) => (
            <tr key={`${trace.tenant_id}:${trace.event_id}`}>
              <td className="px-3 py-2 font-mono text-text-primary">{trace.event_id}</td>
              <td className="px-3 py-2">{trace.event_type || '—'}</td>
              <td className="px-3 py-2">
                <Badge variant="accent" size="sm">path: {trace.path}</Badge>
              </td>
              <td className="px-3 py-2">
                {trace.complete && trace.outcome ? (
                  <Badge variant={trace.outcome === 'accepted' ? 'success' : trace.outcome === 'rejected' ? 'danger' : 'warning'} size="sm">
                    {trace.outcome}
                  </Badge>
                ) : (
                  <Badge variant="info" size="sm">in-flight</Badge>
                )}
              </td>
              <td className="px-3 py-2 text-[10px] text-text-muted">{trace.started_at}</td>
              <td className="px-3 py-2 text-right">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onInspect(trace)}
                  className="text-xs"
                >
                  Inspect
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TierTable({ tiers }: { readonly tiers: SdkVersionTiersPayload | undefined }) {
  if (!tiers) {
    return (
      <EmptyState
        title="No version-compatibility manifest"
        description="GET /v1/config/sdk/versions did not return a tier table. Retry or check the route."
      />
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-text-secondary">Consultation:</span>
        <Badge variant={tiers.enabled ? 'success' : 'default'} size="sm">
          {tiers.enabled ? 'enabled' : 'disabled'}
        </Badge>
        <Badge variant="accent" size="sm">mode: {tiers.mode}</Badge>
        <span className="text-[10px] text-text-muted">
          schema {tiers.schema_version} · fail-closed date {tiers.blocked_after_date}
        </span>
      </div>
      <div className="overflow-x-auto rounded-md border border-border-subtle">
        <table className="w-full text-left text-xs">
          <caption className="sr-only">SDK version-compatibility tier table</caption>
          <thead className="bg-surface-sunken text-[10px] uppercase tracking-wide text-text-muted">
            <tr>
              <th className="px-3 py-2">Band</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Version range</th>
              <th className="px-3 py-2">Capabilities</th>
              <th className="px-3 py-2">Dates</th>
              <th className="px-3 py-2">Note</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle">
            {tiers.tiers.map((band) => (
              <tr key={band.id}>
                <td className="px-3 py-2">
                  <span className="font-mono text-text-primary">{band.id}</span>
                  <span className="ml-1 text-text-muted">{band.label}</span>
                </td>
                <td className="px-3 py-2">
                  <Badge
                    variant={band.status === 'supported' ? 'success' : band.status === 'deprecated' ? 'info' : band.status === 'blocked' ? 'danger' : band.status === 'read_compatible' ? 'warning' : 'default'}
                    size="sm"
                  >
                    {band.status}
                  </Badge>
                </td>
                <td className="px-3 py-2 font-mono text-text-secondary">
                  [{band.min_version}, {band.max_version_exclusive})
                </td>
                <td className="px-3 py-2 font-mono text-[10px] text-text-secondary">
                  {band.capabilities.join(' · ') || '—'}
                </td>
                <td className="px-3 py-2 text-[10px] text-text-muted">
                  {band.deprecated_after ? `deprecated ${band.deprecated_after}` : ''}
                  {band.blocked_after ? `${band.deprecated_after ? ' · ' : ''}blocked ${band.blocked_after}` : ''}
                  {!band.deprecated_after && !band.blocked_after ? '—' : ''}
                </td>
                <td className="px-3 py-2 text-[10px] text-text-muted">{band.note ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-text-muted">
        Unclassified ({tiers.unclassified.label}): {tiers.unclassified.note}. Bands are advisory
        policy data; enforcement is by the single fail-closed {tiers.blocked_after_date} date in
        mode `enforce` only, never by band alone.
      </p>
    </div>
  );
}

function ReplayCard({ replay }: { readonly replay: ReplayStatus | undefined }) {
  if (!replay) {
    return <EmptyState title="Replay service unreported" description="GET /v1/kyber/ingest/replay/status did not return a payload." />;
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="text-text-secondary">Replay service:</span>
      <Badge variant={replay.enabled ? 'success' : 'default'} size="sm">
        {replay.enabled ? 'enabled' : 'disabled'}
      </Badge>
      <span className="font-mono text-[10px] text-text-secondary">source_service: {replay.source_service}</span>
      <span className="text-[10px] text-text-muted">dry-run default: {String(replay.dry_run_default)}</span>
    </div>
  );
}

/** Per-path status legend — disposition colors used across funnel + inspector. */
function StatusLegend() {
  const legend: Array<{ status: string; tone: string }> = [
    { status: 'accepted', tone: 'bg-green-600' },
    { status: 'duplicate', tone: 'bg-text-muted' },
    { status: 'rejected', tone: 'bg-red-500' },
    { status: 'degraded', tone: 'bg-yellow-600' },
    { status: 'observed / in-flight', tone: 'bg-blue-500' },
  ];
  return (
    <div className="flex flex-wrap items-center gap-3 text-[10px] text-text-muted">
      <span className="uppercase tracking-wide">Status legend</span>
      {legend.map((entry) => (
        <span key={entry.status} className="inline-flex items-center gap-1">
          <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${entry.tone}`} />
          {entry.status}
        </span>
      ))}
    </div>
  );
}

export function IngestionOpsPage() {
  const [state, setState] = useState<OpsState>({
    status: undefined,
    pipeline: undefined,
    funnel: undefined,
    recent: undefined,
    replay: undefined,
    tiers: undefined,
    failed: [],
  });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Observation Inspector search state.
  const [eventId, setEventId] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [inspected, setInspected] = useState<ObservationTrace | null | undefined>(undefined);
  const [searching, setSearching] = useState(false);

  const observabilityOff = state.status?.enabled === false || state.funnel?.enabled === false || state.pipeline?.enabled === false;

  const loadAll = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [statusR, pipelineR, funnelR, recentR, replayR, tiersR] = await Promise.allSettled([
        api.ingestionOps.observabilityStatus(),
        api.sdkHealth.pipelineLag(),
        api.ingestionOps.funnel(),
        api.ingestionOps.recentTraces(50),
        api.ingestionOps.replayStatus(),
        api.ingestionOps.versionTiers(),
      ]);
      const tiersEnvelope = settledValue<SdkVersionTiersEnvelope>(tiersR);
      const failed = [
        settledReason(statusR),
        settledReason(pipelineR),
        settledReason(funnelR),
        settledReason(recentR),
        settledReason(replayR),
        settledReason(tiersR),
      ].filter((reason): reason is string => Boolean(reason));
      setState({
        status: settledValue<ObservabilityStatus>(statusR),
        pipeline: settledValue<PipelineHealth>(pipelineR),
        funnel: settledValue<FunnelSnapshot>(funnelR),
        recent: settledValue<RecentTracesResponse>(recentR)?.traces,
        replay: settledValue<ReplayStatus>(replayR),
        tiers: tiersEnvelope?.data,
        failed,
      });
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load ingestion control plane');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  const inspectTrace = async (event: string, tenant: string) => {
    setSearching(true);
    setInspected(undefined);
    try {
      const body = (await api.ingestionOps.trace(event, tenant)) as TraceResponse;
      setInspected(body.trace);
    } catch (err) {
      setInspected(null);
      setLoadError(err instanceof Error ? err.message : 'Inspector lookup failed');
    } finally {
      setSearching(false);
    }
  };

  const runInspector = (event: string, tenant: string) => () => {
    void inspectTrace(event.trim(), tenant.trim());
  };

  const inspectRecent = (trace: ObservationTrace) => {
    setEventId(trace.event_id);
    setTenantId(trace.tenant_id);
    void inspectTrace(trace.event_id, trace.tenant_id);
  };

  const retry = () => setAttempt((n) => n + 1);

  const mutedNote = useMemo(() => (observabilityOff
    ? 'Ingestion telemetry is OFF in this environment — every count below is zeroed and each trace surface reports empty. Flip AETHER_INGESTION_OBSERVABILITY_ENABLED (default OFF) and restart to record.'
    : 'Ingestion telemetry is ON — the funnel records in-process as observations flow.'), [observabilityOff]);

  if (loading) {
    return (
      <PageWrapper
        title="Ingestion Ops"
        subtitle="Kyber ingestion control plane — funnel, observation traces, SDK fleet and version tiers."
      >
        <LoadingState lines={6} />
      </PageWrapper>
    );
  }

  if (loadError && state.pipeline === undefined && state.funnel === undefined) {
    return (
      <PageWrapper
        title="Ingestion Ops"
        subtitle="Kyber ingestion control plane — funnel, observation traces, SDK fleet and version tiers."
      >
        <ErrorState title="Unable to load the ingestion control plane" message={loadError} onRetry={retry} />
      </PageWrapper>
    );
  }

  return (
    <PageWrapper
      title="Ingestion Ops"
      subtitle="Kyber ingestion control plane — funnel, observation traces, SDK fleet and version tiers."
      actions={
        <div className="flex items-center gap-2">
          <StatusLegend />
          <Button variant="secondary" size="sm" onClick={retry}>↺ Refresh</Button>
        </div>
      }
    >
      <StatusBanner pipeline={state.pipeline} />

      <div className="rounded-md border border-border-subtle bg-surface-sunken px-3 py-2 text-[11px] text-text-muted">
        {mutedNote}
        {state.failed.length > 0 ? (
          <div className="mt-1">Some surfaces failed to load: {state.failed.join(' · ')}</div>
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Ingestion funnel</CardTitle>
        </CardHeader>
        <CardContent>
          <FunnelTable funnel={state.funnel} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Observation Inspector</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              runInspector(eventId, tenantId)();
            }}
          >
            <div className="flex flex-col gap-1">
              <label htmlFor="io-event-id" className="text-[10px] uppercase tracking-wide text-text-muted">event_id</label>
              <input
                id="io-event-id"
                className="rounded-md border border-border-subtle bg-surface-sunken px-2 py-1.5 font-mono text-xs"
                value={eventId}
                onChange={(e) => setEventId(e.target.value)}
                placeholder="evt_…"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="io-tenant-id" className="text-[10px] uppercase tracking-wide text-text-muted">tenant_id (optional)</label>
              <input
                id="io-tenant-id"
                className="rounded-md border border-border-subtle bg-surface-sunken px-2 py-1.5 font-mono text-xs"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                placeholder="tenant"
              />
            </div>
            <Button variant="primary" size="sm" type="submit" disabled={searching || eventId.trim() === ''}>
              {searching ? 'Inspecting…' : 'Inspect'}
            </Button>
          </form>
          <TraceLadder trace={inspected} isSearching={searching} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent observation traces</CardTitle>
        </CardHeader>
        <CardContent>
          <RecentTracesTable traces={state.recent} onInspect={inspectRecent} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>SDK fleet</CardTitle>
        </CardHeader>
        <CardContent>
          <SdkFleetMonitor />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>SDK version-compatibility tiers</CardTitle>
        </CardHeader>
        <CardContent>
          <TierTable tiers={state.tiers} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Replay service</CardTitle>
        </CardHeader>
        <CardContent>
          <ReplayCard replay={state.replay} />
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
