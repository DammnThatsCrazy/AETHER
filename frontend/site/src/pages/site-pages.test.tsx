import { readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { App } from '@site/app/app';
import { PAGE_META } from '@site/design/page-meta';
import type { SiteId } from '@site/site/site';
import { CONNECT_CONNECTORS } from '@site/pages/aether/aether-connect';

vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

let landedAt = '';
function Probe() {
  const location = useLocation();
  landedAt = `${location.pathname}${location.search}`;
  return null;
}

function renderAt(site: SiteId, path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App site={site} />
      <Probe />
    </MemoryRouter>,
  );
}

const PAGES: Array<[SiteId, string, keyof typeof PAGE_META]> = [
  ['aether', '/', 'aether-home'],
  ['aether', '/platform', 'aether-platform'],
  ['aether', '/how-it-works', 'aether-how-it-works'],
  ['aether', '/applications', 'aether-applications'],
  ['aether', '/applications/customer-intelligence', 'aether-customer-intelligence'],
  ['aether', '/platform/lenses', 'aether-lenses'],
  ['aether', '/platform/agents', 'aether-agents'],
  ['aether', '/connect', 'aether-connect'],
  ['aether', '/trust', 'aether-trust'],
  ['aether', '/security', 'aether-security'],
  ['aether', '/procurement', 'aether-procurement'],
  ['aether', '/pricing', 'aether-pricing'],
  ['aether', '/docs/glossary', 'glossary'],
  ['aether', '/docs/symbol-key', 'symbol-key'],
  ['olympus', '/', 'olympus-home'],
  ['olympus', '/technology', 'olympus-technology'],
  ['olympus', '/applications', 'olympus-applications'],
  ['olympus', '/company', 'olympus-company'],
  ['olympus', '/principles', 'olympus-principles'],
  ['olympus', '/research', 'olympus-research'],
  ['olympus', '/stories', 'olympus-stories'],
];

describe.each(PAGES)('%s %s', (site, path, slug) => {
  it('renders its design page with the design title', () => {
    renderAt(site, path);
    expect(document.title).toBe(PAGE_META[slug].title);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('main')).toBeTruthy();
    expect(screen.getByRole('contentinfo')).toBeTruthy();
  });
});

describe('templated Aether pages', () => {
  it('names each platform feature page and sends unknown features to the platform overview', () => {
    const { unmount } = renderAt('aether', '/platform/graph');
    expect(document.title).toBe('Graph — Aether');
    unmount();
    renderAt('aether', '/platform/not-a-feature');
    expect(landedAt).toBe('/platform');
  });

  it('serves trust topics under /trust and connection topics under /connect', () => {
    const { unmount } = renderAt('aether', '/trust/privacy');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('What happens to people’s data?');
    expect(document.title).toBe('Privacy — Aether');
    unmount();
    const second = renderAt('aether', '/connect/sdks');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('How do I connect my website or app?');
    second.unmount();
    renderAt('aether', '/trust/sdks');
    expect(landedAt).toBe('/trust');
  });
});

describe('provider logos', () => {
  const brandDir = resolve(__dirname, '../../../../packages/brand/src/identity/marks/providers');
  const files = new Set(readdirSync(brandDir));

  it('shows all 21 integrations on Connect, each a reviewed local mark', () => {
    expect(CONNECT_CONNECTORS).toHaveLength(21);
    renderAt('aether', '/connect');
    const srcs = [...document.querySelectorAll('#connectors img')].map((i) => i.getAttribute('src') ?? '');
    expect(srcs).toHaveLength(21);
    for (const src of srcs) {
      expect(src).toMatch(/^\/providers\/[a-z0-9-]+\.svg$/);
      expect(files.has(src.replace('/providers/', '')), src).toBe(true);
    }
  });

  it('counts every integration on the home page', () => {
    renderAt('aether', '/');
    expect(screen.getByText('ready-made integrations').previousElementSibling?.textContent).toBe('21');
  });
});

describe('Pricing', () => {
  it('sends plan choices to sign-up with the chosen interval', async () => {
    renderAt('aether', '/pricing');
    const beta = () => screen.getByRole('link', { name: 'Choose Beta' });
    expect(beta().getAttribute('href')).toBe('/app/signup?plan=beta&interval=monthly');
    const toggle = screen.queryByRole('radio', { name: 'Annual' });
    if (toggle) {
      await userEvent.click(toggle);
      expect(beta().getAttribute('href')).toBe('/app/signup?plan=beta&interval=annual');
    }
    expect(screen.getByRole('link', { name: /Talk through scope/ }).getAttribute('href')).toBe('/contact?type=product&plan=epsilon');
  });
});

describe('Olympus interactions', () => {
  it('opens one research area at a time', async () => {
    renderAt('olympus', '/research');
    const buttons = () => within(screen.getByRole('main')).getAllByRole('button');
    const open = () => buttons().filter((b) => b.getAttribute('aria-expanded') === 'true');
    expect(open()).toHaveLength(1);
    const closed = buttons().find((b) => b.getAttribute('aria-expanded') === 'false')!;
    await userEvent.click(closed);
    expect(open()).toEqual([closed]);
  });

  it('switches application areas from the tabs', async () => {
    renderAt('olympus', '/applications');
    const tabs = screen.getAllByRole('tab');
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    await userEvent.click(tabs[1]!);
    expect(tabs[1]).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('link', { name: /See agent tracking/ }).getAttribute('href')).toBe(
      'https://aether.olympuslabsml.com/platform/agents',
    );
  });

  it('links Olympus pages to Aether with absolute URLs', () => {
    renderAt('olympus', '/');
    const main = screen.getByRole('main');
    expect(within(main).getAllByRole('link').some((a) => a.getAttribute('href') === 'https://aether.olympuslabsml.com/')).toBe(true);
  });
});
