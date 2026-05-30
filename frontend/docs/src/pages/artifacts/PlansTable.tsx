import plansJson from '../../../../../docs/_generated/plans.json';

interface PlanPricing {
  option_a: string;
  option_b: string;
  option_c: string;
}

interface Plan {
  plan_id: string;
  display_name: string;
  target_user: string;
  monthly_quota: number;
  member_cap: number;
  burst_rpm: number;
  blended_overage_per_1k: string;
  service_count: number;
  pricing: PlanPricing;
}

function fmtNum(n: number): string {
  return n.toLocaleString('en-US');
}

function fmtMoney(s: string): string {
  const n = Number(s);
  if (!Number.isFinite(n)) return s;
  return `$${n.toLocaleString('en-US')}`;
}

export default function PlansTable() {
  const plans = (plansJson as { plans: Plan[] }).plans;

  return (
    <div style={{ maxWidth: 1040, margin: '2rem auto', padding: '0 1.5rem', fontFamily: 'system-ui, sans-serif' }}>
      <header style={{ marginBottom: '2rem', borderBottom: '1px solid #e5e7eb', paddingBottom: '1rem' }}>
        <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#6b7280', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Generated · {plansJson.generated_from}
        </div>
        <h1 style={{ margin: 0, fontSize: '1.75rem', fontWeight: 700 }}>Plans &amp; Pricing</h1>
        <p style={{ color: '#6b7280', marginTop: '0.5rem', marginBottom: 0 }}>
          {plans.length} subscription plans · option_a / option_b / option_c reflect annual / quarterly / monthly cadences
        </p>
      </header>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem', minWidth: 880 }}>
          <thead>
            <tr style={{ background: '#f9fafb' }}>
              <th style={th}>Plan</th>
              <th style={th}>Target</th>
              <th style={thNum}>Quota / mo</th>
              <th style={thNum}>Members</th>
              <th style={thNum}>Burst RPM</th>
              <th style={thNum}>Overage / 1k</th>
              <th style={thNum}>Services</th>
              <th style={thNum}>Annual</th>
              <th style={thNum}>Quarterly</th>
              <th style={thNum}>Monthly</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((p, i) => (
              <tr key={p.plan_id} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb' }}>
                <td style={td}>
                  <div style={{ fontWeight: 700, color: '#111' }}>{p.display_name}</div>
                  <div style={{ fontSize: '0.7rem', color: '#9ca3af', fontFamily: 'monospace' }}>{p.plan_id}</div>
                </td>
                <td style={td}>{p.target_user}</td>
                <td style={tdNum}>{fmtNum(p.monthly_quota)}</td>
                <td style={tdNum}>{p.member_cap}</td>
                <td style={tdNum}>{fmtNum(p.burst_rpm)}</td>
                <td style={tdNum}>${p.blended_overage_per_1k}</td>
                <td style={tdNum}>{p.service_count}</td>
                <td style={tdNum}>{fmtMoney(p.pricing.option_a)}</td>
                <td style={tdNum}>{fmtMoney(p.pricing.option_b)}</td>
                <td style={tdNum}>{fmtMoney(p.pricing.option_c)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const th: React.CSSProperties = {
  textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 600,
  color: '#374151', borderBottom: '1px solid #e5e7eb',
};
const thNum: React.CSSProperties = { ...th, textAlign: 'right' };
const td: React.CSSProperties = {
  padding: '0.5rem 0.75rem', borderBottom: '1px solid #f3f4f6', color: '#374151',
};
const tdNum: React.CSSProperties = {
  ...td, textAlign: 'right', fontFamily: 'monospace', fontSize: '0.8rem',
};
