import { useCallback, useEffect, useState } from 'react';
import { isLocalMocked } from '@kyber/lib/env';
import { approvalsApi, commerceApi } from '@kyber/lib/api/commerce';
import type {
  ApprovalRequest,
  ApprovalStatus,
  EvidenceBundle,
  LifecycleTrace,
} from '@kyber/lib/schemas/commerce';
import { fixtureApprovalQueue, fixtureApprovalApproved, fixtureLifecycleTrace } from '@kyber/fixtures/commerce';

export interface UseApprovalsResult {
  readonly approvals: readonly ApprovalRequest[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly mode: 'mocked' | 'live';
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
  const mode: 'mocked' | 'live' = isLocalMocked() ? 'mocked' : 'live';

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (mode === 'mocked') {
        const filtered = statusFilter
          ? fixtureApprovalQueue.filter((a) => a.status === statusFilter)
          : fixtureApprovalQueue;
        setApprovals(filtered);
      } else {
        const items = await approvalsApi.list(statusFilter ? { status: statusFilter } : undefined);
        setApprovals(items);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load approvals');
    } finally {
      setLoading(false);
    }
  }, [mode, statusFilter]);

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
      if (mode === 'mocked') {
        const next: ApprovalRequest = {
          ...fixtureApprovalApproved,
          approval_id: approvalId,
          status: action === 'approve' ? 'approved' : action === 'reject' ? 'rejected' : 'escalated',
          decided_by: decidedBy,
          decision_reason: reason,
          is_override: isOverride,
          decided_at: new Date().toISOString(),
        };
        setApprovals((prev) => prev.map((a) => (a.approval_id === approvalId ? next : a)));
        return next;
      }
      const result = await approvalsApi.decide(approvalId, action, decidedBy, reason, isOverride);
      await refresh();
      return result;
    },
    [mode, refresh]
  );

  const revoke = useCallback(
    async (approvalId: string, revokedBy: string, reason: string) => {
      if (mode === 'mocked') {
        const next = {
          ...fixtureApprovalApproved,
          approval_id: approvalId,
          status: 'revoked' as const,
          decided_by: revokedBy,
          decision_reason: reason,
        };
        setApprovals((prev) => prev.map((a) => (a.approval_id === approvalId ? next : a)));
        return next;
      }
      const result = await approvalsApi.revoke(approvalId, revokedBy, reason);
      await refresh();
      return result;
    },
    [mode, refresh]
  );

  const assign = useCallback(
    async (approvalId: string, assigneeId: string, assignedBy: string) => {
      if (mode === 'mocked') {
        const next = {
          ...fixtureApprovalApproved,
          approval_id: approvalId,
          status: 'assigned' as const,
          assigned_to: assigneeId,
        };
        setApprovals((prev) => prev.map((a) => (a.approval_id === approvalId ? next : a)));
        return next;
      }
      const result = await approvalsApi.assign(approvalId, assigneeId, assignedBy);
      await refresh();
      return result;
    },
    [mode, refresh]
  );

  const loadEvidence = useCallback(
    async (approvalId: string): Promise<EvidenceBundle> => {
      if (mode === 'mocked') {
        return {
          approval: fixtureApprovalApproved,
          policy_decision: null,
          requirement: null,
        };
      }
      return approvalsApi.evidence(approvalId);
    },
    [mode]
  );

  const loadTrace = useCallback(
    async (challengeId: string): Promise<LifecycleTrace> => {
      if (mode === 'mocked') {
        return fixtureLifecycleTrace;
      }
      return commerceApi.explain(challengeId);
    },
    [mode]
  );

  return { approvals, loading, error, mode, refresh, decide, revoke, assign, loadEvidence, loadTrace };
}
