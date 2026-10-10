import { useEffect, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Input, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';

type AnyRecord = Record<string, unknown>;

const TARGETING_COPY =
  'Aether observes cluster targeting — it never executes campaigns and never mutates external campaign platforms.';

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info'] as const;

function severityColor(severity: string): 'success' | 'warning' | 'danger' | 'info' | 'default' {
  if (severity === 'critical' || severity === 'high') return 'danger';
  if (severity === 'medium') return 'warning';
  if (severity === 'low') return 'info';
  return 'default';
}

function formatRate(rate: unknown): string {
  if (rate === null || rate === undefined) return '—';
  return `${(Number(rate) * 100).toFixed(1)}%`;
}

function formatAge(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(diff)) return '—';
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 1) return '<1h';
  if (hours < 48) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function humanize(value: unknown): string {
  return String(value ?? '—').replace(/_/g, ' ');
}

function Metric({ label, value }: { readonly label: string; readonly value: unknown }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? 0)}</div>
      </CardContent>
    </Card>
  );
}

// ── Fleet health ───────────────────────────────────────────────────────────────

function FleetHealthSection({ health }: { readonly health: AnyRecord }) {
  const leakageBySeverity = (health.leakageBySeverity ?? {}) as Record<string, number>;
  const intentsBySource = (health.intentsBySource ?? {}) as Record<string, number>;
  return (
    <>
      <div className="grid gap-3 md:grid-cols-3">
        <Metric label="Tenants observed" value={health.tenantsObserved} />
        <Metric label="Targeting intents" value={health.intentCount} />
        <Metric label="Eligibility snapshots" value={health.snapshotCount} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Leakage by severity</CardTitle></CardHeader>
          <CardContent>
            {Object.keys(leakageBySeverity).length === 0 ? (
              <p className="text-xs text-text-muted font-mono">No leakage findings across the fleet.</p>
            ) : (
              <div className="flex items-center gap-2 flex-wrap">
                {SEVERITY_ORDER.filter(s => leakageBySeverity[s] !== undefined).map(severity => (
                  <Badge key={severity} variant={severityColor(severity)}>
                    {severity}: {leakageBySeverity[severity]}
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Intents by source</CardTitle></CardHeader>
          <CardContent className="text-xs font-mono space-y-1">
            {Object.keys(intentsBySource).length === 0 ? (
              <p className="text-text-muted">No targeting intents observed.</p>
            ) : (
              Object.entries(intentsBySource).map(([source, count]) => (
                <div key={source} className="flex justify-between">
                  <span className="text-text-muted">{humanize(source)}</span>
                  <span className="text-text-primary">{count}</span>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

// ── Leakage queue ──────────────────────────────────────────────────────────────

interface LeakageQueueRow {
  readonly findingId: string;
  readonly tenantId: string;
  readonly campaignId: string;
  readonly clusterId: string;
  readonly severity: string;
  readonly leakageRate: number | null;
  readonly reasonCode?: string;
  readonly likelyCauses?: string[];
  readonly computedAt?: string;
}

function LeakageDetailDrawer({ finding, onClose }: {
  readonly finding: LeakageQueueRow;
  readonly onClose: () => void;
}) {
  return (
    <div className="fixed inset-y-0 right-0 z-40 w-[480px] max-w-full border-l border-border-default bg-surface-sunken shadow-xl overflow-y-auto p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-mono font-bold text-text-primary">Leakage finding detail</div>
          <div className="text-[10px] text-text-muted font-mono">{finding.findingId}</div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>[x] Close</Button>
      </div>

      <div className="text-[10px] text-text-muted font-mono">
        Evidence-backed observation only — remediation happens in the tenant&apos;s external campaign platform.
      </div>

      <Card>
        <CardHeader><CardTitle>Finding</CardTitle></CardHeader>
        <CardContent className="text-xs font-mono space-y-1">
          <div className="flex justify-between"><span className="text-text-muted">Tenant</span><span className="text-text-primary">{finding.tenantId}</span></div>
          <div className="flex justify-between"><span className="text-text-muted">Campaign</span><span className="text-text-primary">{finding.campaignId}</span></div>
          <div className="flex justify-between"><span className="text-text-muted">Cluster</span><span className="text-text-primary">{finding.clusterId}</span></div>
          <div className="flex justify-between"><span className="text-text-muted">Severity</span><Badge variant={severityColor(finding.severity)}>{finding.severity}</Badge></div>
          <div className="flex justify-between"><span className="text-text-muted">Leakage rate</span><span className="text-danger">{formatRate(finding.leakageRate)}</span></div>
          <div className="flex justify-between"><span className="text-text-muted">Exclusion reason</span><span className="text-text-primary">{humanize(finding.reasonCode)}</span></div>
          <div className="flex justify-between"><span className="text-text-muted">Computed</span><span className="text-text-primary">{finding.computedAt ?? '—'}</span></div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Likely causes</CardTitle></CardHeader>
        <CardContent>
          {(finding.likelyCauses ?? []).length === 0 ? (
            <p className="text-xs text-text-muted font-mono">No likely causes recorded.</p>
          ) : (
            <div className="flex items-center gap-1.5 flex-wrap">
              {(finding.likelyCauses ?? []).map(cause => (
                <Badge key={cause} size="sm">{humanize(cause)}</Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function LeakageQueueSection() {
  const [rows, setRows] = useState<LeakageQueueRow[]>([]);
  const [severity, setSeverity] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<LeakageQueueRow | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.admin.kyber.targetingLeakageQueue(severity || undefined)
      .then((d) => { if (!cancelled) setRows(((d as AnyRecord).queue ?? []) as LeakageQueueRow[]); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [severity]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>Exclusion leakage queue</CardTitle>
          <select
            value={severity}
            onChange={e => setSeverity(e.target.value)}
            aria-label="Filter leakage by severity"
            className="text-xs font-mono border border-border-default rounded px-2 py-1 bg-surface-sunken text-text-primary"
          >
            <option value="">All severities</option>
            {SEVERITY_ORDER.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? <LoadingState lines={4} /> : error ? (
          <EmptyState title="Unable to load leakage queue" description={error} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="Leakage queue is empty"
            description="Exclusion leakage findings appear here when observed reach overlaps excluded clusters."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono border-collapse">
              <thead>
                <tr className="border-b border-border-default text-text-muted">
                  <th className="py-2 px-2 text-left">Tenant</th>
                  <th className="py-2 px-2 text-left">Campaign</th>
                  <th className="py-2 px-2 text-left">Cluster</th>
                  <th className="py-2 px-2 text-left">Severity</th>
                  <th className="py-2 px-2 text-right">Rate</th>
                  <th className="py-2 px-2 text-right">Age</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(row => (
                  <tr
                    key={row.findingId}
                    className="border-b border-border-subtle hover:bg-surface-hover cursor-pointer"
                    onClick={() => setSelected(row)}
                  >
                    <td className="py-2 px-2 font-semibold text-text-primary">{row.tenantId}</td>
                    <td className="py-2 px-2">{row.campaignId}</td>
                    <td className="py-2 px-2">{row.clusterId}</td>
                    <td className="py-2 px-2"><Badge variant={severityColor(row.severity)}>{row.severity}</Badge></td>
                    <td className="py-2 px-2 text-right text-danger">{formatRate(row.leakageRate)}</td>
                    <td className="py-2 px-2 text-right">{formatAge(row.computedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
      {selected && <LeakageDetailDrawer finding={selected} onClose={() => setSelected(null)} />}
    </Card>
  );
}

// ── Mapping quality diagnostics ────────────────────────────────────────────────

interface MappingQualityRow {
  readonly tenantId: string;
  readonly campaignId: string;
  readonly provider: string | null;
  readonly qualityScore: number | null;
  readonly blocksSuggestions: boolean | null;
  readonly providerSyncFreshness: string | null;
  readonly reasons?: string[];
  readonly computedAt?: string;
}

function MappingQualitySection() {
  const [rows, setRows] = useState<MappingQualityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.admin.kyber.targetingMappingQuality()
      .then((d) => { if (!cancelled) setRows(((d as AnyRecord).diagnostics ?? []) as MappingQualityRow[]); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return (
    <Card>
      <CardHeader><CardTitle>Provider mapping quality</CardTitle></CardHeader>
      <CardContent>
        {loading ? <LoadingState lines={4} /> : error ? (
          <EmptyState title="Unable to load mapping quality" description={error} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="No mapping quality diagnostics"
            description="Diagnostics appear once provider targeting observations are recorded."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono border-collapse">
              <thead>
                <tr className="border-b border-border-default text-text-muted">
                  <th className="py-2 px-2 text-left">Tenant</th>
                  <th className="py-2 px-2 text-left">Campaign</th>
                  <th className="py-2 px-2 text-left">Provider</th>
                  <th className="py-2 px-2 text-right">Quality</th>
                  <th className="py-2 px-2 text-left">Freshness</th>
                  <th className="py-2 px-2 text-left">Suggestions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${row.tenantId}:${row.campaignId}:${index}`} className="border-b border-border-subtle">
                    <td className="py-2 px-2 font-semibold text-text-primary">{row.tenantId}</td>
                    <td className="py-2 px-2">{row.campaignId}</td>
                    <td className="py-2 px-2">{row.provider ?? '—'}</td>
                    <td className={`py-2 px-2 text-right ${Number(row.qualityScore ?? 0) < 0.5 ? 'text-danger' : 'text-text-primary'}`}>
                      {formatRate(row.qualityScore)}
                    </td>
                    <td className="py-2 px-2">{row.providerSyncFreshness ?? 'unknown'}</td>
                    <td className="py-2 px-2">
                      {row.blocksSuggestions
                        ? <Badge variant="danger">blocked</Badge>
                        : <Badge variant="success">allowed</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Recompute controls ─────────────────────────────────────────────────────────

type RecomputeMode = 'snapshot' | 'leakage';

function RecomputeSection() {
  const [mode, setMode] = useState<RecomputeMode>('snapshot');
  const [tenantId, setTenantId] = useState('');
  const [intentId, setIntentId] = useState('');
  const [asOf, setAsOf] = useState('');
  const [observationId, setObservationId] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const valid = tenantId.trim() !== '' && (
    mode === 'snapshot' ? intentId.trim() !== '' && asOf.trim() !== '' : observationId.trim() !== ''
  );

  const run = () => {
    if (!valid) return;
    setRunning(true);
    setResult(null);
    setError(null);
    const body = mode === 'snapshot'
      ? { tenantId: tenantId.trim(), intentId: intentId.trim(), asOf: asOf.trim() }
      : { tenantId: tenantId.trim(), observationId: observationId.trim() };
    api.admin.kyber.targetingRecompute(body)
      .then((d) => {
        const recomputed = String((d as AnyRecord).recomputed ?? mode);
        setResult(`Recompute complete: ${recomputed}`);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        setRunning(false);
        setConfirming(false);
      });
  };

  const inputClass = 'text-xs font-mono';

  return (
    <Card>
      <CardHeader><CardTitle>Recompute controls</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[10px] text-text-muted font-mono">
          Audited, idempotent recomputation of Aether&apos;s own evidence. Recompute never mutates external
          campaign platforms and never executes campaigns.
        </p>

        <div className="flex gap-1 border border-border-default rounded-md p-0.5 w-fit" role="tablist" aria-label="Recompute mode">
          {([
            ['snapshot', 'Eligibility snapshot'],
            ['leakage', 'Leakage re-evaluation'],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              role="tab"
              aria-selected={mode === value}
              onClick={() => { setMode(value); setConfirming(false); }}
              className={`px-3 py-1 text-xs rounded transition-colors ${mode === value ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'}`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="grid gap-2 md:grid-cols-3">
          <Input
            aria-label="Recompute tenant ID"
            placeholder="tenantId (e.g. tenant_001)"
            value={tenantId}
            onChange={e => { setTenantId(e.target.value); setConfirming(false); }}
            className={inputClass}
          />
          {mode === 'snapshot' ? (
            <>
              <Input
                aria-label="Recompute intent ID"
                placeholder="intentId"
                value={intentId}
                onChange={e => { setIntentId(e.target.value); setConfirming(false); }}
                className={inputClass}
              />
              <Input
                aria-label="Recompute as-of timestamp"
                placeholder="asOf (ISO timestamp)"
                value={asOf}
                onChange={e => { setAsOf(e.target.value); setConfirming(false); }}
                className={inputClass}
              />
            </>
          ) : (
            <Input
              aria-label="Recompute observation ID"
              placeholder="observationId"
              value={observationId}
              onChange={e => { setObservationId(e.target.value); setConfirming(false); }}
              className={inputClass}
            />
          )}
        </div>

        <div className="flex items-center gap-2">
          {!confirming ? (
            <Button size="sm" variant="secondary" disabled={!valid || running} onClick={() => setConfirming(true)}>
              Recompute…
            </Button>
          ) : (
            <>
              <Button size="sm" variant="primary" disabled={running} onClick={run}>
                {running ? 'Recomputing…' : 'Confirm recompute'}
              </Button>
              <Button size="sm" variant="ghost" disabled={running} onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </>
          )}
        </div>

        {result && <p className="text-xs text-success font-mono">{result}</p>}
        {error && <p className="text-xs text-danger font-mono">Recompute failed: {error}</p>}
      </CardContent>
    </Card>
  );
}

// ── Release readiness ──────────────────────────────────────────────────────────

function ReleaseReadinessSection() {
  const [data, setData] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.admin.kyber.targetingReleaseReadiness()
      .then((d) => { if (!cancelled) setData(d as AnyRecord); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const checks = ((data?.checks ?? []) as AnyRecord[]);
  const flags = (data?.flags ?? {}) as Record<string, boolean>;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle>Release readiness</CardTitle>
          {data && (
            <Badge variant={data.ready ? 'success' : 'danger'}>{data.ready ? 'ready' : 'not ready'}</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? <LoadingState lines={4} /> : error ? (
          <EmptyState title="Unable to load release readiness" description={error} />
        ) : !data ? (
          <EmptyState title="No readiness report" description="Release readiness has not been evaluated yet." />
        ) : (
          <>
            <div className="space-y-1">
              {checks.map((check, index) => (
                <div key={`${String(check.name)}:${index}`} className="flex items-center justify-between text-xs font-mono">
                  <span className="text-text-muted">{humanize(check.name)}</span>
                  <span className="flex items-center gap-2">
                    {check.detail ? <span className="text-text-muted">{String(check.detail)}</span> : null}
                    <Badge variant={check.passed ? 'success' : 'danger'} size="sm">
                      {check.passed ? 'pass' : 'fail'}
                    </Badge>
                  </span>
                </div>
              ))}
            </div>
            {Object.keys(flags).length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap">
                {Object.entries(flags).map(([flag, on]) => (
                  <Badge key={flag} variant={on ? 'success' : 'default'} size="sm">
                    {humanize(flag)}: {on ? 'on' : 'off'}
                  </Badge>
                ))}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Audit trail ────────────────────────────────────────────────────────────────

function AuditTrailSection() {
  const [entries, setEntries] = useState<AnyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.admin.kyber.targetingAudit()
      .then((d) => { if (!cancelled) setEntries(((d as AnyRecord).audit ?? []) as AnyRecord[]); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return (
    <Card>
      <CardHeader><CardTitle>Audit trail</CardTitle></CardHeader>
      <CardContent>
        {loading ? <LoadingState lines={4} /> : error ? (
          <EmptyState title="Unable to load audit trail" description={error} />
        ) : entries.length === 0 ? (
          <EmptyState
            title="No audit entries"
            description="Operator recomputes and targeting lifecycle events appear here."
          />
        ) : (
          <div className="space-y-2">
            {entries.map((entry, index) => (
              <div
                key={String(entry.id ?? index)}
                className="flex items-center justify-between gap-2 border-b border-border-subtle pb-2 last:border-0 text-xs font-mono"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge size="sm">{humanize(entry.action)}</Badge>
                  <span className="text-text-primary">{String(entry.tenantId ?? '—')}</span>
                  <span className="text-text-muted">by {String(entry.actor ?? 'system')}</span>
                </div>
                <span className="text-text-muted">{String(entry.occurredAt ?? '—')}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export function TargetingIntelligencePage() {
  const enabled = isFeatureEnabled('enableTargetingIntelligence');
  const [health, setHealth] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    api.admin.kyber.targetingHealth()
      .then((d) => setHealth(d as AnyRecord))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [enabled]);

  if (!enabled) {
    return (
      <PageWrapper title="Targeting Intelligence" subtitle={TARGETING_COPY}>
        <EmptyState
          title="Targeting intelligence is disabled"
          description='Enable the "enableTargetingIntelligence" feature flag (VITE_FEATURE_FLAGS) to view fleet-wide cluster targeting diagnostics.'
        />
      </PageWrapper>
    );
  }

  if (loading) return <PageWrapper title="Targeting Intelligence"><LoadingState lines={6} /></PageWrapper>;
  if (error) {
    return (
      <PageWrapper title="Targeting Intelligence">
        <EmptyState title="Unable to load targeting fleet health" description={error} />
      </PageWrapper>
    );
  }

  return (
    <PageWrapper
      title="Targeting Intelligence"
      subtitle={`Fleet-wide cluster targeting evidence health. ${TARGETING_COPY}`}
    >
      <FleetHealthSection health={health ?? {}} />
      <LeakageQueueSection />
      <MappingQualitySection />
      <RecomputeSection />
      <ReleaseReadinessSection />
      <AuditTrailSection />
    </PageWrapper>
  );
}
