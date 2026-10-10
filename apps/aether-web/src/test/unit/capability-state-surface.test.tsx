import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  ProviderHealthBadge,
  type ProviderHealthStatus,
} from '@aether-app/pages/payment-rails/payment-rails-shared';

/**
 * Representative-surface proof: the payment-rails provider-health badge renders
 * each real server status through the canonical capability matrix, each with a
 * DISTINCT capability-state marker — a not-configured provider can never read
 * as live.
 */
describe('Payment-rails ProviderHealthBadge → capability matrix', () => {
  const cases: Array<[ProviderHealthStatus, string]> = [
    ['healthy', 'partner_live'],
    ['degraded', 'degraded'],
    ['not_configured', 'not_configured'],
    ['error', 'error'],
  ];

  it('maps each provider health status to a distinct capability state', () => {
    const markers = cases.map(([status]) => {
      const { container } = render(<ProviderHealthBadge status={status} />);
      const el = container.querySelector('[data-capability-state]');
      return el?.getAttribute('data-capability-state');
    });
    expect(new Set(markers).size).toBe(cases.length);
  });

  it('renders the expected capability state and keeps the raw label visible', () => {
    for (const [status, expected] of cases) {
      const { container, getByText } = render(<ProviderHealthBadge status={status} />);
      expect(container.querySelector(`[data-capability-state="${expected}"]`)).not.toBeNull();
      // Raw server term stays visible (label with underscores → spaces).
      expect(getByText(status.replace(/_/g, ' '))).toBeInTheDocument();
    }
  });
});
