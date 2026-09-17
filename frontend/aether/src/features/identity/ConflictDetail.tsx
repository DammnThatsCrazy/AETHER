/**
 * Conflict Detail — PR 8, blueprint §12.3.
 *
 * Detailed view of a single identity conflict / review, including matching
 * and conflicting evidence, candidate profiles, confidence, and approve/reject
 * controls.
 */

import { RequireAuth } from '@aether-app/features/auth';
import { useAuth } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';
import { useQuery, useMutation } from '@aether/ui';
import { queryCache } from '@aether/ui';
import { useParams, useNavigate } from 'react-router-dom';
import type { FC, MouseEvent } from 'react';

const STALE = 30_000;

interface ConflictDetailData {
  readonly conflict_id: string;
  readonly tenant_id: string;
  readonly candidate_a: { readonly entity_id: string; readonly confidence?: number };
  readonly candidate_b: { readonly entity_id: string; readonly confidence?: number };
  readonly matching_evidence: Array<{
    readonly signal: string;
    readonly status: string;
    readonly reason_codes: string[];
    readonly source_events: string[];
  }>;
  readonly conflicting_evidence: Array<{
    readonly signal: string;
    readonly status: string;
    readonly reason_codes: string[];
    readonly source_events: string[];
  }>;
  readonly recommended_action: string;
  readonly confidence: number;
  readonly risk_level: string;
  readonly affected_projections: string[];
  readonly created_at: string;
  readonly status: string;
}

