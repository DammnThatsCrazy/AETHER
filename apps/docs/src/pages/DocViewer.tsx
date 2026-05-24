import { useEffect, useState, type ComponentType } from 'react';
import { Link, useParams } from 'react-router-dom';
import DocPage from '../components/DocPage';
import { getContentLoader } from '../lib/docs-loader';
import type { DocFrontmatter } from '../lib/frontmatter';

type DocModule = { default: ComponentType; frontmatter: DocFrontmatter };

export default function DocViewer() {
  const { slug = '' } = useParams<{ slug: string }>();
  const [mod, setMod] = useState<DocModule | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setMod(null);
    setError(null);
    const loader = getContentLoader(decodeURIComponent(slug));
    if (!loader) {
      setError(`No rendered content for "${slug}" yet — this doc is queued for MDX authoring.`);
      return;
    }
    loader()
      .then((m) => setMod(m))
      .catch((e: unknown) => setError(String(e)));
  }, [slug]);

  if (error) {
    return (
      <div
        style={{
          fontFamily: 'system-ui, -apple-system, sans-serif',
          maxWidth: 720,
          margin: '4rem auto',
          padding: '0 1.5rem',
        }}
      >
        <Link to="/" style={{ color: '#6b7280', fontSize: '0.875rem' }}>
          ← All docs
        </Link>
        <div
          style={{
            marginTop: '2rem',
            padding: '1.25rem',
            background: '#fff7ed',
            border: '1px solid #fed7aa',
            borderRadius: 6,
            color: '#92400e',
          }}
        >
          {error}
        </div>
      </div>
    );
  }

  if (!mod) {
    return (
      <div
        style={{
          fontFamily: 'system-ui, sans-serif',
          maxWidth: 720,
          margin: '4rem auto',
          padding: '0 1.5rem',
          color: '#6b7280',
        }}
      >
        Loading…
      </div>
    );
  }

  return (
    <div>
      <div
        style={{
          fontFamily: 'system-ui, sans-serif',
          maxWidth: 720,
          margin: '1rem auto',
          padding: '0 1.5rem',
        }}
      >
        <Link to="/" style={{ color: '#6b7280', fontSize: '0.875rem', textDecoration: 'none' }}>
          ← All docs
        </Link>
      </div>
      <DocPage Content={mod.default} frontmatter={mod.frontmatter} />
    </div>
  );
}
