/** Mirrors scripts/docs_schema.json — keep in sync when the schema changes. */

export type Visibility = 'P' | 'C' | 'I';

export type Section =
  | 'home' | 'quickstart' | 'concepts' | 'sdks' | 'api'
  | 'architecture' | 'ai' | 'data' | 'operations' | 'self-hosting'
  | 'enterprise' | 'compliance' | 'security' | 'smart-contracts'
  | 'tutorials' | 'examples' | 'reference' | 'troubleshooting'
  | 'kyber' | 'changelog' | 'glossary';

export type Audience =
  | 'exec' | 'buyer' | 'dev-junior' | 'dev-senior'
  | 'architect' | 'security' | 'compliance' | 'ops' | 'ai';

export type Status = 'stable' | 'beta' | 'experimental' | 'deprecated';

export interface DocFrontmatter {
  title: string;
  slug: string;
  section: Section;
  visibility: Visibility;
  audience: Audience[];
  status: Status;
  since_version?: string;
  last_synced_commit?: string;
  source_files?: string[];
  flags?: string[];
  prereqs?: string[];
  related?: string[];
  canonical_owner?: string;
  estimated_read_minutes?: number;
  toc_depth?: number;
}
