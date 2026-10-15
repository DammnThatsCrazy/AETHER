import envJson from '../../../../../docs/_generated/env.json';

interface EnvVar {
  name: string;
  default: string;
  description: string;
  required_in_production: boolean;
}

interface EnvCategory {
  name: string;
  vars: EnvVar[];
}

export default function EnvVars() {
  const categories = (envJson as { categories: EnvCategory[] }).categories;
  const total = categories.reduce((n, c) => n + c.vars.length, 0);
  const required = categories.flatMap((c) => c.vars).filter((v) => v.required_in_production).length;

  return (
    <div style={{ maxWidth: 860, margin: '2rem auto', padding: '0 1.5rem', fontFamily: 'system-ui, sans-serif' }}>
      <header style={{ marginBottom: '2rem', borderBottom: '1px solid #e5e7eb', paddingBottom: '1rem' }}>
        <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#6b7280', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Generated · {envJson.generated_from}
        </div>
        <h1 style={{ margin: 0, fontSize: '1.75rem', fontWeight: 700 }}>Environment Variables</h1>
        <p style={{ color: '#6b7280', marginTop: '0.5rem', marginBottom: 0 }}>
          {total} variables · <span style={{ color: '#dc2626', fontWeight: 600 }}>{required} required in production</span>
        </p>
      </header>

      {categories.map((cat) => (
        <section key={cat.name} style={{ marginBottom: '2rem' }}>
          <h2 style={{ fontSize: '0.875rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#6b7280', borderBottom: '1px solid #e5e7eb', paddingBottom: '0.4rem', marginBottom: '0.75rem' }}>
            {cat.name}
          </h2>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
            <thead>
              <tr style={{ background: '#f9fafb' }}>
                <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 600, color: '#374151', borderBottom: '1px solid #e5e7eb', width: '30%' }}>Variable</th>
                <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 600, color: '#374151', borderBottom: '1px solid #e5e7eb', width: '15%' }}>Default</th>
                <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 600, color: '#374151', borderBottom: '1px solid #e5e7eb' }}>Description</th>
                <th style={{ textAlign: 'center', padding: '0.5rem 0.75rem', fontWeight: 600, color: '#374151', borderBottom: '1px solid #e5e7eb', width: '80px' }}>Prod req.</th>
              </tr>
            </thead>
            <tbody>
              {cat.vars.map((v, i) => (
                <tr key={v.name} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb' }}>
                  <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #f3f4f6', fontFamily: 'monospace', fontSize: '0.8rem', fontWeight: 600, color: '#111', wordBreak: 'break-all' }}>{v.name}</td>
                  <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #f3f4f6', fontFamily: 'monospace', fontSize: '0.8rem', color: '#6b7280' }}>{v.default || '—'}</td>
                  <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #f3f4f6', color: '#374151' }}>{v.description || '—'}</td>
                  <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #f3f4f6', textAlign: 'center' }}>
                    {v.required_in_production ? (
                      <span style={{ color: '#dc2626', fontWeight: 700 }}>✓</span>
                    ) : (
                      <span style={{ color: '#d1d5db' }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}
