import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { TimeProvider } from '@aether/ui';
import {
  ExplorationProvider,
  type ExplorationClient,
} from '@aether/ui/exploration';
import { CampaignExplorationTab } from '@aether-app/pages/campaigns/campaigns-page';

function client(adapterAvailable = true): ExplorationClient {
  return {
    queryLatest: vi.fn().mockResolvedValue({
      contract_version: '1',
      query_id: 'query-1',
      normalized_context: {
        version: '1',
        scope: { tenant_id: 'tenant-campaign-test', surface: 'campaign360' },
        temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
      },
      data: {
        campaigns: [{ campaign_id: 'campaign-1', count: 7 }],
        unattributed_count: 2,
        nodes: [],
      },
      pagination: { cursor: null, has_more: false, total_estimate: 1 },
      completeness: { complete: true, sampled: false, truncated: false },
      truth: { overall_state: 'ready', dimensions: [] },
      applicability: { entries: [] },
      execution: { duration_ms: 2, cache_status: 'bypass', adapters: ['campaign360'] },
      warnings: [],
    }),
    resolveLink: vi.fn().mockResolvedValue({
      link: {
        to: 'journeys',
        context: {
          version: '1',
          scope: { tenant_id: 'tenant-campaign-test', surface: 'journeys' },
          temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
        },
      },
      applicability: { entries: [] },
      adapter_available: adapterAvailable,
      warnings: adapterAvailable ? [] : ['surface_backend_not_available_on_this_deployment'],
    }),
    validate: vi.fn(),
    query: vi.fn(),
    facets: vi.fn(),
    facetsLatest: vi.fn(),
    listViews: vi.fn(),
    saveView: vi.fn(),
    getView: vi.fn(),
    deleteView: vi.fn(),
    cancelLatest: vi.fn(),
  } as unknown as ExplorationClient;
}

describe('Campaign exploration surface', () => {
  it('renders graph-backed truth and uses the advanced table contract', async () => {
    const explorationClient = client();
    render(
      <MemoryRouter>
        <TimeProvider>
          <ExplorationProvider
            tenantId="tenant-campaign-test"
            surface="campaign360"
            client={explorationClient}
          >
            <CampaignExplorationTab />
          </ExplorationProvider>
        </TimeProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText('campaign-1')).toBeInTheDocument();
    expect(screen.getByText('1 returned of 1 total')).toBeInTheDocument();
    expect(screen.getByText(/2 returned nodes have no asserted campaign attribution/)).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Campaign exploration results' })).toBeInTheDocument();
  });

  it('fails closed when a resolved campaign link has no adapter', async () => {
    const explorationClient = client(false);
    render(
      <MemoryRouter>
        <TimeProvider>
          <ExplorationProvider
            tenantId="tenant-campaign-link-test"
            surface="campaign360"
            client={explorationClient}
          >
            <CampaignExplorationTab />
          </ExplorationProvider>
        </TimeProvider>
      </MemoryRouter>,
    );

    await userEvent.click(await screen.findByText('campaign-1'));
    await waitFor(() =>
      expect(screen.getByText('Campaign exploration is unavailable in this release.')).toBeInTheDocument(),
    );
  });
});
