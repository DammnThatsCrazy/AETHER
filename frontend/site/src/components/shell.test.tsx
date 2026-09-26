import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { App } from '@site/app/app';
import type { SiteId } from '@site/site/site';

vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

function renderAt(site: SiteId, path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App site={site} />
    </MemoryRouter>,
  );
}

const hrefOf = (name: string, scope: HTMLElement) =>
  within(scope).getByRole('link', { name }).getAttribute('href');

describe('site header', () => {
  it('shows the Aether navigation with relative links on the Aether site', () => {
    renderAt('aether', '/missing');
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual([
      'About', 'How it works', 'Connections', 'Pricing', 'Developers', 'Security',
    ]);
    expect(hrefOf('Pricing', nav)).toBe('/pricing');
    const header = screen.getByRole('banner');
    expect(hrefOf('Sign in', header)).toBe('/app/signin');
    expect(hrefOf('Request a pilot', header)).toBe('/contact?type=pilot');
    expect(hrefOf('Olympus Labs', header)).toBe('https://olympuslabsml.com/');
  });

  it('links from Olympus to Aether with absolute URLs', () => {
    renderAt('olympus', '/missing');
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(hrefOf('Company', nav)).toBe('/company');
    expect(hrefOf('Aether', nav)).toBe('https://aether.olympuslabsml.com/');
    expect(hrefOf('Explore Aether', screen.getByRole('banner'))).toBe('https://aether.olympuslabsml.com/');
  });

  it('opens and closes the mobile menu', async () => {
    renderAt('aether', '/missing');
    const toggle = screen.getByRole('button', { name: 'Open menu' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle);
    expect(screen.getByRole('navigation', { name: 'Mobile' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Close menu' }));
    expect(screen.queryByRole('navigation', { name: 'Mobile' })).toBeNull();
  });

  it('closes the mobile menu when a same-page fragment link is chosen', async () => {
    renderAt('aether', '/');
    await userEvent.click(screen.getByRole('button', { name: 'Open menu' }));
    const mobile = screen.getByRole('navigation', { name: 'Mobile' });
    const about = within(mobile).getByRole('link', { name: /About/ });
    expect(about.getAttribute('href')).toBe('/#about');
    await userEvent.click(about);
    expect(screen.queryByRole('navigation', { name: 'Mobile' })).toBeNull();
  });
});

describe('page shell', () => {
  it('offers a skip link to a focusable main landmark', () => {
    renderAt('olympus', '/missing');
    const skip = screen.getByRole('link', { name: 'Skip to content' });
    expect(skip.getAttribute('href')).toBe('#main');
    const main = screen.getByRole('main');
    expect(main.id).toBe('main');
    expect(main.getAttribute('tabindex')).toBe('-1');
  });
});

describe('site footer', () => {
  it('points each column at the right site', () => {
    renderAt('aether', '/missing');
    const footer = screen.getByRole('contentinfo');
    expect(hrefOf('Company', within(footer).getByRole('navigation', { name: 'Olympus Labs' }))).toBe(
      'https://olympuslabsml.com/company',
    );
    expect(hrefOf('Documentation', footer)).toBe('/docs');
    expect(hrefOf('contact@olympuslabsml.com', footer)).toBe('mailto:contact@olympuslabsml.com');
  });
});

describe('not found page', () => {
  it('shows the requested path and the site-specific way back', () => {
    renderAt('aether', '/no/such/page');
    expect(screen.getByRole('heading', { level: 1, name: 'This page does not exist' })).toBeInTheDocument();
    expect(screen.getByText('/no/such/page')).toBeInTheDocument();
    const main = screen.getByRole('main');
    expect(hrefOf('Documentation Quickstarts, SDKs, connectors', main)).toBe('/docs');
    expect(document.title).toBe('Page not found');
  });

  it('offers Olympus destinations on the Olympus site', () => {
    renderAt('olympus', '/gone');
    const main = screen.getByRole('main');
    expect(hrefOf('Aether The flagship product', main)).toBe('https://aether.olympuslabsml.com/');
    expect(hrefOf('Research Open questions', main)).toBe('/research');
  });
});

describe('favicon', () => {
  it('uses the mark of the resolved site', () => {
    const link = document.createElement('link');
    link.rel = 'icon';
    link.href = '/favicon-aether.svg';
    document.head.appendChild(link);
    const { unmount } = renderAt('olympus', '/missing');
    expect(link.getAttribute('href')).toBe('/logo-olympus-arch.svg');
    unmount();
    renderAt('aether', '/missing');
    expect(link.getAttribute('href')).toBe('/favicon-aether.svg');
    link.remove();
  });
});
