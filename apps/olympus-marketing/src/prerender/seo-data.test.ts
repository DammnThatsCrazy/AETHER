import { describe, expect, it } from 'vitest';
import { SECTIONS } from '../content/sections';
import { getLaunchPackPage, launchPackRoutes } from '../../../marketing/src/content-loader';
import seoData from '../../seo-data.json';

/**
 * Keeps the prerender manifest (seo-data.json) in bijective parity with the
 * editorial section copy that actually renders each route. The title suffix here
 * must equal the composite document title the section page renders
 * (`src/pages/section-page.tsx` uses `\`${section.title} — Olympus Labs\``).
 */
const SUFFIX = 'Olympus Labs';

interface SeoRoute {
  readonly path: string;
  readonly title: string;
  readonly description: string;
}

interface SeoData {
  readonly host: string;
  readonly robotsDisallow: string[];
  readonly routes: SeoRoute[];
}

const SEO = seoData as unknown as SeoData;

describe('seo-data.json parity with the content model', () => {
  it('hosts an absolute origin with no trailing slash', () => {
    expect(SEO.host.startsWith('https://')).toBe(true);
    expect(SEO.host.endsWith('/')).toBe(false);
  });

  it('carries every rendered section and launch-pack route exactly once', () => {
    const expectedPaths = new Set(
      [...SECTIONS.map((section) => section.slug), ...launchPackRoutes('Olympus Labs')].filter(
        (path) => path !== '/',
      ),
    );
    const routePaths = SEO.routes.map((route) => route.path);
    expect(SEO.routes).toHaveLength(expectedPaths.size);
    expect(new Set(routePaths)).toEqual(expectedPaths);
  });

  it('matches each legacy or launch-pack route head to the exact copy it renders', () => {
    for (const section of SECTIONS) {
      const route = SEO.routes.find((candidate) => candidate.path === section.slug);
      expect(route, `no seo-data route for ${section.slug}`).toBeDefined();
      if (route === undefined) continue;
      const packRoute = section.slug === '/products/aether' ? '/aether' : section.slug;
      const packPage = getLaunchPackPage('Olympus Labs', packRoute);
      expect(route.title).toBe(packPage?.seoTitle ?? `${section.title} — ${SUFFIX}`);
      expect(route.description).toBe(packPage?.seoDescription ?? section.description);
    }
  });

  it('excludes the home route and any robots-disallowed (auth) route from prerendering', () => {
    for (const route of SEO.routes) {
      expect(route.path).not.toBe('/');
      expect(SEO.robotsDisallow).not.toContain(route.path);
    }
  });
});
