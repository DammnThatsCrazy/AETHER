import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  LoadingState,
  TerminalSeparator,
} from '@aether/ui';
import { cn, formatRelativeTime } from '@kyber/lib/utils';
import { api } from '@kyber/lib/api';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';

/**
 * One-Person Ops — live Agent Command Center panels.
 *
 * Additive panels for the Command page, gated on `enableAgentCommandCenter`:
 *  - worker/runtime health strip (+ kill switch state and confirmed action)
 *  - run history with status filter, error display, and stuck highlighting
 *  - stuck runs panel
 *  - operator briefings feed with generate action
 *  - compressed ops alerts feed
 *
 * All data comes from the /v1/agent/* routes (snake_case payloads). The
 * worker-only route POST /v1/agent/runs/{run_id}/status is never called here.
 */

type AnyRecord = Record<string, unknown>;

const RUN_STATUSES = ['queued', 'running', 'completed', 'failed', 'retry', 'stale'] as const;

interface AgentRunRow {
  readonly run_id: string;
  readonly tenant_id?: string;
  readonly objective_id?: string | null;
  readonly controller?: string;
  readonly queue?: string;
  readonly status: string;
  readonly attempt?: number;
  readonly created_at?: string;
  readonly updated_at?: string;
  readonly error?: string | null;
}

interface BriefingRow {
  readonly id: string;
  readonly tenant_id?: string;
  readonly type: string;
  readonly title: string;
  readonly body: string;
  readonly created_at: string;
}

interface OpsAlertRow {
  readonly id: string;
  readonly severity: string;
  readonly kind: string;
  readonly message: string;
  readonly count: number;
  readonly dedupe_key?: string;
  readonly first_seen_at?: string;
  readonly last_seen_at?: string;
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function humanize(value: unknown): string {
  return String(value ?? '—').replace(/_/g, ' ');
}

function runStatusVariant(status: string): 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'stale') return 'danger';
  if (status === 'retry') return 'warning';
  if (status === 'running') return 'accent';
  return 'info';
}

function severityColor(severity: string): 'success' | 'warning' | 'danger' | 'info' | 'default' {
  if (severity === 'critical' || severity === 'high') return 'danger';
  if (severity === 'medium') return 'warning';
  if (severity === 'low') return 'info';
  return 'default';
}

function briefingTypeVariant(type: string): 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info' {
  if (type === 'alert') return 'danger';
  if (type === 'handoff') return 'accent';
  if (type === 'run_complete') return 'success';
  return 'default';
}

// ── Worker / runtime health strip ─────────────────────────────────────────────

function OpsMetric({ label, value, tone, testId }: {
  readonly label: string;
  readonly value: unknown;
  readonly tone?: string | undefined;
  readonly testId: string;
}) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div data-testid={testId} className={cn('mt-1 text-2xl font-semibold', tone ?? 'text-text-primary')}>
          {String(value ?? 0)}
        </div>
      </CardContent>
    </Card>
  );
}

function KillSwitchControl({ engaged, onChanged }: {
  readonly engaged: boolean;
  readonly onChanged: (engaged: boolean) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const action = engaged ? 'release' : 'engage';

  const run = () => {
    setBusy(true);
    setError(null);
    api.agent.killSwitch(action, 'kyber operator action')
      .then((d) => onChanged(((d as AnyRecord).kill_switch as boolean) ?? !engaged))
      .catch((e: unknown) => setError(errorMessage(e)))
      .finally(() => {
        setBusy(false);
        setConfirming(false);
      });
  };

  return (
    <div className="flex items-center gap-2">
      {!confirming ? (
        <Button size="sm" variant={engaged ? 'secondary' : 'danger'} disabled={busy} onClick={() => setConfirming(true)}>
          {engaged ? 'Release kill switch…' : 'Engage kill switch…'}
        </Button>
      ) : (
        <>
          <Button size="sm" variant="danger" disabled={busy} onClick={run}>
            {busy ? 'Applying…' : `Confirm ${action}`}
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirming(false)}>
            Cancel
          </Button>
        </>
      )}
      {error && <span className="text-xs text-danger font-mono">Kill switch failed: {error}</span>}
    </div>
  );
}

