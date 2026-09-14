import type { ComponentType } from 'react';
import type { DocFrontmatter, Visibility } from './frontmatter';
import manifestJson from '../../../../docs/_generated/doc-manifest.json';

export interface ManifestEntry {
  path: string;
  title?: string;
  slug?: string;
  section?: string;
  visibility?: Visibility;
  audience?: string[];
  status?: string;
  since_version?: string;
  estimated_read_minutes?: number;
  toc_depth?: number;
  canonical_owner?: string;
  flags?: string[];
}

export interface DocManifest {
  version: string;
  generated_from: string;
  docs: ManifestEntry[];
}

export const manifest = manifestJson as DocManifest;

type DocModule = {
  default: ComponentType;
  frontmatter: DocFrontmatter;
};

// Lazy glob of curated MDX content authored under src/content/.
// These are fully MDX-safe files; use import.meta.glob for type safety.
const contentModules = import.meta.glob<DocModule>('../content/**/*.{md,mdx}');

// The public launch-pack corpus is authored under docs/public so it remains a
// repository-level documentation source of truth. Render it through the same
// MDX pipeline instead of leaving manifest entries as non-renderable stubs.
const publicModules = import.meta.glob<DocModule>('../../../../docs/public/**/*.md');

function publicLoaderForSlug(slug: string): (() => Promise<DocModule>) | null {
  const entry = manifest.docs.find(
    (candidate) => candidate.slug === slug && candidate.path.startsWith('docs/public/'),
  );
  if (entry === undefined) return null;
  const path = Object.keys(publicModules).find((candidate) => candidate.endsWith(`/${entry.path}`));
  return path === undefined ? null : publicModules[path] ?? null;
}

/** Returns a lazy loader for an MDX module by its content-relative path. */
export function getContentLoader(slug: string): (() => Promise<DocModule>) | null {
  for (const [modPath, loader] of Object.entries(contentModules)) {
    // Match by slug embedded in the MDX file path (e.g. content/overview.mdx → "overview")
    if (modPath.includes(`/${slug}.`) || modPath.endsWith(`/${slug}`)) {
      return loader;
    }
  }
  return publicLoaderForSlug(slug);
}

/** All content slugs available for rendering. */
export function getAvailableSlugs(): string[] {
  const authoredSlugs = Object.keys(contentModules).map((p) => {
    const base = p.replace(/^.*\/content\//, '').replace(/\.(md|mdx)$/, '');
    return base;
  });
  const launchPackSlugs = manifest.docs
    .filter((entry) => entry.path.startsWith('docs/public/') && publicLoaderForSlug(entry.slug ?? '') !== null)
    .map((entry) => entry.slug ?? '')
    .filter(Boolean);
  return [...new Set([...authoredSlugs, ...launchPackSlugs])];
}

/** Get docs from the manifest filtered by visibility tier(s). */
export function getDocsByVisibility(tiers: Visibility[]): ManifestEntry[] {
  const set = new Set<Visibility>(tiers);
  return manifest.docs.filter((d) => d.visibility && set.has(d.visibility));
}

/** Get docs from the manifest grouped by section. */
export function getDocsBySection(tiers: Visibility[]): Map<string, ManifestEntry[]> {
  const docs = getDocsByVisibility(tiers);
  const map = new Map<string, ManifestEntry[]>();
  for (const doc of docs) {
    const section = doc.section ?? 'other';
    if (!map.has(section)) map.set(section, []);
    map.get(section)!.push(doc);
  }
  return map;
}
