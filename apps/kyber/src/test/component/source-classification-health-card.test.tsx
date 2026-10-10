import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SourceClassificationHealthCard } from '@kyber/pages/measurement/kyber-measurement-ops-page';

function confirmAction(label: string) {
  fireEvent.click(screen.getByRole('button', { name: label }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
}

function requestIdFactory() {
  let sequence = 0;
  return () => `repair-request-${String(++sequence).padStart(4, '0')}`;
}

describe('SourceClassificationHealthCard', () => {
  it('reuses an action request ID after failure and rotates it after success', async () => {
    let attempt = 0;
    const onReclassify = vi.fn(async (params: Record<string, unknown>) => {
      attempt += 1;
      if (attempt === 1) throw new Error('temporary timeout');
      return {
        status: 'queued',
        job_id: `job-${attempt}`,
        request_id: params.request_id,
        replayed: attempt === 2,
      };
    });

    render(
      <SourceClassificationHealthCard
        health={{ status: 'degraded', summary: { total: 12, unclassified: 2 } }}
        loading={false}
        error={null}
        onRefresh={vi.fn(async () => undefined)}
        onReclassify={onReclassify}
        requestIdFactory={requestIdFactory()}
      />,
    );

    expect(screen.getByText('degraded')).toBeInTheDocument();

    confirmAction('Dry-run reclassification');
    await screen.findByText(/temporary timeout/);
    const firstRequestId = onReclassify.mock.calls[0]?.[0]?.request_id;

    confirmAction('Dry-run reclassification');
    await screen.findByText(/Job: job-2/);
    expect(screen.getByText(/Replayed: Yes/)).toBeInTheDocument();
    expect(onReclassify.mock.calls[1]?.[0]?.request_id).toBe(firstRequestId);

    confirmAction('Dry-run reclassification');
    await waitFor(() => expect(onReclassify).toHaveBeenCalledTimes(3));
    expect(onReclassify.mock.calls[2]?.[0]?.request_id).not.toBe(firstRequestId);
  });

  it('rotates request IDs when repair inputs change', async () => {
    const onReclassify = vi.fn(async (_params: Record<string, unknown>) => {
      throw new Error('retryable');
    });

    render(
      <SourceClassificationHealthCard
        health={{ status: 'healthy', summary: { total: 4, unclassified: 0 } }}
        loading={false}
        error={null}
        onRefresh={vi.fn(async () => undefined)}
        onReclassify={onReclassify}
        requestIdFactory={requestIdFactory()}
      />,
    );

    confirmAction('Run source repair');
    await screen.findByText(/retryable/);
    const firstRequestId = onReclassify.mock.calls[0]?.[0]?.request_id;

    fireEvent.change(screen.getByLabelText('Touchpoint limit'), { target: { value: '750' } });
    confirmAction('Run source repair');
    await waitFor(() => expect(onReclassify).toHaveBeenCalledTimes(2));

    expect(onReclassify.mock.calls[1]?.[0]?.request_id).not.toBe(firstRequestId);
  });
});
