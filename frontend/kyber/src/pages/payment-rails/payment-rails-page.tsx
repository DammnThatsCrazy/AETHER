import { useEffect, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';

type AnyRecord = Record<string, unknown>;

const OBSERVABILITY_COPY =
  'Aether observes payment rails — it does not execute or settle payments, or custody funds.';

const PROVIDER_LABELS: Record<string, string> = {
  privy: 'Privy',
  stripe: 'Stripe',
  coinbase: 'Coinbase',
  moonpay: 'MoonPay',
  bridge: 'Bridge',
};

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

interface ProviderFleetRow {
  readonly provider: string;
  readonly status: string;
  readonly configured_tenants: number;
  readonly webhook_verified_24h: number;
  readonly webhook_rejected_24h: number;
  readonly sessions_observed_24h: number;
  readonly sessions_completed_24h: number;
  readonly sessions_failed_24h: number;
  readonly sessions_unresolved: number;
  readonly reconciliation_matched_rate: number | null;
  readonly reconciliation_conflicts: number;
}

interface TenantFleetRow {
  readonly tenant_id: string;
  readonly providers_configured: number;
  readonly providers_degraded: number;
  readonly sessions_observed_24h: number;
  readonly sessions_unresolved: number;
  readonly reconciliation_conflicts: number;
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

function formatTs(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function formatRate(rate: unknown): string {
  if (rate === null || rate === undefined) return '—';
  return `${(Number(rate) * 100).toFixed(1)}%`;
}

function formatBool(value: unknown): string {
  if (value === null || value === undefined) return '—';
  return value ? 'yes' : 'no';
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

function TenantDiagnosticsDrawer({ tenantId, onClose }: TenantDrawerProps) {
  const [detail, setDetail] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail(null);
    api.admin.kyber.paymentRailsTenant(tenantId)
      .then((d) => { if (!cancelled) setDetail(d as AnyRecord); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tenantId]);

  const providers = (detail?.providers ?? []) as AnyRecord[];

  return (
    <div className="fixed inset-y-0 right-0 z-40 w-[480px] max-w-full border-l border-border-default bg-surface-sunken shadow-xl overflow-y-auto p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-mono font-bold text-text-primary">Tenant payment rail diagnostics</div>
          <div className="text-[10px] text-text-muted font-mono">{tenantId}</div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>[x] Close</Button>
      </div>

      <div className="text-[10px] text-text-muted font-mono">
        Adapter, config, and reconciliation health only — raw tenant payment payloads are never shown in Kyber.
      </div>

      {loading ? <LoadingState lines={6} /> : error ? (
        <EmptyState title="Unable to load tenant diagnostics" description={error} />
      ) : providers.length === 0 ? (
        <EmptyState title="No payment rail adapters" description="This tenant has no payment rail providers configured." />
      ) : (
        providers.map((entry) => {
          const provider = String(entry.provider ?? 'unknown');
          const adapter = (entry.adapter ?? {}) as AnyRecord;
          const health = (entry.health ?? {}) as AnyRecord;
          const healthStatus = String(health.status ?? 'not_configured');
          return (
            <Card key={provider}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>{providerLabel(provider)}</CardTitle>
                  <Badge variant={statusColor(healthStatus)}>{statusLabel(healthStatus)}</Badge>
                </div>
              </CardHeader>
              <CardContent className="text-xs font-mono space-y-1">
                <DiagnosticsRow label="Adapter status" value={statusLabel(String(adapter.status ?? '—'))} />
                <DiagnosticsRow label="Environment" value={String(adapter.environment ?? '—')} />
                <DiagnosticsRow label="Webhook configured" value={formatBool(adapter.webhook_configured)} />
                <DiagnosticsRow label="Polling configured" value={formatBool(adapter.polling_configured)} />
                <DiagnosticsRow label="Sessions 24h" value={String(health.sessions_observed_24h ?? 0)} />
                <DiagnosticsRow label="Completed 24h" value={String(health.sessions_completed_24h ?? 0)} tone="success" />
                <DiagnosticsRow label="Failed 24h" value={String(health.sessions_failed_24h ?? 0)} tone="danger" />
                <DiagnosticsRow
                  label="Webhooks 24h"
                  value={`${String(health.webhook_verified_24h ?? 0)} ok / ${String(health.webhook_rejected_24h ?? 0)} rejected`}
                />
                <DiagnosticsRow label="Unresolved" value={String(health.sessions_unresolved ?? 0)} tone={Number(health.sessions_unresolved ?? 0) > 0 ? 'warning' : 'default'} />
                <DiagnosticsRow label="Matched rate" value={formatRate(health.reconciliation_matched_rate)} />
                <DiagnosticsRow label="Conflicts" value={String(health.reconciliation_conflicts ?? 0)} tone={Number(health.reconciliation_conflicts ?? 0) > 0 ? 'danger' : 'default'} />
                <DiagnosticsRow label="Last event" value={formatTs(health.last_event_at as string | null)} />
              </CardContent>
            </Card>
          );
        })
      )}
    </div>
  );
}

export function PaymentRailsPage() {
  const enabled = isFeatureEnabled('enablePaymentRails');
  const [data, setData] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [selectedTenantId, setSelectedTenantId] = useState<string | null>(null);
  const [cardLinked, setCardLinked] = useState<AnyRecord | null>(null);

  useEffect(() => {
    if (!enabled) return;
    api.admin.kyber.paymentRailsHealth()
      .then((d) => setData(d as AnyRecord))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
    api.admin.kyber.cardLinkedPaymentRailsDiagnostics?.()
      .then((d) => setCardLinked(d as AnyRecord))
      .catch(() => setCardLinked(null));
  }, [enabled]);

  if (!enabled) {
    return (
      <PageWrapper title="Payment Rails" subtitle={OBSERVABILITY_COPY}>
        <EmptyState
          title="Payment rail observability is disabled"
          description='Enable the "enablePaymentRails" feature flag (VITE_FEATURE_FLAGS) to view fleet-wide payment rail health.'
        />
      </PageWrapper>
    );
  }

  if (loading) return <PageWrapper title="Payment Rails"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Payment Rails"><EmptyState title="Unable to load payment rail health" description={error} /></PageWrapper>;

  const d = data ?? {};
  const totals = (d.totals ?? {}) as AnyRecord;
  const providers = (d.providers ?? []) as ProviderFleetRow[];
  const tenants = (d.tenants ?? []) as TenantFleetRow[];

  return (
    <PageWrapper
      title="Payment Rails"
      subtitle={`Fleet-wide, cross-tenant payment rail health. ${OBSERVABILITY_COPY}`}
    >
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Configured tenants" value={totals.configured_tenants} />
        <Metric label="Sessions observed 24h" value={totals.sessions_observed_24h} />
        <Metric label="Unresolved sessions" value={totals.sessions_unresolved} />
        <Metric label="Reconciliation conflicts" value={totals.reconciliation_conflicts} />
      </div>


      <Card>
        <CardHeader><CardTitle>Card-linked Observability</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {!cardLinked ? (
            <EmptyState
              title="Card-linked diagnostics unavailable"
              description="Enable KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED to view catalog coverage, PaymentScan status, source quality, reconciliation, and privacy gates."
            />
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-4">
                <Metric label="Card programs" value={cardLinked.card_program_count} />
                <Metric label="Issuers" value={cardLinked.issuer_count} />
                <Metric label="Card-linked flows" value={cardLinked.flow_count} />
                <Metric label="Region restricted" value={cardLinked.region_restricted_records} />
              </div>
              <div className="grid gap-3 md:grid-cols-3 text-xs font-mono">
                <Card><CardContent className="space-y-1"><DiagnosticsRow label="PaymentScan" value={String(cardLinked.paymentscan_status ?? 'catalog_and_benchmarks_only')} /><DiagnosticsRow label="Top-up support" value={String(cardLinked.topup_support ?? 0)} /><DiagnosticsRow label="Spend support" value={String(cardLinked.spend_support ?? 0)} /></CardContent></Card>
                <Card><CardContent className="space-y-1"><DiagnosticsRow label="Unmatched events" value={String(cardLinked.unmatched_events ?? 0)} /><DiagnosticsRow label="Reconciliation conflicts" value={String(cardLinked.reconciliation_conflicts ?? 0)} /><DiagnosticsRow label="Consent blocked" value={String(cardLinked.consent_blocked_records ?? 0)} /></CardContent></Card>
                <Card><CardContent className="space-y-1"><DiagnosticsRow label="Blocked PII attempts" value={String(cardLinked.blocked_pii_attempts ?? 0)} /><DiagnosticsRow label="Payment networks" value={String(cardLinked.payment_network_count ?? 0)} /><DiagnosticsRow label="Chain/currency coverage" value={`${String(cardLinked.chain_count ?? 0)} / ${String(cardLinked.currency_count ?? 0)}`} /></CardContent></Card>
              </div>
              {Array.isArray(cardLinked.basis_mislabeling_warnings) && cardLinked.basis_mislabeling_warnings.length > 0 && (
                <div className="space-y-1">
                  {cardLinked.basis_mislabeling_warnings.map((w, i) => <Badge key={i} variant="warning">{String(w)}</Badge>)}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Per-provider fleet health (24h)</CardTitle></CardHeader>
        <CardContent>
          {providers.length === 0 ? (
            <EmptyState
              title="No payment rail providers"
              description="No tenant has a payment rail provider configured yet."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono border-collapse">
                <thead>
                  <tr className="border-b border-border-default text-text-muted">
                    <th className="py-2 px-2 text-left">Provider</th>
                    <th className="py-2 px-2 text-left">Status</th>
                    <th className="py-2 px-2 text-right">Tenants</th>
                    <th className="py-2 px-2 text-right">Webhooks ok</th>
                    <th className="py-2 px-2 text-right">Webhooks rejected</th>
                    <th className="py-2 px-2 text-right">Observed</th>
                    <th className="py-2 px-2 text-right">Completed</th>
                    <th className="py-2 px-2 text-right">Failed</th>
                    <th className="py-2 px-2 text-right">Unresolved</th>
                    <th className="py-2 px-2 text-right">Matched</th>
                    <th className="py-2 px-2 text-right">Conflicts</th>
                  </tr>
                </thead>
                <tbody>
                  {providers.map((row) => (
                    <tr key={row.provider} className="border-b border-border-subtle">
                      <td className="py-2 px-2 font-semibold text-text-primary">{providerLabel(row.provider)}</td>
                      <td className="py-2 px-2"><Badge variant={statusColor(row.status)}>{statusLabel(row.status)}</Badge></td>
                      <td className="py-2 px-2 text-right">{row.configured_tenants}</td>
                      <td className="py-2 px-2 text-right text-success">{row.webhook_verified_24h}</td>
                      <td className="py-2 px-2 text-right text-warning">{row.webhook_rejected_24h}</td>
                      <td className="py-2 px-2 text-right">{row.sessions_observed_24h}</td>
                      <td className="py-2 px-2 text-right text-success">{row.sessions_completed_24h}</td>
                      <td className="py-2 px-2 text-right text-danger">{row.sessions_failed_24h}</td>
                      <td className="py-2 px-2 text-right">{row.sessions_unresolved}</td>
                      <td className="py-2 px-2 text-right">{formatRate(row.reconciliation_matched_rate)}</td>
                      <td className="py-2 px-2 text-right">{row.reconciliation_conflicts}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Per-tenant payment rail health (24h)</CardTitle></CardHeader>
        <CardContent>
          {tenants.length === 0 ? (
            <EmptyState
              title="No tenants with payment rails"
              description="Tenants appear here once they configure a payment rail provider."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono border-collapse">
                <thead>
                  <tr className="border-b border-border-default text-text-muted">
                    <th className="py-2 px-2 text-left">Tenant</th>
                    <th className="py-2 px-2 text-left">Status</th>
                    <th className="py-2 px-2 text-right">Providers</th>
                    <th className="py-2 px-2 text-right">Degraded</th>
                    <th className="py-2 px-2 text-right">Observed</th>
                    <th className="py-2 px-2 text-right">Unresolved</th>
                    <th className="py-2 px-2 text-right">Conflicts</th>
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
                      <td className="py-2 px-2 text-right">{row.providers_configured}</td>
                      <td className="py-2 px-2 text-right text-warning">{row.providers_degraded}</td>
                      <td className="py-2 px-2 text-right">{row.sessions_observed_24h}</td>
                      <td className="py-2 px-2 text-right">{row.sessions_unresolved}</td>
                      <td className="py-2 px-2 text-right text-danger">{row.reconciliation_conflicts}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {selectedTenantId && (
        <TenantDiagnosticsDrawer tenantId={selectedTenantId} onClose={() => setSelectedTenantId(null)} />
      )}
    </PageWrapper>
  );
}
