import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
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
  formatCount,
  useTimeContext,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useImportOpsDetail, useRequeueImport } from '@kyber/features/imports-ops';
import type { ImportCommitRecord } from '@kyber/features/imports-ops';
import { ImportStatusBadge, formatImportDate } from './imports-ops-page';

function Field({ label, children }: { readonly label: string; readonly children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-text-muted font-mono">{label}</div>
      <div className="text-sm text-text-primary mt-0.5 font-mono break-all">{children}</div>
    </div>
  );
}

function commitKey(commit: ImportCommitRecord): string {
  return commit.commit_id ?? commit.id ?? `${commit.created_at ?? ''}-${commit.status ?? ''}`;
}

export function ImportOpsDetailPage() {
  const { importId } = useParams<{ importId: string }>();
  const id = importId ?? null;

  const { detail, loading, error, refresh } = useImportOpsDetail(id);
  const { requeue, loading: requeuing, error: requeueError } = useRequeueImport();
  const [requeueMessage, setRequeueMessage] = useState<string | null>(null);
  const timeCtx = useTimeContext();

  const handleRequeue = async () => {
    if (!id) return;
    setRequeueMessage(null);
    const result = await requeue(id);
    if (result) {
      const jobStatus = result.job.status ?? result.job.id ?? 'enqueued';
      setRequeueMessage(`Requeue accepted — commit job ${jobStatus}.`);
      refresh();
    } else {
      setRequeueMessage('Requeue failed.');
    }
  };

  if (loading && !detail) {
    return (
      <PageWrapper title="Import detail">
        <LoadingState lines={8} />
      </PageWrapper>
    );
  }

  if (error) {
    return (
      <PageWrapper title="Import detail">
        <ErrorState title="Failed to load import" message={error} onRetry={refresh} />
      </PageWrapper>
    );
  }

  if (!detail) {
    return (
      <PageWrapper title="Import detail">
        <EmptyState
          title="Import not found"
          description="This import session does not exist or is no longer visible."
          action={<Link to="/imports" className="text-sm text-accent hover:underline">Back to imports</Link>}
        />
      </PageWrapper>
    );
  }

  const session = detail.session;
  const isFailed = session.status === 'failed';

  const commitColumns = [
    {
      key: 'commit_id',
      header: 'Commit',
      render: (row: ImportCommitRecord) => (
        <span className="font-mono text-xs text-text-primary">{commitKey(row)}</span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row: ImportCommitRecord) => (row.status ? <Badge size="sm">{row.status}</Badge> : <span className="text-text-muted">—</span>),
    },
    {
      key: 'row_count',
      header: 'Rows',
      render: (row: ImportCommitRecord) => (
        <span className="font-mono text-text-secondary">
          {row.row_count !== null && row.row_count !== undefined ? formatCount(row.row_count, timeCtx) : '—'}
        </span>
      ),
    },
    {
      key: 'vertices_count',
      header: 'Vertices',
      render: (row: ImportCommitRecord) => (
        <span className="font-mono text-text-secondary">
          {row.vertices_count !== null && row.vertices_count !== undefined ? formatCount(row.vertices_count, timeCtx) : '—'}
        </span>
      ),
    },
    {
      key: 'edges_count',
      header: 'Edges',
      render: (row: ImportCommitRecord) => (
        <span className="font-mono text-text-secondary">
          {row.edges_count !== null && row.edges_count !== undefined ? formatCount(row.edges_count, timeCtx) : '—'}
        </span>
      ),
    },
    {
      key: 'rolled_back',
      header: 'Rolled back',
      render: (row: ImportCommitRecord) =>
        row.rolled_back ? <Badge size="sm" variant="danger">yes</Badge> : <span className="text-text-muted font-mono text-xs">no</span>,
    },
    {
      key: 'created_at',
      header: 'Created',
      render: (row: ImportCommitRecord) => (
        <span className="text-xs text-text-muted">{formatImportDate(row.created_at, timeCtx)}</span>
      ),
    },
  ];

  const requeueAction = isFailed ? (
    <Button variant="danger" disabled={requeuing} onClick={() => void handleRequeue()}>
      {requeuing ? 'Requeuing…' : 'Requeue import'}
    </Button>
  ) : undefined;

  return (
    <PageWrapper
      title="Import detail"
      subtitle={session.tenant_id}
      actions={requeueAction}
    >
      <Link to="/imports" className="text-xs text-text-muted hover:text-text-primary font-mono">
        ← Back to imports
      </Link>

      {(requeueMessage || requeueError) && (
        <p className="text-xs font-mono text-text-secondary">{requeueMessage ?? requeueError}</p>
      )}

      {/* Session summary */}
      <Card>
        <CardHeader>
          <CardTitle>Session</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 mb-4">
            <span className="font-mono text-text-primary text-sm break-all">{session.id}</span>
            <ImportStatusBadge status={session.status} />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <Field label="Tenant">{session.tenant_id}</Field>
            <Field label="Source">{session.source_kind}</Field>
            <Field label="Files">{formatCount(session.file_count, timeCtx)}</Field>
            <Field label="Rows">
              {session.row_count !== null && session.row_count !== undefined ? formatCount(session.row_count, timeCtx) : '—'}
            </Field>
            <Field label="Created by">{session.created_by ?? '—'}</Field>
            <Field label="Created">{formatImportDate(session.created_at, timeCtx)}</Field>
            <Field label="Updated">{formatImportDate(session.updated_at, timeCtx)}</Field>
            <Field label="Commits">{formatCount(detail.commit_count, timeCtx)}</Field>
          </div>
          {isFailed && (
            <p className="text-xs text-text-muted mt-4">
              This import failed. Requeue resets the session and re-enqueues its commit job; the recovery is audited.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Commit history */}
      <Card>
        <CardHeader>
          <CardTitle>Commit history</CardTitle>
        </CardHeader>
        <CardContent>
          {detail.commits.length === 0 ? (
            <EmptyState title="No commits yet" description="Commit history for this import will appear here." />
          ) : (
            <DataTable
              columns={commitColumns}
              data={detail.commits}
              keyExtractor={commitKey}
            />
          )}
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
