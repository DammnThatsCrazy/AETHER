import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

const runtime = vi.hoisted(() => ({
  entry: null as Record<string, unknown> | null,
  approve: vi.fn(),
  reject: vi.fn(),
  manualReviewEnabled: true,
  queryEnabled: false,
  queryMode: 'ready' as 'ready' | 'loading' | 'error',
  fetcher: vi.fn(),
}));

vi.mock('@aether-app/features/auth', () => ({
  RequireAuth: ({ children }: { children: ReactNode }) => children,
}));

vi.mock('@aether/ui/exploration', () => ({
  useGraphContext: () => ({ scope: { tenant_id: 'tenant-a' } }),
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    identity: {
      reviewQueue: vi.fn(async () => ({
        entries: runtime.entry ? [runtime.entry] : [],
        total: runtime.entry ? 1 : 0,
        status: 'ok',
      })),
      approveConflict: runtime.approve,
      rejectConflict: runtime.reject,
    },
  },
}));

vi.mock('@aether/ui', () => ({
  queryCache: { invalidatePrefix: vi.fn() },
  useCapabilities: () => ({ capabilities: { feature_flags: { identity_manual_review_enabled: runtime.manualReviewEnabled } } }),
  useQuery: ({ fetcher, enabled }: { fetcher: () => Promise<unknown>; enabled: boolean }) => {
    runtime.fetcher = vi.fn(fetcher);
    runtime.queryEnabled = enabled;
    return {
      data: runtime.queryMode === 'ready' ? {
        entries: runtime.entry ? [runtime.entry] : [],
        total: runtime.entry ? 1 : 0,
        status: 'ok',
      } : null,
      isLoading: runtime.queryMode === 'loading',
      error: runtime.queryMode === 'error' ? new Error('review queue unavailable') : null,
      refetch: fetcher,
    };
  },
  useMutation: ({ mutationFn }: { mutationFn: (id: string) => Promise<unknown> }) => ({
    mutate: mutationFn,
    isLoading: false,
    error: null,
  }),
}));

import { IdentityReviewQueue } from '@aether-app/features/identity/IdentityReviewQueue';

function queueEntry(status: string) {
  return {
    conflict_id: 'review-12345678',
    tenant_id: 'tenant-a',
    entry_type: 'late_binding_candidate',
    candidate_a: { entity_id: '' },
    candidate_b: { entity_id: '' },
    candidate_source_identity_ids: ['import-source'],
    matching_evidence: [],
    conflicting_evidence: [],
    recommended_action: 'review_identity_evidence',
    confidence: 0,
    risk_level: 'medium',
    affected_projections: [],
    created_at: '2026-09-27T00:00:00Z',
    status,
  };
}

describe('Identity review queue recovery states', () => {
  beforeEach(() => {
    runtime.manualReviewEnabled = true;
    runtime.queryEnabled = false;
    runtime.queryMode = 'ready';
    runtime.entry = null;
    runtime.fetcher = vi.fn();
    runtime.approve.mockReset().mockResolvedValue({ status: 'approval_in_progress' });
    runtime.reject.mockReset().mockResolvedValue({ status: 'rejected' });
  });

  it('shows a running approval without presenting duplicate actions', () => {
    runtime.entry = queueEntry('approving');
    render(<IdentityReviewQueue />);

    expect(screen.getByRole('status')).toHaveTextContent('Approval is still running');
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument();
  });

  it.each(['approval_recovery_required', 'merge_committed'])(
    'offers safe server recovery for %s without offering rejection',
    async (status) => {
      runtime.entry = queueEntry(status);
      const user = userEvent.setup();
      render(<IdentityReviewQueue />);

      await user.click(screen.getByRole('button', { name: 'Retry server recovery' }));
      expect(runtime.approve).toHaveBeenCalledWith('review-12345678');
      expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument();
      expect(screen.getByRole('status')).toHaveTextContent(
        status === 'merge_committed' ? 'merge is committed' : 'needs recovery',
      );
    },
  );

  it('does not fetch the queue when the backend review capability is off', () => {
    runtime.manualReviewEnabled = false;
    render(<IdentityReviewQueue />);
    expect(screen.getByText(/identity review is not enabled/i)).toBeInTheDocument();
    expect(runtime.queryEnabled).toBe(false);
    expect(runtime.fetcher).not.toHaveBeenCalled();
  });

  it('shows loading without presenting a successful empty queue', () => {
    runtime.queryMode = 'loading';
    render(<IdentityReviewQueue />);

    expect(screen.getByText('Loading review queue...')).toBeInTheDocument();
    expect(screen.queryByText('No open identity reviews')).not.toBeInTheDocument();
  });

  it('shows a successful empty review queue without action controls', () => {
    render(<IdentityReviewQueue />);

    expect(screen.getByText('No open identity reviews')).toBeInTheDocument();
    expect(screen.getByText(/no conflicts or late-binding candidates awaiting review/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /approve|reject/i })).not.toBeInTheDocument();
    expect(screen.queryByText('Unable to load review queue.')).not.toBeInTheDocument();
  });

  it('shows failure and retry rather than a successful empty queue', () => {
    runtime.queryMode = 'error';
    render(<IdentityReviewQueue />);

    expect(screen.getByText('Unable to load review queue.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByText('No open identity reviews')).not.toBeInTheDocument();
  });
});
