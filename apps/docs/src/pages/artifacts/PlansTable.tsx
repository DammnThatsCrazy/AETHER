import plansJson from '../../../../../docs/_generated/plans.json';

interface PlanPricing {
  monthly: string;
  annual: string;
}

interface Plan {
  plan_id: string;
  display_name: string;
  stripe_product_id: string;
  target_user: string;
  monthly_quota: number;
  member_cap: number;
  burst_rpm: number;
  event_overage_per_1k: string;
  acu_overage_per_1k: string;
  managed_per_acu: string;
  byok_per_acu: string;
  service_count: number;
  pricing: PlanPricing;
}

function fmtNum(n: number): string {
  return n.toLocaleString('en-US');
}

function fmtMoney(s: string): string {
  const n = Number(s);
  if (!Number.isFinite(n) || n === 0) return s === '0' ? 'Free' : s;
  return `$${n.toLocaleString('en-US')}`;
}

export default function PlansTable() {
  const plans = (plansJson as unknown as { plans: Plan[] }).plans;

  return (
    <div style={{ maxWidth: 1100, margin: '2rem auto', padding: '0 1.5rem', fontFamily: 'system-ui, sans-serif' }}>
      <header style={{ marginBottom: '2rem', borderBottom: '1px solid #e5e7eb', paddingBottom: '1rem' }}>
        <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#6b7280', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Generated · {plansJson.generated_from}
        </div>
        <h1 style={{ margin: 0, fontSize: '1.75rem', fontWeight: 700 }}>Plans &amp; Pricing</h1>
        <p style={{ color: '#6b7280', marginTop: '0.5rem', marginBottom: 0 }}>
          {plans.length} plan tiers · monthly / annual pricing
        </p>
      </header>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem', minWidth: 960 }}>
          <thead>
            <tr style={{ background: '#f9fafb' }}>
              <th style={th}>Plan</th>
              <th style={th}>Target</th>
              <th style={thNum}>Quota / mo</th>
              <th style={thNum}>Members</th>
              <th style={thNum}>Burst RPM</th>
              <th style={thNum}>Event / 1k</th>
              <th style={thNum}>ACU / 1k</th>
              <th style={thNum}>Services</th>
              <th style={thNum}>Monthly</th>
              <th style={thNum}>Annual</th>
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
                <td style={tdNum}>{p.monthly_quota > 0 ? fmtNum(p.monthly_quota) : 'Custom'}</td>
                <td style={tdNum}>{p.member_cap > 0 ? p.member_cap : 'Contract'}</td>
                <td style={tdNum}>{p.burst_rpm > 0 ? fmtNum(p.burst_rpm) : 'Custom'}</td>
                <td style={tdNum}>{Number(p.event_overage_per_1k) > 0 ? `$${p.event_overage_per_1k}` : 'Custom'}</td>
                <td style={tdNum}>{Number(p.acu_overage_per_1k) > 0 ? `$${p.acu_overage_per_1k}` : 'Custom'}</td>
                <td style={tdNum}>{p.service_count}</td>
                <td style={tdNum}>{fmtMoney(p.pricing.monthly)}</td>
                <td style={tdNum}>{fmtMoney(p.pricing.annual)}</td>
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
