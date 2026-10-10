import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ApprovalQueue } from '@kyber/components/commerce/approval-queue';
import { LifecycleTraceView } from '@kyber/components/commerce/lifecycle-trace-view';
import { approvalsApi } from '@kyber/lib/api/commerce';
import { fixtureApprovalQueue, fixtureLifecycleTrace } from '../fixtures/commerce';

describe('ApprovalQueue', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(approvalsApi, 'list').mockImplementation(async (filters) => {
      const status = filters?.status;
      return status
        ? fixtureApprovalQueue.filter((approval) => approval.status === status)
        : fixtureApprovalQueue;
    });
  });

  it('renders the API-backed queue', async () => {
    render(
      <ApprovalQueue canApprove={false} currentUserId="user_test" />
    );
    await waitFor(() => {
      expect(screen.getByText(/APPROVAL QUEUE/)).toBeInTheDocument();
    });
    expect(approvalsApi.list).toHaveBeenCalledWith(undefined);
  });

  it('shows both critical and normal approvals returned by the API', async () => {
    render(
      <ApprovalQueue canApprove={false} currentUserId="user_test" />
    );
    await waitFor(() => {
      expect(screen.getByText('CRITICAL')).toBeInTheDocument();
    });
    expect(screen.getByText('NORMAL')).toBeInTheDocument();
  });

  it('hides approve buttons when canApprove=false', async () => {
    render(
      <ApprovalQueue canApprove={false} currentUserId="user_test" />
    );
    await waitFor(() => {
      expect(screen.getByText(/APPROVAL QUEUE/)).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /^approve/ })).not.toBeInTheDocument();
  });

  it('shows approve/reject/escalate buttons when canApprove=true', async () => {
    render(
      <ApprovalQueue canApprove={true} currentUserId="user_ops" />
    );
    await waitFor(() => {
      expect(screen.getByText(/APPROVAL QUEUE/)).toBeInTheDocument();
    });
    // Two pending-ish items x 3 buttons each = at least 6 buttons
    const approveBtns = screen.getAllByRole('button', { name: /^approve/ });
    expect(approveBtns.length).toBeGreaterThanOrEqual(2);
  });

  it('buttons are disabled when no decision reason is provided', async () => {
    render(
      <ApprovalQueue canApprove={true} currentUserId="user_ops" />
    );
    await waitFor(() => {
      expect(screen.getByText(/APPROVAL QUEUE/)).toBeInTheDocument();
    });
    const approveBtns = screen.getAllByRole('button', { name: /^approve/ });
    expect(approveBtns[0]).toBeDisabled();
  });

  it('buttons become enabled when reason is provided', async () => {
    render(
      <ApprovalQueue canApprove={true} currentUserId="user_ops" />
    );
    await waitFor(() => {
      expect(screen.getByLabelText(/decision reason/i)).toBeInTheDocument();
    });
    const input = screen.getByLabelText(/decision reason/i);
    fireEvent.change(input, { target: { value: 'LGTM' } });
    const approveBtns = screen.getAllByRole('button', { name: /^approve/ });
    expect(approveBtns[0]).not.toBeDisabled();
  });

  it('filters by status when statusFilter provided', async () => {
    render(
      <ApprovalQueue canApprove={false} currentUserId="user_test" statusFilter="approved" />
    );
    await waitFor(() => {
      expect(screen.getByText(/no approvals in queue/)).toBeInTheDocument();
    });
    expect(approvalsApi.list).toHaveBeenCalledWith({ status: 'approved' });
  });
});

describe('LifecycleTraceView', () => {
  it('renders all 9 lifecycle stages', () => {
    render(<LifecycleTraceView trace={fixtureLifecycleTrace} />);
    expect(screen.getByText('Challenge')).toBeInTheDocument();
    expect(screen.getByText('Policy')).toBeInTheDocument();
    expect(screen.getByText('Approval')).toBeInTheDocument();
    expect(screen.getByText('Authorization')).toBeInTheDocument();
    expect(screen.getByText('Receipt')).toBeInTheDocument();
    expect(screen.getByText('Settlement')).toBeInTheDocument();
    expect(screen.getByText('Entitlement')).toBeInTheDocument();
    expect(screen.getByText('Grant')).toBeInTheDocument();
    expect(screen.getByText('Fulfillment')).toBeInTheDocument();
  });

  it('shows graph write and event counts', () => {
    render(<LifecycleTraceView trace={fixtureLifecycleTrace} />);
    expect(screen.getByText(/graph mutations:/)).toBeInTheDocument();
    expect(screen.getByText(/events emitted:/)).toBeInTheDocument();
  });

  it('marks stages as present when data exists', () => {
    const { container } = render(<LifecycleTraceView trace={fixtureLifecycleTrace} />);
    const presentStages = container.querySelectorAll('.lifecycle-trace__stage--present');
    expect(presentStages.length).toBe(9);
  });

  it('marks stages as absent for missing data', () => {
    const partial = { ...fixtureLifecycleTrace, entitlement: null, grant: null, fulfillment: null };
    const { container } = render(<LifecycleTraceView trace={partial} />);
    const absentStages = container.querySelectorAll('.lifecycle-trace__stage--absent');
    expect(absentStages.length).toBe(3);
  });
});
