import providersJson from '../../../../../docs/_generated/providers.json';

interface Provider {
  name: string;
  class: string;
}

interface ProviderCategory {
  enum_name: string;
  value: string;
  providers: Provider[];
}

function humanize(value: string): string {
  return value
    .split('_')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(' ');
}

export default function Providers() {
  const categories = (providersJson as { categories: ProviderCategory[] }).categories;
  const totalProviders = categories.reduce((n, c) => n + c.providers.length, 0);

  return (
    <div style={{ maxWidth: 980, margin: '2rem auto', padding: '0 1.5rem', fontFamily: 'system-ui, sans-serif' }}>
      <header style={{ marginBottom: '2rem', borderBottom: '1px solid #e5e7eb', paddingBottom: '1rem' }}>
        <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#6b7280', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Generated · {providersJson.generated_from}
        </div>
        <h1 style={{ margin: 0, fontSize: '1.75rem', fontWeight: 700 }}>Provider Matrix</h1>
        <p style={{ color: '#6b7280', marginTop: '0.5rem', marginBottom: 0 }}>
          {totalProviders} providers across {categories.length} categories
        </p>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1.25rem' }}>
        {categories.map((cat) => (
          <section
            key={cat.enum_name}
            style={{
              border: '1px solid #e5e7eb',
              borderRadius: 8,
              padding: '1rem',
              background: '#fff',
            }}
          >
            <h2
              style={{
                fontSize: '0.875rem',
                fontWeight: 700,
                margin: 0,
                marginBottom: '0.25rem',
                color: '#111',
              }}
            >
              {humanize(cat.value)}
            </h2>
            <div
              style={{
                fontFamily: 'monospace',
                fontSize: '0.7rem',
                color: '#9ca3af',
                marginBottom: '0.75rem',
              }}
            >
              {cat.enum_name}
            </div>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: '0.4rem' }}>
              {cat.providers.map((p) => (
                <li
                  key={p.name}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                    padding: '0.3rem 0.5rem',
                    background: '#f9fafb',
                    borderRadius: 4,
                  }}
                >
                  <span style={{ fontWeight: 600, color: '#111', fontSize: '0.875rem' }}>{p.name}</span>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.72rem', color: '#6b7280' }}>{p.class}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
