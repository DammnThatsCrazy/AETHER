/**
 * Build-time prerender runner for the marketing workspace.
 *
 * Reads `seo-data.json` (the prerender manifest authored in parity with
 * `src/content/sections.ts`) and the freshly built `dist/index.html`, then
 * emits, for every route with a non-"/" path, a static `dist/<path>/index.html`
 * shell whose <head> matches exactly what the route renders client-side. It also
 * writes `dist/robots.txt` and `dist/sitemap.xml` (sitemap includes the home
 * loc, which is served by `dist/index.html` itself and is never rewritten here).
 *
 * Zero-dependency plain Node ESM. Paths resolve relative to this script unless
 * overridden on argv:
 *
 *   node scripts/prerender.mjs [seoDataPath] [distDir]
 *
 * Any missing input file or malformed manifest throws, so a failed prerender
 * fails the build visibly.
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** Default manifest + built-site locations, relative to this script. */
const DEFAULT_SEO = path.join(HERE, '..', 'seo-data.json');
const DEFAULT_DIST = path.join(HERE, '..', 'dist');

/** Escape a value for a double-quoted HTML attribute. */
export function escapeAttrValue(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/** Escape a value for HTML/XML text content. */
export function escapeText(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/**
 * Split one opening tag (`<meta name="description" content="..."/>`) into its
 * element name, attribute list, and self-closing flag. Attribute values are kept
 * verbatim (already-escaped source text is not re-escaped on write-back).
 */
function parseOpenTag(open) {
  const match = /^<([a-zA-Z][a-zA-Z0-9-]*)([\s\S]*?)(\/?)>$/.exec(open);
  if (match === null) return null;
  const attrs = [];
  const attrRe = /([a-zA-Z_:][a-zA-Z0-9_.:-]*)\s*=\s*"([^"]*)"/g;
  let attr;
  while ((attr = attrRe.exec(match[2])) !== null) {
    attrs.push({ name: attr[1], value: attr[2] });
  }
  return { name: match[1], attrs, selfClose: match[3] === '/' };
}

function renderOpenTag(tag) {
  const body = tag.attrs.map((attr) => `${attr.name}="${attr.value}"`).join(' ');
  return `<${tag.name}${body.length > 0 ? ` ${body}` : ''}${tag.selfClose ? ' /' : ''}>`;
}

/**
 * Replace `attr`'s value on the first `<element>` whose opening tag carries the
 * `identity` attribute pairs. Reports whether a matching tag was found so callers
 * can inject a fresh tag when one is absent (never duplicating an existing one).
 */
function setElementAttr(html, element, identity, attr, value) {
  const tagOpenRe = new RegExp(`<${element}\\b[^>]*>`, 'gi');
  let replaced = false;
  const out = html.replace(tagOpenRe, (open) => {
    if (replaced) return open;
    const parsed = parseOpenTag(open);
    if (parsed === null) return open;
    const matches = identity.every(([name, expected]) =>
      parsed.attrs.some((candidate) => candidate.name === name && candidate.value === expected),
    );
    if (!matches) return open;
    replaced = true;
    const nextAttrs = parsed.attrs.filter((candidate) => candidate.name !== attr);
    nextAttrs.push({ name: attr, value: escapeAttrValue(value) });
    return renderOpenTag({ ...parsed, attrs: nextAttrs });
  });
  return { html: out, replaced };
}

/** Replace the text content of the first `<title>` element. */
function setTitle(html, title) {
  const titleRe = /<title\b[^>]*>[\s\S]*?<\/title>/gi;
  let replaced = false;
  const out = html.replace(titleRe, (tag) => {
    if (replaced) return tag;
    replaced = true;
    const openEnd = tag.indexOf('>') + 1;
    return `${tag.slice(0, openEnd)}${escapeText(title)}</title>`;
  });
  return { html: out, replaced };
}

/** Insert `tagHtml` just before `</head>` (falling back to appending at the end). */
function injectIntoHead(html, tagHtml) {
  if (/<\/head>/i.test(html)) {
    return html.replace(/<\/head>/i, `${tagHtml}\n  </head>`);
  }
  return `${html}${tagHtml}\n`;
}

/** The canonical origin + trailing path piece is what every route's shell needs. */
function canonicalUrl(host, routePath) {
  return `${String(host).replace(/\/+$/, '')}${routePath}`;
}

/**
 * Emit a per-route shell: a copy of the built `dist/index.html` with the
 * title, meta description, canonical, and Open Graph + Twitter slots replaced by
 * the route's authored values. Missing tags are injected; existing tags are
 * updated in place — never duplicated. `dist/index.html` itself is untouched.
 */
