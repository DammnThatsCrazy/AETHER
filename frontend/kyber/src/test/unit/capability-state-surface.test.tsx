import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@kyber/lib/featureFlags', () => ({
  featureFlags: { kyberDerivativesOps: false },
  isFeatureEnabled: () => false,
}));

import { FlagGate, implementationStatusBadge } from '@kyber/components/economic-ops';

/**
 * Representative-surface proof for the operator app: the economic-ops helpers
 * shared by the stablecoin / derivatives / interop ops pages route the backend
 * ImplementationStatus through the canonical capability matrix, and a
 * feature-flag-off surface renders the honest `disabled` state (not a generic
 * empty state).
 */
describe('implementationStatusBadge → capability matrix', () => {
  const cases: Array<[string, string]> = [
    ['provider_live', 'partner_live'],
    ['credential_gated', 'credential_required'],
    ['staging_validation_required', 'sandbox_validated'],
    ['scaffolded', 'not_configured'],
    ['mocked_local', 'not_configured'],
  ];

  it('maps each implementation status to the expected capability state', () => {
    for (const [status, expected] of cases) {
      const { container, getByText } = render(<>{implementationStatusBadge(status)}</>);
      expect(container.querySelector(`[data-capability-state="${expected}"]`)).not.toBeNull();
      // Exact backend token stays visible for the operator.
      expect(getByText(status)).toBeInTheDocument();
    }
  });

  it('gives live vs credential-gated vs mocked distinct treatments', () => {
    const markers = ['provider_live', 'credential_gated', 'mocked_local'].map((s) => {
      const { container } = render(<>{implementationStatusBadge(s)}</>);
      return container.querySelector('[data-capability-state]')?.getAttribute('data-capability-state');
    });
    expect(new Set(markers).size).toBe(3);
  });
});

describe('FlagGate renders the honest disabled capability state', () => {
  it('shows a disabled panel (not a generic empty state) when the flag is off', () => {
    const { container, getByText } = render(
      <FlagGate flag="kyberDerivativesOps" domainLabel="Derivatives Intelligence">
        <div>should-not-render</div>
      </FlagGate>,
    );
    expect(container.querySelector('[data-capability-state="disabled"]')).not.toBeNull();
    expect(getByText(/Derivatives Intelligence ops is disabled/)).toBeInTheDocument();
    expect(container.textContent).not.toContain('should-not-render');
  });
});
