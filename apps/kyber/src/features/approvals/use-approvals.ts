import { useCallback, useEffect, useState } from 'react';
import { approvalsApi, commerceApi } from '@kyber/lib/api/commerce';
import type {
  ApprovalRequest,
  ApprovalStatus,
  EvidenceBundle,
  LifecycleTrace,
} from '@kyber/lib/schemas/commerce';

export interface UseApprovalsResult {
  readonly approvals: readonly ApprovalRequest[];
  readonly loading: boolean;
  readonly error: string | null;
  refresh(): Promise<void>;
  decide(approvalId: string, action: 'approve' | 'reject' | 'escalate', decidedBy: string, reason: string, isOverride?: boolean): Promise<ApprovalRequest>;
  revoke(approvalId: string, revokedBy: string, reason: string): Promise<ApprovalRequest>;
  assign(approvalId: string, assigneeId: string, assignedBy: string): Promise<ApprovalRequest>;
  loadEvidence(approvalId: string): Promise<EvidenceBundle>;
  loadTrace(challengeId: string): Promise<LifecycleTrace>;
}

export function useApprovals(statusFilter?: ApprovalStatus): UseApprovalsResult {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await approvalsApi.list(statusFilter ? { status: statusFilter } : undefined);
      setApprovals(items);
    } catch (e) {
      setApprovals([]);
      setError(e instanceof Error ? e.message : 'failed to load approvals');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const decide = useCallback(
    async (
      approvalId: string,
      action: 'approve' | 'reject' | 'escalate',
      decidedBy: string,
      reason: string,
      isOverride = false
    ): Promise<ApprovalRequest> => {
      setError(null);
      try {
        const result = await approvalsApi.decide(approvalId, action, decidedBy, reason, isOverride);
        await refresh();
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to decide approval');
        throw e;
      }
    },
    [refresh]
  );

  const revoke = useCallback(
    async (approvalId: string, revokedBy: string, reason: string) => {
      setError(null);
      try {
        const result = await approvalsApi.revoke(approvalId, revokedBy, reason);
        await refresh();
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to revoke approval');
        throw e;
      }
    },
    [refresh]
  );

  const assign = useCallback(
    async (approvalId: string, assigneeId: string, assignedBy: string) => {
      setError(null);
      try {
        const result = await approvalsApi.assign(approvalId, assigneeId, assignedBy);
        await refresh();
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to assign approval');
        throw e;
      }
    },
    [refresh]
  );

  const loadEvidence = useCallback(
    async (approvalId: string): Promise<EvidenceBundle> => approvalsApi.evidence(approvalId),
    []
  );

  const loadTrace = useCallback(
    async (challengeId: string): Promise<LifecycleTrace> => commerceApi.explain(challengeId),
    []
  );

  return { approvals, loading, error, refresh, decide, revoke, assign, loadEvidence, loadTrace };
}
