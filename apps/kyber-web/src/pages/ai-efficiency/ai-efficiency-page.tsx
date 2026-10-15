import { useEffect, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';

type AnyRecord = Record<string, unknown>;

const AI_EFFICIENCY_COPY =
  'Aether observes AI execution economics — proposals only, never automatic changes to models, prompts, or routing.';

const DETECTOR_LABELS: Record<string, string> = {
  retry_waste: 'Retry waste',
  model_overqualification: 'Model overqualification',
  deterministic_replacement_candidate: 'Deterministic replacement',
  cache_opportunity: 'Cache opportunity',
  failed_workflow_concentration: 'Failed workflow concentration',
};

function detectorLabel(detector: string): string {
  return DETECTOR_LABELS[detector] ?? detector;
}

interface TenantEfficiencyRow {
  readonly tenant_id: string;
  readonly fact_count: number;
  readonly cost_coverage: number | null;
  readonly unknown_cost_share: number | null;
  readonly open_findings: number;
  readonly status: string;
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

function statusColor(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'healthy') return 'success';
  if (status === 'degraded') return 'warning';
  if (status === 'error') return 'danger';
  return 'default';
}

function statusLabel(status: string): string {
  return status.replace(/_/g, ' ');
}

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

function coverageTone(rate: number): string {
  if (rate >= 0.9) return 'bg-success';
  if (rate >= 0.7) return 'bg-warning';
  return 'bg-danger';
}

/** Cost coverage gauge — share of AI execution facts with a known cost basis. */
function CoverageGauge({ label, rate }: { readonly label: string; readonly rate: unknown }) {
  const value = rate === null || rate === undefined ? null : Number(rate);
  const clamped = value === null ? 0 : Math.max(0, Math.min(1, value));
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{formatRate(rate)}</div>
        <div className="mt-2 h-1.5 rounded bg-surface-raised overflow-hidden" role="presentation">
          <div
            className={`h-1.5 rounded ${value === null ? 'bg-surface-raised' : coverageTone(clamped)}`}
            style={{ width: `${clamped * 100}%` }}
          />
        </div>
        <div className="mt-1 text-[10px] text-text-muted font-mono">
          Unknown costs stay unknown — they are never counted as zero.
        </div>
      </CardContent>
    </Card>
  );
}

interface DiagnosticsRowProps {
  readonly label: string;
  readonly value: string;
  readonly tone?: 'default' | 'success' | 'warning' | 'danger';
}

function DiagnosticsRow({ label, value, tone = 'default' }: DiagnosticsRowProps) {
  const toneClass =
    tone === 'success' ? 'text-success' : tone === 'warning' ? 'text-warning' : tone === 'danger' ? 'text-danger' : 'text-text-primary';
  return (
    <div className="flex justify-between">
      <span className="text-text-muted">{label}</span>
      <span className={toneClass}>{value}</span>
    </div>
  );
}

interface TenantDrawerProps {
  readonly tenantId: string;
  readonly onClose: () => void;
}

