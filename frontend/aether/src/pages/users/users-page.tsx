import { useNavigate } from 'react-router-dom';
import {
  Badge, Button, DataTable, EmptyState, ErrorState,
  Input, LoadingState, Skeleton,
} from '@aether/ui';
import { useUsers } from '@aether-app/features/users/use-users';

function scoreColor(score: number | undefined): 'success' | 'warning' | 'danger' | 'default' {
  if (score === undefined) return 'default';
  if (score >= 0.7) return 'success';
  if (score >= 0.4) return 'warning';
  return 'danger';
}

function churnBadge(risk: string | undefined) {
  if (!risk) return null;
  const variant = risk === 'low' ? 'success' : risk === 'medium' ? 'warning' : risk === 'churned' ? 'danger' : 'warning';
  return <Badge variant={variant} size="sm">{risk}</Badge>;
}

function tierBadge(tier: string | undefined) {
  if (!tier || tier === 'none') return null;
  const variant = ['gold', 'platinum', 'diamond'].includes(tier) ? 'warning' : 'default';
  return <Badge variant={variant} size="sm">{tier}</Badge>;
}

function relativeTime(iso: string | undefined): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const d = Math.floor(diff / 86_400_000);
  if (d === 0) return 'Today';
  if (d === 1) return 'Yesterday';
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
}

export function UsersPage() {
  const navigate = useNavigate();
  const { users, search, setSearch, isLoading, error, reload } = useUsers();

  if (error) {
    return (
      <div className="p-8">
        <ErrorState
          title="Failed to load users"
          message={error}
          onRetry={reload}
        />
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Users</h1>
          <div className="text-sm text-text-secondary mt-0.5">
            {isLoading ? <Skeleton className="w-20 h-3 inline-block" /> : `${users.length} users`}
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={reload}>Refresh</Button>
      </div>

      {/* Search */}
      <Input
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Search by name, email, wallet, device ID…"
        className="max-w-md"
      />

      {/* Table */}
      {isLoading ? (
        <LoadingState lines={8} />
      ) : users.length === 0 ? (
        <EmptyState
          title="No users found"
          description={search ? `No results for "${search}"` : 'No users have been ingested yet.'}
        />
      ) : (
        <DataTable
          keyExtractor={u => u.id}
          onRowClick={u => navigate(`/users/${u.id}`)}
          data={users}
          columns={[
            {
              key: 'user',
              header: 'User',
              render: u => (
                <div>
                  <div className="font-medium text-text-primary">{u.displayName}</div>
                  {u.email && <div className="text-text-muted text-xs">{u.email}</div>}
                  <div className="text-text-muted text-xs font-mono">{u.id}</div>
                </div>
              ),
            },
            {
              key: 'trust',
              header: 'Trust',
              render: u => u.trustScore !== undefined
                ? <Badge variant={scoreColor(u.trustScore)} size="sm">{Math.round(u.trustScore * 100)}</Badge>
                : <span className="text-text-muted">—</span>,
            },
            {
              key: 'risk',
              header: 'Risk',
              render: u => u.riskScore !== undefined
                ? <Badge variant={scoreColor(1 - u.riskScore)} size="sm">{Math.round(u.riskScore * 100)}</Badge>
                : <span className="text-text-muted">—</span>,
            },
            {
              key: 'churn',
              header: 'Churn',
              render: u => churnBadge(u.churnRisk) ?? <span className="text-text-muted">—</span>,
            },
            {
              key: 'tier',
              header: 'Tier',
              render: u => tierBadge(u.loyaltyTier) ?? <span className="text-text-muted">—</span>,
            },
            {
              key: 'sessions',
              header: 'Sessions (30d)',
              render: u => u.sessionCount30d !== undefined
                ? <span className="text-text-primary">{u.sessionCount30d}</span>
                : <span className="text-text-muted">—</span>,
            },
            {
              key: 'platforms',
              header: 'Platforms',
              render: u => u.platforms?.length
                ? <div className="flex gap-1 flex-wrap">{u.platforms.slice(0, 3).map(p => <Badge key={p} variant="default" size="sm">{p}</Badge>)}</div>
                : <span className="text-text-muted">—</span>,
            },
            {
              key: 'lastSeen',
              header: 'Last seen',
              render: u => <span className="text-text-secondary">{relativeTime(u.lastSeenAt)}</span>,
            },
          ]}
        />
      )}
    </div>
  );
}
