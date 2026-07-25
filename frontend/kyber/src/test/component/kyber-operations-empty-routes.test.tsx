import type { ComponentType } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { KyberDerivativesOpsPage } from '@kyber/pages/derivatives/kyber-derivatives-ops-page';
import { ImplementationPage } from '@kyber/pages/implementation';
import { KyberInteropOpsPage } from '@kyber/pages/interop/kyber-interop-ops-page';
import { JourneyHealthPage } from '@kyber/pages/journey-health';
import { KyberStablecoinsOpsPage } from '@kyber/pages/stablecoins/kyber-stablecoins-ops-page';

const opsMocks = vi.hoisted(() => ({
  empty: vi.fn(async () => ({ items: [], count: 0 })),
  correlationEmpty: vi.fn(async () => ({
    message_count: 0,
    out_of_order_discoveries: 0,
    uncorrelated_messages: 0,
    by_status: {},
  })),
}));

vi.mock('@kyber/lib/featureFlags', () => ({
  featureFlags: { kyberStablecoinOps: true, kyberDerivativesOps: true, kyberInteropOps: true },
  isFeatureEnabled: () => true,
}));
vi.mock('@kyber/lib/api/stablecoins-ops', () => ({
  stablecoinsOpsApi: { registryStatus: opsMocks.empty, finalityCheckpoints: opsMocks.empty, reconciliation: opsMocks.empty, unresolvedObservations: opsMocks.empty },
}));
vi.mock('@kyber/lib/api/derivatives-ops', () => ({
  derivativesOpsApi: { fleet: opsMocks.empty, checkpoints: opsMocks.empty, streamGaps: opsMocks.empty, variances: opsMocks.empty },
}));
vi.mock('@kyber/lib/api/interop-ops', () => ({
  interopOpsApi: {
    providersHealth: opsMocks.empty,
    correlationHealth: opsMocks.correlationEmpty,
    policyDrift: opsMocks.empty,
  },
}));
vi.mock('@kyber/features/onboarding', () => ({
  useImplementationOverview: () => ({ loading: false, error: null, data: {} }),
  useImplementationTenants: () => ({ loading: false, error: null, data: { items: [], count: 0 } }),
  useTenantImplementation: () => ({ loading: false, error: null, data: null }),
  useImplementationBlockers: () => ({ loading: false, error: null, data: { items: [], count: 0 } }),
  useCustomerSuccessTriggers: () => ({ loading: false, error: null, data: { items: [], count: 0 } }),
}));
vi.mock('@kyber/features/journey-health', () => ({
  useJourneyHealth: () => ({
    data: { overview: {}, sdkParity: { platforms: {} }, droppedEvents: { items: [] } },
    loading: false,
    error: null,
  }),
}));

const cases: readonly [string, string, ComponentType, string][] = [
  ['/stablecoins/ops', '/stablecoins/ops', KyberStablecoinsOpsPage, 'No finality checkpoints'],
  ['/derivatives/ops', '/derivatives/ops', KyberDerivativesOpsPage, 'No adapters registered'],
  ['/interoperability/ops', '/interoperability/ops', KyberInteropOpsPage, 'No provider adapters registered'],
  ['/implementation', '/implementation', ImplementationPage, 'No implementation plans yet'],
  ['/implementation/tenant-local', '/implementation/:tenantId', ImplementationPage, 'No tenant selected'],
  ['/journey-health', '/journey-health', JourneyHealthPage, 'No SDK journey emissions yet'],
];

describe('Kyber operations successful-empty routes', () => {
  it.each(cases)('%s renders a successful empty state', async (route, routePattern, Page, emptyText) => {
    render(
      <ThemeProvider><ToastProvider><MemoryRouter initialEntries={[route]}>
        <Routes><Route path={routePattern} element={<Page />} /></Routes>
      </MemoryRouter></ToastProvider></ThemeProvider>,
    );
    expect(await screen.findByText(emptyText)).toBeInTheDocument();
  });
});
