import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import {
  APP_SIGNUP_PATH,
  AETHER_APP_URL,
  buildAppHandoffUrl,
} from '@aether-marketing/lib/handoff';
import { SignupPage } from '@aether-marketing/pages/auth/signup-page';

function renderSignupPage(navigate: (url: string) => void = () => {}) {
  return render(
    <MemoryRouter initialEntries={['/signup']}>
      <SignupPage navigate={navigate} />
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

describe('SignupPage', () => {
  it('renders the sign-up form', () => {
    renderSignupPage();

    expect(screen.getByRole('heading', { name: 'Create a workspace' })).toBeInTheDocument();
    expect(screen.getByLabelText('Your name')).toBeInTheDocument();
    expect(screen.getByLabelText('Work email')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue to sign-up' })).toBeInTheDocument();
  });

  it('requires a name before handing off', () => {
    const navigate = vi.fn();
    renderSignupPage(navigate);

    fireEvent.change(screen.getByLabelText('Work email'), {
      target: { value: 'ada@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue to sign-up' }));

    const name = screen.getByLabelText('Your name');
    expect(name).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Enter your name to get started.')).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('blocks an invalid email with an accessible inline error', () => {
    const navigate = vi.fn();
    renderSignupPage(navigate);

    fireEvent.change(screen.getByLabelText('Your name'), {
      target: { value: 'Ada Lovelace' },
    });
    fireEvent.change(screen.getByLabelText('Work email'), {
      target: { value: 'not-an-email' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue to sign-up' }));

    const email = screen.getByLabelText('Work email');
    expect(email).toHaveAttribute('aria-invalid', 'true');
    const message = screen.getByText('Enter a valid work email address.');
    expect(message).toBeInTheDocument();
    expect(email).toHaveAttribute('aria-describedby', 'email-error');
    expect(message.id).toBe('email-error');
    expect(navigate).not.toHaveBeenCalled();
  });

  it('navigates to the app sign-up handoff on a valid submit', () => {
    const navigate = vi.fn();
    renderSignupPage(navigate);

    fireEvent.change(screen.getByLabelText('Your name'), {
      target: { value: 'Ada Lovelace' },
    });
    fireEvent.change(screen.getByLabelText('Work email'), {
      target: { value: 'ada@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue to sign-up' }));

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith(
      buildAppHandoffUrl(APP_SIGNUP_PATH, { name: 'Ada Lovelace', email: 'ada@example.com' }),
    );
  });

  it('links to the internal sign-in route', () => {
    renderSignupPage();

    expect(screen.getByRole('link', { name: 'Already have an account? Sign in' })).toHaveAttribute(
      'href',
      '/login',
    );
  });

  it('renders no element pointing at the application origin as a link', () => {
    renderSignupPage();
    expectNoApplicationOriginLink();
  });
});
