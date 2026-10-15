import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  formatCount,
  formatInstant,
  useTimeContext,
  useToast,
  type TimeContext,
} from '@aether/ui';
import type { ImportStatus } from '@aether/shared';
import { useImports, useCreateImport } from '@aether-app/features/imports';
import type { ImportSessionRecord } from '@aether-app/features/imports';

const IMPORT_COPY =
  'Upload a file, map it onto Aether primitives, validate, then commit — nothing is imported until it is staged with lineage.';

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

function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 14)}…` : id;
}

export function ImportsPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const timeCtx = useTimeContext();
  const { imports, loading, error, refresh } = useImports();
  const { create, loading: creating } = useCreateImport();

  const handleNewImport = async () => {
    const created = await create();
    if (created) {
      toast.success('Import session created');
      void navigate(`/imports/${created.id}`);
    } else {
      toast.error('Failed to create import');
    }
  };

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
    <div className="p-8 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Import Engine</h1>
          <p className="text-sm text-text-secondary mt-0.5">{IMPORT_COPY}</p>
        </div>
        <Button onClick={() => void handleNewImport()} disabled={creating}>
          {creating ? 'Creating…' : 'New import'}
        </Button>
      </div>

      {loading && imports.length === 0 ? (
        <LoadingState lines={6} />
      ) : error ? (
        <ErrorState title="Failed to load imports" message={error} onRetry={refresh} />
      ) : imports.length === 0 ? (
        <EmptyState
          title="No imports yet"
          description="Create an import to upload a file, map it onto Aether primitives, and stage it into the graph."
          action={
            <Button variant="secondary" onClick={() => void handleNewImport()} disabled={creating}>
              New import
            </Button>
          }
        />
      ) : (
        <DataTable
          columns={columns}
          data={imports}
          keyExtractor={row => row.id}
          onRowClick={row => void navigate(`/imports/${row.id}`)}
        />
      )}
    </div>
  );
}
