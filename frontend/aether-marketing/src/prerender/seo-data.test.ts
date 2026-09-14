import { describe, expect, it } from 'vitest';
import { CAPABILITIES } from '../content/capabilities';
import { SECTIONS } from '../content/sections';
import { SOLUTIONS } from '../content/solutions';
import { getLaunchPackPage, launchPackRoutes } from '../../../marketing/src/content-loader';
import seoData from '../../seo-data.json';

/**
 * Keeps the prerender manifest (seo-data.json) in bijective parity with the
 * editorial copy that actually renders each route: every top-level section AND
 * every capability/solution deep page carries exactly one manifest route, and
 * nothing else does. The title suffix here must equal the composite document
 * title each page renders (`src/pages/section-page.tsx`,
 * `src/pages/capability-page.tsx`, and `src/pages/solution-page.tsx` all use
 * `` `…title — Aether by Olympus Labs` ``).
 */
const SUFFIX = 'Aether by Olympus Labs';

/** Authentication threshold routes are noindex hand-offs, never prerendered. */
const AUTH_ROUTES = ['/login', '/signup', '/forgot-password'];

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

/** Locate the manifest route for one rendered content page path. */
function routeFor(path: string): SeoRoute | undefined {
  return SEO.routes.find((candidate) => candidate.path === path);
}

describe('seo-data.json parity with the content model', () => {
  it('hosts an absolute origin with no trailing slash', () => {
    expect(SEO.host.startsWith('https://')).toBe(true);
    expect(SEO.host.endsWith('/')).toBe(false);
  });

  it('carries every rendered legacy and launch-pack route exactly once', () => {
    const topLevelPaths = SECTIONS.map((section) => section.slug);
    const capabilityPaths = CAPABILITIES.map((capability) => `/platform/${capability.slug}`);
    const solutionPaths = SOLUTIONS.map((solution) => `/solutions/${solution.slug}`);
    const expectedPaths = new Set(
      [...topLevelPaths, ...capabilityPaths, ...solutionPaths, ...launchPackRoutes('Aether')].filter(
        (path) => path !== '/',
      ),
    );

    expect(SEO.routes).toHaveLength(expectedPaths.size);
    const routePaths = SEO.routes.map((route) => route.path);
    expect(new Set(routePaths)).toEqual(expectedPaths);
  });

  it('matches each legacy or launch-pack route head to the exact copy it renders', () => {
    for (const section of SECTIONS) {
      const route = routeFor(section.slug);
      expect(route, `no seo-data route for ${section.slug}`).toBeDefined();
      if (route === undefined) continue;
      const packRoute = section.slug === '/platform' ? '/product' : section.slug;
      const packPage = getLaunchPackPage('Aether', packRoute);
      expect(route.title).toBe(packPage?.seoTitle ?? `${section.title} — ${SUFFIX}`);
      expect(route.description).toBe(packPage?.seoDescription ?? section.description);
    }

    for (const capability of CAPABILITIES) {
      const path = `/platform/${capability.slug}`;
      const route = routeFor(path);
      expect(route, `no seo-data route for ${path}`).toBeDefined();
      if (route === undefined) continue;
      const packPage = getLaunchPackPage('Aether', path);
      expect(route.title).toBe(packPage?.seoTitle ?? `${capability.title} — ${SUFFIX}`);
      expect(route.description).toBe(packPage?.seoDescription ?? capability.description);
    }

    for (const solution of SOLUTIONS) {
      const path = `/solutions/${solution.slug}`;
      const route = routeFor(path);
      expect(route, `no seo-data route for ${path}`).toBeDefined();
      if (route === undefined) continue;
      const packPage = getLaunchPackPage('Aether', path);
      expect(route.title).toBe(packPage?.seoTitle ?? `${solution.title} — ${SUFFIX}`);
      expect(route.description).toBe(packPage?.seoDescription ?? solution.description);
    }
  });

  it('excludes the home route and every auth threshold route from prerendering', () => {
    expect(SEO.robotsDisallow).toEqual(AUTH_ROUTES);
    for (const route of SEO.routes) {
      expect(route.path).not.toBe('/');
      expect(AUTH_ROUTES).not.toContain(route.path);
      expect(SEO.robotsDisallow).not.toContain(route.path);
    }
  });
});
