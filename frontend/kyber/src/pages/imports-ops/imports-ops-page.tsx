import { useNavigate } from 'react-router-dom';
import {
  Badge,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  formatCount,
  formatInstant,
  useTimeContext,
  type TimeContext,
} from '@aether/ui';
import type { ImportStatus } from '@aether/shared';
import { PageWrapper } from '@kyber/components/layout';
import { useImportsTimeline } from '@kyber/features/imports-ops';
import type { ImportSessionRecord } from '@kyber/features/imports-ops';

const PAGE_SUBTITLE =
  'Cross-tenant view of every import session, newest first. Operators triage stuck or failed imports and requeue recoveries — Aether never mutates tenant data without lineage.';

const STATUS_VARIANTS: Record<ImportStatus, 'success' | 'warning' | 'danger' | 'info' | 'accent' | 'default'> = {
  created: 'default',
  files_pending: 'default',
  uploaded: 'info',
  analyzing: 'info',
  analyzed: 'info',
  mapping: 'info',
  mapped: 'accent',
  validating: 'info',
  validated: 'accent',
  review_required: 'warning',
  approved: 'accent',
  committing: 'info',
  committed: 'success',
  partially_committed: 'warning',
  failed: 'danger',
  cancelled: 'default',
  rolled_back: 'danger',
};

export function ImportStatusBadge({ status }: { readonly status: ImportStatus }) {
  return <Badge variant={STATUS_VARIANTS[status] ?? 'default'}>{status}</Badge>;
}

export function formatImportDate(iso: string | null | undefined, ctx: TimeContext): string {
  if (!iso) return '—';
  try {
    return formatInstant(iso, ctx);
  } catch {
    return iso;
  }
}

export function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 14)}…` : id;
}

export function ImportsOpsPage() {
  const navigate = useNavigate();
  const timeCtx = useTimeContext();
  const { sessions, count, loading, error, refresh } = useImportsTimeline();

  const columns = [
    {
      key: 'id',
      header: 'Import',
      render: (row: ImportSessionRecord) => (
        <div>
          <div className="font-mono text-text-primary">{shortId(row.id)}</div>
          <div className="text-xs text-text-muted font-mono">{row.source_kind}</div>
        </div>
      ),
    },
    {
      key: 'tenant_id',
      header: 'Tenant',
      render: (row: ImportSessionRecord) => (
        <span className="font-mono text-text-secondary">{row.tenant_id}</span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row: ImportSessionRecord) => <ImportStatusBadge status={row.status} />,
    },
    {
      key: 'file_count',
      header: 'Files',
      render: (row: ImportSessionRecord) => (
        <span className="font-mono">{formatCount(row.file_count, timeCtx)}</span>
      ),
    },
    {
      key: 'row_count',
      header: 'Rows',
      render: (row: ImportSessionRecord) => (
        <span className="font-mono text-text-secondary">
          {row.row_count !== null && row.row_count !== undefined ? formatCount(row.row_count, timeCtx) : '—'}
        </span>
      ),
    },
    {
      key: 'created_at',
      header: 'Created',
      render: (row: ImportSessionRecord) => (
        <span className="text-xs text-text-muted">{formatImportDate(row.created_at, timeCtx)}</span>
      ),
    },
  ];

  return (
    <PageWrapper title="Tenant Import Engine" subtitle={PAGE_SUBTITLE}>
      {loading && sessions.length === 0 ? (
        <LoadingState lines={6} />
      ) : error ? (
        <ErrorState title="Failed to load import timeline" message={error} onRetry={refresh} />
      ) : sessions.length === 0 ? (
        <EmptyState
          title="No imports yet"
          description="Once tenants stage imports, their sessions appear here across every tenant, newest first."
        />
      ) : (
        <>
          <div className="text-xs text-text-muted font-mono">
            {formatCount(count, timeCtx)} session{count === 1 ? '' : 's'} across all tenants
          </div>
          <DataTable
            columns={columns}
            data={sessions}
            keyExtractor={row => row.id}
            onRowClick={row => void navigate(`/imports/${row.id}`)}
          />
        </>
      )}
    </PageWrapper>
  );
}
