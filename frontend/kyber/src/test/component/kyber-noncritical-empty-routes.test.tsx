import type { ComponentType } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { DeliveryOpsPage } from '@kyber/pages/delivery/delivery-ops';
import { DuneFeederPage } from '@kyber/pages/dune-feeder/dune-feeder-page';
import { FleetGraphPage } from '@kyber/pages/noesis/fleet-graph-page';
import { ReviewQueuePage } from '@kyber/pages/suggestions/review-queue-page';
import { SuggestionsPage } from '@kyber/pages/suggestions/suggestions-page';

const emptyApi = vi.hoisted(() => ({
  listTenants: vi.fn(async () => ({ tenants: [], total: 0 })),
  feederHealth: vi.fn(async () => ({
    status: 'ok',
    total_bronze_records: 0,
    total_silver_records: 0,
    total_gold_records: 0,
    unique_source_tags: 0,
    rejection_rate: 0,
    last_ingest_at: null,
    last_ingest_source_tag: null,
    graph_isolation_enforced: true,
  })),
  feederGold: vi.fn(async () => ({ records: [], record_count: 0 })),
  deliveryJobs: vi.fn(async () => ({ items: [], count: 0 })),
}));

vi.mock('@kyber/features/noesis', () => ({
  useFleetTenantEnvelope: () => ({ envelope: null, isLoading: false, error: null, refresh: vi.fn() }),
  useKyberOperatorEntry: () => ({
    session: null,
    isEntering: false,
    isExiting: false,
    error: null,
    enterTenant: vi.fn(),
    exitTenant: vi.fn(),
  }),
}));

vi.mock('@kyber/features/suggestions', () => ({
  useSuggestions: () => ({ data: [], loading: false, error: null, refresh: vi.fn() }),
  useSuggestionsSummary: () => ({ data: {}, loading: false, error: null }),
  useReviewQueue: () => ({ data: [], loading: false, error: null, refresh: vi.fn() }),
  useSuggestionActions: () => ({
    approve: vi.fn(),
    reject: vi.fn(),
    suppress: vi.fn(),
    loading: false,
    error: null,
  }),
}));

vi.mock('@kyber/lib/api/endpoints', () => ({
  api: {
    admin: {
      tenants: { list: emptyApi.listTenants },
      kyber: {
        duneFeederHealth: emptyApi.feederHealth,
        duneFeederGold: emptyApi.feederGold,
      },
    },
  },
}));

vi.mock('@kyber/lib/api', () => ({
  api: {
    admin: {
      kyber: {
        listDeliveryJobs: emptyApi.deliveryJobs,
      },
    },
  },
}));

const cases: readonly [string, ComponentType, string][] = [
  ['/noesis/fleet', FleetGraphPage, 'No tenants found'],
  ['/intelligence/suggestions', SuggestionsPage, 'No suggestions found'],
  ['/intelligence/suggestions/review', ReviewQueuePage, 'No items in review queue'],
  ['/dune-feeder', DuneFeederPage, 'No Gold records yet. Ingest Bronze rows, promote to Silver, then materialize Gold via the admin API.'],
  ['/delivery', DeliveryOpsPage, 'No jobs found'],
];

describe('Kyber noncritical successful-empty routes', () => {
  it.each(cases)('%s renders a successful empty state', async (route, Page, emptyText) => {
    render(
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[route]}>
            <Routes><Route path={route} element={<Page />} /></Routes>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );

    expect(await screen.findByText(emptyText)).toBeInTheDocument();
  });
});
