import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AETHER_APP_URL } from '@aether-marketing/lib/handoff';
import { SignupPage } from '@aether-marketing/pages/auth/signup-page';

function renderSignupPage(navigate: (url: string) => void = () => {}) {
  return render(
    <MemoryRouter initialEntries={['/signup']}>
      <SignupPage navigate={navigate} />
    </MemoryRouter>,
  );
}

function expectNoApplicationOriginLink(): void {
  const origin = AETHER_APP_URL.replace(/\/$/, '');
  for (const link of screen.getAllByRole('link')) {
    expect(link.getAttribute('href') ?? '').not.toContain(`${origin}/`);
  }
}

afterEach(() => {
  try {
    window.localStorage.removeItem('aether.marketing.signup.v1');
  } catch {
    // noop
  }
});

describe('SignupPage', () => {
  it('renders the waitlist form', () => {
    renderSignupPage();

    expect(screen.getByRole('heading', { name: 'Create a workspace' })).toBeInTheDocument();
    expect(screen.getByLabelText('Your name')).toBeInTheDocument();
    expect(screen.getByLabelText('Work email')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Join the waitlist' })).toBeInTheDocument();
  });

  it('requires a name before submitting', () => {
    renderSignupPage();

    fireEvent.change(screen.getByLabelText('Work email'), {
      target: { value: 'ada@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Join the waitlist' }));

    const name = screen.getByLabelText('Your name');
    expect(name).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Enter your name to get started.')).toBeInTheDocument();
  });

  it('blocks an invalid email with an accessible inline error', () => {
    renderSignupPage();

    fireEvent.change(screen.getByLabelText('Your name'), {
      target: { value: 'Ada Lovelace' },
    });
    fireEvent.change(screen.getByLabelText('Work email'), {
      target: { value: 'not-an-email' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Join the waitlist' }));

    const email = screen.getByLabelText('Work email');
    expect(email).toHaveAttribute('aria-invalid', 'true');
    const message = screen.getByText('Enter a valid work email address.');
    expect(message).toBeInTheDocument();
    expect(email).toHaveAttribute('aria-describedby', 'email-error');
    expect(message.id).toBe('email-error');
  });

  it('saves to localStorage and shows confirmation on valid submit', async () => {
    renderSignupPage();

    fireEvent.change(screen.getByLabelText('Your name'), {
      target: { value: 'Ada Lovelace' },
    });
    fireEvent.change(screen.getByLabelText('Work email'), {
      target: { value: 'ada@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Join the waitlist' }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: "We'll be in touch" })).toBeInTheDocument();
    });

    const stored = JSON.parse(window.localStorage.getItem('aether.marketing.signup.v1') ?? '{}');
    expect(stored.name).toBe('Ada Lovelace');
    expect(stored.email).toBe('ada@example.com');
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
