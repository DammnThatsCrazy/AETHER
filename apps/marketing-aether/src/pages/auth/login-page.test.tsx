import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AETHER_APP_URL } from '@aether-marketing/lib/handoff';
import { LoginPage } from '@aether-marketing/pages/auth/login-page';

function renderLoginPage(navigate: (url: string) => void = () => {}) {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <LoginPage navigate={navigate} />
    </MemoryRouter>,
  );
}

function expectNoApplicationOriginLink(): void {
  const origin = AETHER_APP_URL.replace(/\/$/, '');
  for (const link of screen.getAllByRole('link')) {
    expect(link.getAttribute('href') ?? '').not.toContain(`${origin}/`);
  }
}

describe('LoginPage', () => {
  it('renders the coming-soon sign-in page', () => {
    renderLoginPage();

    expect(screen.getByRole('heading', { name: 'Sign in to your workspace' })).toBeInTheDocument();
    expect(screen.getByText('Coming soon')).toBeInTheDocument();
  });

  it('links to the waitlist signup', () => {
    renderLoginPage();

    const links = screen.getAllByRole('link', { name: 'Join the waitlist' });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(link).toHaveAttribute('href', '/signup');
    }
  });

  it('renders no element pointing at the application origin as a link', () => {
    renderLoginPage();
    expectNoApplicationOriginLink();
  });
});
