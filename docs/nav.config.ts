/**
 * docs/nav.config.ts — canonical navigation configuration.
 *
 * Declares the ordered list of documentation sections, their display
 * titles, and the minimum visibility tier needed to see them. The
 * apps/docs frontend uses this for sidebar ordering and section headers.
 *
 * Adding a new section: append an entry here; CI/frontmatter validators
 * enforce that every doc's `section:` field appears in the schema enum.
 */

export type SectionId =
  | 'home' | 'quickstart' | 'concepts' | 'sdks' | 'api'
  | 'architecture' | 'ai' | 'data' | 'operations' | 'self-hosting'
  | 'enterprise' | 'compliance' | 'security' | 'smart-contracts'
  | 'tutorials' | 'examples' | 'reference' | 'troubleshooting'
  | 'kyber' | 'changelog' | 'glossary';

export type TierVisibility = 'P' | 'C' | 'I';

export interface NavSection {
  id: SectionId;
  title: string;
  /** Minimum tier whose bundle includes this section. Default: 'P'. */
  minTier?: TierVisibility;
}

/** Ordered display list — first entry appears first in the sidebar. */
export const sections: NavSection[] = [
  { id: 'home',           title: 'Overview' },
  { id: 'quickstart',     title: 'Quickstart' },
  { id: 'concepts',       title: 'Concepts' },
  { id: 'sdks',           title: 'SDKs' },
  { id: 'api',            title: 'API Reference' },
  { id: 'architecture',   title: 'Architecture' },
  { id: 'ai',             title: 'AI Systems' },
  { id: 'data',           title: 'Data Systems' },
  { id: 'self-hosting',   title: 'Self-Hosting' },
  { id: 'smart-contracts',title: 'Smart Contracts' },
  { id: 'tutorials',      title: 'Tutorials' },
  { id: 'examples',       title: 'Examples' },
  { id: 'reference',      title: 'Reference' },
  { id: 'troubleshooting',title: 'Troubleshooting' },
  { id: 'kyber',          title: 'Kyber Console' },
  { id: 'changelog',      title: 'Changelog' },
  { id: 'glossary',       title: 'Glossary' },
  { id: 'compliance',     title: 'Compliance',  minTier: 'C' },
  { id: 'enterprise',     title: 'Enterprise',  minTier: 'C' },
  { id: 'security',       title: 'Security',    minTier: 'C' },
  { id: 'operations',     title: 'Operations',  minTier: 'I' },
];

/** Returns sections visible at a given tier (P ⊂ C ⊂ I). */
export function sectionsForTier(tier: TierVisibility): NavSection[] {
  const tierRank: Record<TierVisibility, number> = { P: 0, C: 1, I: 2 };
  return sections.filter((s) => tierRank[s.minTier ?? 'P'] <= tierRank[tier]);
}
