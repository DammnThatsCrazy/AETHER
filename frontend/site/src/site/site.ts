/**
 * One build serves two sites:
 *
 * - olympuslabsml.com (and staging.olympuslabsml.com, www.staging.olympuslabsml.com):
 *   Olympus Labs company pages
 * - aether.olympuslabsml.com (and aether.staging.olympuslabsml.com): Aether
 *   marketing, docs, status, contact, legal and the portal at /app
 *
 * The site is chosen from the hostname. A build-time VITE_SITE (used by the
 * per-site prerender) wins, then a `?site=` query parameter so a single
 * Amplify default domain or PR preview can show either site. Anything
 * unrecognised is Aether, the product site.
 */

import { resolveDocId } from '@site/pages/docs/docs-model';

export type SiteId = 'olympus' | 'aether';

const OLYMPUS_HOSTS = new Set([
  'olympuslabsml.com',
  'www.olympuslabsml.com',
  'staging.olympuslabsml.com',
  'www.staging.olympuslabsml.com',
]);

export function isSiteId(value: unknown): value is SiteId {
  return value === 'olympus' || value === 'aether';
}

export function resolveSite(
  hostname: string,
  search = '',
  buildSite: string | undefined = import.meta.env.VITE_SITE,
): SiteId {
  if (isSiteId(buildSite)) return buildSite;
  const requested = new URLSearchParams(search).get('site');
  if (isSiteId(requested)) return requested;
  return OLYMPUS_HOSTS.has(hostname.toLowerCase()) ? 'olympus' : 'aether';
}

/**
 * The site named by `?site=` when that parameter is what picked it (no
 * build-time VITE_SITE). Same-site links carry it forward so a preview host
 * stays on the chosen site as the visitor navigates.
 */
export function querySelectedSite(search: string, buildSite: string | undefined = import.meta.env.VITE_SITE): SiteId | null {
  if (isSiteId(buildSite)) return null;
  const requested = new URLSearchParams(search).get('site');
  return isSiteId(requested) ? requested : null;
}

function withSiteParam(path: string, site: SiteId): string {
  const hashAt = path.indexOf('#');
  const base = hashAt === -1 ? path : path.slice(0, hashAt);
  const hash = hashAt === -1 ? '' : path.slice(hashAt);
  if (/[?&]site=/.test(base)) return path;
  return `${base}${base.includes('?') ? '&' : '?'}site=${site}${hash}`;
}

export interface SiteOrigins {
  olympus: string;
  aether: string;
}

function trimOrigin(value: string | undefined, fallback: string): string {
  const origin = (value ?? '').trim() || fallback;
  return origin.replace(/\/+$/, '');
}

const PRODUCTION: SiteOrigins = { olympus: 'https://olympuslabsml.com', aether: 'https://aether.olympuslabsml.com' };
const STAGING: SiteOrigins = { olympus: 'https://www.staging.olympuslabsml.com', aether: 'https://aether.staging.olympuslabsml.com' };
const STAGING_HOSTS = new Set(['staging.olympuslabsml.com', 'www.staging.olympuslabsml.com', 'aether.staging.olympuslabsml.com']);

function currentHostname(): string {
  return typeof window === 'undefined' ? '' : window.location.hostname;
}

/**
 * Absolute origins for cross-site links. VITE_SITE_OLYMPUS_URL and
 * VITE_SITE_AETHER_URL win; otherwise a staging host links to its staging
 * pair, so testers are never sent to production, and anything else uses the
 * production origins.
 */
export function siteOrigins(env: Record<string, string | undefined> = import.meta.env, hostname: string = currentHostname()): SiteOrigins {
  const defaults = STAGING_HOSTS.has(hostname.toLowerCase()) ? STAGING : PRODUCTION;
  return {
    olympus: trimOrigin(env.VITE_SITE_OLYMPUS_URL, defaults.olympus),
    aether: trimOrigin(env.VITE_SITE_AETHER_URL, defaults.aether),
  };
}

/**
 * A link to `path` on `target`. Same-site links stay relative so they work on
 * every host (production, staging, previews); cross-site links are absolute.
 */
export function siteHref(
  current: SiteId,
  target: SiteId,
  path: string,
  origins: SiteOrigins = siteOrigins(),
  keepSelector = false,
): string {
  if (/^(https?:|mailto:)/.test(path)) return path;
  const normalized = path.startsWith('/') ? path : `/${path}`;
  if (current !== target) return `${origins[target]}${normalized}`;
  return keepSelector ? withSiteParam(normalized, current) : normalized;
}

/**
 * Pages of the retired docs portal (frontend/docs: /doc/<slug>, where the
 * slug is its content path) whose topic lives under another id on the site.
 * Other slugs resolve by their last segment (concepts/signals → signals).
 */
const LEGACY_DOC_SLUGS: Record<string, string> = {
  'quickstart/web-sdk': 'quickstart-web',
  'quickstart/react-sdk': 'quickstart-web',
  'quickstart/node-sdk': 'quickstart-backend',
  'api/ingestion': 'ingestion-api',
  'api/authentication': 'api-conventions',
  'api/webhooks': 'api-conventions',
  'api/profiles': 'profiles',
  'tutorials/shopify-integration': 'connector-catalog',
  'tutorials/stripe-integration': 'connector-catalog',
  'developers/connection-model': 'connectors',
  'developers/events-and-consent': 'events',
  'developers/identity-and-relationships': 'relationships',
  'developers/security-and-privacy': 'sdk-privacy',
};

/**
 * The site's docs path for a path on the retired docs host: its /doc/<slug>
 * pages and bare page names map to a site page id, and anything without a
 * public equivalent (the /artifacts pages, unknown slugs) opens the docs home
 * rather than a not-found page.
 */
export function legacyDocsPath(pathname: string): string {
  const path = pathname.replace(/^\/+|\/+$/g, '');
  let slug = path.startsWith('doc/') ? path.slice('doc/'.length) : path;
  try {
    slug = decodeURIComponent(slug);
  } catch {
    // A malformed escape is treated as an unknown page.
  }
  if (!slug || slug === 'artifacts' || slug.startsWith('artifacts/')) return '/docs';
  const id = resolveDocId(LEGACY_DOC_SLUGS[slug] ?? slug.split('/').pop());
  return id ? `/docs/${id}` : '/docs';
}

/**
 * The docs and status sites used to have their own hosts (docs.* and
 * status.*). Those hosts now point at this build, which sends visitors to the
 * same content on the Aether site: docs.<domain>/<path> → the matching
 * <aether>/docs page (legacyDocsPath, keeping the query and #anchor) and
 * status.<domain>/* → <aether>/status. Returns null for every other host.
 */
export function retiredHostRedirect(
  hostname: string,
  pathname: string,
  search = '',
  hash = '',
  origins: SiteOrigins = siteOrigins(),
): string | null {
  const label = hostname.toLowerCase().split('.')[0];
  if (label === 'docs') {
    return `${origins.aether}${legacyDocsPath(pathname)}${search}${hash}`;
  }
  if (label === 'status') return `${origins.aether}/status`;
  return null;
}
