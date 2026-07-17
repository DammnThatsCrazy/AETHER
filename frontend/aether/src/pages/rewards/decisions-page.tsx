import { useState } from 'react';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  DataTable, EmptyState, ErrorState, LoadingState,
  Tabs, TabsContent, TabsList, TabsTrigger,
  formatCount, useTimeContext,
} from '@aether/ui';
import { useRewardsDecisions } from '@aether-app/features/rewards/use-rewards';

// ── Helpers ───────────────────────────────────────────────────────────────────

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function fmtScore(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(3);
}

function fmtPct(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

type DecisionVariant = 'success' | 'warning' | 'danger' | 'default';

function decisionVariant(decision: string): DecisionVariant {
  if (decision === 'eligible') return 'success';
  if (decision === 'needs_review') return 'warning';
  if (decision.startsWith('blocked_')) return 'danger';
  return 'default';
}

// ── Stat tile ─────────────────────────────────────────────────────────────────

function Stat({ label, value, accent }: { label: string; value: React.ReactNode; accent?: string }) {
  return (
    <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className={`text-xl font-semibold mt-0.5 ${accent ?? 'text-text-primary'}`}>{value}</p>
    </div>
  );
}

// ── Decision row type ─────────────────────────────────────────────────────────

type DecisionRow = Record<string, unknown>;

// ── Decision table ────────────────────────────────────────────────────────────

function DecisionTable({ rows }: { rows: DecisionRow[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No eligibility decisions"
        description="Decisions appear here once Aether has evaluated reward eligibility for incoming events."
      />
    );
  }

  return (
    <DataTable<DecisionRow>
      keyExtractor={r => fmt(r.id ?? r.decision_id)}
      data={rows}
      columns={[
        {
          key: 'decision',
          header: 'Decision',
          render: r => {
            const d = fmt(r.decision ?? r.status);
            return (
              <Badge variant={decisionVariant(d)}>
                {d.replace(/_/g, ' ')}
              </Badge>
            );
          },
        },
        {
          key: 'campaign',
          header: 'Campaign',
          render: r => (
            <span className="text-text-primary text-sm">
              {fmt(r.campaign_name ?? r.campaign_id)}
            </span>
          ),
        },
        {
          key: 'user',
          header: 'User / Wallet',
          render: r => {
            const wallet = fmt(r.wallet_address ?? r.user_address, '');
            const userId = fmt(r.user_id ?? r.entity_id, '');
            return (
              <div className="min-w-0">
                {userId && <p className="text-xs text-text-secondary truncate max-w-[140px]">{userId}</p>}
                {wallet && (
                  <code className="text-xs text-text-muted truncate block max-w-[140px]">
                    {wallet.slice(0, 6)}…{wallet.slice(-4)}
                  </code>
                )}
                {!userId && !wallet && <span className="text-text-muted">—</span>}
              </div>
            );
          },
        },
        {
          key: 'rail',
          header: 'Rail',
          render: r => r.rail
            ? <Badge variant="default">{fmt(r.rail)}</Badge>
            : <span className="text-text-muted">—</span>,
        },
        {
          key: 'attribution_weight',
          header: 'Attribution Weight',
          render: r => (
            <span className="text-text-secondary tabular-nums">
              {fmtPct(r.attribution_weight ?? r.weight)}
            </span>
          ),
        },
        {
          key: 'fraud_score',
          header: 'Fraud Score',
          render: r => {
            const score = r.fraud_score ?? r.risk_score;
            if (score === null || score === undefined) return <span className="text-text-muted">—</span>;
            const n = Number(score);
            const color = n > 0.7 ? 'text-danger' : n > 0.4 ? 'text-warning' : 'text-success';
            return <span className={`tabular-nums font-mono text-xs ${color}`}>{fmtScore(score)}</span>;
          },
        },
        {
          key: 'created_at',
          header: 'Created',
          render: r => (
            <span className="text-text-muted text-xs tabular-nums">
              {relTime(r.created_at as string | null)}
            </span>
          ),
        },
      ]}
    />
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function RewardDecisionsPage() {
  const timeCtx = useTimeContext();
  const [tab, setTab] = useState<'all' | 'eligible' | 'needs_review' | 'blocked'>('all');

  const { data, isLoading, error, refetch } = useRewardsDecisions({ limit: 200 });
  const d = asRecord(data);
  const allDecisions = asList(d.decisions ?? d.items ?? data).map(asRecord);

  const eligible = allDecisions.filter(r => fmt(r.decision ?? r.status) === 'eligible');
  const needsReview = allDecisions.filter(r => fmt(r.decision ?? r.status) === 'needs_review');
  const blocked = allDecisions.filter(r => {
    const dec = fmt(r.decision ?? r.status);
    return dec.startsWith('blocked_') || dec === 'ineligible';
  });

  const tabRows: Record<string, DecisionRow[]> = {
    all: allDecisions,
    eligible,
    needs_review: needsReview,
    blocked,
  };

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Eligibility Decisions</h1>
          <p className="text-sm text-text-secondary mt-0.5">
            Aether verifies eligibility — tenant systems execute rewards via configured rails.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => { void refetch?.(); }}>
          Refresh
        </Button>
      </div>

      {/* Stats row */}
      {!isLoading && !error && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat label="Total decisions" value={formatCount(allDecisions.length, timeCtx)} />
          <Stat label="Eligible" value={formatCount(eligible.length, timeCtx)} accent="text-success" />
          <Stat label="Needs review" value={formatCount(needsReview.length, timeCtx)} accent="text-warning" />
          <Stat label="Blocked / Ineligible" value={formatCount(blocked.length, timeCtx)} accent="text-danger" />
        </div>
      )}

      {/* Content */}
      <Card>
        <CardHeader>
          <CardTitle>Decisions</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <ErrorState
              title="Failed to load decisions"
              message={String(error)}
            />
          ) : isLoading ? (
            <LoadingState lines={8} />
          ) : (
            <Tabs value={tab} onValueChange={v => setTab(v as typeof tab)}>
              <TabsList>
                <TabsTrigger value="all">
                  All <Badge variant="default" size="sm" className="ml-1">{allDecisions.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="eligible">
                  Eligible <Badge variant="success" size="sm" className="ml-1">{eligible.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="needs_review">
                  Needs Review <Badge variant="warning" size="sm" className="ml-1">{needsReview.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="blocked">
                  Blocked <Badge variant="danger" size="sm" className="ml-1">{blocked.length}</Badge>
                </TabsTrigger>
              </TabsList>

              {(['all', 'eligible', 'needs_review', 'blocked'] as const).map(t => (
                <TabsContent key={t} value={t}>
                  <DecisionTable rows={tabRows[t] ?? []} />
                </TabsContent>
              ))}
            </Tabs>
          )}
        </CardContent>
      </Card>

      {/* No-custody notice */}
      <p className="text-xs text-text-muted border border-border-default rounded-md px-3 py-2 bg-surface-raised">
        <strong className="text-text-secondary">No-custody platform:</strong> Aether produces eligibility decisions and action payloads only.
        Tenant rail systems are responsible for executing reward delivery. Campaign budget policy is configured and enforced by the tenant.
      </p>
    </div>
  );
}
