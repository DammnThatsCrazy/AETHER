import { describe, expect, it, vi } from 'vitest';
import { matchRoutes } from 'react-router-dom';
import { ROUTES } from '@site/app/routes';
import { prerenderPages, redirectStubs } from './pages';

describe('prerendered pages', () => {
  it.each(['aether', 'olympus'] as const)('lists each %s page once, on a real route, with search metadata', (site) => {
    const pages = prerenderPages(site);
    expect(new Set(pages.map((p) => p.path)).size).toBe(pages.length);
    for (const page of pages) {
      const matched = matchRoutes(ROUTES[site], page.path);
      expect(matched?.at(-1)?.route.path, page.path).not.toBe('*');
      expect(page.title.length, page.path).toBeGreaterThan(3);
      expect(page.description.length, page.path).toBeGreaterThan(20);
      expect(page.image, page.path).toMatch(/\.png$/);
    }
  });

  it('covers every docs page and each site’s own pages', () => {
    const aether = prerenderPages('aether').map((p) => p.path);
    expect(aether).toEqual(expect.arrayContaining(['/', '/platform/graph', '/trust/privacy', '/connect/sdks', '/docs/connector-catalog', '/docs/glossary', '/pricing']));
    expect(prerenderPages('olympus').map((p) => p.path)).toEqual(expect.arrayContaining(['/', '/technology', '/stories', '/legal/terms']));
  });

  it('keeps /status out of the sitemap of a pilot-only build', () => {
    vi.stubEnv('VITE_PILOT_ONLY', 'true');
    expect(prerenderPages('aether').find((p) => p.path === '/status')?.index).toBe(false);
    vi.stubEnv('VITE_PILOT_ONLY', '');
    expect(prerenderPages('aether').find((p) => p.path === '/status')?.index).toBe(true);
  });

  it('turns retired Aether URLs into redirect pages that do not shadow real pages', () => {
    const stubs = redirectStubs('aether');
    const pages = new Set(prerenderPages('aether').map((p) => p.path));
    expect(stubs.find((s) => s.path === '/integrations')?.to).toBe('/connect');
    expect(stubs.find((s) => s.path === '/company')).toMatchObject({ olympus: true });
    for (const s of stubs) expect(pages.has(s.path), s.path).toBe(false);
    expect(redirectStubs('olympus')).toEqual([]);
  });
});
