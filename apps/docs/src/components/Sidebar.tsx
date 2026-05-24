import { NavLink, useLocation } from 'react-router-dom';
import { sectionsForTier, type NavSection } from '@content/nav.config';
import { getDocsBySection } from '../lib/docs-loader';
import { getBundleTier } from '../lib/tier';
import type { ManifestEntry } from '../lib/docs-loader';

const tier = getBundleTier();
const visibleSections = sectionsForTier(tier);

// Visibility tiers the current bundle shows
const VISIBLE_TIERS = tier === 'I' ? ['P', 'C', 'I'] as const
  : tier === 'C' ? ['P', 'C'] as const
  : ['P'] as const;

const docsBySection = getDocsBySection([...VISIBLE_TIERS]);

const SIDEBAR_W = 240;

function SectionBlock({ section, docs }: { section: NavSection; docs: ManifestEntry[] }) {
  if (docs.length === 0) return null;
  const { pathname } = useLocation();

  return (
    <div style={{ marginBottom: '1.25rem' }}>
      <div
        style={{
          fontSize: '0.7rem',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.07em',
          color: '#9ca3af',
          padding: '0 0.75rem',
          marginBottom: '0.25rem',
        }}
      >
        {section.title}
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {docs.map((doc) => {
          const slug = doc.slug ?? '';
          const href = `/doc/${encodeURIComponent(slug)}`;
          const active = pathname === href;
          return (
            <li key={doc.path}>
              <NavLink
                to={href}
                style={{
                  display: 'block',
                  padding: '0.28rem 0.75rem',
                  fontSize: '0.875rem',
                  color: active ? '#1d4ed8' : '#374151',
                  background: active ? '#eff6ff' : 'transparent',
                  borderRadius: 4,
                  textDecoration: 'none',
                  fontWeight: active ? 600 : 400,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {doc.title ?? slug}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function Sidebar() {
  return (
    <nav
      style={{
        width: SIDEBAR_W,
        minWidth: SIDEBAR_W,
        height: '100vh',
        position: 'sticky',
        top: 0,
        overflowY: 'auto',
        borderRight: '1px solid #e5e7eb',
        padding: '1.25rem 0',
        background: '#f9fafb',
        flexShrink: 0,
      }}
      aria-label="Documentation navigation"
    >
      <NavLink
        to="/"
        style={{
          display: 'block',
          padding: '0 0.75rem',
          marginBottom: '1.5rem',
          fontWeight: 700,
          fontSize: '1rem',
          color: '#111827',
          textDecoration: 'none',
        }}
      >
        Aether Docs
      </NavLink>

      {visibleSections.map((section) => (
        <SectionBlock
          key={section.id}
          section={section}
          docs={docsBySection.get(section.id) ?? []}
        />
      ))}
    </nav>
  );
}
