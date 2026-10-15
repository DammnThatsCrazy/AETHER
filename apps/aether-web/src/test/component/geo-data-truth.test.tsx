import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { GeoPage } from '@aether-app/pages/geo/geo-page';

const state = vi.hoisted(() => ({
  summary: {} as Record<string, unknown>,
  entities: {} as Record<string, unknown>,
}));

vi.mock('@aether-app/features/geo/use-geo', () => ({
  useGeoSummary: () => state.summary,
  useGeoEntities: () => state.entities,
}));

function renderPage(path = '/geo') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/geo" element={<GeoPage />} />
          <Route path="/geo/:level/:geoId" element={<GeoPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Geo routes data-truth states', () => {
  beforeEach(() => {
    state.summary = { data: null, isLoading: false, error: null, refetch: vi.fn() };
    state.entities = { data: { entities: [], total: 0 }, isLoading: false, error: null, refetch: vi.fn() };
  });

  it('renders loading without geographic totals', () => {
    state.summary = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    renderPage();
    expect(document.querySelector('.animate-pulse, .aether-skeleton')).not.toBeNull();
    expect(screen.queryByText('Entities')).not.toBeInTheDocument();
  });

  it('renders a successful empty geographic state', () => {
    renderPage();
    expect(screen.getByText(/Geographic intelligence is being provisioned/)).toBeInTheDocument();
    expect(screen.getByText('No entities found at this location')).toBeInTheDocument();
  });

  it('renders failures as unavailable rather than empty', () => {
    state.summary = { data: null, isLoading: false, error: 'geo service offline', refetch: vi.fn() };
    state.entities = { data: null, isLoading: false, error: 'entity lookup offline', refetch: vi.fn() };
    renderPage('/geo/country/us');
    expect(screen.getByText('Failed to load geographic data')).toBeInTheDocument();
    expect(screen.getByText('Failed to load geographic entities')).toBeInTheDocument();
  });

  it('renders backend-populated summary and entities', () => {
    state.summary = {
      data: {
        geo_name: 'Global',
        entity_count: 4,
        avg_edges_per_entity: 1.5,
        conversion_rate: 0.25,
        anomaly_flags: 0,
        children: [],
        tier_distribution: {},
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.entities = {
      data: { entities: [{ entity_id: 'entity-1', display_name: 'Observed Entity' }], total: 1 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    renderPage();
    expect(screen.getByText('Observed Entity')).toBeInTheDocument();
    expect(screen.getByText('25.0%')).toBeInTheDocument();
  });
});
