import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { InteropPage } from '@aether-app/pages/interop';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { interop: {
    providers: vi.fn(async () => ({ items: [
      { provider_id: 'layerzero_v2', provider_kind: 'layerzero_v2', implementation_status: 'credential_gated' },
      { provider_id: 'wormhole', provider_kind: 'wormhole', implementation_status: 'scaffolded' },
    ], count: 2 })),
    messages: vi.fn(async () => ({ items: [
      { interop_message_id: 'msg_1', correlation_key: 'lz2:0xabcdef1234567890abcdef', provider_kind: 'layerzero_v2', path_id: 'path-eth-arb', status: 'delivered', source_observed_at: '2026-07-08T00:00:00Z' },
    ], count: 1 })),
    paths: vi.fn(async () => ({ items: [], count: 0 })),
  } },
}));

describe('Interop page', () => {
  it('renders messages and honest provider implementation status', async () => {
    render(<MemoryRouter><InteropPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Interoperability Intelligence')).toBeInTheDocument());
    expect(screen.getByText('Messages observed')).toBeInTheDocument();
    // observation-only banner
    expect(screen.getByText(/never relays, retries, or recovers messages/)).toBeInTheDocument();
  });
});
