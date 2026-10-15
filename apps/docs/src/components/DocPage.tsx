import type { ComponentType } from 'react';
import type { DocFrontmatter, Status, Visibility } from '../lib/frontmatter';

interface Props {
  Content: ComponentType;
  frontmatter: DocFrontmatter;
}

const STATUS_LABEL: Record<Status, string> = {
  stable: '',
  beta: 'Beta',
  experimental: 'Experimental',
  deprecated: 'Deprecated',
};

const STATUS_COLOR: Record<Status, string> = {
  stable: 'transparent',
  beta: '#d97706',
  experimental: '#7c3aed',
  deprecated: '#dc2626',
};

const TIER_LABEL: Record<Visibility, string> = {
  P: 'Public',
  C: 'Customer',
  I: 'Internal',
};

export default function DocPage({ Content, frontmatter }: Props) {
  const { title, status, visibility, estimated_read_minutes } = frontmatter;
  const statusLabel = STATUS_LABEL[status];

  return (
    <article
      style={{
        fontFamily: 'system-ui, -apple-system, sans-serif',
        maxWidth: 720,
        margin: '4rem auto',
        padding: '0 1.5rem',
        lineHeight: 1.7,
        color: '#1a1a1a',
      }}
    >
      <header style={{ marginBottom: '2rem', borderBottom: '1px solid #e5e7eb', paddingBottom: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              padding: '0.2rem 0.5rem',
              borderRadius: 4,
              background: '#f0f4ff',
              color: '#3b4ea8',
              letterSpacing: '0.04em',
            }}
          >
            {TIER_LABEL[visibility]}
          </span>
          {statusLabel && (
            <span
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                padding: '0.2rem 0.5rem',
                borderRadius: 4,
                background: `${STATUS_COLOR[status]}22`,
                color: STATUS_COLOR[status],
                letterSpacing: '0.04em',
              }}
            >
              {statusLabel}
            </span>
          )}
          {estimated_read_minutes && (
            <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>
              {estimated_read_minutes} min read
            </span>
          )}
        </div>
        <h1 style={{ margin: 0, fontSize: '2rem', fontWeight: 700, lineHeight: 1.25 }}>
          {title}
        </h1>
      </header>

      <div
        style={{
          lineHeight: 1.75,
        }}
      >
        <Content />
      </div>
    </article>
  );
}
