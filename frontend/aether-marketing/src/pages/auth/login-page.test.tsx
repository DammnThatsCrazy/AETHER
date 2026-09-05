import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import {
  APP_LOGIN_PATH,
  AETHER_APP_URL,
  buildAppHandoffUrl,
} from '@aether-marketing/lib/handoff';
import { LoginPage } from '@aether-marketing/pages/auth/login-page';

function renderLoginPage(navigate: (url: string) => void = () => {}) {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <LoginPage navigate={navigate} />
    </MemoryRouter>,
  );
}

/** The public→private handoff is a submit action, never a visible anchor: the
 * public page must not render a link that points straight at the app. */
function expectNoApplicationOriginLink(): void {
  const origin = AETHER_APP_URL.replace(/\/$/, '');
  for (const link of screen.getAllByRole('link')) {
    expect(link.getAttribute('href') ?? '').not.toContain(`${origin}/`);
  }
}

describe('LoginPage', () => {
  it('renders the sign-in form', () => {
    renderLoginPage();

    expect(screen.getByRole('heading', { name: 'Sign in to your workspace' })).toBeInTheDocument();
    expect(screen.getByLabelText('Work email')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue to sign-in' })).toBeInTheDocument();
  });

  it('treats an empty email as required', () => {
    const navigate = vi.fn();
    renderLoginPage(navigate);

    fireEvent.click(screen.getByRole('button', { name: 'Continue to sign-in' }));

    expect(screen.getByText('Enter your work email to continue.')).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('blocks an invalid email with an accessible inline error', () => {
    renderLoginPage();

    const email = screen.getByLabelText('Work email');
    fireEvent.change(email, { target: { value: 'not-an-email' } });
    fireEvent.click(screen.getByRole('button', { name: 'Continue to sign-in' }));

    expect(email).toHaveAttribute('aria-invalid', 'true');
    const message = screen.getByText('Enter a valid work email address.');
    expect(message).toBeInTheDocument();
    // The error is wired to the control so it is discoverable by assistive tech.
    expect(email).toHaveAttribute('aria-describedby', 'email-error');
    expect(message.id).toBe('email-error');
  });

  it('navigates to the app login handoff on a valid submit', () => {
    const navigate = vi.fn();
    renderLoginPage(navigate);

    fireEvent.change(screen.getByLabelText('Work email'), {
      target: { value: 'ada@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue to sign-in' }));

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith(
      buildAppHandoffUrl(APP_LOGIN_PATH, { email: 'ada@example.com' }),
    );
  });

  it('links to the internal sign-up and recovery routes', () => {
    renderLoginPage();

    expect(screen.getByRole('link', { name: 'Create an account' })).toHaveAttribute(
      'href',
      '/signup',
    );
    expect(screen.getByRole('link', { name: 'Forgot your password?' })).toHaveAttribute(
      'href',
      '/forgot-password',
    );
  });

  it('renders no element pointing at the application origin as a link', () => {
    renderLoginPage();
    expectNoApplicationOriginLink();
  });
});
