import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get, post } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock('@aether-app/lib/api/rest/client', () => ({
  restClient: { get, post },
  RestClientError: class RestClientError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

vi.mock('@aether/ui/exploration', () => ({
  TruthBanner: ({ surfaceLabel }: { surfaceLabel: string }) => <div>{surfaceLabel}</div>,
  useExplorationContext: () => ({
    version: '1',
    scope: { tenant_id: 'tenant-a', surface: 'graph' },
    temporal: {
      mode: 'as_of',
      field: 'observed_at',
      as_of: '2026-07-01T00:00:00.000Z',
      timezone: 'UTC',
    },
  }),
}));

import { ComparisonPage } from '@aether-app/pages/comparison/comparison-page';

const envelope = (data: unknown) => ({
  data,
  status: 'success',
  timestamp: '2026-07-28T00:00:00.000Z',
});

describe('ComparisonPage', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockResolvedValue(envelope({ definitions: [] }));
    post.mockImplementation((path: string) => {
      if (path === '/v1/intelligence/comparisons') {
        return Promise.resolve(envelope({
          definition: {
            definition_id: 'definition-1',
            tenant_id: 'tenant-a',
            name: 'entity_vs_entity:subject-1',
            mode: 'entity_vs_entity',
            subject: { subject_type: 'entity', subject_id: 'subject-1', tenant_id: 'tenant-a' },
            dimensions: ['behavior'],
          },
        }));
      }
      return Promise.resolve(envelope({
        run: {
          run_id: 'run-1',
          definition_id: 'definition-1',
          tenant_id: 'tenant-a',
          state: 'running',
        },
        job_id: 'job-1',
      }));
    });
  });

  it('blocks an invalid draft before the comparison client creates anything', async () => {
    render(<ComparisonPage />);
    await screen.findByText('No comparison definitions');

    await userEvent.click(screen.getByRole('button', { name: 'Create and run' }));

    expect(screen.getByLabelText('Comparison preflight blockers')).toHaveTextContent(
      'Subject entity is required.',
    );
    expect(post).not.toHaveBeenCalled();
  });

  it('uses the mounted typed client path and preserves canonical context', async () => {
    render(<ComparisonPage />);
    await screen.findByText('No comparison definitions');
    await userEvent.type(screen.getByLabelText('Subject entity'), 'subject-1');
    await userEvent.type(screen.getByLabelText('Baseline entity'), 'baseline-1');

    await userEvent.click(screen.getByRole('button', { name: 'Create and run' }));

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        '/v1/intelligence/comparisons',
        expect.anything(),
        expect.objectContaining({
          mode: 'entity_vs_entity',
          temporal_mode: 'as_of',
          subject: expect.objectContaining({
            subject_id: 'subject-1',
            tenant_id: 'tenant-a',
            as_of: '2026-07-01T00:00:00.000Z',
          }),
          baseline: expect.objectContaining({
            baseline_type: 'entity',
            subject: expect.objectContaining({
              subject_id: 'baseline-1',
              tenant_id: 'tenant-a',
            }),
          }),
        }),
      );
      expect(post).toHaveBeenCalledWith(
        '/v1/intelligence/comparisons/definition-1/runs',
        expect.anything(),
        { as_of: '2026-07-01T00:00:00.000Z' },
      );
    });
  });
});
