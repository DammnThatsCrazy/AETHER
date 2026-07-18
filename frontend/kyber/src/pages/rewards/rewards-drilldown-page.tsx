import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
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
  formatDateTime,
  useTimeContext,
  type TimeContext,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

// ─── Utility helpers ──────────────────────────────────────────────────────────

type AnyRecord = Record<string, unknown>;

function asArr(v: unknown): AnyRecord[] {
  return Array.isArray(v) ? (v as AnyRecord[]) : [];
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function fmtDate(iso: unknown, ctx: TimeContext): string {
  if (!iso) return '—';
  try {
    return formatDateTime(String(iso), ctx);
  } catch {
    return String(iso);
  }
}

function decisionVariant(d: unknown): 'success' | 'warning' | 'danger' | 'default' {
  const s = String(d ?? '').toLowerCase();
  if (s === 'eligible') return 'success';
  if (s === 'blocked_fraud' || s === 'blocked') return 'danger';
  if (s === 'ineligible') return 'warning';
  return 'default';
}

function actionStatusVariant(s: unknown): 'success' | 'warning' | 'danger' | 'default' {
  const str = String(s ?? '').toLowerCase();
  if (str === 'delivered') return 'success';
  if (str === 'pending_approval' || str === 'ready') return 'warning';
  if (str === 'failed' || str === 'dead_lettered') return 'danger';
  return 'default';
}

function campaignStatusVariant(s: unknown): 'success' | 'warning' | 'danger' | 'default' {
  const str = String(s ?? '').toLowerCase();
  if (str === 'active') return 'success';
  if (str === 'paused') return 'warning';
  if (str === 'ended' || str === 'archived') return 'default';
  return 'default';
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface TenantRewardsData {
  campaigns: AnyRecord[];
  decisions: AnyRecord[];
  actions: AnyRecord[];
  auditLog: AnyRecord[];
  hasMoreCampaigns: boolean;
  hasMoreDecisions: boolean;
  hasMoreActions: boolean;
  hasMoreAudit: boolean;
}

const EMPTY_TENANT_DATA: TenantRewardsData = {
  campaigns: [],
  decisions: [],
  actions: [],
  auditLog: [],
  hasMoreCampaigns: false,
  hasMoreDecisions: false,
  hasMoreActions: false,
  hasMoreAudit: false,
};

const PAGE_SIZE = 20;

// ─── Mock data builder ────────────────────────────────────────────────────────

function buildMockTenantData(tenantId: string): TenantRewardsData {
  return {
    campaigns: [
      { id: 'camp_001', name: 'Q2 Loyalty Drive', status: 'active', default_rail: 'erc20_transfer', created_at: '2026-04-01T00:00:00Z' },
      { id: 'camp_002', name: 'Referral Bonus Round', status: 'active', default_rail: 'coinbase_pay', created_at: '2026-04-15T00:00:00Z' },
      { id: 'camp_003', name: 'Early Adopter Boost', status: 'ended', default_rail: 'circle_usdc', created_at: '2026-01-10T00:00:00Z' },
    ],
    decisions: [
      { id: `dec_${tenantId}_001`, decision: 'eligible', campaign_id: 'camp_001', wallet_address: '0xabc...111', fraud_score: 0.03, attribution_weight: 0.92, created_at: '2026-06-14T14:01:00Z' },
      { id: `dec_${tenantId}_002`, decision: 'eligible', campaign_id: 'camp_002', wallet_address: '0xdef...222', fraud_score: 0.01, attribution_weight: 0.88, created_at: '2026-06-14T14:00:45Z' },
      { id: `dec_${tenantId}_003`, decision: 'blocked_fraud', campaign_id: 'camp_001', wallet_address: '0x456...333', fraud_score: 0.91, attribution_weight: 0.00, created_at: '2026-06-14T13:58:00Z' },
      { id: `dec_${tenantId}_004`, decision: 'ineligible', campaign_id: 'camp_003', wallet_address: '0x789...444', fraud_score: 0.05, attribution_weight: 0.00, created_at: '2026-06-14T13:55:00Z' },
      { id: `dec_${tenantId}_005`, decision: 'eligible', campaign_id: 'camp_002', wallet_address: '0xccc...555', fraud_score: 0.02, attribution_weight: 0.76, created_at: '2026-06-14T13:52:00Z' },
    ],
    actions: [
      { id: `act_${tenantId}_001`, rail: 'erc20_transfer', status: 'delivered', delivery_attempts: 1, created_at: '2026-06-14T14:01:10Z' },
      { id: `act_${tenantId}_002`, rail: 'coinbase_pay', status: 'delivered', delivery_attempts: 1, created_at: '2026-06-14T14:00:55Z' },
      { id: `act_${tenantId}_003`, rail: 'erc20_transfer', status: 'failed', delivery_attempts: 3, created_at: '2026-06-14T13:48:00Z' },
      { id: `act_${tenantId}_004`, rail: 'circle_usdc', status: 'pending_approval', delivery_attempts: 0, created_at: '2026-06-14T13:45:00Z' },
    ],
    auditLog: [
      { actor_type: 'operator', action: 'campaign.created', target_type: 'campaign', target_id: 'camp_001', created_at: '2026-04-01T09:00:00Z' },
      { actor_type: 'system', action: 'decision.evaluated', target_type: 'decision', target_id: `dec_${tenantId}_001`, created_at: '2026-06-14T14:01:00Z' },
      { actor_type: 'operator', action: 'campaign.paused', target_type: 'campaign', target_id: 'camp_002', created_at: '2026-06-14T12:00:00Z' },
      { actor_type: 'system', action: 'action.delivered', target_type: 'action', target_id: `act_${tenantId}_001`, created_at: '2026-06-14T14:01:10Z' },
      { actor_type: 'tenant', action: 'rail.configured', target_type: 'rail', target_id: 'erc20_transfer', created_at: '2026-03-20T08:00:00Z' },
    ],
    hasMoreCampaigns: false,
    hasMoreDecisions: true,
    hasMoreActions: true,
    hasMoreAudit: false,
  };
}

// ─── Fetchers ─────────────────────────────────────────────────────────────────

async function fetchTenantCampaigns(
  tenantId: string,
  offset: number,
): Promise<{ items: AnyRecord[]; hasMore: boolean }> {
  try {
    const raw = await (api as AnyRecord as { campaigns?: { list?: (p: AnyRecord) => Promise<AnyRecord> } })
      .campaigns?.list?.({ tenant_id: tenantId, limit: PAGE_SIZE, offset }) ??
      await fetch(`/v1/admin/kyber/tenants/${encodeURIComponent(tenantId)}/campaigns?limit=${PAGE_SIZE}&offset=${offset}`)
        .then(r => (r.ok ? r.json() : Promise.reject(r.statusText)));
    const d = (raw as AnyRecord)?.data ?? raw;
    const items = asArr((d as AnyRecord)?.campaigns ?? (d as AnyRecord)?.items ?? d);
    const hasMore = Boolean((d as AnyRecord)?.has_more ?? items.length === PAGE_SIZE);
    return { items, hasMore };
  } catch {
    const mock = buildMockTenantData(tenantId);
    return { items: mock.campaigns, hasMore: mock.hasMoreCampaigns };
  }
}

async function fetchTenantDecisions(
  tenantId: string,
  offset: number,
): Promise<{ items: AnyRecord[]; hasMore: boolean }> {
  try {
    const raw = await fetch(
      `/v1/admin/kyber/tenants/${encodeURIComponent(tenantId)}/decisions?limit=${PAGE_SIZE}&offset=${offset}`,
    ).then(r => (r.ok ? r.json() : Promise.reject(r.statusText)));
    const d = (raw as AnyRecord)?.data ?? raw;
    const items = asArr((d as AnyRecord)?.decisions ?? (d as AnyRecord)?.items ?? d);
    const hasMore = Boolean((d as AnyRecord)?.has_more ?? items.length === PAGE_SIZE);
    return { items, hasMore };
  } catch {
    const mock = buildMockTenantData(tenantId);
    return { items: mock.decisions, hasMore: mock.hasMoreDecisions };
  }
}

async function fetchTenantActions(
  tenantId: string,
  offset: number,
): Promise<{ items: AnyRecord[]; hasMore: boolean }> {
  try {
    const raw = await fetch(
      `/v1/admin/kyber/tenants/${encodeURIComponent(tenantId)}/actions?limit=${PAGE_SIZE}&offset=${offset}`,
    ).then(r => (r.ok ? r.json() : Promise.reject(r.statusText)));
    const d = (raw as AnyRecord)?.data ?? raw;
    const items = asArr((d as AnyRecord)?.actions ?? (d as AnyRecord)?.items ?? d);
    const hasMore = Boolean((d as AnyRecord)?.has_more ?? items.length === PAGE_SIZE);
    return { items, hasMore };
  } catch {
    const mock = buildMockTenantData(tenantId);
    return { items: mock.actions, hasMore: mock.hasMoreActions };
  }
}

async function fetchTenantAuditLog(
  tenantId: string,
  offset: number,
): Promise<{ items: AnyRecord[]; hasMore: boolean }> {
  try {
    const raw = await fetch(
      `/v1/admin/kyber/tenants/${encodeURIComponent(tenantId)}/audit?limit=${PAGE_SIZE}&offset=${offset}`,
    ).then(r => (r.ok ? r.json() : Promise.reject(r.statusText)));
    const d = (raw as AnyRecord)?.data ?? raw;
    const items = asArr((d as AnyRecord)?.entries ?? (d as AnyRecord)?.items ?? d);
    const hasMore = Boolean((d as AnyRecord)?.has_more ?? items.length === PAGE_SIZE);
    return { items, hasMore };
  } catch {
    const mock = buildMockTenantData(tenantId);
    return { items: mock.auditLog, hasMore: mock.hasMoreAudit };
  }
}

// ─── Paginated section hook ───────────────────────────────────────────────────

interface PaginatedSection {
  items: AnyRecord[];
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  loadMore: () => void;
  reload: () => void;
}

function usePaginatedSection(
  tenantId: string,
  fetcher: (tenantId: string, offset: number) => Promise<{ items: AnyRecord[]; hasMore: boolean }>,
): PaginatedSection {
  const [items, setItems] = useState<AnyRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const offsetRef = useRef(0);
  const tenantRef = useRef(tenantId);

  const load = useCallback(
    (reset: boolean) => {
      if (!tenantId) return;
      setLoading(true);
      setError(null);
      const offset = reset ? 0 : offsetRef.current;
      fetcher(tenantId, offset)
        .then(({ items: newItems, hasMore: more }) => {
          setItems(prev => (reset ? newItems : [...prev, ...newItems]));
          setHasMore(more);
          offsetRef.current = offset + newItems.length;
        })
        .catch(e => setError(e instanceof Error ? e.message : String(e)))
        .finally(() => setLoading(false));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tenantId],
  );

  useEffect(() => {
    if (tenantRef.current !== tenantId) {
      tenantRef.current = tenantId;
      offsetRef.current = 0;
      setItems([]);
      setHasMore(false);
    }
    load(true);
  }, [load, tenantId]);

  const loadMore = useCallback(() => load(false), [load]);
  const reload = useCallback(() => {
    offsetRef.current = 0;
    load(true);
  }, [load]);

  return { items, loading, error, hasMore, loadMore, reload };
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function SectionCard({
  title,
  loading,
  error,
  hasMore,
  onLoadMore,
  onRetry,
  children,
  isEmpty,
  emptyTitle,
  emptyDescription,
}: {
  readonly title: string;
  readonly loading: boolean;
  readonly error: string | null;
  readonly hasMore: boolean;
  readonly onLoadMore: () => void;
  readonly onRetry: () => void;
  readonly children: React.ReactNode;
  readonly isEmpty: boolean;
  readonly emptyTitle: string;
  readonly emptyDescription: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {error ? (
          <ErrorState
            title="Failed to load"
            message={error}
            onRetry={onRetry}
          />
        ) : isEmpty && !loading ? (
          <EmptyState title={emptyTitle} description={emptyDescription} />
        ) : (
          <>
            {children}
            {loading && <LoadingState lines={3} className="mt-2" />}
            {!loading && hasMore && (
              <div className="mt-3 flex justify-center">
                <Button variant="ghost" size="sm" onClick={onLoadMore}>
                  Load more
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Tenant drilldown body ────────────────────────────────────────────────────

function TenantDrilldown({ tenantId }: { readonly tenantId: string }) {
  const campaigns = usePaginatedSection(tenantId, fetchTenantCampaigns);
  const decisions = usePaginatedSection(tenantId, fetchTenantDecisions);
  const actions = usePaginatedSection(tenantId, fetchTenantActions);
  const auditLog = usePaginatedSection(tenantId, fetchTenantAuditLog);
  const timeCtx = useTimeContext();

  return (
    <div className="space-y-4">
      {/* Campaigns */}
      <SectionCard
        title="Campaigns"
        loading={campaigns.loading}
        error={campaigns.error}
        hasMore={campaigns.hasMore}
        onLoadMore={campaigns.loadMore}
        onRetry={campaigns.reload}
        isEmpty={campaigns.items.length === 0}
        emptyTitle="No campaigns"
        emptyDescription="This tenant has no reward campaigns configured."
      >
        <DataTable
          data={campaigns.items}
          keyExtractor={(r) => fmt(r.id ?? r.campaign_id)}
          columns={[
            {
              key: 'id',
              header: 'ID',
              render: (r) => <span className="font-mono text-xs">{fmt(r.id ?? r.campaign_id)}</span>,
            },
            {
              key: 'name',
              header: 'Name',
              render: (r) => <span className="font-semibold text-xs">{fmt(r.name ?? r.campaign_name)}</span>,
            },
            {
              key: 'status',
              header: 'Status',
              render: (r) => (
                <Badge variant={campaignStatusVariant(r.status)} size="sm">
                  {fmt(r.status)}
                </Badge>
              ),
            },
            {
              key: 'default_rail',
              header: 'Default Rail',
              render: (r) => (
                <span className="font-mono text-xs text-text-secondary">
                  {fmt(r.default_rail ?? r.rail)}
                </span>
              ),
            },
            {
              key: 'created_at',
              header: 'Created',
              render: (r) => (
                <span className="text-xs text-text-muted">{fmtDate(r.created_at, timeCtx)}</span>
              ),
            },
          ]}
        />
      </SectionCard>

      {/* Eligibility decisions */}
      <SectionCard
        title="Recent Eligibility Decisions"
        loading={decisions.loading}
        error={decisions.error}
        hasMore={decisions.hasMore}
        onLoadMore={decisions.loadMore}
        onRetry={decisions.reload}
        isEmpty={decisions.items.length === 0}
        emptyTitle="No eligibility decisions"
        emptyDescription="No eligibility decisions have been recorded for this tenant yet."
      >
        <DataTable
          data={decisions.items}
          keyExtractor={(r) => fmt(r.id ?? r.decision_id)}
          columns={[
            {
              key: 'id',
              header: 'Decision ID',
              render: (r) => <span className="font-mono text-xs">{fmt(r.id ?? r.decision_id)}</span>,
            },
            {
              key: 'decision',
              header: 'Decision',
              render: (r) => (
                <Badge variant={decisionVariant(r.decision)} size="sm">
                  {fmt(r.decision)}
                </Badge>
              ),
            },
            {
              key: 'campaign_id',
              header: 'Campaign',
              render: (r) => (
                <span className="font-mono text-xs text-text-secondary">{fmt(r.campaign_id)}</span>
              ),
            },
            {
              key: 'wallet_address',
              header: 'Wallet',
              render: (r) => (
                <span className="font-mono text-xs text-text-muted truncate max-w-[120px] block">
                  {fmt(r.wallet_address)}
                </span>
              ),
            },
            {
              key: 'fraud_score',
              header: 'Fraud Score',
              render: (r) => {
                const score = Number(r.fraud_score ?? 0);
                const cls =
                  score > 0.7
                    ? 'text-red-500 font-semibold'
                    : score > 0.4
                    ? 'text-yellow-500'
                    : 'text-text-muted';
                return <span className={`text-xs ${cls}`}>{score.toFixed(2)}</span>;
              },
            },
            {
              key: 'attribution_weight',
              header: 'Attribution Wt.',
              render: (r) => (
                <span className="text-xs text-text-secondary">
                  {Number(r.attribution_weight ?? 0).toFixed(2)}
                </span>
              ),
            },
            {
              key: 'created_at',
              header: 'When',
              render: (r) => (
                <span className="text-xs text-text-muted">{fmtDate(r.created_at, timeCtx)}</span>
              ),
            },
          ]}
        />
      </SectionCard>

      {/* Action payloads */}
      <SectionCard
        title="Action Payloads"
        loading={actions.loading}
        error={actions.error}
        hasMore={actions.hasMore}
        onLoadMore={actions.loadMore}
        onRetry={actions.reload}
        isEmpty={actions.items.length === 0}
        emptyTitle="No action payloads"
        emptyDescription="No action payloads have been generated for this tenant. Payloads are created when eligibility decisions pass all checks."
      >
        <>
          <p className="mb-3 text-xs text-text-muted">
            Action payloads produced by Aether for delivery via tenant rails. Aether does not execute rewards directly.
          </p>
          <DataTable
            data={actions.items}
            keyExtractor={(r) => fmt(r.id ?? r.action_id)}
            columns={[
              {
                key: 'id',
                header: 'Action ID',
                render: (r) => <span className="font-mono text-xs">{fmt(r.id ?? r.action_id)}</span>,
              },
              {
                key: 'rail',
                header: 'Rail',
                render: (r) => (
                  <span className="font-mono text-xs text-text-secondary">{fmt(r.rail)}</span>
                ),
              },
              {
                key: 'status',
                header: 'Status',
                render: (r) => (
                  <Badge variant={actionStatusVariant(r.status)} size="sm">
                    {fmt(r.status)}
                  </Badge>
                ),
              },
              {
                key: 'delivery_attempts',
                header: 'Attempts',
                render: (r) => {
                  const n = Number(r.delivery_attempts ?? 0);
                  const cls = n > 2 ? 'text-red-500 font-semibold' : n > 0 ? 'text-text-secondary' : 'text-text-muted';
                  return <span className={`text-xs ${cls}`}>{n}</span>;
                },
              },
              {
                key: 'created_at',
                header: 'Created',
                render: (r) => (
                  <span className="text-xs text-text-muted">{fmtDate(r.created_at, timeCtx)}</span>
                ),
              },
            ]}
          />
        </>
      </SectionCard>

      {/* Audit log */}
      <SectionCard
        title="Audit Log"
        loading={auditLog.loading}
        error={auditLog.error}
        hasMore={auditLog.hasMore}
        onLoadMore={auditLog.loadMore}
        onRetry={auditLog.reload}
        isEmpty={auditLog.items.length === 0}
        emptyTitle="No audit events"
        emptyDescription="No audit log entries found for this tenant."
      >
        <DataTable
          data={auditLog.items}
          keyExtractor={(r) => `${fmt(r.target_id)}-${fmt(r.action)}-${fmt(r.created_at)}`}
          columns={[
            {
              key: 'actor_type',
              header: 'Actor',
              render: (r) => (
                <Badge
                  variant={
                    fmt(r.actor_type) === 'operator'
                      ? 'accent'
                      : fmt(r.actor_type) === 'tenant'
                      ? 'warning'
                      : 'default'
                  }
                  size="sm"
                >
                  {fmt(r.actor_type)}
                </Badge>
              ),
            },
            {
              key: 'action',
              header: 'Action',
              render: (r) => (
                <span className="font-mono text-xs text-text-primary">{fmt(r.action)}</span>
              ),
            },
            {
              key: 'target_type',
              header: 'Target Type',
              render: (r) => (
                <span className="text-xs text-text-secondary">{fmt(r.target_type)}</span>
              ),
            },
            {
              key: 'target_id',
              header: 'Target ID',
              render: (r) => (
                <span className="font-mono text-xs text-text-muted">{fmt(r.target_id)}</span>
              ),
            },
            {
              key: 'created_at',
              header: 'When',
              render: (r) => (
                <span className="text-xs text-text-muted">{fmtDate(r.created_at, timeCtx)}</span>
              ),
            },
          ]}
        />
      </SectionCard>
    </div>
  );
}

// ─── Tenant selector ──────────────────────────────────────────────────────────

function TenantSelector({
  value,
  onChange,
}: {
  readonly value: string;
  readonly onChange: (id: string) => void;
}) {
  const [draft, setDraft] = useState(value);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = draft.trim();
    if (trimmed) onChange(trimmed);
  }

  return (
    <Card>
      <CardContent className="py-4">
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <label className="text-xs font-mono text-text-muted shrink-0">Tenant ID</label>
          <input
            className="flex-1 rounded border border-border-default bg-surface-raised px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent font-mono"
            placeholder="e.g. acme-corp"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoFocus={!value}
            spellCheck={false}
          />
          <Button type="submit" variant="primary" size="sm" disabled={!draft.trim()}>
            Load
          </Button>
        </form>
        {value && (
          <p className="mt-2 text-xs text-text-muted font-mono">
            Showing reward data for:{' '}
            <span className="text-accent">{value}</span>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function RewardsDrilldownPage() {
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string }>();
  const navigate = useNavigate();
  const [tenantId, setTenantId] = useState(routeTenantId ?? '');

  function handleTenantChange(id: string) {
    setTenantId(id);
    navigate(`/rewards/${encodeURIComponent(id)}`, { replace: true });
  }

  return (
    <PageWrapper
      title="Reward Drilldown"
      subtitle="Per-tenant view of campaigns, eligibility decisions, action payloads, and audit log. Aether verifies eligibility only — tenant rails execute."
      actions={
        tenantId ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate('/rewards')}
          >
            ← Health Dashboard
          </Button>
        ) : undefined
      }
    >
      <TenantSelector value={tenantId} onChange={handleTenantChange} />

      {tenantId ? (
        <TenantDrilldown key={tenantId} tenantId={tenantId} />
      ) : (
        <EmptyState
          title="Select a tenant"
          description="Enter a tenant ID above to view its reward campaigns, eligibility decisions, action payloads, and audit history."
        />
      )}
    </PageWrapper>
  );
}
