import type { ComponentType } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { AttributionStudioPage } from '@kyber/pages/measurement/attribution-studio-page';
import { CampaignIntelligencePage } from '@kyber/pages/measurement/campaign-intelligence-page';
import { ConversionExplorerPage } from '@kyber/pages/measurement/conversion-explorer-page';
import { JourneyExplorerPage } from '@kyber/pages/measurement/journey-explorer-page';
import { MeasurementOverviewPage } from '@kyber/pages/measurement/measurement-overview-page';

vi.mock('@kyber/features/measurement', () => ({
  useAttributionStudio: () => ({ data: { runs: [] }, loading: false, error: null }),
  useCampaignIntelligence: () => ({ data: { spend: [], reconciliation: {} }, loading: false, error: null }),
  useConversionExplorer: () => ({ data: { conversions: [] }, loading: false, error: null }),
  useJourneyExplorer: () => ({ data: { journeys: [] }, loading: false, error: null }),
  useJourneyExplain: () => ({ data: {}, loading: false, error: null }),
  useJourneyHealth: () => ({
    data: {
      summary: {
        total_journeys: 0,
        avg_steps_per_journey: 0,
        quality_breakdown: {},
        compiler_versions: {},
      },
      failed_or_partial: [],
      rebuild_queue_depth: null,
      web3_finality_backlog: null,
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
  useJourneySteps: () => ({ data: { steps: [], hasMore: false }, loading: false, error: null, loadMore: vi.fn() }),
  useJourneyTransitions: () => ({ data: { transitions: {}, families: {} }, loading: false, error: null }),
  useMeasurementOverview: () => ({ data: { overview: {}, quality: {}, health: { connectors: {} } }, loading: false, error: null }),
}));

const cases: readonly [string, ComponentType, string][] = [
  ['/measurement', MeasurementOverviewPage, 'No connectors configured'],
  ['/measurement/attribution', AttributionStudioPage, 'No attribution runs'],
  ['/measurement/journeys', JourneyExplorerPage, 'No journeys found'],
  ['/measurement/conversions', ConversionExplorerPage, 'No conversions found'],
  ['/measurement/campaigns', CampaignIntelligencePage, 'No spend records'],
];

describe('Kyber measurement successful-empty routes', () => {
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
