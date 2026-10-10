import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { KyberStablecoinsOpsPage } from '@kyber/pages/stablecoins/kyber-stablecoins-ops-page';
import { KyberDerivativesOpsPage } from '@kyber/pages/derivatives/kyber-derivatives-ops-page';
import { KyberInteropOpsPage } from '@kyber/pages/interop/kyber-interop-ops-page';

vi.mock('@kyber/lib/featureFlags', () => ({
  featureFlags: { kyberStablecoinOps: true, kyberDerivativesOps: true, kyberInteropOps: true },
  isFeatureEnabled: (flag: string) =>
    ['kyberStablecoinOps', 'kyberDerivativesOps', 'kyberInteropOps'].includes(flag),
}));

vi.mock('@kyber/lib/api/stablecoins-ops', () => ({
  stablecoinsOpsApi: {
    registryStatus: vi.fn(async () => ({ asset_count: 3, deployment_count: 5 })),
    finalityCheckpoints: vi.fn(async () => ({ items: [], count: 0 })),
    reconciliation: vi.fn(async () => ({ items: [], count: 0 })),
    unresolvedObservations: vi.fn(async () => ({ items: [], count: 0 })),
  },
}));

vi.mock('@kyber/lib/api/derivatives-ops', () => ({
  derivativesOpsApi: {
    fleet: vi.fn(async () => ({ items: [
      { adapter_id: 'simulator', venue_id: 'venue-sim', implementation_status: 'mocked_local', authority_type: 'read_only' },
    ], count: 1 })),
    checkpoints: vi.fn(async () => ({ items: [], count: 0 })),
    streamGaps: vi.fn(async () => ({ items: [], count: 0 })),
    variances: vi.fn(async () => ({ items: [], count: 0 })),
  },
}));

vi.mock('@kyber/lib/api/interop-ops', () => ({
  interopOpsApi: {
    providersHealth: vi.fn(async () => ({ items: [
      { provider_id: 'layerzero_v2', provider_kind: 'layerzero_v2', implementation_status: 'credential_gated', checkpoints: [] },
      { provider_id: 'wormhole', provider_kind: 'wormhole', implementation_status: 'scaffolded', checkpoints: [] },
    ], count: 2 })),
    correlationHealth: vi.fn(async () => ({
      message_count: 4, out_of_order_discoveries: 1, uncorrelated_messages: 0,
      by_status: { delivered: 3, verified: 1 },
    })),
    policyDrift: vi.fn(async () => ({ items: [], count: 0 })),
  },
}));

describe('Kyber Stablecoin Ops page', () => {
  it('renders registry status and finality sections', async () => {
    render(<MemoryRouter><KyberStablecoinsOpsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Stablecoin Ops')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('3 canonical assets')).toBeInTheDocument());
    expect(screen.getByText('Finality checkpoints')).toBeInTheDocument();
    expect(screen.getByText(/never executes, mints, or moves funds/)).toBeInTheDocument();
  });
});

describe('Kyber Derivatives Ops page', () => {
  it('renders adapter fleet with honest implementation status', async () => {
    render(<MemoryRouter><KyberDerivativesOpsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Derivatives Ops')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('mocked_local')).toBeInTheDocument());
    expect(screen.getByText('Run conformance')).toBeInTheDocument();
    expect(screen.getByText(/never places, modifies, or cancels orders/)).toBeInTheDocument();
  });
});

describe('Kyber Interop Ops page', () => {
  it('renders provider health with honest statuses and correlation stats', async () => {
    render(<MemoryRouter><KyberInteropOpsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Interoperability Ops')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('credential_gated')).toBeInTheDocument());
    expect(screen.getByText('scaffolded')).toBeInTheDocument();
    expect(screen.getByText('1 out-of-order discoveries')).toBeInTheDocument();
    expect(screen.getByText(/never relays, retries, or recovers messages/)).toBeInTheDocument();
  });
});
