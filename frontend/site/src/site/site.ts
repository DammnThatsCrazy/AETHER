/**
 * One build serves two sites:
 *
 * - olympuslabsml.com (and staging.olympuslabsml.com): Olympus Labs company pages
 * - aether.olympuslabsml.com (and aether.staging.olympuslabsml.com): Aether
 *   marketing, docs, status, contact, legal and the portal at /app
 *
 * The site is chosen from the hostname. A build-time VITE_SITE (used by the
 * per-site prerender) wins, then a `?site=` query parameter so a single
 * Amplify default domain or PR preview can show either site. Anything
 * unrecognised is Aether, the product site.
 */

export type SiteId = 'olympus' | 'aether';

const OLYMPUS_HOSTS = new Set([
  'olympuslabsml.com',
  'www.olympuslabsml.com',
  'staging.olympuslabsml.com',
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

export interface SiteOrigins {
  olympus: string;
  aether: string;
}

function trimOrigin(value: string | undefined, fallback: string): string {
  const origin = (value ?? '').trim() || fallback;
  return origin.replace(/\/+$/, '');
}

/** Absolute origins for cross-site links (production unless configured). */
export function siteOrigins(env: Record<string, string | undefined> = import.meta.env): SiteOrigins {
  return {
    olympus: trimOrigin(env.VITE_SITE_OLYMPUS_URL, 'https://olympuslabsml.com'),
    aether: trimOrigin(env.VITE_SITE_AETHER_URL, 'https://aether.olympuslabsml.com'),
  };
}

/**
 * A link to `path` on `target`. Same-site links stay relative so they work on
 * every host (production, staging, previews); cross-site links are absolute.
 */
export function siteHref(current: SiteId, target: SiteId, path: string, origins: SiteOrigins = siteOrigins()): string {
  if (/^(https?:|mailto:)/.test(path)) return path;
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return current === target ? normalized : `${origins[target]}${normalized}`;
}
