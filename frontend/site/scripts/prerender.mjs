#!/usr/bin/env node
/**
 * Build-time prerender for the site this build serves (VITE_SITE, default
 * aether). After `vite build` (client) and `vite build --ssr src/entry-server.tsx`
 * it writes, into dist/:
 *
 * - one HTML file per page: `/` → index.html, `/platform/graph` →
 *   platform/graph.html (Amplify serves `/x` from `x.html` without a redirect),
 *   each with its rendered markup, title, description, canonical URL, Open
 *   Graph and Twitter cards, JSON-LD, and the page's runtime hover styles;
 * - 404.html (the not-found page, noindex) for the hosting fallback;
 * - redirect pages for retired Aether marketing URLs;
 * - sitemap.xml and robots.txt for the site's canonical origin. Builds whose
 *   origin is not a production origin (staging) are noindex and disallow all.
 */
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const ssrDir = join(root, 'dist-ssr');
const server = await import(pathToFileURL(join(ssrDir, 'entry-server.js')).href);

const site = process.env.VITE_SITE === 'olympus' ? 'olympus' : 'aether';
const origins = server.origins();
const origin = origins[site];
const PRODUCTION_ORIGINS = new Set(['https://aether.olympuslabsml.com', 'https://www.olympuslabsml.com', 'https://olympuslabsml.com']);
const indexable = PRODUCTION_ORIGINS.has(origin);
const SITE_NAME = site === 'olympus' ? 'Olympus Labs' : 'Aether';
const ORG = { '@type': 'Organization', name: 'Olympus Labs', url: origins.olympus, logo: `${origins.olympus}/logo-olympus-arch.svg` };

const template = readFileSync(join(dist, 'index.html'), 'utf8');
if (!template.includes('<div id="root"></div>')) throw new Error('dist/index.html has no empty #root to fill');

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const url = (path) => origin + (path === '/' ? '/' : path);

function jsonLd(page) {
  const base = { '@context': 'https://schema.org' };
  switch (page.jsonLd) {
    case 'website':
      return [{ ...base, '@type': 'WebSite', name: SITE_NAME, url: url('/') }, { ...base, ...ORG }];
    case 'organization':
      return [{ ...base, ...ORG, description: page.description }];
    case 'product':
      return [
        { ...base, '@type': 'WebSite', name: SITE_NAME, url: url('/') },
        { ...base, '@type': 'SoftwareApplication', name: 'Aether', applicationCategory: 'BusinessApplication', operatingSystem: 'Web', url: url('/'), description: page.description, publisher: ORG },
      ];
    case 'article':
      return [{ ...base, '@type': 'TechArticle', headline: page.title, description: page.description, url: url(page.path), publisher: ORG }];
    default:
      return [{ ...base, '@type': 'WebPage', name: page.title, description: page.description, url: url(page.path), publisher: ORG }];
  }
}

// The hosting fallback serves index.html (or 404.html) for paths that were not
// prerendered. This hides that markup until the app renders the real route.
const GUARD =
  '<script>(function(){var d=document.documentElement,p=location.pathname.replace(/\\/+$/,"")||"/";' +
  'if(p!==d.getAttribute("data-path"))d.setAttribute("data-spa","");})();</script>' +
  '<style>html[data-spa] #root{visibility:hidden}</style>';

function head(page, { robots, css }) {
  const image = page.image ? origin + server.ogImage(page.image) : '';
  const tags = [
    `<title>${esc(page.title)}</title>`,
    `<meta name="description" content="${esc(page.description)}" />`,
    `<meta name="robots" content="${robots}" />`,
    page.canonical === false ? '' : `<link rel="canonical" href="${esc(url(page.path))}" />`,
    `<meta property="og:type" content="website" />`,
    `<meta property="og:site_name" content="${esc(SITE_NAME)}" />`,
    `<meta property="og:title" content="${esc(page.title)}" />`,
    `<meta property="og:description" content="${esc(page.description)}" />`,
    `<meta property="og:url" content="${esc(url(page.path))}" />`,
    image ? `<meta property="og:image" content="${esc(image)}" />` : '',
    image ? '<meta property="og:image:width" content="1200" /><meta property="og:image:height" content="630" />' : '',
    `<meta name="twitter:card" content="${image ? 'summary_large_image' : 'summary'}" />`,
    `<meta name="twitter:title" content="${esc(page.title)}" />`,
    `<meta name="twitter:description" content="${esc(page.description)}" />`,
    image ? `<meta name="twitter:image" content="${esc(image)}" />` : '',
    ...(page.jsonLd ? jsonLd(page).map((d) => `<script type="application/ld+json">${JSON.stringify(d).replace(/</g, '\\u003c')}</script>`) : []),
    css ? `<style id="dc-dynamic">${css}</style>` : '',
    GUARD,
  ];
  return tags.filter(Boolean).join('\n    ');
}

function documentFor(page, body, opts) {
  return template
    .replace('<html lang="en">', `<html lang="en" data-path="${esc(page.path)}" data-site="${site}">`)
    .replace(/<title>[\s\S]*?<\/title>/, head(page, opts))
    .replace('<div id="root"></div>', `<div id="root">${body}</div>`);
}

function write(path, html) {
  const file = path === '/' ? join(dist, 'index.html') : join(dist, `${path.replace(/^\//, '')}.html`);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, html);
  return file;
}

const pages = server.prerenderPages(site);
let count = 0;
for (const page of pages) {
  const { html, css } = server.renderPage(site, page.path);
  if (!html.includes('<h1')) throw new Error(`${page.path}: rendered no <h1>`);
  const robots = indexable && page.index ? 'index, follow' : 'noindex, nofollow';
  write(page.path, documentFor(page, html, { robots, css }));
  count += 1;
}

// Not-found page for the hosting fallback.
{
  const page = { path: '/404', title: 'Page not found', description: 'This page doesn’t exist.', image: '', jsonLd: null, canonical: false };
  const { html, css } = server.renderPage(site, '/404');
  write('/404', documentFor(page, html, { robots: 'noindex, nofollow', css }));
}

// Retired URLs: a redirect page each, pointing crawlers at the new URL.
for (const stub of server.redirectStubs(site)) {
  const target = stub.olympus ? `${origins.olympus}${stub.to}` : stub.to;
  const absolute = target.startsWith('http') ? target : origin + target;
  const html = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8" /><title>Moved</title><link rel="icon" type="image/svg+xml" href="/favicon-aether.svg" /><meta name="robots" content="noindex" /><link rel="canonical" href="${esc(absolute)}" /><meta http-equiv="refresh" content="0; url=${esc(target)}" /></head><body><p>This page moved to <a href="${esc(target)}">${esc(absolute)}</a>.</p></body></html>`;
  write(stub.path, html);
}

const listed = pages.filter((p) => p.index);
writeFileSync(
  join(dist, 'sitemap.xml'),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${listed
    .map((p) => `  <url><loc>${esc(url(p.path))}</loc></url>`)
    .join('\n')}\n</urlset>\n`,
);
writeFileSync(
  join(dist, 'robots.txt'),
  indexable ? `User-agent: *\nAllow: /\n\nSitemap: ${origin}/sitemap.xml\n` : 'User-agent: *\nDisallow: /\n',
);

rmSync(ssrDir, { recursive: true, force: true });
console.log(`prerendered ${count} ${site} pages for ${origin} (${indexable ? 'indexable' : 'noindex'}); sitemap lists ${listed.length}`);
