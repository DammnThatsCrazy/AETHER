/**
 * Identity Review Queue — PR 8, blueprint §12.3.
 *
 * Lists open identity conflicts/reviews with candidate A/B, matching +
 * conflicting evidence, recommended action, confidence, risk level, affected
 * projections, and approve/reject controls.
 */

import { RequireAuth } from '@aether-app/features/auth';
import { useAuth } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';
import { queryCache, useQuery, useMutation } from '@aether/ui';
import type { FC, ReactNode, MouseEvent } from 'react';

const STALE = 30_000;

interface ReviewQueueEntry {
  readonly conflict_id: string;
  readonly tenant_id: string;
  readonly candidate_a: { readonly entity_id: string };
  readonly candidate_b: { readonly entity_id: string };
  readonly matching_evidence: unknown[];
  readonly conflicting_evidence: unknown[];
  readonly recommended_action: string;
  readonly confidence: number;
  readonly risk_level: string;
  readonly affected_projections: string[];
  readonly created_at: string;
  readonly status: string;
}

interface ReviewQueueData {
  readonly entries: ReviewQueueEntry[];
  readonly total: number;
  readonly status: string;
}

async function fetchReviewQueue(tenantId: string, limit = 50): Promise<ReviewQueueData> {
  const r = await api.identity.reviewQueue(tenantId, limit);
  return r as ReviewQueueData;
}

async function approveConflict(conflictId: string, tenantId: string): Promise<void> {
  await api.identity.approveConflict(conflictId, tenantId);
}

async function rejectConflict(conflictId: string, tenantId: string, reason: string): Promise<void> {
  await api.identity.rejectConflict(conflictId, tenantId, { reason });
}

function riskBadge(risk: string): string {
  switch (risk) {
    case 'high':
      return 'inline-flex items-center gap-1 rounded-full bg-theme-danger/20 px-2 py-0.5 text-xs font-medium text-theme-danger';
    case 'medium':
      return 'inline-flex items-center gap-1 rounded-full bg-theme-warning/20 px-2 py-0.5 text-xs font-medium text-theme-warning';
    case 'low':
      return 'inline-flex items-center gap-1 rounded-full bg-surface-success/20 px-2 py-0.5 text-xs font-medium text-theme-success';
    default:
      return 'inline-flex items-center gap-1 rounded-full bg-surface-elevated px-2 py-0.5 text-xs text-text-secondary';
  }
}

