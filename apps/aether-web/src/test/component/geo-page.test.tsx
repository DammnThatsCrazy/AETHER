import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
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

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname}</div>;
}

function renderPage(path = '/geo') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/geo" element={<><GeoPage /><Where /></>} />
          <Route path="/geo/:level/:geoId" element={<><GeoPage /><Where /></>} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

const settled = (data: unknown) => ({ data, isLoading: false, error: null, refetch: vi.fn() });

describe('Geography dot map and location insights', () => {
  beforeEach(() => {
    state.summary = settled({
      geo_name: 'Global',
      entity_count: 100,
      avg_edges_per_entity: 2,
      conversion_rate: 0.1,
      anomaly_flags: 1,
      tier_distribution: { gold: 30, silver: 70 },
      computed_at: null,
      children: [
        { geo_id: 'us', geo_name: 'United States', entity_count: 60, conversion_rate: 0.12, anomaly_flags: 1 },
        { geo_id: 'gb', geo_name: 'United Kingdom', entity_count: 30, conversion_rate: 0.08, anomaly_flags: 0 },
        { geo_id: 'zz-unknown', geo_name: 'Unmapped region', entity_count: 10, conversion_rate: null, anomaly_flags: 0 },
      ],
    });
    state.entities = settled({ entities: [], total: 0 });
  });

  it('plots summary children on the dot map and lists unplaceable ones honestly', () => {
    renderPage();
    const map = screen.getByTestId('geo-dot-map');
    expect(within(map).getByRole('button', { name: 'United States: 60' })).toBeInTheDocument();
    expect(within(map).getByRole('button', { name: 'United Kingdom: 30' })).toBeInTheDocument();
    expect(screen.getByText(/1 region without a map position is listed alongside/)).toBeInTheDocument();
    const drill = screen.getByTestId('geo-drill');
    expect(within(drill).getByText('60.0% · 60')).toBeInTheDocument();
    expect(within(screen.getByTestId('geo-current')).getByText('gold')).toBeInTheDocument();
  });

  it('switches the lens and drills into a country', async () => {
    renderPage();
    await userEvent.click(screen.getByRole('tab', { name: 'Conversion' }));
    expect(within(screen.getByTestId('geo-drill')).getByText('12.0%')).toBeInTheDocument();
    await userEvent.click(within(screen.getByTestId('geo-drill')).getByRole('button', { name: /United States/ }));
    expect(screen.getByTestId('where')).toHaveTextContent('/geo/country/us');
  });
});
