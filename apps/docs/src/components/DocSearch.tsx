import { useMemo, useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { manifest, type ManifestEntry } from '../lib/docs-loader';
import type { Visibility } from '../lib/frontmatter';

interface Props {
  /** Visibility tiers visible in this bundle (mirrors Sidebar/DocIndex). */
  tiers: readonly Visibility[];
}

/**
 * Client-side filter across doc titles (and, as a fallback, slug/section)
 * pulled from the generated manifest (docs/_generated/doc-manifest.json).
 *
 * The canonical frontmatter schema (scripts/docs_schema.json) has no
 * `description` field, so unlike a typical "search titles and descriptions"
 * box this matches on `title`, `slug`, and `section` — the fields the
 * manifest actually carries — plus `audience`, which doubles as a rough
 * topic tag (e.g. searching "security" surfaces docs written for that
 * audience even when the word isn't in the title).
 */
export default function DocSearch({ tiers }: Props) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const tierSet = useMemo(() => new Set(tiers), [tiers]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return manifest.docs
      .filter((d) => d.visibility && tierSet.has(d.visibility) && d.slug)
      .filter((d: ManifestEntry) => {
        const haystack = [d.title, d.slug, d.section, ...(d.audience ?? [])]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        return haystack.includes(q);
      })
      .slice(0, 8);
  }, [query, tierSet]);

  function go(slug: string) {
    navigate(`/doc/${encodeURIComponent(slug)}`);
    setQuery('');
    setOpen(false);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && results[0]?.slug) go(results[0].slug);
    if (e.key === 'Escape') {
      setQuery('');
      setOpen(false);
    }
  }

  return (
    <div style={{ padding: '0 0.75rem', marginBottom: '1.25rem', position: 'relative' }}>
      <input
        type="search"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
        placeholder="Search docs…"
        aria-label="Search documentation"
        style={{
          width: '100%',
          boxSizing: 'border-box',
          padding: '0.4rem 0.6rem',
          fontSize: '0.8rem',
          border: '1px solid #e5e7eb',
          borderRadius: 6,
          background: '#fff',
          color: '#111827',
          fontFamily: 'inherit',
        }}
      />
      {open && query.trim() !== '' && (
        <ul
          role="listbox"
          style={{
            listStyle: 'none',
            margin: '0.25rem 0 0',
            padding: '0.25rem',
            position: 'absolute',
            zIndex: 20,
            left: 0,
            right: 0,
            background: '#fff',
            border: '1px solid #e5e7eb',
            borderRadius: 8,
            boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
            maxHeight: 320,
            overflowY: 'auto',
          }}
        >
          {results.length === 0 && (
            <li style={{ padding: '0.5rem 0.6rem', fontSize: '0.8rem', color: '#9ca3af' }}>
              No matching docs
            </li>
          )}
          {results.map((r) => (
            <li key={r.path}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => go(r.slug ?? '')}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '0.4rem 0.6rem',
                  borderRadius: 6,
                  font: 'inherit',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#f3f4f6')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                <div style={{ fontSize: '0.82rem', color: '#111827', fontWeight: 500 }}>
                  {r.title ?? r.slug}
                </div>
                <div style={{ fontSize: '0.68rem', color: '#9ca3af' }}>{r.section}</div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
