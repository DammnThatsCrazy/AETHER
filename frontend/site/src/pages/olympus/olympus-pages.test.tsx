import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { App } from '@site/app/app';

vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App site="olympus" />
    </MemoryRouter>,
  );

const PAGES = [
  { path: '/company', title: 'Company — Olympus Labs', h1: /A research and infrastructure company/, nav: 'Company', toc: ['thesis', 'build', 'work', 'focus'] },
  { path: '/principles', title: 'Principles — Olympus Labs', h1: /Five principles/, nav: 'Principles', toc: ['principles', 'loop', 'doctrine', 'limits'] },
  { path: '/research', title: 'Research — Olympus Labs', h1: /Open questions/, nav: 'Research', toc: ['areas', 'gate'] },
  { path: '/stories', title: 'Stories and proof — Olympus Labs', h1: /No customer stories are published yet/, nav: 'Stories', toc: ['standard', 'process'] },
];

describe.each(PAGES)('Olympus $path', ({ path, title, h1, nav, toc }) => {
  it('renders its hero, marks the header link, and links every on-page section', () => {
    renderAt(path);
    expect(document.title).toBe(title);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(h1);
    const primary = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(primary).getByRole('link', { name: nav }).getAttribute('aria-current')).toBe('page');
    const onPage = screen.getByRole('navigation', { name: 'On this page' });
    for (const id of toc) {
      expect(within(onPage).getAllByRole('link').some((a) => a.getAttribute('href') === `#${id}`)).toBe(true);
      expect(document.getElementById(id)).not.toBeNull();
    }
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByRole('link', { name: 'Olympus Labs' }).getAttribute('href')).toBe('/');
  });
});

describe('Olympus page details', () => {
  it('links Company to Aether across sites', () => {
    renderAt('/company');
    const links = screen.getAllByRole('link', { name: /Meet Aether|Explore Aether|Aether/ }).map((a) => a.getAttribute('href'));
    expect(links).toContain('https://aether.olympuslabsml.com/');
  });

  it('lists the five principles in order with what each means for Aether', () => {
    renderAt('/principles');
    const section = document.getElementById('principles')!;
    const items = within(within(section).getByRole('list')).getAllByRole('listitem');
    expect(items.map((li) => li.textContent?.split(/(?=[A-Z][a-z])/)[0])).toEqual(['I', 'II', 'III', 'IV', 'V']);
    expect(items[0]!.textContent).toContain('Aether recommends, identifies, and explains. People decide.');
  });

  it('opens research areas to show their open questions', async () => {
    renderAt('/research');
    const identity = screen.getByText('Identity continuity').closest('details')!;
    expect(identity.open).toBe(false);
    expect(identity.textContent).toContain('2 open questions');
    await userEvent.click(within(identity).getByText('Identity continuity'));
    expect(identity.open).toBe(true);
    expect(within(identity).getByText('How is a join undone when the evidence changes?')).toBeTruthy();
  });

  it('routes calls to action to the contact page with a topic', () => {
    renderAt('/stories');
    const hrefs = screen.getAllByRole('link', { name: /Become a proof partner/ }).map((a) => a.getAttribute('href'));
    expect(hrefs).toEqual(['/contact?type=proof', '/contact?type=proof']);
  });
});
