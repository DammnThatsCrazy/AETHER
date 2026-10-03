/**
 * Identity Review Queue — PR 8, blueprint §12.3.
 *
 * Lists open identity conflicts/reviews with candidate A/B, matching +
 * conflicting evidence, recommended action, confidence, risk level, affected
 * projections, and approve/reject controls.
 */

import { RequireAuth } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';
import { queryCache, useCapabilities, useQuery, useMutation } from '@aether/ui';
import { useGraphContext } from '@aether/ui/exploration';
import { useState } from 'react';
import type { FC, ReactNode, MouseEvent } from 'react';

const STALE = 30_000;

interface ReviewQueueEntry {
  readonly conflict_id: string;
  readonly tenant_id: string;
  readonly entry_type?: 'conflict' | 'late_binding_candidate';
  readonly candidate_a: { readonly entity_id: string };
  readonly candidate_b: { readonly entity_id: string };
  readonly candidate_source_identity_ids?: string[];
  readonly identify_source_identity_id?: string | null;
  readonly reason_codes?: string[];
  readonly authority?: string;
  readonly seen_count?: number;
  readonly matching_evidence: Array<{
    readonly source_identity_id?: string;
    readonly provisional_canonical_entity_id?: string;
    readonly claim_type?: string;
    readonly claim_verification_status?: string;
  }>;
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
  void tenantId; // Cache scope only; the backend derives the tenant from auth.
  const r = await api.identity.reviewQueue(limit);
  return r as ReviewQueueData;
}

interface LateBindingActionResponse {
  readonly status: string;
  readonly reason_codes?: string[];
}

async function approveConflict(conflictId: string): Promise<LateBindingActionResponse> {
  const response = await api.identity.approveConflict(conflictId) as
    | LateBindingActionResponse
    | { readonly data?: LateBindingActionResponse };
  return ('data' in response && response.data ? response.data : response) as LateBindingActionResponse;
}

