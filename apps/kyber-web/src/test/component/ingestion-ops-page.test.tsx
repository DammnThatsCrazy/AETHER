/**
 * Kyber — ingestion control plane (WS-E, blueprint Gate G) surface tests.
 *
 * Asserts the Ingestion Ops page renders honest states from stubbed backend
 * payloads and that the sidebar gates the entry behind the `enableIngestionOps`
 * frontend flag (default OFF, mirroring AETHER_INGESTION_OBSERVABILITY_ENABLED):
 *
 *   · the sidebar lists "Ingestion Ops" → /ingestion-ops when the flag is on;
 *   · the sidebar hides it when the flag is off;
 *   · the page renders its funnel / recent-traces / tier-manifest / replay cards
 *     from what the backend reports;
 *   · when the backend reports telemetry OFF (`enabled: false`), the page renders
 *     the honest disabled note rather than claiming health.
 *
 * Routing is not a grant — the /v1/kyber/ingest/observability + replay endpoints
 * are Kyber-operator-only and gate every request; this test only proves the
 * surfaces are wired and honest against backend-supplied state.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { Sidebar } from '@kyber/components/layout';
import { IngestionOpsPage } from '@kyber/features/ingestion-ops';

const state = vi.hoisted(() => ({
  showNav: true,
  telemetryEnabled: true,
}));

const STAGES = [
  'raw', 'received', 'validated', 'bronze', 'normalized',
  'resolved', 'relationships', 'graph_mutations', 'projections', 'metrics_findings',
].map((stage, index) => ({
  stage,
  display: stage.replace(/_/g, ' ').toUpperCase(),
  monitored: ['received', 'validated', 'bronze', 'normalized', 'projections'].includes(stage),
  total: 0,
  by_status: {},
}));

function makeFunnel() {
  return {
    enabled: state.telemetryEnabled,
    recorded_at: '2026-09-06T00:00:00Z',
    instrumentation: {
      monitored_stages: ['received', 'validated', 'bronze', 'normalized', 'projections'],
      declared_unmonitored: ['raw', 'resolved', 'relationships', 'graph_mutations', 'metrics_findings'],
      scope: 'in-process ledger',
    },
    rollup: state.telemetryEnabled
      ? { received: 3, accepted: 2, duplicates: 0, rejected: 0, degraded: 1 }
      : { received: 0, accepted: 0, duplicates: 0, rejected: 0, degraded: 0 },
    stages: STAGES,
  };
}

vi.mock('@kyber/lib/featureFlags', () => ({
  featureFlags: { enableIngestionOps: true },
  isFeatureEnabled: (flag: string) => (flag === 'enableIngestionOps' ? state.showNav : false),
}));

vi.mock('@kyber/lib/api/endpoints', () => ({
  api: {
    sdkHealth: {
      pipelineLag: vi.fn(async () => ({
        probe: 'ingestion-pipeline',
        status: state.telemetryEnabled ? 'healthy' : 'disabled',
        enabled: state.telemetryEnabled,
        timestamp: '2026-09-06T00:00:00Z',
        pipeline: {
          received: 0,
          accepted: 0,
          duplicates: 0,
          rejected: 0,
          degraded: 0,
        },
        stages: STAGES,
      })),
      fleet: vi.fn(async () => ({
        tenant_id: 'test-tenant',
        total_instances: 0,
        healthy_count: 0,
        degraded_count: 0,
        unhealthy_count: 0,
        silent_count: 0,
        avg_health_score: 0,
        platforms: {},
        versions: {},
        computed_at: '2026-09-06T00:00:00Z',
      })),
      driftIncidents: vi.fn(async () => ({ incidents: [] })),
      rolloutStatus: vi.fn(async () => ({
        tenant_id: 'test-tenant',
        current_version: null,
        current_rollout_pct: null,
        previous_version: null,
        has_rollback_available: false,
        current_published_at: null,
      })),
    },
    ingestionOps: {
      observabilityStatus: vi.fn(async () => ({
        enabled: state.telemetryEnabled,
        recorded_at: '2026-09-06T00:00:00Z',
        instrumentation: {
          monitored_stages: ['received', 'validated', 'bronze', 'normalized', 'projections'],
          declared_unmonitored: ['raw', 'resolved', 'relationships', 'graph_mutations', 'metrics_findings'],
          scope: 'in-process ledger',
        },
      })),
      funnel: vi.fn(async () => makeFunnel()),
      recentTraces: vi.fn(async () => ({ traces: [] })),
      replayStatus: vi.fn(async () => ({
        enabled: true,
        source_service: 'sdk-bronze-replay',
        dry_run_default: true,
      })),
      versionTiers: vi.fn(async () => ({
        data: {
          schema_version: '1.0.0',
          enabled: false,
          mode: 'off',
          blocked_after_date: '2027-01-31',
          tiers: [
            {
              id: 'supported',
              status: 'supported',
              label: '8.x',
              min_version: '8.0.0',
              max_version_exclusive: '',
              deprecated_after: null,
              blocked_after: null,
              capabilities: ['batch_ingestion', 'server_side_ingestion', 'canonical_observation_envelope', 'normalization_spine', 'idempotent_replay'],
              note: 'none',
            },
            {
              id: 'read_compatible',
              status: 'read_compatible',
              label: '6.x',
              min_version: '6.0.0',
              max_version_exclusive: '7.0.0',
              deprecated_after: null,
              blocked_after: null,
              capabilities: ['batch_ingestion', 'server_side_ingestion', 'idempotent_replay'],
              note: null,
            },
          ],
          unclassified: {
            id: 'unclassified',
            label: 'unknown library / unparseable version',
            note: 'never blocked; open-bounds sentinel',
          },
        },
      })),
      trace: vi.fn(async () => ({ trace: null })),
    },
  },
}));

vi.mock('@aether/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aether/ui')>();
  return {
    ...actual,
    useCapabilities: () => ({ capabilities: null, buildInfo: null, loading: false, error: null, refresh: vi.fn() }),
    useBuildInfo: () => null,
  };
});

function renderSidebar() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

function renderPage() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter>
          <IngestionOpsPage />
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe('Kyber ingestion control plane', () => {
  it('lists Ingestion Ops in the sidebar when enableIngestionOps is on', () => {
    state.showNav = true;
    renderSidebar();
    expect(screen.getByRole('link', { name: 'Ingestion Ops' })).toHaveAttribute('href', '/ingestion-ops');
  });

  it('hides Ingestion Ops from the sidebar when enableIngestionOps is off', () => {
    state.showNav = false;
    renderSidebar();
    expect(screen.queryByRole('link', { name: 'Ingestion Ops' })).toBeNull();
  });

  it('renders the control plane cards from enabled backend telemetry', async () => {
    state.showNav = true;
    state.telemetryEnabled = true;
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Ingestion Ops' })).toBeInTheDocument();
    expect(await screen.findByText(/Ingestion telemetry is ON/)).toBeInTheDocument();
    expect(screen.getByText('Ingestion funnel')).toBeInTheDocument();
    expect(screen.getByText('SDK version-compatibility tiers')).toBeInTheDocument();
    expect(screen.getByText('Replay service')).toBeInTheDocument();
    // Empty recent-trace state (the ledger has no recorded observations yet).
    expect(await screen.findByText('No recent observation traces')).toBeInTheDocument();
  });

  it('renders an honest disabled note when the backend reports telemetry OFF', async () => {
    state.showNav = true;
    state.telemetryEnabled = false;
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Ingestion Ops' })).toBeInTheDocument();
    expect(await screen.findByText(/AETHER_INGESTION_OBSERVABILITY_ENABLED is OFF/)).toBeInTheDocument();
    expect(screen.getByText('Pipeline observability disabled')).toBeInTheDocument();
  });
});
