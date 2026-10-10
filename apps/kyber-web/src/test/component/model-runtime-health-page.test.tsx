/**
 * ModelRuntimeHealthPage — Kyber model-runtime health surface (ADR-008 D8).
 *
 * The page is read-only and credential-free by design:
 *   · a status banner per overall status (ok / degraded / unhealthy);
 *   · a per-provider table (Provider, Configured, Healthy, Reason);
 *   · an extra checks list (name + Pass/Fail);
 *   · a loading region (aria-label "Loading health") and error + retry that
 *     re-calls the injected fetch client;
 *   · reason strings are redacted against common secret shapes, so no
 *     "sk-"/"AKIA"/"Bearer" text can reach the DOM.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ModelRuntimeHealthPage } from '@kyber/features/model-runtime/ModelRuntimeHealthPage';
import type { HealthResponse } from '@kyber/features/model-runtime/types';

const OK_HEALTH: HealthResponse = {
  status: 'ok',
  providers: [
    { provider: 'openai', configured: true, healthy: true, reason: '' },
    { provider: 'anthropic', configured: true, healthy: true, reason: '' },
  ],
  checks: { model_registry_synced: true, circuit_breaker_open: false, kill_switch: false },
};

const DEGRADED_HEALTH: HealthResponse = {
  status: 'degraded',
  providers: [
    { provider: 'openai', configured: true, healthy: true, reason: '' },
    { provider: 'anthropic', configured: true, healthy: false, reason: 'rate limit exceeded' },
  ],
  checks: { model_registry_synced: true, circuit_breaker_open: false, kill_switch: false },
};

const UNHEALTHY_HEALTH: HealthResponse = {
  status: 'unhealthy',
  providers: [{ provider: 'anthropic', configured: false, healthy: false, reason: 'not configured' }],
  checks: { model_registry_synced: false, circuit_breaker_open: true },
};

const CREDENTIAL_HEALTH: HealthResponse = {
  status: 'degraded',
  providers: [
    { provider: 'openai', configured: true, healthy: false, reason: 'sk-abc123 configured but unhealthy' },
    { provider: 'anthropic', configured: true, healthy: false, reason: 'AKIA1234567890ABCD rejected' },
    { provider: 'x402', configured: false, healthy: false, reason: 'Bearer token missing' },
    {
      provider: 'jwt-provider',
      configured: false,
      healthy: false,
      reason: 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature invalid',
    },
  ],
  checks: {},
};

function resolve(health: HealthResponse) {
  return vi.fn(async () => health);
}

describe('ModelRuntimeHealthPage', () => {
  it('renders an ok status banner', async () => {
    render(<ModelRuntimeHealthPage api={{ fetchHealth: resolve(OK_HEALTH) }} />);
    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Overall status ok' })).toBeInTheDocument(),
    );
    expect(screen.getByText('Model Runtime Health')).toBeInTheDocument();
    expect(screen.getByText('Provider health')).toBeInTheDocument();
    expect(screen.getByText('Extra checks')).toBeInTheDocument();
  });

  it('renders a degraded status banner', async () => {
    render(<ModelRuntimeHealthPage api={{ fetchHealth: resolve(DEGRADED_HEALTH) }} />);
    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Overall status degraded' })).toBeInTheDocument(),
    );
  });

  it('renders an unhealthy status banner', async () => {
    render(<ModelRuntimeHealthPage api={{ fetchHealth: resolve(UNHEALTHY_HEALTH) }} />);
    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Overall status unhealthy' })).toBeInTheDocument(),
    );
  });

  it('renders per-provider rows with configured/healthy/reason', async () => {
    render(<ModelRuntimeHealthPage api={{ fetchHealth: resolve(DEGRADED_HEALTH) }} />);
    await waitFor(() => expect(screen.getByText('openai')).toBeInTheDocument());

    expect(screen.getByText('anthropic')).toBeInTheDocument();
    expect(screen.getByText('rate limit exceeded')).toBeInTheDocument();
    expect(screen.getAllByText('Yes').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('No')).toBeInTheDocument();

    expect(screen.getByText('Provider')).toBeInTheDocument();
    expect(screen.getByText('Configured')).toBeInTheDocument();
    expect(screen.getByText('Healthy')).toBeInTheDocument();
    expect(screen.getByText('Reason')).toBeInTheDocument();
  });

  it('renders extra checks with Pass/Fail booleans', async () => {
    render(<ModelRuntimeHealthPage api={{ fetchHealth: resolve(DEGRADED_HEALTH) }} />);
    await waitFor(() => expect(screen.getByText('model_registry_synced')).toBeInTheDocument());

    expect(screen.getByText('circuit_breaker_open')).toBeInTheDocument();
    expect(screen.getByText('kill_switch')).toBeInTheDocument();
    expect(screen.getAllByText('Pass')).toHaveLength(1);
    expect(screen.getAllByText('Fail')).toHaveLength(2);
  });

  it('shows a loading region while the fetch is in flight', async () => {
    let resolveHealth!: (value: HealthResponse) => void;
    const pending = new Promise<HealthResponse>((res) => {
      resolveHealth = res;
    });
    const fetchHealth = vi.fn(() => pending);

    render(<ModelRuntimeHealthPage api={{ fetchHealth }} />);

    expect(screen.getByRole('status', { name: 'Loading health' })).toBeInTheDocument();

    resolveHealth(OK_HEALTH);
    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Overall status ok' })).toBeInTheDocument(),
    );
    expect(fetchHealth).toHaveBeenCalledTimes(1);
  });

  it('shows an error and retries by re-calling the injected api', async () => {
    const fetchHealth = vi
      .fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(OK_HEALTH);

    render(<ModelRuntimeHealthPage api={{ fetchHealth }} />);

    await screen.findByText('Unable to load health');
    expect(screen.getByText(/boom/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Overall status ok' })).toBeInTheDocument(),
    );
    expect(fetchHealth).toHaveBeenCalledTimes(2);
  });

  it('never renders credential material from reason strings', async () => {
    render(<ModelRuntimeHealthPage api={{ fetchHealth: resolve(CREDENTIAL_HEALTH) }} />);
    await waitFor(() => expect(screen.getByText('openai')).toBeInTheDocument());

    const bodyText = document.body.textContent ?? '';
    expect(bodyText).not.toContain('sk-');
    expect(bodyText).not.toContain('pk_');
    expect(bodyText).not.toContain('rk_live_');
    expect(bodyText).not.toContain('whsec_');
    expect(bodyText).not.toContain('AKIA');
    expect(bodyText).not.toContain('Bearer');
    expect(bodyText).not.toContain('Authorization:');
    expect(bodyText).not.toContain('X-Api-Key:');
    expect(bodyText).not.toContain('password=');
    expect(bodyText).not.toContain('secret=');
    expect(bodyText).not.toContain('key=');
    expect(bodyText).not.toContain('eyJ');
    expect(bodyText).not.toContain('sk-abc123');
    expect(bodyText).not.toContain('AKIA1234567890ABCD');
    expect(bodyText).not.toContain('eyJhbGci');
    expect(screen.getAllByText('Details unavailable.')).toHaveLength(4);
  });
});