async function rejectConflict(conflictId: string): Promise<LateBindingActionResponse> {
  const response = await api.identity.rejectConflict(conflictId, { reason: 'tenant_review_rejected' }) as
    | LateBindingActionResponse
    | { readonly data?: LateBindingActionResponse };
  return ('data' in response && response.data ? response.data : response) as LateBindingActionResponse;
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

function lateBindingStatusText(status: string): string {
  switch (status) {
    case 'approving':
      return 'Approval is still running. The server has not reported a final outcome yet.';
    case 'approval_recovery_required':
      return 'The approval outcome needs recovery. Retry asks the server to safely reclaim the durable action.';
    case 'merge_committed':
      return 'The identity merge is committed. Retry lets the server finish source binding and projection recovery.';
    default:
      return 'This candidate is awaiting review.';
  }
}

export const IdentityReviewQueue: FC<{ readonly className?: string; readonly children?: ReactNode }> = ({
  className = '',
  children,
}) => {
  const graphContext = useGraphContext();
  const tenantId = graphContext.scope.tenant_id;
  const { capabilities } = useCapabilities();
  const enabled = capabilities?.feature_flags.identity_manual_review_enabled === true;
  const [lateBindingStatus, setLateBindingStatus] = useState<Record<string, string>>({});
  const latestLateBindingAction = Object.entries(lateBindingStatus).slice(-1)[0];

  const { data, isLoading, error, refetch } = useQuery<ReviewQueueData>({
    key: `identity-review-queue:${tenantId}`,
    fetcher: () => fetchReviewQueue(tenantId, 50),
    enabled: enabled && !!tenantId,
    staleTime: STALE,
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveConflict(id),
    onSuccess: (result, id) => {
      setLateBindingStatus((current) => ({ ...current, [id]: result.status }));
      queryCache.invalidatePrefix('identity-review-queue');
      refetch();
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => rejectConflict(id),
    onSuccess: (result, id) => {
      setLateBindingStatus((current) => ({ ...current, [id]: result.status }));
      queryCache.invalidatePrefix('identity-review-queue');
      refetch();
    },
  });

  const handleApprove = async (conflictId: string, e: MouseEvent) => {
    e.stopPropagation();
    await approveMutation.mutate(conflictId);
  };

  const handleReject = async (conflictId: string, reason: string, e: MouseEvent) => {
    e.stopPropagation();
    void reason;
    await rejectMutation.mutate(conflictId);
  };

  if (!enabled) {
    return (
      <RequireAuth>
        <div className={`flex min-h-64 items-center justify-center bg-surface-base px-6 text-center text-sm text-text-secondary ${className}`}>
          Identity review is not enabled in this environment.
        </div>
      </RequireAuth>
    );
  }

  return (
    <RequireAuth>
      <div className={`flex flex-col bg-surface-base ${className}`}>
        <header className="flex h-14 items-center border-b border-surface-border bg-surface-surface px-4">
          <div className="flex items-center gap-2">
            <span className="text-text-primary text-sm font-medium">Review Queue</span>
            <span className="text-text-secondary text-xs">/ Conflicts and Late-Binding Candidates</span>
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
              <div className="flex flex-col gap-3">
                {Object.entries(lateBindingStatus).length > 0 && (
                  <div className="rounded border border-surface-border bg-surface-surface p-3 text-xs text-text-secondary" role="status" aria-live="polite">
                    Latest late-binding action for {latestLateBindingAction?.[0].slice(0, 8)}: {latestLateBindingAction?.[1]}
                  </div>
                )}
                <div className="flex h-48 flex-col items-center justify-center rounded border border-surface-border bg-surface-surface p-6 text-text-secondary">
                  <span className="text-lg font-medium text-text-primary">No open identity reviews</span>
                  <span className="mt-1 text-sm">There are no conflicts or late-binding candidates awaiting review.</span>
                </div>
              </div>
            ) : (
              <>
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-text-secondary text-sm">
                    {data.total} open identity review{data.total !== 1 ? 's' : ''}
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
                            {entry.entry_type === 'late_binding_candidate' ? 'Identity candidate' : 'Conflict'} {entry.conflict_id.slice(0, 8)}
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

                      {/* Review shows tenant-local provisional targets without granting link authority. */}
                      {entry.entry_type === 'late_binding_candidate' ? (
                        <div className="rounded bg-surface-elevated p-3 text-xs">
                          <div className="text-text-secondary mb-1">Imported evidence and provisional profiles</div>
                          <div className="font-mono text-text-primary break-all">
                            {(entry.candidate_source_identity_ids ?? []).join(', ')}
                          </div>
                          {entry.matching_evidence.some((item) => item.provisional_canonical_entity_id) && (
                            <div className="mt-2">
                              <div className="text-text-secondary mb-1">Profile candidates</div>
                              <ul className="space-y-1 font-mono text-text-primary break-all">
                                {Array.from(new Set(entry.matching_evidence
                                  .map((item) => item.provisional_canonical_entity_id)
                                  .filter((id): id is string => Boolean(id))))
                                  .map((id) => <li key={id}>{id}</li>)}
                              </ul>
                            </div>
                          )}
                          <div className="mt-2 text-text-secondary">
                            Approval asks the server to recheck current import evidence and durable anonymous identity-link consent. Matching claims or this review alone do not authorize a link.
                          </div>
                          {(entry.reason_codes?.length ?? 0) > 0 && (
                            <div className="mt-2 text-text-secondary">Reasons: {entry.reason_codes?.join(', ')}</div>
                          )}
                        </div>
                      ) : (
                        <div className="grid grid-cols-2 gap-3 text-xs">
                          <div className="rounded bg-surface-elevated p-3">
                            <div className="text-text-secondary mb-1">Candidate A</div>
                            <div className="font-mono text-text-primary break-all">{entry.candidate_a.entity_id}</div>
                          </div>
                          <div className="rounded bg-surface-elevated p-3">
                            <div className="text-text-secondary mb-1">Candidate B</div>
                            <div className="font-mono text-text-primary break-all">{entry.candidate_b.entity_id}</div>
                          </div>
                        </div>
                      )}

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
                      {entry.entry_type === 'late_binding_candidate' ? (
                        <div className="flex flex-col gap-2">
                          {entry.status === 'open' ? (
                            <div className="flex items-center gap-2">
                              <button
                                className="rounded bg-theme-success px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
                                disabled={approveMutation.isLoading || rejectMutation.isLoading}
                                onClick={(e) => handleApprove(entry.conflict_id, e)}
                              >
                                {approveMutation.isLoading ? 'Checking...' : 'Approve after server checks'}
                              </button>
                              <button
                                className="rounded border border-surface-border bg-surface-elevated px-3 py-1 text-xs font-medium text-text-primary hover:bg-surface-accent disabled:opacity-50"
                                disabled={approveMutation.isLoading || rejectMutation.isLoading}
                                onClick={(e) => handleReject(entry.conflict_id, 'tenant_review_rejected', e)}
                              >
                                Reject without linking
                              </button>
                            </div>
                          ) : entry.status === 'approval_recovery_required' || entry.status === 'merge_committed' ? (
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-text-secondary" role="status">
                                {lateBindingStatusText(entry.status)}
                              </span>
                              <button
                                className="rounded bg-surface-accent px-3 py-1 text-xs font-medium text-text-on-accent disabled:opacity-50"
                                disabled={approveMutation.isLoading || rejectMutation.isLoading}
                                onClick={(e) => handleApprove(entry.conflict_id, e)}
                              >
                                {approveMutation.isLoading ? 'Recovering...' : 'Retry server recovery'}
                              </button>
                            </div>
                          ) : (
                            <div className="text-xs text-text-secondary" role="status">
                              {lateBindingStatusText(entry.status)}
                            </div>
                          )}
                          {lateBindingStatus[entry.conflict_id] && (
                            <div className="text-xs text-text-secondary" role="status">
                              Server result: {lateBindingStatus[entry.conflict_id]}
                            </div>
                          )}
                        </div>
                      ) : <div className="flex items-center gap-2">
                        <button
                          className="rounded bg-theme-success px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
                          disabled={approveMutation.isLoading || approveMutation.error !== null}
                          onClick={(e) => handleApprove(entry.conflict_id, e)}
                        >
                          {approveMutation.isLoading ? '...' : 'Approve'}
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
                      </div>}
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
