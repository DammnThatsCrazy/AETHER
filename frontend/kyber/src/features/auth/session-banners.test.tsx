import { screen, waitFor, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { KyberSessionBanners } from './session-banners';
import {
  makePrincipal,
  makeScope,
  makeSession,
  renderWithAuth,
} from '@kyber/test/kyber-auth-doubles';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('session banners', () => {
  it('renders the restricted banner when the device is pending approval', async () => {
    renderWithAuth(<KyberSessionBanners />, {
      principal: makePrincipal({ session_status: 'restricted', device_approval_state: 'pending' }),
      session: makeSession({ status: 'restricted', device_approval_state: 'pending' }),
    });
    const banner = await screen.findByTestId('banner-restricted-session');
    expect(banner).toHaveTextContent(/awaiting approval/i);
  });

  it('renders the risk-limited banner with the backend risk reasons', async () => {
    renderWithAuth(<KyberSessionBanners />, {
      principal: makePrincipal({ session_status: 'risk_limited' }),
      session: makeSession({ status: 'risk_limited', risk_reasons: ['impossible_travel'] }),
    });
    const banner = await screen.findByTestId('banner-risk-limited');
    expect(banner).toHaveTextContent('impossible_travel');
  });

  it.each(['revoked', 'expired', 'locked'] as const)(
    'renders the terminated banner for a %s session',
    async (status) => {
      renderWithAuth(<KyberSessionBanners />, {
        principal: makePrincipal({ session_status: status }),
        session: makeSession({ status }),
      });
      expect(await screen.findByTestId('banner-session-terminated')).toBeInTheDocument();
    },
  );

  it('renders a dismissible unapproved-device banner on an otherwise active session', async () => {
    renderWithAuth(<KyberSessionBanners />, {
      principal: makePrincipal({ session_status: 'active', device_approval_state: 'pending' }),
      session: makeSession({ device_approval_state: 'pending' }),
    });
    const banner = await screen.findByTestId('banner-unapproved-device');
    expect(banner).toBeInTheDocument();
    act(() => {
      screen.getByLabelText(/Dismiss/i).click();
    });
    await waitFor(() =>
      expect(screen.queryByTestId('banner-unapproved-device')).not.toBeInTheDocument(),
    );
  });

  it('renders the step-up banner when the backend asks for one', async () => {
    renderWithAuth(<KyberSessionBanners />, {
      principal: makePrincipal({ authentication_strength: 'device_bound' }),
      session: makeSession({ step_up_required: true }),
    });
    expect(await screen.findByTestId('banner-step-up-required')).toBeInTheDocument();
  });

  it('renders nothing for a healthy session', async () => {
    const { container } = renderWithAuth(<KyberSessionBanners />);
    await waitFor(() => expect(container.querySelectorAll('[data-session-banner]')).toHaveLength(0));
  });
});

describe('active scope banner', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  it('shows the tenant, purpose and a live countdown', async () => {
    renderWithAuth(<KyberSessionBanners />, {
      principal: makePrincipal({
        active_scope: makeScope({ expires_at: new Date(Date.now() + 65_000).toISOString() }),
      }),
    });

    const banner = await screen.findByTestId('banner-active-scope');
    expect(banner).toHaveTextContent('tenant_acme');
    expect(banner).toHaveTextContent('customer support');

    const countdown = screen.getByTestId('scope-countdown');
    const first = countdown.textContent ?? '';
    expect(first).toMatch(/^\d{2}:\d{2}$/);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(screen.getByTestId('scope-countdown').textContent).not.toBe(first);
  });

  it('clears tenant access once the scope has expired', async () => {
    renderWithAuth(<KyberSessionBanners />, {
      principal: makePrincipal({
        active_scope: makeScope({ expires_at: new Date(Date.now() - 1_000).toISOString() }),
      }),
    });

    await waitFor(() =>
      expect(screen.queryByTestId('banner-active-scope')).not.toBeInTheDocument(),
    );
  });
});