function TenantEfficiencyDrawer({ tenantId, onClose }: TenantDrawerProps) {
  const [detail, setDetail] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail(null);
    api.admin.kyber.aiEfficiencyTenant(tenantId)
      .then((d) => { if (!cancelled) setDetail(d as AnyRecord); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tenantId]);

  const detectorCounts = (detail?.detector_counts ?? {}) as Record<string, number>;
  const models = (detail?.models ?? []) as AnyRecord[];
  const findings = (detail?.findings ?? []) as AnyRecord[];

  return (
    <div className="fixed inset-y-0 right-0 z-40 w-[480px] max-w-full border-l border-border-default bg-surface-sunken shadow-xl overflow-y-auto p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-mono font-bold text-text-primary">Tenant AI efficiency diagnostics</div>
          <div className="text-[10px] text-text-muted font-mono">{tenantId}</div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>[x] Close</Button>
      </div>

      <div className="text-[10px] text-text-muted font-mono">
        Aggregate execution economics only — prompts, completions, and raw invocation payloads are never shown in Kyber.
      </div>

      {loading ? <LoadingState lines={6} /> : error ? (
        <EmptyState title="Unable to load tenant diagnostics" description={error} />
      ) : !detail ? (
        <EmptyState title="No AI execution facts" description="This tenant has no observed AI invocations yet." />
      ) : (
        <>
          <Card>
            <CardHeader><CardTitle>Coverage</CardTitle></CardHeader>
            <CardContent className="text-xs font-mono space-y-1">
              <DiagnosticsRow label="AI execution facts" value={String(detail.fact_count ?? 0)} />
              <DiagnosticsRow label="Cost coverage" value={formatRate(detail.cost_coverage)} />
              <DiagnosticsRow
                label="Unknown-cost share"
                value={formatRate(detail.unknown_cost_share)}
                tone={Number(detail.unknown_cost_share ?? 0) > 0.1 ? 'warning' : 'default'}
              />
              <DiagnosticsRow label="Workflows observed" value={String(detail.workflow_count ?? 0)} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Detector findings</CardTitle></CardHeader>
            <CardContent className="text-xs font-mono space-y-1">
              {Object.keys(detectorCounts).length === 0 ? (
                <p className="text-text-muted">No open detector findings.</p>
              ) : (
                Object.entries(detectorCounts).map(([detector, count]) => (
                  <DiagnosticsRow
                    key={detector}
                    label={detectorLabel(detector)}
                    value={String(count)}
                    tone={Number(count) > 0 ? 'warning' : 'default'}
                  />
                ))
              )}
            </CardContent>
          </Card>

          {models.length > 0 && (
            <Card>
              <CardHeader><CardTitle>Models observed</CardTitle></CardHeader>
              <CardContent className="text-xs font-mono space-y-1">
                {models.map((m) => (
                  <DiagnosticsRow
                    key={`${String(m.provider)}:${String(m.model)}`}
                    label={`${String(m.provider ?? 'unknown')} / ${String(m.model ?? 'unknown')}`}
                    value={`${String(m.invocations ?? 0)} invocations`}
                  />
                ))}
              </CardContent>
            </Card>
          )}

          {findings.length > 0 && (
            <Card>
              <CardHeader><CardTitle>Open findings</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {findings.map((f, index) => (
                  <div key={`${String(f.detector)}:${index}`} className="flex items-center gap-2 flex-wrap text-xs">
                    <Badge variant={severityColor(String(f.severity ?? ''))}>{String(f.severity ?? 'info')}</Badge>
                    <Badge size="sm">{detectorLabel(String(f.detector ?? ''))}</Badge>
                    <span className="text-text-primary">{String(f.title ?? '')}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

export function AiEfficiencyPage() {
  const enabled = isFeatureEnabled('enableAiEfficiency');
  const [data, setData] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [selectedTenantId, setSelectedTenantId] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    api.admin.kyber.aiEfficiencyHealth()
      .then((d) => setData(d as AnyRecord))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [enabled]);

  if (!enabled) {
    return (
      <PageWrapper title="AI Efficiency Health" subtitle={AI_EFFICIENCY_COPY}>
        <EmptyState
          title="AI efficiency health is disabled"
          description='Enable the "enableAiEfficiency" feature flag (VITE_FEATURE_FLAGS) to view fleet-wide AI outcome efficiency health.'
        />
      </PageWrapper>
    );
  }

  if (loading) return <PageWrapper title="AI Efficiency Health"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="AI Efficiency Health"><EmptyState title="Unable to load AI efficiency health" description={error} /></PageWrapper>;

  const d = data ?? {};
  const detectorCounts = (d.detector_counts ?? {}) as Record<string, number>;
  const tenants = (d.tenants ?? []) as TenantEfficiencyRow[];

  return (
    <PageWrapper
      title="AI Efficiency Health"
      subtitle={`Fleet-wide, cross-tenant AI outcome efficiency health. ${AI_EFFICIENCY_COPY}`}
    >
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="AI execution facts" value={d.fact_count} />
        <Metric label="Tenants observed" value={d.tenants_observed} />
        <CoverageGauge label="Cost coverage" rate={d.cost_coverage} />
        <Metric label="Unknown-cost share" value={formatRate(d.unknown_cost_share)} />
      </div>

      <Card>
        <CardHeader><CardTitle>Detector findings (fleet)</CardTitle></CardHeader>
        <CardContent>
          {Object.keys(detectorCounts).length === 0 ? (
            <EmptyState
              title="No detector findings"
              description="Deterministic efficiency detectors have not flagged anything across the fleet."
            />
          ) : (
            <div className="grid gap-2 md:grid-cols-3">
              {Object.entries(detectorCounts).map(([detector, count]) => (
                <div key={detector} className="flex items-center justify-between rounded border border-border-default px-2 py-1.5">
                  <span className="text-xs font-mono text-text-secondary">{detectorLabel(detector)}</span>
                  <span className={`text-xs font-mono ${Number(count) > 0 ? 'text-warning' : 'text-text-primary'}`}>{count}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Per-tenant AI efficiency</CardTitle></CardHeader>
        <CardContent>
          {tenants.length === 0 ? (
            <EmptyState
              title="No tenants with AI executions"
              description="Tenants appear here once their AI invocations are observed."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono border-collapse">
                <thead>
                  <tr className="border-b border-border-default text-text-muted">
                    <th className="py-2 px-2 text-left">Tenant</th>
                    <th className="py-2 px-2 text-left">Status</th>
                    <th className="py-2 px-2 text-right">Facts</th>
                    <th className="py-2 px-2 text-right">Cost coverage</th>
                    <th className="py-2 px-2 text-right">Unknown share</th>
                    <th className="py-2 px-2 text-right">Open findings</th>
                  </tr>
                </thead>
                <tbody>
                  {tenants.map((row) => (
                    <tr
                      key={row.tenant_id}
                      className="border-b border-border-subtle hover:bg-surface-hover cursor-pointer"
                      onClick={() => setSelectedTenantId(row.tenant_id)}
                    >
                      <td className="py-2 px-2 font-semibold text-text-primary">{row.tenant_id}</td>
                      <td className="py-2 px-2"><Badge variant={statusColor(row.status)}>{statusLabel(row.status)}</Badge></td>
                      <td className="py-2 px-2 text-right">{row.fact_count}</td>
                      <td className="py-2 px-2 text-right">{formatRate(row.cost_coverage)}</td>
                      <td className="py-2 px-2 text-right text-warning">{formatRate(row.unknown_cost_share)}</td>
                      <td className="py-2 px-2 text-right text-danger">{row.open_findings}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {selectedTenantId && (
        <TenantEfficiencyDrawer tenantId={selectedTenantId} onClose={() => setSelectedTenantId(null)} />
      )}
    </PageWrapper>
  );
}
