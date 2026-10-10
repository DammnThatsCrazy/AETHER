import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ThemeProvider } from '@aether/ui';
import {
  EntitlementBadge,
  GENERIC_ENTITLEMENT_REASON,
  sanitizeEntitlementReason,
} from '@aether-app/features/model-selection/EntitlementBadge';

function renderBadge(props: {
  modelId?: string;
  entitled?: boolean;
  reason?: string | null;
}) {
  return render(
    <ThemeProvider>
      <EntitlementBadge
        modelId={props.modelId ?? 'claude-sonnet-5'}
        entitled={props.entitled ?? true}
        reason={props.reason ?? null}
      />
    </ThemeProvider>,
  );
}

describe('EntitlementBadge (ADR-008 D4)', () => {
  it('renders "Entitled" when the model is entitled', () => {
    renderBadge({ entitled: true });
    expect(screen.getByText('Entitled')).toBeInTheDocument();
    expect(screen.queryByText('Not entitled')).not.toBeInTheDocument();
  }, 15_000);

  it('renders "Not entitled" when the model is not entitled', () => {
    renderBadge({ entitled: false });
    expect(screen.getByText('Not entitled')).toBeInTheDocument();
    expect(screen.queryByText('Entitled')).not.toBeInTheDocument();
  }, 15_000);

  it('shows the reason when provided and the model is not entitled', () => {
    renderBadge({ entitled: false, reason: 'Routing policy denies this model' });
    expect(screen.getByTestId('entitlement-reason')).toHaveTextContent(
      'Routing policy denies this model',
    );
  }, 15_000);

  it('never renders a secret-shaped reason (falls back to generic)', () => {
    renderBadge({ entitled: false, reason: 'sk-abc123xyz' });
    expect(screen.getByTestId('entitlement-reason')).toHaveTextContent(
      GENERIC_ENTITLEMENT_REASON,
    );
    expect(screen.queryByText(/sk-/)).not.toBeInTheDocument();
    expect(screen.queryByText(/abc123/)).not.toBeInTheDocument();
  }, 15_000);

  it('renders the generic reason when no reason is provided and not entitled', () => {
    renderBadge({ entitled: false, reason: null });
    expect(screen.getByTestId('entitlement-reason')).toHaveTextContent(
      GENERIC_ENTITLEMENT_REASON,
    );
  }, 15_000);

  it('exposes the badge with role=status and data attributes', () => {
    renderBadge({ modelId: 'gpt-4o-mini', entitled: false });
    const badge = screen.getByTestId('entitlement-badge');
    expect(badge).toHaveAttribute('role', 'status');
    expect(badge).toHaveAttribute('data-model-id', 'gpt-4o-mini');
    expect(badge).toHaveAttribute('data-entitled', 'false');
  }, 15_000);

  it('does not show a reason for an entitled model even when one is passed', () => {
    renderBadge({ entitled: true, reason: 'sk-ignored' });
    expect(screen.getByText('Entitled')).toBeInTheDocument();
    expect(screen.queryByTestId('entitlement-reason')).not.toBeInTheDocument();
  }, 15_000);

  describe('sanitizeEntitlementReason', () => {
    it('returns the generic fallback for empty, null, or whitespace reasons', () => {
      expect(sanitizeEntitlementReason(null)).toBe(GENERIC_ENTITLEMENT_REASON);
      expect(sanitizeEntitlementReason(undefined)).toBe(
        GENERIC_ENTITLEMENT_REASON,
      );
      expect(sanitizeEntitlementReason('   ')).toBe(GENERIC_ENTITLEMENT_REASON);
    }, 15_000);

    it('redacts credential-shaped reasons', () => {
      expect(sanitizeEntitlementReason('key=super-secret-value')).toBe(
        GENERIC_ENTITLEMENT_REASON,
      );
      expect(sanitizeEntitlementReason('Bearer eyJhbGciOiJIUzI1NiJ9.abc.def')).toBe(
        GENERIC_ENTITLEMENT_REASON,
      );
      expect(sanitizeEntitlementReason('AKIAIOSFODNN7EXAMPLE')).toBe(
        GENERIC_ENTITLEMENT_REASON,
      );
    }, 15_000);

    it('passes through a benign reason unchanged', () => {
      expect(sanitizeEntitlementReason('Policy requires an explicit model')).toBe(
        'Policy requires an explicit model',
      );
    }, 15_000);
  });
});
