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

const hrefOf = (name: string | RegExp, scope: HTMLElement) =>
  within(scope).getByRole('link', { name }).getAttribute('href');

describe('site header', () => {
  it('shows the Aether navigation with relative links on the Aether site', async () => {
    renderAt('aether', '/missing');
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(nav).getAllByRole('button').map((b) => b.textContent?.replace(/[↓⌄▾]/g, '').trim())).toEqual([
      'Platform', 'Applications', 'Connect', 'Developers',
    ]);
    expect(hrefOf('Pricing', nav)).toBe('/pricing');
    await userEvent.click(within(nav).getByRole('button', { name: /Platform/ }));
    const menu = within(nav).getByRole('menu');
    expect(within(menu).getByRole('menuitem', { name: /Lenses/ }).getAttribute('href')).toBe('/platform/lenses');
    expect(within(menu).getByRole('menuitem', { name: /Profiles/ }).getAttribute('href')).toBe('/platform/profiles');
    const header = screen.getByRole('banner');
    expect(hrefOf('Sign in', header)).toBe('/app/signin');
    expect(hrefOf('Request a pilot', header)).toBe('/contact?type=pilot');
    expect(hrefOf('Get started', header)).toBe('/app/signup');
    expect(hrefOf('Olympus Labs', header)).toBe('https://olympuslabsml.com/');
  });

  it('links from Olympus to Aether with absolute URLs', () => {
    renderAt('olympus', '/missing');
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(hrefOf('Research', nav)).toBe('/research');
    expect(hrefOf('Aether', nav)).toBe('https://aether.olympuslabsml.com/');
    expect(hrefOf('Explore Aether', screen.getByRole('banner'))).toBe('https://aether.olympuslabsml.com/');
    expect(hrefOf('Contact', screen.getByRole('banner'))).toBe('/contact');
  });

  it('opens the mobile menu and closes it when a link is chosen', async () => {
    renderAt('aether', '/');
    const toggle = screen.getByRole('button', { name: 'Open menu' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle);
    const mobile = screen.getByRole('navigation', { name: 'Mobile' });
    const revenue = within(mobile).getByRole('link', { name: 'Revenue intelligence' });
    expect(revenue.getAttribute('href')).toBe('/applications#revenue');
    await userEvent.click(revenue);
    expect(screen.queryByRole('navigation', { name: 'Mobile' })).toBeNull();
  });

  it('offers a skip link to a focusable main landmark', () => {
    renderAt('olympus', '/');
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
    expect(hrefOf('Connect', within(footer).getByRole('navigation', { name: 'Aether' }))).toBe('/connect');
    expect(hrefOf('Documentation', footer)).toBe('/docs');
    expect(hrefOf('Glossary', footer)).toBe('/docs/glossary');
    expect(hrefOf('Privacy and data use', footer)).toBe('/legal/privacy');
    expect(hrefOf('team@olympuslabsml.com', footer)).toBe('mailto:team@olympuslabsml.com');
  });

  it('keeps legal links on the visitor’s site', () => {
    renderAt('olympus', '/missing');
    const footer = screen.getByRole('contentinfo');
    expect(hrefOf('Terms and use', footer)).toBe('/legal/terms');
    expect(hrefOf('Documentation', footer)).toBe('https://aether.olympuslabsml.com/docs');
  });
});

describe('not found page', () => {
  it('shows the requested path and the site-specific way back', () => {
    renderAt('aether', '/no/such/page');
    expect(screen.getByRole('heading', { level: 1, name: 'This page doesn’t exist.' })).toBeInTheDocument();
    expect(screen.getByText('/no/such/page')).toBeInTheDocument();
    const way = screen.getByRole('navigation', { name: 'Go somewhere else' });
    expect(hrefOf(/Documentation/, way)).toBe('/docs');
    expect(hrefOf(/Status/, way)).toBe('/status');
    expect(document.title).toBe('Page not found');
  });

  it('offers Olympus destinations on the Olympus site', () => {
    renderAt('olympus', '/gone');
    const way = screen.getByRole('navigation', { name: 'Go somewhere else' });
    expect(hrefOf(/^Aether/, way)).toBe('https://aether.olympuslabsml.com/');
    expect(hrefOf(/Research/, way)).toBe('/research');
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
