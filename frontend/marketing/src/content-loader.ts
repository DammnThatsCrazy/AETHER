/// <reference types="vite/client" />

export type LaunchPackBrand = 'Olympus Labs' | 'Aether' | 'Shared' | 'Olympus Labs + Aether';

export interface LaunchPackPage {
  readonly sourcePath: string;
  readonly brand: LaunchPackBrand;
  readonly route: string;
  readonly pageType: string;
  readonly status: string;
  readonly seoTitle: string;
  readonly seoDescription: string;
  readonly primaryCta?: string | undefined;
  readonly secondaryCta?: string | undefined;
  readonly body: string;
}

const rawPages = import.meta.glob('../content/**/*.md', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>;

function parseScalar(value: string): string {
  const trimmed = value.trim();
  if (
    trimmed.length >= 2 &&
    ((trimmed.startsWith('"') && trimmed.endsWith('"')) ||
      (trimmed.startsWith("'") && trimmed.endsWith("'")))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function parsePage(sourcePath: string, source: string): LaunchPackPage | null {
  const normalized = source.replace(/\r\n/g, '\n');
  if (!normalized.startsWith('---\n')) return null;
  const frontmatterEnd = normalized.indexOf('\n---\n', 4);
  if (frontmatterEnd < 0) return null;

  const frontmatter = new Map<string, string>();
  for (const line of normalized.slice(4, frontmatterEnd).split('\n')) {
    const separator = line.indexOf(':');
    if (separator < 0) continue;
    frontmatter.set(line.slice(0, separator).trim(), parseScalar(line.slice(separator + 1)));
  }

  const brand = frontmatter.get('brand');
  const route = frontmatter.get('route');
  const pageType = frontmatter.get('page_type');
  const status = frontmatter.get('status');
  if (
    !brand ||
    !route ||
    !pageType ||
    !status ||
    !['Olympus Labs', 'Aether', 'Shared', 'Olympus Labs + Aether'].includes(brand)
  ) {
    return null;
  }

  return {
    sourcePath,
    brand: brand as LaunchPackBrand,
    route,
    pageType,
    status,
    seoTitle: frontmatter.get('seo_title') ?? '',
    seoDescription: frontmatter.get('seo_description') ?? '',
    ...(frontmatter.get('primary_cta') ? { primaryCta: frontmatter.get('primary_cta') } : {}),
    ...(frontmatter.get('secondary_cta') ? { secondaryCta: frontmatter.get('secondary_cta') } : {}),
    body: normalized.slice(frontmatterEnd + 5).trim(),
  };
}

const pages = Object.entries(rawPages)
  .map(([sourcePath, source]) => parsePage(sourcePath, source))
  .filter((page): page is LaunchPackPage => page !== null);

export const launchPackPages: readonly LaunchPackPage[] = pages;

export function getLaunchPackPage(
  brand: Exclude<LaunchPackBrand, 'Shared' | 'Olympus Labs + Aether'>,
  route: string,
): LaunchPackPage | undefined {
  const normalizedRoute = route.length > 1 ? route.replace(/\/$/, '') : route;
  return (
    pages.find((page) => page.brand === brand && page.route === normalizedRoute) ??
    pages.find(
      (page) =>
        (page.brand === 'Shared' || page.brand === 'Olympus Labs + Aether') &&
        page.route === normalizedRoute,
    )
  );
}

export function launchPackRoutes(
  brand: Exclude<LaunchPackBrand, 'Shared' | 'Olympus Labs + Aether'>,
): readonly string[] {
  return pages
    .filter((page) => page.brand === brand)
    .map((page) => page.route)
    .sort();
}

/** Return the authored H1 from a launch-pack page for shells that keep a
 * richer interactive surface below the editorial hero. */
export function launchPackHeading(page: LaunchPackPage | undefined): string | undefined {
  if (page === undefined) return undefined;
  return page.body.match(/^#\s+(.+)$/m)?.[1]?.trim();
}
