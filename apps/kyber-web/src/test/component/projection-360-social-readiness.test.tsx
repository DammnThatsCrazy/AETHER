import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { TimeProvider } from '@aether/ui';
import {
  ExplorationProvider,
  type ExplorationClient,
} from '@aether/ui/exploration';
import {
  ProjectionSurfacePanel,
  projectionSurfaceEvidenceReadiness,
} from '@kyber/features/projection-360';

/** Full-mock exploration client (mirrors projection-360-summary.test.tsx). */
function client(tenantId: string): ExplorationClient {
  return {
    queryLatest: vi.fn().mockResolvedValue(null),
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

describe('projectionSurfaceEvidenceReadiness (M10 honest gate)', () => {
  it('marks relationship/social (relationship_360) in_flight surfaces as not ready', () => {
    // Social evidence plane is in_flight (M3+ not built): no evidence-backed
    // data yet. Unknown is never zero — the surface stays unavailable.
    expect(projectionSurfaceEvidenceReadiness('social360')).toEqual({
      ready: false,
      reason: 'no_evidence_backed_data_yet',
    });
    expect(projectionSurfaceEvidenceReadiness('relationship360')).toEqual({
      ready: false,
      reason: 'no_evidence_backed_data_yet',
    });
  });

  it('leaves implemented measurement surfaces ready', () => {
    expect(projectionSurfaceEvidenceReadiness('outcome360').ready).toBe(true);
    expect(projectionSurfaceEvidenceReadiness('economic360').ready).toBe(true);
    expect(projectionSurfaceEvidenceReadiness('infrastructure360').ready).toBe(true);
  });
});

describe('ProjectionSurfacePanel — honest social unavailable state (M10)', () => {
  it('renders "not available / no evidence-backed data yet" for social360 without querying', async () => {
    const explorationClient = client('tenant-360-social-readiness-kyber');

    render(
      <MemoryRouter>
        <TimeProvider>
          <ExplorationProvider
            tenantId="tenant-360-social-readiness-kyber"
            surface="campaign360"
            client={explorationClient}
          >
            <ProjectionSurfacePanel surface="social360" />
          </ExplorationProvider>
        </TimeProvider>
      </MemoryRouter>,
    );

    expect(screen.getByText('Social 360 — unavailable')).toBeInTheDocument();
    expect(screen.getByText('no_evidence_backed_data_yet')).toBeInTheDocument();

    // No server query is issued for an in_flight social plane, and no
    // fabricated metric/section body is offered.
    expect(explorationClient.queryLatest).not.toHaveBeenCalled();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });
});
