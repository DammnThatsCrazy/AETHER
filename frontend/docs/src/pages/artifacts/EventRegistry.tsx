import eventsJson from '../../../../../docs/_generated/events.json';

interface AetherEvent {
  name: string;
  family: string;
  consent_purpose: string;
  section_comment: string;
}

const FAMILY_COLORS: Record<string, string> = {
  core: '#1d4ed8',
  identity: '#7c3aed',
  consent: '#16a34a',
  commerce: '#d97706',
  wallet: '#0891b2',
  agent: '#db2777',
  x402: '#9333ea',
};

const PURPOSE_COLORS: Record<string, string> = {
  analytics: '#1d4ed8',
  commerce: '#d97706',
  marketing: '#db2777',
  agent: '#9333ea',
  web3: '#0891b2',
};

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      display: 'inline-block', padding: '0.15rem 0.5rem',
      borderRadius: 4, fontSize: '0.75rem', fontWeight: 600,
      background: `${color}18`, color, letterSpacing: '0.02em',
    }}>
      {label}
    </span>
  );
}

export default function EventRegistry() {
  const events = (eventsJson as { events: AetherEvent[] }).events;
  const families = (eventsJson as { families: string[] }).families;

  return (
    <div style={{ maxWidth: 860, margin: '2rem auto', padding: '0 1.5rem', fontFamily: 'system-ui, sans-serif' }}>
      <header style={{ marginBottom: '2rem', borderBottom: '1px solid #e5e7eb', paddingBottom: '1rem' }}>
        <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#6b7280', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Generated · {eventsJson.generated_from}
        </div>
        <h1 style={{ margin: 0, fontSize: '1.75rem', fontWeight: 700 }}>Event Registry</h1>
        <p style={{ color: '#6b7280', marginTop: '0.5rem', marginBottom: 0 }}>
          {events.length} events across {families.length} families
        </p>
      </header>

      {families.map((family) => {
        const familyEvents = events.filter((e) => e.family === family);
        if (familyEvents.length === 0) return null;
        const color = FAMILY_COLORS[family] ?? '#6b7280';
        return (
          <section key={family} style={{ marginBottom: '2rem' }}>
            <h2 style={{ fontSize: '0.875rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#6b7280', borderBottom: '1px solid #e5e7eb', paddingBottom: '0.4rem', marginBottom: '0.75rem' }}>
              <Badge label={family} color={color} />
              <span style={{ marginLeft: '0.5rem', color: '#9ca3af', fontSize: '0.8rem', fontWeight: 400 }}>{familyEvents.length} events</span>
            </h2>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ background: '#f9fafb' }}>
                  <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 600, color: '#374151', borderBottom: '1px solid #e5e7eb' }}>Event</th>
                  <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 600, color: '#374151', borderBottom: '1px solid #e5e7eb' }}>Consent purpose</th>
                  <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 600, color: '#374151', borderBottom: '1px solid #e5e7eb' }}>Notes</th>
                </tr>
              </thead>
              <tbody>
                {familyEvents.map((ev, i) => (
                  <tr key={ev.name} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb' }}>
                    <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #f3f4f6', fontFamily: 'monospace', fontWeight: 600, color: '#111' }}>{ev.name}</td>
                    <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #f3f4f6' }}>
                      <Badge label={ev.consent_purpose} color={PURPOSE_COLORS[ev.consent_purpose] ?? '#6b7280'} />
                    </td>
                    <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #f3f4f6', color: '#6b7280' }}>{ev.section_comment}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        );
      })}
    </div>
  );
}
