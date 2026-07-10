import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  useToast,
} from '@aether/ui';
import {
  paymentRailProviders,
  fundingSessionStatuses,
  reconciliationStates,
} from '@aether/shared';
import type { PaymentRailProvider, ReconciliationState } from '@aether/shared';
import {
  useFundingSessions,
  useFundingSession,
  useReconciliationRecords,
  usePaymentRailHealth,
  useProviderStatus,
  useSyncProvider,
} from '@aether-app/features/payment-rails';
import type { FundingSessionRecord, PaymentRailHealthRecord } from '@aether-app/features/payment-rails';
import {
  OBSERVABILITY_COPY,
  ProviderBadge,
  ProviderHealthBadge,
  ReconciliationStateBadge,
  SessionStatusBadge,
  flowTypeLabel,
  formatDateTime,
  formatMatchedRate,
  formatNativeAmount,
  providerLabel,
} from './payment-rails-shared';

const PROVIDER_OPTIONS = [
  { value: '', label: 'All providers' },
  ...paymentRailProviders.map(p => ({ value: p, label: providerLabel(p) })),
];

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  ...fundingSessionStatuses.map(s => ({ value: s, label: s })),
];

const RECONCILIATION_OPTIONS = [
  { value: '', label: 'All reconciliation states' },
  ...reconciliationStates.map(s => ({ value: s, label: s })),
];

const NOT_CONFIGURED_TITLE = 'Payment rail observability is not configured';
const NOT_CONFIGURED_DESCRIPTION =
  'This workspace does not have the payment rail observability plane enabled. Contact your administrator or Aether support to enable it.';

const selectClass =
  'text-sm border border-border-default rounded-md px-3 py-1.5 bg-surface-default text-text-primary focus:outline-none focus:ring-1 focus:ring-accent';

interface HealthStatProps {
  readonly label: string;
  readonly value: string;
  readonly tone?: 'default' | 'success' | 'warning' | 'danger';
}

function HealthStat({ label, value, tone = 'default' }: HealthStatProps) {
  const toneClass =
    tone === 'success' ? 'text-success' : tone === 'warning' ? 'text-warning' : tone === 'danger' ? 'text-danger' : 'text-text-primary';
  return (
    <div className="flex items-center justify-between text-xs font-mono">
      <span className="text-text-muted">{label}</span>
      <span className={toneClass}>{value}</span>
    </div>
  );
}

interface ProviderHealthCardProps {
  readonly provider: PaymentRailProvider;
  readonly health: PaymentRailHealthRecord | undefined;
  readonly syncing: boolean;
  readonly syncDisabled: boolean;
  readonly onSync: (provider: PaymentRailProvider) => void;
}