export const IdentityReviewQueue: FC<{ readonly className?: string; readonly children?: ReactNode }> = ({
  className = '',
  children,
}) => {
  const { user } = useAuth();
  const tenantId = user?.id ?? '';

  const { data, isLoading, error, refetch } = useQuery<ReviewQueueData>({
    key: ['identity-review-queue', tenantId],
    fetcher: () => fetchReviewQueue(tenantId, 50),
    enabled: !!tenantId,
    staleTime: STALE,
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveConflict(id, tenantId),
    onSuccess: () => {
      queryCache.invalidatePrefix('identity-review-queue');
      refetch();
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      rejectConflict(id, tenantId, reason),
    onSuccess: () => {
      queryCache.invalidatePrefix('identity-review-queue');
      refetch();
    },
  });

  const handleApprove = async (conflictId: string, e: MouseEvent) => {
    e.stopPropagation();
    await approveMutation.mutateAsync(conflictId);
  };

  const handleReject = async (conflictId: string, reason: string, e: MouseEvent) => {
    e.stopPropagation();
    await rejectMutation.mutate({ id: conflictId, reason });
  };

  return (
    <RequireAuth>
      <div className={`flex flex-col bg-surface-base ${className}`}>
        <header className="flex h-14 items-center border-b border-surface-border bg-surface-surface px-4">
          <div className="flex items-center gap-2">
            <span className="text-text-primary text-sm font-medium">Review Queue</span>
            <span className="text-text-secondary text-xs">/ Identity Conflicts</span>
          </div>
        </header>

        <main className="flex-1 px-6 py-6">
          <div className="mx-auto max-w-5xl">
            {isLoading ? (
              <div className="flex h-48 items-center justify-center text-text-secondary text-sm">
                Loading review queue...
              </div>
            ) : error || !data ? (
              <div className="flex h-48 flex-col items-center justify-center text-text-secondary text-sm">
                Unable to load review queue.
                <button
                  className="mt-2 rounded bg-surface-accent px-3 py-1 text-xs text-text-on-accent"
                  onClick={() => { queryCache.invalidatePrefix('identity-review-queue'); refetch(); }}
                >
                  Retry
                </button>
              </div>
            ) : data.entries.length === 0 ? (
              <div className="flex h-48 flex-col items-center justify-center rounded border border-surface-border bg-surface-surface p-6 text-text-secondary">
                <span className="text-lg font-medium text-text-primary">No open conflicts</span>
                <span className="mt-1 text-sm">All identity conflicts have been reviewed or there are none.</span>
              </div>
            ) : (
              <>
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-text-secondary text-sm">
                    {data.total} open conflict{data.total !== 1 ? 's' : ''}
                  </p>
                </div>
                <div className="space-y-3">
                  {data.entries.map((entry) => (
                    <div
                      key={entry.conflict_id}
                      className="flex flex-col gap-3 rounded border border-surface-border bg-surface-surface p-4"
                    >
                      {/* Header */}
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex flex-col gap-1 min-w-0">
                          <div className="text-text-primary text-sm font-medium">
                            Conflict {entry.conflict_id.slice(0, 8)}
                          </div>
                          <div className="flex items-center gap-2 text-xs text-text-secondary">
                            <span>Created {entry.created_at}</span>
                            <span className={riskBadge(entry.risk_level)}>{entry.risk_level} risk</span>
                            <span>confidence {entry.confidence.toFixed(2)}</span>
                          </div>
                        </div>
                        <span className="rounded bg-surface-elevated px-2 py-0.5 text-xs text-text-secondary capitalize">
                          {entry.recommended_action}
                        </span>
                      </div>

                      {/* Candidates */}
                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div className="rounded bg-surface-elevated p-3">
                          <div className="text-text-secondary mb-1">Candidate A</div>
                          <div className="font-mono text-text-primary break-all">
                            {entry.candidate_a.entity_id}
                          </div>
                        </div>
                        <div className="rounded bg-surface-elevated p-3">
                          <div className="text-text-secondary mb-1">Candidate B</div>
                          <div className="font-mono text-text-primary break-all">
                            {entry.candidate_b.entity_id}
                          </div>
                        </div>
                      </div>

                      {/* Evidence + projections */}
                      <div className="flex flex-wrap gap-2 text-xs">
                        <span className="rounded bg-surface-elevated px-2 py-1 text-theme-success">
                          {entry.matching_evidence.length} matching evidence
                        </span>
                        <span className="rounded bg-surface-elevated px-2 py-1 text-theme-danger">
                          {entry.conflicting_evidence.length} conflicting
                        </span>
                        {entry.affected_projections.length > 0 && (
                          <span className="rounded bg-surface-elevated px-2 py-1 text-text-secondary">
                            Projections: {entry.affected_projections.join(', ')}
                          </span>
                        )}
                      </div>

                      {/* Controls */}
                      <div className="flex items-center gap-2">
                        <button
                          className="rounded bg-theme-success px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
                          disabled={approveMutation.isPaused || approveMutation.isError}
                          onClick={(e) => handleApprove(entry.conflict_id, e)}
                        >
                          {approveMutation.isPaused ? '...' : 'Approve'}
                        </button>
                        <button
                          className="rounded border border-surface-border bg-surface-elevated px-3 py-1 text-xs font-medium text-text-primary hover:bg-surface-accent"
                          onClick={(e) => {
                            const reason = window.prompt('Reason for rejection:') ?? '';
                            if (reason) handleReject(entry.conflict_id, reason, e);
                          }}
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
          {children}
        </main>
      </div>
    </RequireAuth>
  );
};

export default IdentityReviewQueue;
