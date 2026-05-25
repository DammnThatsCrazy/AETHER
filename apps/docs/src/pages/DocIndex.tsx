import { Link } from 'react-router-dom';
import { getDocsBySection, getAvailableSlugs, type ManifestEntry } from '../lib/docs-loader';
import type { Visibility } from '../lib/frontmatter';

interface Props {
  tier: Visibility;
}

const TIER_LABELS: Record<Visibility, string> = {
  P: 'Public docs',
  C: 'Customer portal',
  I: 'Internal docs',
};

const STATUS_COLOR: Record<string, string> = {
  stable: '#16a34a',
  beta: '#d97706',
  experimental: '#7c3aed',
  deprecated: '#dc2626',
};

const SECTION_ORDER = [
  'home', 'quickstart', 'concepts', 'sdks', 'api',
  'architecture', 'ai', 'data', 'operations', 'compliance',
  'security', 'smart-contracts', 'tutorials', 'examples',
  'reference', 'troubleshooting', 'kyber', 'changelog', 'glossary',
];

function sortSections(sections: Map<string, ManifestEntry[]>) {
  const ordered: [string, ManifestEntry[]][] = [];
  for (const s of SECTION_ORDER) {
    if (sections.has(s)) ordered.push([s, sections.get(s)!]);
  }
  for (const [s, docs] of sections) {
    if (!SECTION_ORDER.includes(s)) ordered.push([s, docs]);
  }
  return ordered;
}

export default function DocIndex({ tier }: Props) {
  // P tier: show public docs; C tier: also include public; I tier: show all
  const tiers: Visibility[] =
    tier === 'I' ? ['P', 'C', 'I'] : tier === 'C' ? ['P', 'C'] : ['P'];

  const bySection = getDocsBySection(tiers);
  const availableSlugs = new Set(getAvailableSlugs());

  return (
    <div
      style={{
        fontFamily: 'system-ui, -apple-system, sans-serif',
        maxWidth: 900,
        margin: '2rem auto',
        padding: '0 1.5rem',
      }}
    >
      <header style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, marginBottom: '0.25rem' }}>
          {TIER_LABELS[tier]}
        </h1>
        <p style={{ color: '#6b7280', margin: 0 }}>
          {bySection.size} sections · {[...bySection.values()].flat().length} docs
        </p>
      </header>

      {sortSections(bySection).map(([section, docs]) => (
        <section key={section} style={{ marginBottom: '2rem' }}>
          <h2
            style={{
              fontSize: '0.875rem',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.07em',
              color: '#6b7280',
              borderBottom: '1px solid #e5e7eb',
              paddingBottom: '0.4rem',
              marginBottom: '0.75rem',
            }}
          >
            {section}
          </h2>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: '0.5rem' }}>
            {docs.map((doc) => {
              const slug = doc.slug ?? '';
              // Use the full slug — getAvailableSlugs() returns the content-
              // relative path (e.g. "concepts/identity-resolution"), so
              // stripping to the last segment would falsely mark every nested
              // page as non-renderable.
              const isRenderable = availableSlugs.has(slug);
              return (
                <li key={doc.path} style={{ display: 'flex', alignItems: 'baseline', gap: '0.75rem' }}>
                  {isRenderable ? (
                    <Link
                      to={`/doc/${encodeURIComponent(slug)}`}
                      style={{ color: '#1d4ed8', textDecoration: 'none', fontWeight: 500 }}
                    >
                      {doc.title ?? slug}
                    </Link>
                  ) : (
                    <span style={{ color: '#374151', fontWeight: 500 }}>
                      {doc.title ?? slug}
                    </span>
                  )}
                  {doc.status && doc.status !== 'stable' && (
                    <span
                      style={{
                        fontSize: '0.7rem',
                        fontWeight: 600,
                        padding: '0.1rem 0.4rem',
                        borderRadius: 3,
                        background: `${STATUS_COLOR[doc.status]}22`,
                        color: STATUS_COLOR[doc.status],
                        letterSpacing: '0.04em',
                      }}
                    >
                      {doc.status}
                    </span>
                  )}
                  {doc.estimated_read_minutes && (
                    <span style={{ fontSize: '0.75rem', color: '#9ca3af' }}>
                      {doc.estimated_read_minutes} min
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
