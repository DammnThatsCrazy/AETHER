import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AppRouter } from '@aether-marketing/app/router';
import { AETHER_DOCS_URL, OLYMPUS_SITE_URL } from '@aether-marketing/lib/env';

describe('Aether marketing shell', () => {
  it('renders the home page inside the persistent shell', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <AppRouter />
      </MemoryRouter>,
    );

    const header = screen.getByRole('banner');
    // Primary product navigation, scoped to the header's Primary nav region.
    const nav = within(header).getByRole('navigation', { name: 'Primary' });
    expect(within(nav).getByRole('link', { name: 'Platform' })).toHaveAttribute('href', '/platform');
    expect(within(nav).getByRole('link', { name: 'Solutions' })).toHaveAttribute('href', '/solutions');
    expect(within(nav).getByRole('link', { name: 'Developers' })).toHaveAttribute('href', '/developers');
    expect(within(nav).getByRole('link', { name: 'Integrations' })).toHaveAttribute('href', '/integrations');
    expect(within(nav).getByRole('link', { name: 'Security' })).toHaveAttribute('href', '/security');
    expect(within(nav).getByRole('link', { name: 'Pricing' })).toHaveAttribute('href', '/pricing');

    // Header utility actions are the public entry into the authentication
    // threshold routes, which live in this shell (the tenant hand-off happens
    // on those pages). Docs stays an external destination.
    expect(within(header).getByRole('link', { name: 'Docs' })).toHaveAttribute('href', AETHER_DOCS_URL);
    expect(within(header).getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
    expect(within(header).getByRole('link', { name: 'Start building' })).toHaveAttribute(
      'href',
      '/signup',
    );

    // Brand hierarchy: Aether product mark with Olympus Labs attribution.
    const attributions = screen.getAllByRole('link', { name: 'Olympus Labs' });
    expect(attributions.length).toBeGreaterThan(0);
    for (const link of attributions) {
      expect(link).toHaveAttribute('href', OLYMPUS_SITE_URL);
    }

    // Editorial home present.
    expect(
      screen.getByRole('heading', { level: 1, name: /one governed graph/i }),
    ).toBeInTheDocument();
  });

  it('renders auth threshold pages under the quiet AuthLayout', () => {
    render(
      <MemoryRouter initialEntries={['/login']}>
        <AppRouter />
      </MemoryRouter>,
    );

    // The login page is a real form now, not an external link out to the app.
    expect(screen.getByRole('heading', { name: /sign in to your workspace/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/work email/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue to sign-in' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Continue to the Aether app' })).not.toBeInTheDocument();

    // AuthLayout keeps the quiet cross-links only.
    expect(screen.getByRole('link', { name: 'Security' })).toHaveAttribute('href', '/security');
    expect(screen.getByRole('link', { name: 'Company' })).toHaveAttribute('href', '/company');
  });
});
