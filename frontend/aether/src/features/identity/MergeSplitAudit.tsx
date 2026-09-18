/**
 * Merge/Split Audit — PR 8, blueprint §12.4.
 *
 * Audit log of manual and automatic identity merges and splits, with operator
 * info, confirmation tokens, graph version changes, and rejection reasons.
 */

import { RequireAuth } from '@aether-app/features/auth';
import { useAuth } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';
import { queryCache, useQuery } from '@aether/ui';
import type { FC, ReactNode } from 'react';

const STALE = 60_000;

interface AuditEntry {
  readonly id: string;
  readonly tenant_id: string;
  readonly type: 'merge' | 'split';
  readonly operator_id: string;
  readonly actor_type: string;
  readonly reason: string;
  readonly confirmation_token: string;
  readonly expected_graph_version: string;
  readonly actual_graph_version: string;
  readonly rejected: boolean;
  readonly rejection_reason: string | null;
  readonly resulting_entity_ids: string[];
  readonly source_entity_ids: string[];
  readonly canonical_entity_id: string | null;
  readonly created_at: string;
}

interface AuditData {
  readonly entries: AuditEntry[];
  readonly total: number;
  readonly status: string;
}

async function fetchMergeSplitAudit(tenantId: string, limit = 50): Promise<AuditData> {
  const r = await api.identity.mergeSplitAudit(tenantId, limit);
  return r as AuditData;
}

function typeBadge(type: string): string {
  return type === 'merge'
    ? 'inline-flex items-center gap-1 rounded-full bg-theme-success/20 px-2 py-0.5 text-xs font-medium text-theme-success'
    : 'inline-flex items-center gap-1 rounded-full bg-theme-warning/20 px-2 py-0.5 text-xs font-medium text-theme-warning';
}

function statusBadge(rejected: boolean, rejection_reason: string | null): string {
  if (!rejected) return 'inline-flex items-center gap-1 rounded-full bg-surface-success/20 px-2 py-0.5 text-xs font-medium text-theme-success';
  return 'inline-flex items-center gap-1 rounded-full bg-theme-danger/20 px-2 py-0.5 text-xs font-medium text-theme-danger';
}

export const MergeSplitAudit: FC<{ readonly className?: string; readonly children?: ReactNode }> = ({
  className = '',
  children,
}) => {
  const { user } = useAuth();
  const tenantId = user?.id ?? '';

  const { data, isLoading, error, refetch } = useQuery<AuditData>({
    key: `identity-merge-split-audit:${tenantId}`,
    fetcher: () => fetchMergeSplitAudit(tenantId, 50),
    enabled: !!tenantId,
    staleTime: STALE,
  });

  return (
    <RequireAuth>
      <div className={`flex flex-col bg-surface-base ${className}`}>
        <header className="flex h-14 items-center border-b border-surface-border bg-surface-surface px-4">
          <div className="flex items-center gap-2">
            <span className="text-text-primary text-sm font-medium">Merge/Split Audit</span>
            <span className="text-text-secondary text-xs">/ Identity Operations</span>
          </div>
        </header>

        <main className="flex-1 px-6 py-6">
          <div className="mx-auto max-w-5xl">
            {isLoading ? (
              <div className="flex h-48 items-center justify-center text-text-secondary text-sm">
                Loading audit log...
              </div>
            ) : error || !data ? (
              <div className="flex h-48 flex-col items-center justify-center rounded border border-surface-border bg-surface-surface p-6 text-text-secondary text-sm">
                Unable to load audit log.
                <button
                  className="mt-2 rounded bg-surface-accent px-3 py-1 text-xs text-text-on-accent"
                  onClick={() => { queryCache.invalidatePrefix('identity-merge-split-audit'); refetch(); }}
                >
                  Retry
                </button>
              </div>
            ) : data.entries.length === 0 ? (
              <div className="flex h-48 flex-col items-center justify-center rounded border border-surface-border bg-surface-surface p-6 text-text-secondary">
                <span className="text-lg font-medium text-text-primary">No audit entries</span>
                <span className="mt-1 text-sm">No manual merges or splits have been performed yet.</span>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-text-secondary text-sm">
                    {data.total} audit entr{data.total !== 1 ? 'ies' : 'y'}
                  </p>
                </div>
                {data.entries.map((entry) => (
                  <div
                    key={entry.id}
                    className="flex flex-col gap-2 rounded border border-surface-border bg-surface-surface p-4"
                  >
                    <div className="flex items-start justify-between gap-4 flex-wrap">
                      <div className="flex items-center gap-2">
                        <span className={typeBadge(entry.type)}>{entry.type}</span>
                        <span className="text-text-primary text-sm font-medium">
                          {entry.type === 'merge'
                            ? `Merge ${entry.source_entity_ids.join(' + ')}`
                            : `Split ${entry.source_entity_ids.join(', ')}`}
                        </span>
                        {entry.canonical_entity_id && (
                          <span className="rounded bg-surface-elevated px-2 py-0.5 text-xs font-mono text-text-secondary">
                            → {entry.canonical_entity_id}
                          </span>
                        )}
                      </div>
                      <span className={statusBadge(entry.rejected, entry.rejection_reason)}>
                        {entry.rejected ? 'Rejected' : 'Applied'}
                      </span>
                    </div>

                    <div className="flex flex-wrap gap-3 text-xs text-text-secondary">
                      <span>Operator: {entry.operator_id} ({entry.actor_type})</span>
                      <span>Graph version: {entry.expected_graph_version} → {entry.actual_graph_version}</span>
                      <span>Token: {entry.confirmation_token.slice(0, 8)}…</span>
                      <span>Reason: {entry.reason}</span>
                      {entry.rejection_reason && (
                        <span className="text-theme-danger">Rejection: {entry.rejection_reason}</span>
                      )}
                      {entry.resulting_entity_ids.length > 0 && (
                        <span className="text-theme-success">
                          Results: {entry.resulting_entity_ids.join(', ')}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center justify-between text-xs text-text-muted">
                      <span>{entry.created_at}</span>
                      <span className="text-text-muted">tenant {entry.tenant_id.slice(0, 8)}…</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          {children}
        </main>
      </div>
    </RequireAuth>
  );
};

export default MergeSplitAudit;
