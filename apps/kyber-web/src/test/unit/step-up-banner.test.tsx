import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ bound: false, supported: true }));
const stepUp = vi.fn();

vi.mock('@kyber/features/auth/hooks', () => ({
  useKyberStepUp: () => ({ isRequired: true, isSteppedUp: false, isSupported: state.supported, state: 'idle', error: null, stepUp }),
  useKyberDevice: () => ({ isBound: state.bound, isApproved: state.bound, isPendingApproval: false, isRevoked: false }),
  useKyberSession: () => ({ isRestricted: false, isRevoked: false, isExpired: false, isLocked: false }),
  useKyberScope: () => ({ scope: null, isActive: false, msRemaining: 0, isExpiring: false }),
  formatCountdown: () => '',
}));

import { StepUpRequiredBanner } from '@kyber/features/auth/session-banners';

describe('StepUpRequiredBanner', () => {
  beforeEach(() => { stepUp.mockReset(); state.bound = false; state.supported = true; });

  it('sends an identity-approved operator to Google to re-verify', () => {
    const assign = vi.fn();
    Object.defineProperty(window, 'location', { value: { ...window.location, assign, pathname: '/tenants', search: '?q=1' }, writable: true });
    render(<StepUpRequiredBanner />);
    fireEvent.click(screen.getByRole('button', { name: 'Re-verify with Google' }));
    expect(assign).toHaveBeenCalledWith(expect.stringMatching(/\/v1\/kyber\/auth\/step-up\?next=%2Ftenants%3Fq%3D1$/));
    expect(stepUp).not.toHaveBeenCalled();
  });

  it('keeps the authenticator path for a device-bound session', () => {
    state.bound = true;
    render(<StepUpRequiredBanner />);
    fireEvent.click(screen.getByRole('button', { name: 'Verify now' }));
    expect(stepUp).toHaveBeenCalled();
  });
});
