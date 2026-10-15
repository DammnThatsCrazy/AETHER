import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import {
  APP_LOGIN_PATH,
  AETHER_APP_URL,
  buildAppHandoffUrl,
} from '@aether-marketing/lib/handoff';
import { ForgotPasswordPage } from '@aether-marketing/pages/auth/forgot-password-page';

function renderForgotPasswordPage(navigate: (url: string) => void = () => {}) {
  return render(
    <MemoryRouter initialEntries={['/forgot-password']}>
      <ForgotPasswordPage navigate={navigate} />
    </MemoryRouter>,
  );
}

/** The public→private handoff is a submit action, never a visible anchor. */
function expectNoApplicationOriginLink(): void {
  const origin = AETHER_APP_URL.replace(/\/$/, '');
  for (const link of screen.getAllByRole('link')) {
    expect(link.getAttribute('href') ?? '').not.toContain(`${origin}/`);
  }
}

describe('ForgotPasswordPage', () => {
  it('renders the recovery form', () => {
    renderForgotPasswordPage();

    expect(screen.getByRole('heading', { name: 'Reset your password' })).toBeInTheDocument();
    expect(screen.getByLabelText('Work email')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue to recovery' })).toBeInTheDocument();
  });

  it('navigates to the app sign-in handoff on a valid submit', () => {
    const navigate = vi.fn();
    renderForgotPasswordPage(navigate);

    fireEvent.change(screen.getByLabelText('Work email'), {
      target: { value: 'ada@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue to recovery' }));

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith(
      buildAppHandoffUrl(APP_LOGIN_PATH, { email: 'ada@example.com' }),
    );
  });

  it('blocks an empty email before handing off', () => {
    const navigate = vi.fn();
    renderForgotPasswordPage(navigate);

    fireEvent.click(screen.getByRole('button', { name: 'Continue to recovery' }));

    expect(screen.getByText('Enter your work email to continue.')).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('states the honest recovery boundary on the page', () => {
    renderForgotPasswordPage();

    expect(
      screen.getByText(/the public site does not send password-reset email/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/recovery is handled inside the Aether application/i)).toBeInTheDocument();
  });

  it('links back to sign-in and the home page', () => {
    renderForgotPasswordPage();

    expect(screen.getByRole('link', { name: 'Return to sign in' })).toHaveAttribute('href', '/login');
    expect(screen.getByRole('link', { name: 'Back to the Aether home page' })).toHaveAttribute(
      'href',
      '/',
    );
  });

  it('renders no element pointing at the application origin as a link', () => {
    renderForgotPasswordPage();
    expectNoApplicationOriginLink();
  });
});