function RuntimeHealthStrip() {
  const [health, setHealth] = useState<AnyRecord | null>(null);
  const [killEngaged, setKillEngaged] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.agent.health()
      .then((d) => {
        if (cancelled) return;
        const h = d as AnyRecord;
        setHealth(h);
        setKillEngaged((h.kill_switch as boolean | undefined) ?? false);
      })
      .catch((e: unknown) => { if (!cancelled) setError(errorMessage(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const staleWorkers = Number(health?.stale_workers ?? 0);
  const failedRuns = Number(health?.failed_runs ?? 0);
  const stuckRuns = Number(health?.stuck_runs ?? 0);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <CardTitle>Worker runtime health</CardTitle>
          <div className="flex items-center gap-2 flex-wrap">
            {killEngaged === null ? (
              <Badge variant="default">kill switch unknown</Badge>
            ) : (
              <Badge variant={killEngaged ? 'danger' : 'success'}>
                {killEngaged ? 'kill switch engaged' : 'kill switch clear'}
              </Badge>
            )}
            <KillSwitchControl engaged={killEngaged === true} onChanged={setKillEngaged} />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? <LoadingState lines={2} /> : error ? (
          <EmptyState title="Unable to load agent runtime health" description={error} />
        ) : (
          <div className="grid gap-3 grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
            <OpsMetric label="Queue depth" value={health?.queue_depth} testId="ops-metric-queue-depth" />
            <OpsMetric label="Workers" value={health?.worker_count} testId="ops-metric-worker-count" />
            <OpsMetric
              label="Stale workers"
              value={health?.stale_workers}
              tone={staleWorkers > 0 ? 'text-danger' : undefined}
              testId="ops-metric-stale-workers"
            />
            <OpsMetric label="Active runs" value={health?.active_runs} testId="ops-metric-active-runs" />
            <OpsMetric
              label="Failed runs"
              value={health?.failed_runs}
              tone={failedRuns > 0 ? 'text-danger' : undefined}
              testId="ops-metric-failed-runs"
            />
            <OpsMetric
              label="Stuck runs"
              value={health?.stuck_runs}
              tone={stuckRuns > 0 ? 'text-warning' : undefined}
              testId="ops-metric-stuck-runs"
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Run history + stuck runs ──────────────────────────────────────────────────

function RunOpsSection() {
  const [runs, setRuns] = useState<AgentRunRow[]>([]);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [stuck, setStuck] = useState<AgentRunRow[]>([]);
  const [stuckLoading, setStuckLoading] = useState(true);
  const [stuckError, setStuckError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.agent.runs(status ? { status } : undefined)
      .then((d) => { if (!cancelled) setRuns(((d as AnyRecord).runs ?? []) as AgentRunRow[]); })
      .catch((e: unknown) => { if (!cancelled) setError(errorMessage(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [status]);

  useEffect(() => {
    let cancelled = false;
    api.agent.stuckRuns()
      .then((d) => { if (!cancelled) setStuck(((d as AnyRecord).runs ?? []) as AgentRunRow[]); })
      .catch((e: unknown) => { if (!cancelled) setStuckError(errorMessage(e)); })
      .finally(() => { if (!cancelled) setStuckLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const stuckIds = new Set(stuck.map(r => r.run_id));

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <CardTitle>Run history</CardTitle>
            <select
              value={status}
              onChange={e => setStatus(e.target.value)}
              aria-label="Filter runs by status"
              className="text-xs font-mono border border-border-default rounded px-2 py-1 bg-surface-sunken text-text-primary"
            >
              <option value="">All statuses</option>
              {RUN_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? <LoadingState lines={4} /> : error ? (
            <EmptyState title="Unable to load run history" description={error} />
          ) : runs.length === 0 ? (
            <EmptyState
              title="No runs"
              description="Worker runs appear here as objectives are dispatched."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono border-collapse">
                <thead>
                  <tr className="border-b border-border-default text-text-muted">
                    <th className="py-2 px-2 text-left">Run</th>
                    <th className="py-2 px-2 text-left">Controller</th>
                    <th className="py-2 px-2 text-left">Queue</th>
                    <th className="py-2 px-2 text-left">Status</th>
                    <th className="py-2 px-2 text-right">Attempt</th>
                    <th className="py-2 px-2 text-left">Error</th>
                    <th className="py-2 px-2 text-right">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map(run => {
                    const isStuck = run.status === 'stale' || stuckIds.has(run.run_id);
                    return (
                      <tr
                        key={run.run_id}
                        data-testid={`run-row-${run.run_id}`}
                        data-stuck={isStuck || undefined}
                        className={cn(
                          'border-b border-border-subtle',
                          isStuck && 'bg-warning/10 border-l-2 border-l-warning',
                        )}
                      >
                        <td className="py-2 px-2 font-semibold text-text-primary">{run.run_id}</td>
                        <td className="py-2 px-2">{run.controller ?? '—'}</td>
                        <td className="py-2 px-2">{run.queue ?? '—'}</td>
                        <td className="py-2 px-2"><Badge variant={runStatusVariant(run.status)}>{run.status}</Badge></td>
                        <td className="py-2 px-2 text-right">{run.attempt ?? 1}</td>
                        <td className="py-2 px-2 max-w-[280px]">
                          {run.error
                            ? <span className="text-danger">{run.error}</span>
                            : <span className="text-text-muted">—</span>}
                        </td>
                        <td className="py-2 px-2 text-right text-text-muted">
                          {run.updated_at ? formatRelativeTime(run.updated_at) : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle>Stuck runs</CardTitle>
            <Badge variant={stuck.length > 0 ? 'danger' : 'success'}>{stuck.length}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          {stuckLoading ? <LoadingState lines={2} /> : stuckError ? (
            <EmptyState title="Unable to load stuck runs" description={stuckError} />
          ) : stuck.length === 0 ? (
            <EmptyState
              title="No stuck runs"
              description="Runs with lost heartbeats or exhausted retries appear here for recovery."
            />
          ) : (
            <div className="space-y-2">
              {stuck.map(run => (
                <div
                  key={run.run_id}
                  data-testid={`stuck-run-${run.run_id}`}
                  className="border border-danger/30 bg-danger/5 rounded px-3 py-2 text-xs font-mono space-y-1"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-text-primary">{run.run_id}</span>
                    <span className="flex items-center gap-2">
                      <Badge variant="danger">{run.status}</Badge>
                      <span className="text-text-muted">attempt {run.attempt ?? 1}</span>
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2 text-text-muted">
                    <span>{run.controller ?? '—'} · {run.queue ?? '—'}</span>
                    <span>{run.updated_at ? formatRelativeTime(run.updated_at) : '—'}</span>
                  </div>
                  {run.error && <div className="text-danger">{run.error}</div>}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Operator briefings ────────────────────────────────────────────────────────

function BriefingsSection() {
  const [briefings, setBriefings] = useState<BriefingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateResult, setGenerateResult] = useState<string | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const fetchBriefings = useCallback(
    () =>
      api.agent.briefings()
        .then((d) => setBriefings(((d as AnyRecord).briefings ?? []) as BriefingRow[]))
        .catch((e: unknown) => setError(errorMessage(e))),
    [],
  );

  useEffect(() => {
    setLoading(true);
    setError(null);
    void fetchBriefings().finally(() => setLoading(false));
  }, [fetchBriefings]);

  const generate = () => {
    setGenerating(true);
    setGenerateResult(null);
    setGenerateError(null);
    api.agent.generateBriefing()
      .then(() => {
        setGenerateResult('Briefing generated');
        return fetchBriefings();
      })
      .catch((e: unknown) => setGenerateError(errorMessage(e)))
      .finally(() => setGenerating(false));
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>Operator briefings</CardTitle>
          <Button size="sm" variant="secondary" disabled={generating} onClick={generate}>
            {generating ? 'Generating…' : 'Generate briefing'}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {generateResult && <p className="text-xs text-success font-mono">{generateResult}</p>}
        {generateError && <p className="text-xs text-danger font-mono">Briefing generation failed: {generateError}</p>}
        {loading ? <LoadingState lines={3} /> : error ? (
          <EmptyState title="Unable to load briefings" description={error} />
        ) : briefings.length === 0 ? (
          <EmptyState
            title="No briefings"
            description="Run-complete, alert, handoff, and daily briefings appear here."
          />
        ) : (
          <div className="space-y-2">
            {briefings.map(b => (
              <div key={b.id} className="border-b border-border-subtle pb-2 last:border-0 space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 min-w-0">
                    <Badge variant={briefingTypeVariant(b.type)} size="sm">{humanize(b.type)}</Badge>
                    <span className="text-xs font-mono font-semibold text-text-primary truncate">{b.title}</span>
                  </span>
                  <span className="text-[10px] text-text-muted font-mono shrink-0">
                    {formatRelativeTime(b.created_at)}
                  </span>
                </div>
                <p className="text-xs text-text-secondary">{b.body}</p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Ops alerts ────────────────────────────────────────────────────────────────

function OpsAlertsSection() {
  const [alerts, setAlerts] = useState<OpsAlertRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.agent.opsAlerts()
      .then((d) => { if (!cancelled) setAlerts(((d as AnyRecord).alerts ?? []) as OpsAlertRow[]); })
      .catch((e: unknown) => { if (!cancelled) setError(errorMessage(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle>Ops alerts</CardTitle>
          {alerts.length > 0 && <Badge variant="warning">{alerts.length}</Badge>}
        </div>
      </CardHeader>
      <CardContent>
        {loading ? <LoadingState lines={3} /> : error ? (
          <EmptyState title="Unable to load ops alerts" description={error} />
        ) : alerts.length === 0 ? (
          <EmptyState
            title="No ops alerts"
            description="Compressed worker and run alerts appear here as they are raised."
          />
        ) : (
          <div className="space-y-2">
            {alerts.map(alert => (
              <div key={alert.id} className="border-b border-border-subtle pb-2 last:border-0 space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 flex-wrap">
                    <Badge variant={severityColor(alert.severity)}>{alert.severity}</Badge>
                    <Badge size="sm">{humanize(alert.kind)}</Badge>
                    {alert.count > 1 && (
                      <span title={`${alert.count} compressed occurrences`}>
                        <Badge variant="warning" size="sm">×{alert.count}</Badge>
                      </span>
                    )}
                  </span>
                  <span className="text-[10px] text-text-muted font-mono shrink-0">
                    {alert.last_seen_at ? `last ${formatRelativeTime(alert.last_seen_at)}` : '—'}
                  </span>
                </div>
                <p className="text-xs text-text-secondary font-mono">{alert.message}</p>
                {alert.first_seen_at && (
                  <p className="text-[10px] text-text-muted font-mono">
                    first seen {formatRelativeTime(alert.first_seen_at)}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Flag-gated wrapper ────────────────────────────────────────────────────────

/** Renders nothing unless `enableAgentCommandCenter` is on — the Command page
 *  is byte-for-byte unchanged with the flag off. */
export function CommandCenterOpsPanels() {
  if (!isFeatureEnabled('enableAgentCommandCenter')) return null;

  return (
    <div className="space-y-4" data-testid="command-center-ops">
      <TerminalSeparator label="agent ops" />
      <RuntimeHealthStrip />
      <RunOpsSection />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <BriefingsSection />
        <OpsAlertsSection />
      </div>
    </div>
  );
}
