import { Link } from 'react-router-dom';
import { sectionsForTier } from '@content/nav.config';
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

export default function DocIndex({ tier }: Props) {
  const tiers: Visibility[] =
    tier === 'I' ? ['P', 'C', 'I'] : tier === 'C' ? ['P', 'C'] : ['P'];

  const bySection = getDocsBySection(tiers);
  const availableSlugs = new Set(getAvailableSlugs());
  // Use nav config for section order + display titles
  const orderedSections = sectionsForTier(tier).filter((s) => bySection.has(s.id));
  // Append any sections in manifest but not in nav config (shouldn't happen, but safe)
  const knownIds = new Set(orderedSections.map((s) => s.id));
  for (const id of bySection.keys()) {
    if (!knownIds.has(id as never)) orderedSections.push({ id: id as never, title: id });
  }

  return (
    <div style={{ maxWidth: 720, margin: '2rem auto', padding: '0 1.5rem' }}>
      <header style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, marginBottom: '0.25rem' }}>
          {TIER_LABELS[tier]}
        </h1>
        <p style={{ color: '#6b7280', margin: 0 }}>
          {bySection.size} sections · {[...bySection.values()].flat().length} docs
        </p>
      </header>

      {orderedSections.map(({ id, title }) => {
        const docs = bySection.get(id) ?? [];
        if (docs.length === 0) return null;
        return (
          <section key={id} style={{ marginBottom: '2rem' }}>
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
              {title}
            </h2>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: '0.5rem' }}>
              {docs.map((doc: ManifestEntry) => {
                const slug = doc.slug ?? '';
                const isRenderable = availableSlugs.has(slug.split('/').pop() ?? '');
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
                      <span style={{ color: '#374151', fontWeight: 500 }}>{doc.title ?? slug}</span>
                    )}
                    {doc.status && doc.status !== 'stable' && (
                      <span
                        style={{
                          fontSize: '0.7rem',
                          fontWeight: 600,
                          padding: '0.1rem 0.4rem',
                          borderRadius: 3,
                          background: `${STATUS_COLOR[doc.status] ?? '#6b7280'}22`,
                          color: STATUS_COLOR[doc.status] ?? '#6b7280',
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
        );
      })}
    </div>
  );
}
