// @vitest-environment node
import { afterEach, describe, expect, it } from 'vitest';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** Directory of this test file — the workspace `scripts/` folder. */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PRERENDER = path.join(HERE, 'prerender.mjs');
const WORKSPACE_ROOT = path.join(HERE, '..');
const SEO_DATA_PATH = path.join(WORKSPACE_ROOT, 'seo-data.json');

const FIXTURE_INDEX = `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content="FIXTURE_DEFAULT_DESCRIPTION" />
    <title>FIXTURE_DEFAULT_TITLE</title>
    <meta name="robots" content="index,follow" />
    <link rel="canonical" href="https://example.test/" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="Fixture Site" />
    <meta property="og:url" content="https://example.test/" />
    <meta property="og:title" content="FIXTURE_DEFAULT_OG_TITLE" />
    <meta property="og:description" content="FIXTURE_DEFAULT_OG_DESCRIPTION" />
    <meta name="twitter:card" content="summary" />
    <meta name="twitter:title" content="FIXTURE_DEFAULT_TWITTER_TITLE" />
    <meta name="twitter:description" content="FIXTURE_DEFAULT_TWITTER_DESCRIPTION" />
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
`;

const FIXTURE_SEO = {
  host: 'https://example.test',
  robotsDisallow: ['/login', '/admin'],
  routes: [
    {
      path: '/products',
      title: 'Products — Example',
      description: 'A fixture product catalogue page.',
    },
    {
      path: '/products/widget',
      title: 'Widget — Products — Example',
      description: 'A nested fixture product page.',
    },
  ],
};

/** Filesystem helpers, per-test temp sandbox, torn down in afterEach. */
let sandboxRoot;
let distDir;
let seoPath;

function sandbox() {
  sandboxRoot = mkdtempSync(path.join(tmpdir(), 'prerender-'));
  distDir = path.join(sandboxRoot, 'dist');
  seoPath = path.join(sandboxRoot, 'seo-data.json');
  mkdirSync(distDir, { recursive: true });
  writeFileSync(path.join(distDir, 'index.html'), FIXTURE_INDEX, 'utf8');
  writeFileSync(seoPath, JSON.stringify(FIXTURE_SEO, null, 2), 'utf8');
}

function runPrerender() {
  const result = spawnSync(process.execPath, [PRERENDER, seoPath, distDir], {
    encoding: 'utf8',
  });
  if (result.error !== undefined) throw result.error;
  expect(result.status).toBe(0);
  return result.stdout;
}

afterEach(() => {
  if (sandboxRoot !== undefined) {
    rmSync(sandboxRoot, { recursive: true, force: true });
    sandboxRoot = undefined;
  }
});

describe('scripts/prerender.mjs', () => {
  it('writes a per-route shell with a complete head for a nested route', () => {
    sandbox();
    runPrerender();

    const shellPath = path.join(distDir, 'products', 'widget', 'index.html');
    expect(existsSync(shellPath)).toBe(true);
    const html = readFileSync(shellPath, 'utf8');

    expect(html).toContain('<title>Widget — Products — Example</title>');
    expect(html).toContain('content="A nested fixture product page."');
    expect(html).toContain('href="https://example.test/products/widget"');
    expect(html).toContain('content="https://example.test/products/widget"');
    expect(html).toContain('property="og:title" content="Widget — Products — Example"');
    expect(html).toContain('content="A nested fixture product page."');
    expect(html).toContain('name="twitter:title" content="Widget — Products — Example"');
    expect(html).toContain('name="twitter:description" content="A nested fixture product page."');
  });

  it('writes a shell for a top-level route and leaves dist/index.html untouched', () => {
    sandbox();
    runPrerender();

    const shellPath = path.join(distDir, 'products', 'index.html');
    expect(existsSync(shellPath)).toBe(true);
    const html = readFileSync(shellPath, 'utf8');
    expect(html).toContain('<title>Products — Example</title>');
    expect(html).toContain('href="https://example.test/products"');
    expect(html).toContain('content="A fixture product catalogue page."');

    expect(readFileSync(path.join(distDir, 'index.html'), 'utf8')).toBe(FIXTURE_INDEX);
  });

  it('writes robots.txt honouring every disallow entry', () => {
    sandbox();
    runPrerender();

    const robots = readFileSync(path.join(distDir, 'robots.txt'), 'utf8');
    expect(robots).toContain('User-agent: *');
    expect(robots).toContain('Allow: /');
    expect(robots).toContain('Disallow: /login');
    expect(robots).toContain('Disallow: /admin');
  });

  it('writes a well-formed sitemap.xml with the home loc and every route loc', () => {
    sandbox();
    runPrerender();

    const sitemap = readFileSync(path.join(distDir, 'sitemap.xml'), 'utf8');
    expect(sitemap).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(sitemap).toContain('<loc>https://example.test/</loc>');
    expect(sitemap).toContain('<loc>https://example.test/products</loc>');
    expect(sitemap).toContain('<loc>https://example.test/products/widget</loc>');
  });

  it('fails the build (non-zero exit) when the manifest or index.html is missing', () => {
    sandbox();
    const bad = spawnSync(process.execPath, [PRERENDER, path.join(sandboxRoot, 'nope.json'), distDir], {
      encoding: 'utf8',
    });
    expect(bad.status).not.toBe(0);

    const noIndex = spawnSync(process.execPath, [PRERENDER, seoPath, path.join(sandboxRoot, 'empty')], {
      encoding: 'utf8',
    });
    expect(noIndex.status).not.toBe(0);
  });
});

describe('workspace seo-data.json manifest sanity', () => {
  it('declares a route per content section with a complete, "/"-prefixed path', () => {
    const raw = readFileSync(SEO_DATA_PATH, 'utf8');
    const seo = JSON.parse(raw);
    expect(typeof seo.host).toBe('string');
    expect(Array.isArray(seo.routes)).toBe(true);
    expect(seo.routes.length).toBeGreaterThan(0);

    for (const route of seo.routes) {
      expect(route.path.startsWith('/')).toBe(true);
      expect(route.path).not.toBe('/');
      expect(typeof route.title).toBe('string');
      expect(route.title.length).toBeGreaterThan(0);
      expect(typeof route.description).toBe('string');
      expect(route.description.length).toBeGreaterThan(0);
    }
  });

  it('never lists a robots-disallowed (auth) route as a crawlable route', () => {
    const seo = JSON.parse(readFileSync(SEO_DATA_PATH, 'utf8'));
    const routePaths = seo.routes.map((route) => route.path);
    for (const disallowed of seo.robotsDisallow) {
      expect(routePaths).not.toContain(disallowed);
    }
  });
});