function ProviderHealthCard({ provider, health, syncing, syncDisabled, onSync }: ProviderHealthCardProps) {
  const status = health?.status ?? 'not_configured';
  const configured = health?.configured ?? false;

  return (
    <Card>
      <CardContent className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-medium text-text-primary">{providerLabel(provider)}</span>
          <ProviderHealthBadge status={status} />
        </div>
        {configured ? (
          <>
            <HealthStat label="Sessions 24h" value={(health?.sessions_observed_24h ?? 0).toLocaleString()} />
            <HealthStat label="Completed 24h" value={(health?.sessions_completed_24h ?? 0).toLocaleString()} tone="success" />
            <HealthStat label="Failed 24h" value={(health?.sessions_failed_24h ?? 0).toLocaleString()} tone="danger" />
            <HealthStat
              label="Webhooks 24h"
              value={`${(health?.webhook_verified_24h ?? 0).toLocaleString()} ok / ${(health?.webhook_rejected_24h ?? 0).toLocaleString()} rejected`}
              tone={(health?.webhook_rejected_24h ?? 0) > 0 ? 'warning' : 'default'}
            />
            <HealthStat label="Unresolved" value={(health?.sessions_unresolved ?? 0).toLocaleString()} tone={(health?.sessions_unresolved ?? 0) > 0 ? 'warning' : 'default'} />
            <HealthStat label="Conflicts" value={(health?.reconciliation_conflicts ?? 0).toLocaleString()} tone={(health?.reconciliation_conflicts ?? 0) > 0 ? 'danger' : 'default'} />
            <HealthStat label="Matched rate" value={formatMatchedRate(health?.reconciliation_matched_rate)} />
            <HealthStat label="Last event" value={formatDateTime(health?.last_event_at)} />
            <Button
              variant="secondary"
              size="sm"
              className="w-full mt-1"
              disabled={syncDisabled}
              onClick={() => onSync(provider)}
            >
              {syncing ? 'Syncing…' : 'Sync status'}
            </Button>
          </>
        ) : (
          <p className="text-xs text-text-muted">
            No {providerLabel(provider)} adapter is configured for this workspace.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

interface DetailFieldProps {
  readonly label: string;
  readonly value: string | null | undefined;
  readonly mono?: boolean;
}

function DetailField({ label, value, mono = true }: DetailFieldProps) {
  return (
    <div>
      <div className="text-text-muted font-mono">{label}</div>
      <div className={`mt-0.5 break-all ${mono ? 'font-mono text-text-primary' : 'text-text-secondary'}`}>
        {value ?? '—'}
      </div>
    </div>
  );
}

interface SessionDetailDrawerProps {
  readonly sessionId: string;
  readonly onClose: () => void;
}

function SessionDetailDrawer({ sessionId, onClose }: SessionDetailDrawerProps) {
  const { session, loading, error, refresh } = useFundingSession(sessionId);
  const { records } = useReconciliationRecords();
  const { status: adapterStatus } = useProviderStatus(session?.provider ?? null);

  const reconciliation = records.find(r => r.funding_session_id === sessionId) ?? null;
  const discrepancies = reconciliation?.discrepancies ?? [];

  return (
    <div className="fixed inset-y-0 right-0 z-40 w-[520px] max-w-full border-l border-border-default bg-surface-raised shadow-xl overflow-y-auto p-6 space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold text-text-primary">Funding session</h2>
          <div className="text-[10px] text-text-muted font-mono">{sessionId}</div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
      </div>

      {loading && !session ? (
        <LoadingState lines={8} />
      ) : error ? (
        <ErrorState title="Failed to load funding session" message={error} onRetry={refresh} />
      ) : !session ? (
        <EmptyState
          title="Session not found"
          description="This funding session does not exist or is not visible to your tenant."
        />
      ) : (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            <ProviderBadge provider={session.provider} />
            <SessionStatusBadge status={session.status} />
            <ReconciliationStateBadge state={session.reconciliation_state} />
            <Badge size="sm">{flowTypeLabel(session.flow_type)}</Badge>
            <Badge size="sm">{session.rail}</Badge>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Flow</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <DetailField label="Flow type" value={flowTypeLabel(session.flow_type)} mono={false} />
                <DetailField label="Rail" value={session.rail} />
                <DetailField label="Provider detail" value={session.provider_detail} />
                <DetailField label="Provider status" value={session.provider_status} />
                <DetailField label="Status reason" value={session.status_reason} />
                <DetailField label="Occurred at" value={formatDateTime(session.occurred_at)} mono={false} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Amounts (native units — never converted)</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <DetailField
                  label="Source"
                  value={formatNativeAmount(session.source_amount, session.source_asset ?? session.fiat_currency)}
                />
                <DetailField label="Source chain" value={session.source_chain} />
                <DetailField
                  label="Destination"
                  value={formatNativeAmount(session.destination_amount, session.destination_asset ?? session.fiat_currency)}
                />
                <DetailField label="Destination chain" value={session.destination_chain} />
                <DetailField label="Destination address" value={session.destination_address} />
                <DetailField label="Fee" value={formatNativeAmount(session.fee_amount, session.fee_currency)} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Attribution</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <DetailField label="Actor kind" value={session.actor_kind} />
                <DetailField label="User" value={session.user_id} />
                <DetailField label="Agent" value={session.agent_id} />
                <DetailField label="Org" value={session.org_id} />
                <DetailField label="Session" value={session.session_id} />
                <DetailField label="Device" value={session.device_id} />
                <DetailField label="Journey" value={session.journey_id} />
                <DetailField label="Campaign" value={session.campaign_id} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Provider references</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <DetailField label="Provider session" value={session.provider_session_id} />
                <DetailField label="Provider transaction" value={session.provider_transaction_id} />
                <DetailField label="Customer ref" value={session.provider_customer_ref} />
                <DetailField label="Deposit address" value={session.deposit_address_id} />
                <DetailField label="Virtual account" value={session.virtual_account_id} />
                <DetailField label="Tx hash" value={session.tx_hash} />
                <DetailField label="Idempotency key" value={session.idempotency_key} />
              </div>
              {adapterStatus && (
                <div className="grid grid-cols-2 gap-3 text-xs mt-3 pt-3 border-t border-border-subtle">
                  <DetailField label="Adapter status" value={adapterStatus.status} />
                  <DetailField label="Adapter environment" value={adapterStatus.environment} />
                  <DetailField label="Webhook configured" value={adapterStatus.webhook_configured === undefined || adapterStatus.webhook_configured === null ? undefined : String(adapterStatus.webhook_configured)} />
                  <DetailField label="Polling configured" value={adapterStatus.polling_configured === undefined || adapterStatus.polling_configured === null ? undefined : String(adapterStatus.polling_configured)} />
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Reconciliation</CardTitle>
            </CardHeader>
            <CardContent>
              {!reconciliation ? (
                <p className="text-xs text-text-muted">No reconciliation record for this session yet.</p>
              ) : (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <div className="text-text-muted font-mono">State</div>
                      <div className="mt-0.5"><ReconciliationStateBadge state={reconciliation.state} /></div>
                    </div>
                    <DetailField label="Last source" value={reconciliation.last_source} />
                    <DetailField label="SDK event" value={reconciliation.sdk_event_id} />
                    <DetailField label="Provider event" value={reconciliation.provider_event_id} />
                    <DetailField label="First observed" value={formatDateTime(reconciliation.first_observed_at)} mono={false} />
                    <DetailField label="Last checked" value={formatDateTime(reconciliation.last_checked_at)} mono={false} />
                    <DetailField label="Resolved" value={reconciliation.resolved_at ? formatDateTime(reconciliation.resolved_at) : undefined} mono={false} />
                  </div>
                  {discrepancies.length > 0 && (
                    <div>
                      <div className="text-xs text-text-muted font-mono mb-1.5">Discrepancies</div>
                      <table className="w-full text-xs font-mono">
                        <thead>
                          <tr className="border-b border-border-default text-text-muted">
                            <th className="py-1 pr-2 text-left font-medium">Field</th>
                            <th className="py-1 pr-2 text-left font-medium">SDK value</th>
                            <th className="py-1 text-left font-medium">Provider value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {discrepancies.map(d => (
                            <tr key={d.field} className="border-b border-border-subtle last:border-0">
                              <td className="py-1 pr-2 text-text-primary">{d.field}</td>
                              <td className="py-1 pr-2 text-warning">{d.sdk_value ?? '—'}</td>
                              <td className="py-1 text-danger">{d.provider_value ?? '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <DetailField label="Created" value={formatDateTime(session.created_at)} mono={false} />
            <DetailField label="Updated" value={formatDateTime(session.updated_at)} mono={false} />
          </div>
        </>
      )}
    </div>
  );
}

interface ReconciliationSummaryProps {
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
  readonly counts: Record<ReconciliationState, number>;
  readonly total: number;
}

function ReconciliationSummary({ loading, error, refresh, counts, total }: ReconciliationSummaryProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Reconciliation summary</CardTitle>
      </CardHeader>
      <CardContent>
        {loading && total === 0 && !error ? (
          <LoadingState lines={2} />
        ) : error ? (
          <ErrorState title="Failed to load reconciliation records" message={error} onRetry={refresh} />
        ) : total === 0 ? (
          <p className="text-xs text-text-muted">No reconciliation records yet.</p>
        ) : (
          <div className="grid gap-2 md:grid-cols-3">
            {reconciliationStates.map(state => (
              <div key={state} className="flex items-center justify-between rounded border border-border-default px-2 py-1.5">
                <ReconciliationStateBadge state={state} />
                <span className="text-xs font-mono text-text-primary">{(counts[state] ?? 0).toLocaleString()}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function PaymentRailsPage() {
  const { toast } = useToast();
  const [provider, setProvider] = useState('');
  const [status, setStatus] = useState('');
  const [reconciliationState, setReconciliationState] = useState('');
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [syncingProvider, setSyncingProvider] = useState<PaymentRailProvider | null>(null);

  const params: { provider?: string; status?: string; reconciliation_state?: string } = {};
  if (provider) params.provider = provider;
  if (status) params.status = status;
  if (reconciliationState) params.reconciliation_state = reconciliationState;

  const { sessions, notConfigured, loading, error, refresh } = useFundingSessions(params);
  const health = usePaymentRailHealth();
  const reconciliation = useReconciliationRecords();
  const { sync, loading: syncLoading } = useSyncProvider();

  const healthByProvider = new Map(health.providers.map(h => [h.provider, h]));

  const reconciliationCounts = reconciliation.records.reduce<Record<ReconciliationState, number>>(
    (acc, record) => {
      acc[record.state] = (acc[record.state] ?? 0) + 1;
      return acc;
    },
    {} as Record<ReconciliationState, number>,
  );

  const handleSync = async (target: PaymentRailProvider) => {
    setSyncingProvider(target);
    const result = await sync(target);
    setSyncingProvider(null);
    if (result !== null) {
      toast.success(`${providerLabel(target)} status sync requested`);
    } else {
      toast.error(`Failed to sync ${providerLabel(target)} status`);
    }
  };

  const columns = [
    {
      key: 'provider',
      header: 'Provider',
      render: (row: FundingSessionRecord) => (
        <div>
          <ProviderBadge provider={row.provider} />
          {row.provider_detail && (
            <div className="text-[10px] text-text-muted font-mono mt-0.5">via {row.provider_detail}</div>
          )}
        </div>
      ),
    },
    {
      key: 'flow',
      header: 'Flow',
      render: (row: FundingSessionRecord) => (
        <div>
          <div className="text-text-primary">{flowTypeLabel(row.flow_type)}</div>
          <div className="text-[10px] text-text-muted font-mono">{row.rail}</div>
        </div>
      ),
    },
    {
      key: 'amount',
      header: 'Amount',
      render: (row: FundingSessionRecord) => (
        <div className="font-mono text-xs">
          <div>{formatNativeAmount(row.source_amount, row.source_asset ?? row.fiat_currency)}</div>
          <div className="text-text-muted">
            → {formatNativeAmount(row.destination_amount, row.destination_asset ?? row.fiat_currency)}
          </div>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row: FundingSessionRecord) => <SessionStatusBadge status={row.status} />,
    },
    {
      key: 'reconciliation',
      header: 'Reconciliation',
      render: (row: FundingSessionRecord) => <ReconciliationStateBadge state={row.reconciliation_state} />,
    },
    {
      key: 'occurred_at',
      header: 'Occurred',
      render: (row: FundingSessionRecord) => (
        <span className="text-xs text-text-muted">{formatDateTime(row.occurred_at)}</span>
      ),
    },
  ];

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Payment Rails</h1>
        <p className="text-sm text-text-secondary mt-0.5">
          Funding sessions observed across payment rail providers. {OBSERVABILITY_COPY}
        </p>
      </div>

      {/* Provider health */}
      {health.loading && health.providers.length === 0 && !health.error && !health.notConfigured ? (
        <LoadingState lines={4} />
      ) : health.error ? (
        <ErrorState title="Failed to load provider health" message={health.error} onRetry={health.refresh} />
      ) : health.notConfigured ? (
        <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {paymentRailProviders.map(p => (
            <ProviderHealthCard
              key={p}
              provider={p}
              health={healthByProvider.get(p)}
              syncing={syncingProvider === p && syncLoading}
              syncDisabled={syncLoading}
              onSync={target => void handleSync(target)}
            />
          ))}
        </div>
      )}

      <ReconciliationSummary
        loading={reconciliation.loading}
        error={reconciliation.error}
        refresh={reconciliation.refresh}
        counts={reconciliationCounts}
        total={reconciliation.records.length}
      />

      {/* Funding sessions */}
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <select
            value={provider}
            onChange={e => setProvider(e.target.value)}
            className={selectClass}
            aria-label="Filter by provider"
          >
            {PROVIDER_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          <select
            value={status}
            onChange={e => setStatus(e.target.value)}
            className={selectClass}
            aria-label="Filter by status"
          >
            {STATUS_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          <select
            value={reconciliationState}
            onChange={e => setReconciliationState(e.target.value)}
            className={selectClass}
            aria-label="Filter by reconciliation state"
          >
            {RECONCILIATION_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {loading && sessions.length === 0 ? (
          <LoadingState lines={6} />
        ) : error ? (
          <ErrorState title="Failed to load funding sessions" message={error} onRetry={refresh} />
        ) : notConfigured ? (
          <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />
        ) : sessions.length === 0 ? (
          <EmptyState
            title="No funding sessions observed yet"
            description="Sessions appear here once a configured provider reports onramp, offramp, deposit, settlement, or refund activity."
          />
        ) : (
          <DataTable
            columns={columns}
            data={sessions}
            keyExtractor={row => row.id}
            onRowClick={row => setSelectedSessionId(row.id)}
          />
        )}
      </div>

      {selectedSessionId && (
        <SessionDetailDrawer sessionId={selectedSessionId} onClose={() => setSelectedSessionId(null)} />
      )}
    </div>
  );
}