async function fetchConflictDetail(conflictId: string, tenantId: string): Promise<ConflictDetailData> {
  const r = await api.identity.conflictDetail(conflictId, tenantId);
  return r as ConflictDetailData;
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

export const ConflictDetail: FC = () => {
  const { conflictId } = useParams<{ conflictId?: string }>() ?? {};
  const navigate = useNavigate();
  const { user } = useAuth();
  const tenantId = user?.id ?? '';

  const { data, isLoading, error, refetch } = useQuery<ConflictDetailData>({
    key: `identity-conflict-detail:${conflictId}:${tenantId}`,
    fetcher: () => fetchConflictDetail(conflictId ?? '', tenantId),
    enabled: !!conflictId && !!tenantId,
    staleTime: STALE,
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveConflict(id, tenantId),
    onSuccess: () => {
      queryCache.invalidatePrefix('identity-conflict-detail');
      refetch();
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      rejectConflict(id, tenantId, reason),
    onSuccess: () => {
      queryCache.invalidatePrefix('identity-conflict-detail');
      refetch();
    },
  });

  if (!conflictId) {
    navigate('/identity/review-queue');
    return null;
  }

  return (
    <RequireAuth>
      <div className="flex flex-col bg-surface-base min-h-screen">
        <header className="flex h-14 items-center border-b border-surface-border bg-surface-surface px-4">
          <div className="flex items-center gap-2">
            <button
              className="rounded-none border-none bg-transparent p-0 text-text-secondary hover:text-text-primary text-xs font-medium"
              onClick={() => navigate('/identity/review-queue')}
            >
              ← Review Queue
            </button>
            <span className="text-text-primary text-sm font-medium">Conflict Detail</span>
          </div>
        </header>

        <main className="flex-1 px-6 py-6">
          <div className="mx-auto max-w-4xl">
            {isLoading ? (
              <div className="flex h-48 items-center justify-center text-text-secondary text-sm">
                Loading conflict detail...
              </div>
            ) : error || !data ? (
              <div className="flex h-48 flex-col items-center justify-center rounded border border-surface-border bg-surface-surface p-6 text-text-secondary text-sm">
                Unable to load conflict detail.
                <button
                  className="mt-2 rounded bg-surface-accent px-3 py-1 text-xs text-text-on-accent"
                  onClick={() => { queryCache.invalidatePrefix('identity-conflict-detail'); refetch(); }}
                >
                  Retry
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Header */}
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h1 className="text-text-primary text-lg font-semibold">
                      Conflict {data.conflict_id.slice(0, 8)}
                    </h1>
                    <p className="text-text-secondary text-sm">Created {data.created_at}</p>
                  </div>
                  <span className={riskBadge(data.risk_level)}>{data.risk_level} risk</span>
                </div>

                {/* Candidates */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="rounded border border-surface-border bg-surface-surface p-4">
                    <div className="text-text-secondary text-xs mb-2">Candidate A</div>
                    <div className="font-mono text-sm text-text-primary break-all">
                      {data.candidate_a.entity_id}
                    </div>
                    <div className="mt-1 text-xs text-text-secondary">
                      confidence {data.candidate_a.confidence != null ? data.candidate_a.confidence.toFixed(2) : 'n/a'}
                    </div>
                  </div>
                  <div className="rounded border border-surface-border bg-surface-surface p-4">
                    <div className="text-text-secondary text-xs mb-2">Candidate B</div>
                    <div className="font-mono text-sm text-text-primary break-all">
                      {data.candidate_b.entity_id}
                    </div>
                    <div className="mt-1 text-xs text-text-secondary">
                      confidence {data.candidate_b.confidence != null ? data.candidate_b.confidence.toFixed(2) : 'n/a'}
                    </div>
                  </div>
                </div>

                {/* Evidence */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="rounded border border-surface-border bg-surface-surface p-4">
                    <h2 className="text-text-primary text-sm font-medium mb-2">
                      Matching Evidence ({data.matching_evidence.length})
                    </h2>
                    {data.matching_evidence.length === 0 ? (
                      <div className="text-text-secondary text-xs">No matching evidence recorded.</div>
                    ) : (
                      <ul className="space-y-1 text-xs text-text-secondary">
                        {data.matching_evidence.map((ev, i) => (
                          <li key={i} className="rounded bg-surface-elevated p-2">
                            <span className="text-theme-success">{String(ev.signal ?? '')}</span>
                            <span className="text-text-muted ml-1">{ev.reason_codes.join(', ')}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="rounded border border-surface-border bg-surface-surface p-4">
                    <h2 className="text-text-primary text-sm font-medium mb-2">
                      Conflicting Evidence ({data.conflicting_evidence.length})
                    </h2>
                    {data.conflicting_evidence.length === 0 ? (
                      <div className="text-text-secondary text-xs">No conflicting evidence recorded.</div>
                    ) : (
                      <ul className="space-y-1 text-xs text-text-secondary">
                        {data.conflicting_evidence.map((ev, i) => (
                          <li key={i} className="rounded bg-surface-elevated p-2">
                            <span className="text-theme-danger">{String(ev.signal ?? '')}</span>
                            <span className="text-text-muted ml-1">{ev.reason_codes.join(', ')}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>

                {/* Projections */}
                <div className="rounded border border-surface-border bg-surface-surface p-4">
                  <h2 className="text-text-primary text-sm font-medium mb-2">Affected Projections</h2>
                  <div className="flex flex-wrap gap-2 text-xs">
                    {data.affected_projections.length === 0 ? (
                      <span className="text-text-secondary">None</span>
                    ) : (
                      data.affected_projections.map((p) => (
                        <span key={p} className="rounded bg-surface-elevated px-2 py-1 text-text-secondary">
                          {p}
                        </span>
                      ))
                    )}
                  </div>
                </div>

                {/* Controls */}
                <div className="flex items-center gap-3 rounded border border-surface-border bg-surface-surface p-4">
                  <span className="text-text-secondary text-sm">Recommended action:</span>
                  <span className="rounded bg-surface-elevated px-3 py-1 text-xs text-text-primary capitalize">
                    {data.recommended_action}
                  </span>
                  <div className="ml-auto flex gap-2">
                    <button
                      className="rounded bg-theme-success px-4 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                      disabled={approveMutation.isLoading}
                      onClick={() => approveMutation.mutate(data.conflict_id)}
                    >
                      {approveMutation.isLoading ? '...' : 'Approve'}
                    </button>
                    <button
                      className="rounded border border-surface-border bg-surface-elevated px-4 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-accent"
                      onClick={() => {
                        const reason = window.prompt('Reason for rejection:') ?? '';
                        if (reason) rejectMutation.mutate({ id: data.conflict_id, reason });
                      }}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </RequireAuth>
  );
};

export default ConflictDetail;
