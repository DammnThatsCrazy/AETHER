import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { TimeProvider } from '@aether/ui';
import {
  ExplorationProvider,
  type ExplorationClient,
} from '@aether/ui/exploration';
import type { ExplorationResultEnvelope } from '@aether/shared/exploration-contract';
import { ProjectionSurfacePanel, ProjectionSurfaceSummary } from '@kyber/features/projection-360';
import type { ProjectionSurfaceSummary as ProjectionSurfaceSummaryModel } from '@kyber/features/projection-360/projection-360-types';

/** Full-mock exploration client — every method is stubbed (mirrors the
 * campaign-exploration precedent) so the provider surface is never exercised
 * unmocked; only queryLatest carries a projection summary payload. */
function client(
  data: ProjectionSurfaceSummaryModel,
  surface: string,
  tenantId: string,
): ExplorationClient {
  const envelope: ExplorationResultEnvelope<ProjectionSurfaceSummaryModel> = {
    contract_version: '1',
    query_id: 'query-360',
    normalized_context: {
      version: '1',
      scope: { tenant_id: tenantId, surface },
      temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
    },
    data,
    pagination: { cursor: null, has_more: false, total_estimate: null },
    completeness: { complete: true, sampled: false, truncated: false },
    truth: { overall_state: 'ready', dimensions: [] },
    applicability: { entries: [] },
    execution: { duration_ms: 2, cache_status: 'bypass', adapters: [surface] },
    warnings: [],
  };
  return {
    queryLatest: vi.fn().mockResolvedValue(envelope),
    resolveLink: vi.fn(),
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

function availableSummary(): ProjectionSurfaceSummaryModel {
  return {
    projectionId: 'outcome360',
    available: true,
    digest: 'digest-abc-123',
    lensIds: ['baseline'],
    temporalMode: 'window',
    degradationState: 'none',
    sections: [
      { id: 'summary', state: 'available' },
      { id: 'findings', state: 'available' },
      { id: 'outcomes', state: 'stale' },
      { id: 'evidence', state: 'degraded' },
      { id: 'cohorts', state: 'suppressed' },
    ],
    suppressedSections: ['cohorts'],
  };
}

describe('ProjectionSurfaceSummary (server-computed 360 state)', () => {
  it('renders typed per-section states and provenance digest verbatim', () => {
    render(<ProjectionSurfaceSummary summary={availableSummary()} />);

    // Registry-backed display name — no client-typed label literal.
    expect(screen.getByText('Outcome 360')).toBeInTheDocument();
    expect(screen.getByText('digest-abc-123')).toBeInTheDocument();
    expect(screen.getByText('lenses:')).toBeInTheDocument();
    expect(screen.getByText('baseline')).toBeInTheDocument();

    // Typed states surface as-is — never reinterpreted.
    expect(screen.getByText('summary')).toBeInTheDocument();
    expect(screen.getByText('findings')).toBeInTheDocument();
    expect(screen.getByText('outcomes')).toBeInTheDocument();
    expect(screen.getByText('stale')).toBeInTheDocument();
    expect(screen.getByText('evidence')).toBeInTheDocument();
    expect(screen.getByText('degraded')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Outcome 360 sections' })).toBeInTheDocument();
  });

  it('hides a suppressed section and reports the withheld count', () => {
    render(<ProjectionSurfaceSummary summary={availableSummary()} />);

    // Suppressed sections never render as content.
    expect(screen.queryByText('cohorts')).not.toBeInTheDocument();
    expect(screen.getByText('1 section is suppressed by projection policy.')).toBeInTheDocument();
  });

  it('renders a content-free degraded reason when the projection is unavailable', () => {
    render(
      <ProjectionSurfaceSummary
        summary={{ projectionId: 'economic360', available: false, reason: 'provider_unavailable', sections: [] }}
      />,
    );

    expect(screen.getByText('Economic 360 — unavailable')).toBeInTheDocument();
    expect(screen.getByText('provider_unavailable')).toBeInTheDocument();
    // No fabricated sections are offered.
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });
});

describe('ProjectionSurfacePanel (gated over the typed exploration transport)', () => {
  it('re-targets the context to the projection surface and renders the server summary', async () => {
    const explorationClient = client(availableSummary(), 'outcome360', 'tenant-360-kyber-panel');

    render(
      <MemoryRouter>
        <TimeProvider>
          <ExplorationProvider
            tenantId="tenant-360-kyber-panel"
            surface="campaign360"
            client={explorationClient}
          >
            <ProjectionSurfacePanel surface="outcome360" focus={{ kind: 'campaign', id: 'campaign-1' }} />
          </ExplorationProvider>
        </TimeProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText('Outcome 360')).toBeInTheDocument();
    expect(await screen.findByText('digest-abc-123')).toBeInTheDocument();

    const queryLatest = explorationClient.queryLatest as ReturnType<typeof vi.fn>;
    const [request] = queryLatest.mock.calls[0] as [{ context: { scope: { surface: string } } }];
    expect(request.context.scope.surface).toBe('outcome360');
  });

  it('fails closed on a server-declared unavailable envelope', async () => {
    const explorationClient = client(
      { projectionId: 'outcome360', available: false, reason: 'provider_unavailable', sections: [] },
      'outcome360',
      'tenant-360-kyber-unavail',
    );

    render(
      <MemoryRouter>
        <TimeProvider>
          <ExplorationProvider
            tenantId="tenant-360-kyber-unavail"
            surface="campaign360"
            client={explorationClient}
          >
            <ProjectionSurfacePanel surface="outcome360" focus={{ kind: 'campaign', id: 'campaign-2' }} />
          </ExplorationProvider>
        </TimeProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText('Outcome 360 — unavailable')).toBeInTheDocument();
    expect(await screen.findByText('provider_unavailable')).toBeInTheDocument();
  });
});