export function injectRouteHead(html, { title, description, canonical }) {
  let out = html;

  const titleResult = setTitle(out, title);
  out = titleResult.html;
  if (!titleResult.replaced) out = injectIntoHead(out, `<title>${escapeText(title)}</title>`);

  // [attrName, slotKey, value] — the head slots the section pages own client-side.
  const slots = [
    ['name', 'description', description],
    ['rel', 'canonical', canonical],
    ['property', 'og:title', title],
    ['property', 'og:description', description],
    ['property', 'og:url', canonical],
    ['name', 'twitter:title', title],
    ['name', 'twitter:description', description],
  ];

  for (const [attrName, slotKey, value] of slots) {
    const element = slotKey === 'canonical' ? 'link' : 'meta';
    const valueAttr = slotKey === 'canonical' ? 'href' : 'content';
    const result = setElementAttr(out, element, [[attrName, slotKey]], valueAttr, value);
    out = result.html;
    if (!result.replaced) {
      const fallback =
        slotKey === 'canonical'
          ? `<link rel="canonical" href="${escapeAttrValue(value)}" />`
          : `<meta ${attrName}="${escapeAttrValue(slotKey)}" content="${escapeAttrValue(value)}" />`;
      out = injectIntoHead(out, fallback);
    }
  }

  return out;
}

/**
 * Render a robots.txt from the manifest's disallow list. The marketing sites
 * are fully crawlable except for the disallowed auth/hand-off routes.
 */
export function renderRobotsTxt(disallow) {
  const lines = ['User-agent: *', 'Allow: /'];
  for (const entry of disallow) {
    lines.push(`Disallow: ${entry}`);
  }
  return `${lines.join('\n')}\n`;
}

/** Render a sitemap.xml urlset; `paths` includes "/" for the home page. */
export function renderSitemap(host, paths) {
  const origin = String(host).replace(/\/+$/, '');
  const urls = paths.map((routePath) => {
    const absolute = routePath === '/' ? `${origin}/` : `${origin}${routePath}`;
    return `  <url>\n    <loc>${escapeText(absolute)}</loc>\n  </url>`;
  });
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...urls,
    '</urlset>',
    '',
  ];
  return lines.join('\n');
}

/** Read the manifest and write every prerender artifact into `distDir`. */
export function runPrerender(seoPath, distDir) {
  let raw;
  try {
    raw = readFileSync(seoPath, 'utf8');
  } catch (error) {
    throw new Error(`prerender: cannot read manifest at ${seoPath}: ${error.message}`);
  }

  let seo;
  try {
    seo = JSON.parse(raw);
  } catch (error) {
    throw new Error(`prerender: malformed JSON in ${seoPath}: ${error.message}`);
  }

  const { host, robotsDisallow = [], routes = [] } = seo ?? {};
  if (typeof host !== 'string' || host.length === 0) {
    throw new Error(`prerender: ${seoPath} must declare a host string`);
  }
  if (!Array.isArray(robotsDisallow) || !Array.isArray(routes)) {
    throw new Error(`prerender: ${seoPath} must declare robotsDisallow and routes arrays`);
  }

  const indexHtmlPath = path.join(distDir, 'index.html');
  let template;
  try {
    template = readFileSync(indexHtmlPath, 'utf8');
  } catch (error) {
    throw new Error(`prerender: built dist/index.html missing at ${indexHtmlPath}: ${error.message}`);
  }

  const origin = String(host).replace(/\/+$/, '');

  for (const route of routes) {
    if (route === null || typeof route !== 'object') {
      throw new Error(`prerender: ${seoPath} routes must be objects`);
    }
    const { path: routePath, title, description } = route;
    if (typeof routePath !== 'string' || !routePath.startsWith('/')) {
      throw new Error(`prerender: ${seoPath} route is missing a "/"-prefixed path`);
    }
    if (typeof title !== 'string' || title.length === 0 || typeof description !== 'string') {
      throw new Error(`prerender: ${seoPath} route ${routePath} must carry a title and description`);
    }
    if (routePath === '/') continue; // home is served by dist/index.html, not a shell

    const canonical = canonicalUrl(origin, routePath);
    const shell = injectRouteHead(template, { title, description, canonical });
    const relativeDir = routePath.replace(/^\/+/, '').split('/');
    const outFile = path.join(distDir, ...relativeDir, 'index.html');
    mkdirSync(path.dirname(outFile), { recursive: true });
    writeFileSync(outFile, shell);
  }

  writeFileSync(path.join(distDir, 'robots.txt'), renderRobotsTxt(robotsDisallow));
  writeFileSync(path.join(distDir, 'sitemap.xml'), renderSitemap(origin, ['/', ...routes.map((route) => route.path)]));
}

const isMain =
  process.argv[1] !== undefined && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  const [seoArg = DEFAULT_SEO, distArg = DEFAULT_DIST] = process.argv.slice(2);
  runPrerender(seoArg, distArg);
  process.stdout.write(`prerender: wrote per-route shells, robots.txt, and sitemap.xml into ${distArg}\n`);
}
