import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App, type DemoSeedStatus } from '@demo/App';
import type { DemoConfig } from '@demo/lib/env';

const config: DemoConfig = {
  environment: 'test',
  apiBaseUrl: 'https://api.invalid',
  tenantId: 'selected-demo-tenant',
  seedNamespace: 'acceptance',
  aetherUrl: 'https://aether.invalid',
  kyberUrl: 'https://kyber.invalid',
};

const seeded: DemoSeedStatus = {
  seeded: true,
  is_demo_tenant: true,
  tenant_id: 'selected-demo-tenant',
  tenant_name: 'Backend demo tenant',
  data_origin: 'synthetic_seed',
  latest_run: {
    seed_run_id: 'run-1',
    dataset_version: 'v1',
    namespace: 'acceptance',
    tenant_id: 'selected-demo-tenant',
    checksum: 'sha256:abc',
    status: 'completed',
    started_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:00:01Z',
    inserted_counts: { entities: 2 },
    updated_counts: {},
    skipped_counts: { tenant: 1 },
  },
};

function response(data: DemoSeedStatus, ok = true): Response {
  return { ok, status: ok ? 200 : 503, json: async () => ({ data }) } as Response;
}

afterEach(() => vi.unstubAllGlobals());

describe('Aether Demo App backend data truth', () => {
  it('renders loading then authoritative unseeded state without a demo banner', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      ...seeded,
      seeded: false,
      is_demo_tenant: false,
      data_origin: null,
      tenant_name: null,
      latest_run: null,
    })));
    render(<App config={config} />);
    expect(screen.getByLabelText('Loading demo seed status')).toBeInTheDocument();
    expect(await screen.findByText('No demonstration dataset is seeded')).toBeInTheDocument();
    expect(screen.queryByTestId('synthetic-data-banner')).not.toBeInTheDocument();
  });

  it('renders backend provenance and a backend-driven banner when seeded', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(seeded));
    vi.stubGlobal('fetch', fetchMock);
    render(<App config={config} />);
    expect(await screen.findByText('Backend demo tenant')).toBeInTheDocument();
    expect(screen.getByTestId('synthetic-data-banner')).toHaveTextContent(
      'synthetic records were seeded into the backend',
    );
    expect(screen.getByText('sha256:abc')).toBeInTheDocument();
    expect(screen.getByText('entities')).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/v1/demo-seed/status?');
  });

  it('renders unavailable rather than empty when the backend request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')));
    render(<App config={config} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('network down');
    expect(screen.queryByText('No demonstration dataset is seeded')).not.toBeInTheDocument();
    expect(screen.queryByTestId('synthetic-data-banner')).not.toBeInTheDocument();
  });

  it('rejects malformed successful responses as unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: {} }),
    } as Response));
    render(<App config={config} />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('invalid response'));
  });
});
