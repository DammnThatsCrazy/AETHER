import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CapabilityProvider, ThemeProvider, ToastProvider, type Capabilities } from '@aether/ui';
import { DataExchangeGate } from '@aether-app/pages/settings/data-exchange-section';
import type { DataExchangeCapabilities } from '@aether-app/features/data-exchange';

/**
 * Data Exchange Gate — canonical-capability gating for the Settings section.
 *
 * The backend mounts /v1/data-exchange/* only while the plane is enabled. This
 * suite proves the Settings mount consults the CANONICAL capability contract
 * (feature_flags.data_exchange_enabled) and does NOT mount the DX surface — and
 * therefore issues ZERO data-exchange requests — when the plane is off or the
 * flag is absent. The DX barrel is spied at the hook seam so "never called" is
 * asserted directly.
 */

const dx = vi.hoisted(() => ({
  capabilities: vi.fn(),
  artifacts: vi.fn(),
  downloadUrl: vi.fn(),
  createExport: vi.fn(),
  createReport: vi.fn(),
}));

vi.mock('@aether-app/features/data-exchange', () => ({
  useDataExchangeCapabilities: dx.capabilities,
  useDataExchangeArtifacts: dx.artifacts,
  useDataExchangeDownloadUrl: dx.downloadUrl,
  useCreateDataExchangeExport: dx.createExport,
  useCreateDataExchangeReport: dx.createReport,
  dataExchangeSurfaceEnabled: () => true,
}));

const DX_ENABLED = {
  data_exchange: {
    enabled: true,
    flags: { exports_enabled: true, reports_enabled: true },
  },
  available_formats: [],
  available_sources: [],
  blocked_classifications: [],
} as DataExchangeCapabilities;

function canonicalCaps(flag: boolean | undefined): Capabilities {
  return {
    tenant_id: 'tenant-local',
    release: {
      deployment_profile: 'local',
      environment: 'local',
      release_class: null,
      enforcement: {
        policy_enforcement: false,
        route_registry_enforced: false,
        kyber_operator_gate: false,
      },
      enabled_route_prefixes: [],
      excluded_domains: [],
    },
    profile_sub_resources: [],
    providers: [],
    consent_purposes_granted: [],
    consent_purposes_all: [],
    feature_flags:
      flag === undefined ? {} : { data_exchange_enabled: flag },
    evaluated_at: '2026-09-05T00:00:00.000Z',
  };
}

function renderGate(flag: boolean | undefined) {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={['/settings/data-exchange']}>
          <CapabilityProvider fetchCapabilities={() => Promise.resolve(canonicalCaps(flag))}>
            <DataExchangeGate />
          </CapabilityProvider>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  dx.capabilities.mockReset();
  dx.artifacts.mockReset();
  dx.downloadUrl.mockReset();
  dx.createExport.mockReset();
  dx.createReport.mockReset();
  // The mounted DX surface renders its (closed) creation dialogs, which call
  // these hooks unconditionally — give them hook-shaped returns by default.
  dx.createExport.mockReturnValue({ create: vi.fn(), loading: false });
  dx.createReport.mockReturnValue({ create: vi.fn(), loading: false });
});

describe('DataExchangeGate canonical-capability gating', () => {
  it('renders the not-enabled EmptyState and makes ZERO DX requests when the flag is absent', async () => {
    renderGate(undefined);

    // The DX surface never mounts: no capability / artifact hook is called.
    expect(dx.capabilities).not.toHaveBeenCalled();
    expect(dx.artifacts).not.toHaveBeenCalled();

    await screen.findByText('Data Exchange is not enabled for this workspace');
    expect(dx.capabilities).not.toHaveBeenCalled();
    expect(dx.artifacts).not.toHaveBeenCalled();
    // Graceful disabled state — never a failing-request ErrorState.
    expect(screen.queryByText('Failed to load Data Exchange state')).not.toBeInTheDocument();
    // No creation affordances leak through.
    expect(screen.queryByRole('button', { name: 'New export' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New report' })).not.toBeInTheDocument();
  });

  it('renders the not-enabled EmptyState and makes ZERO DX requests when the flag is false', async () => {
    renderGate(false);

    await screen.findByText('Data Exchange is not enabled for this workspace');
    expect(dx.capabilities).not.toHaveBeenCalled();
    expect(dx.artifacts).not.toHaveBeenCalled();
    expect(screen.queryByText('Failed to load Data Exchange state')).not.toBeInTheDocument();
  });

  it('mounts the DX surface (firing DX hooks) only when the canonical flag is true', async () => {
    dx.capabilities.mockReturnValue({
      capabilities: DX_ENABLED,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    dx.artifacts.mockReturnValue({
      artifacts: [],
      count: 0,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });

    renderGate(true);

    // Capability-summary badges only exist on the mounted DX surface.
    await screen.findByText('Import engine');
    expect(dx.capabilities).toHaveBeenCalled();
    expect(dx.artifacts).toHaveBeenCalled();
    expect(
      screen.queryByText('Data Exchange is not enabled for this workspace'),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Failed to load Data Exchange state')).not.toBeInTheDocument();
  });
});
