import { describe, expect, it } from 'vitest';
import { CAPABILITIES } from '../content/capabilities';
import { SECTIONS } from '../content/sections';
import { SOLUTIONS } from '../content/solutions';
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

  it('carries exactly one route per top-level section and per capability and solution deep page', () => {
    const topLevelPaths = SECTIONS.map((section) => section.slug);
    const capabilityPaths = CAPABILITIES.map((capability) => `/platform/${capability.slug}`);
    const solutionPaths = SOLUTIONS.map((solution) => `/solutions/${solution.slug}`);
    const expectedPaths = [...topLevelPaths, ...capabilityPaths, ...solutionPaths];
    // 8 top-level sections + 11 capability deep pages + 8 solution deep pages.
    const expectedLength = SECTIONS.length + CAPABILITIES.length + SOLUTIONS.length;
    expect(expectedLength).toBe(27);

    expect(SEO.routes).toHaveLength(expectedLength);
    const routePaths = SEO.routes.map((route) => route.path);
    expect(new Set(routePaths).size).toBe(expectedLength);
    // The manifest path set equals the union of the three content collections —
    // every rendered content page is present and nothing extraneous is listed.
    expect(new Set(routePaths)).toEqual(new Set(expectedPaths));
  });

  it('matches each route head to the exact title and description its content renders', () => {
    for (const section of SECTIONS) {
      const route = routeFor(section.slug);
      expect(route, `no seo-data route for ${section.slug}`).toBeDefined();
      if (route === undefined) continue;
      expect(route.title).toBe(`${section.title} — ${SUFFIX}`);
      expect(route.description).toBe(section.description);
    }

    for (const capability of CAPABILITIES) {
      const path = `/platform/${capability.slug}`;
      const route = routeFor(path);
      expect(route, `no seo-data route for ${path}`).toBeDefined();
      if (route === undefined) continue;
      expect(route.title).toBe(`${capability.title} — ${SUFFIX}`);
      expect(route.description).toBe(capability.description);
    }

    for (const solution of SOLUTIONS) {
      const path = `/solutions/${solution.slug}`;
      const route = routeFor(path);
      expect(route, `no seo-data route for ${path}`).toBeDefined();
      if (route === undefined) continue;
      expect(route.title).toBe(`${solution.title} — ${SUFFIX}`);
      expect(route.description).toBe(solution.description);
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
