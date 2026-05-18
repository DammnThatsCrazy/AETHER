import { useState } from 'react';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { AetherBadge } from '../../components/ui/aether-badge';

type Tab = 'workspace' | 'team' | 'security' | 'deployment' | 'integrations' | 'billing';

const INTEGRATIONS = [
  { id: 'shopify',   name: 'Shopify',   status: 'connected', events: '12.4k/d', icon: '⬡' },
  { id: 'stripe',    name: 'Stripe',    status: 'connected', events: '8.2k/d',  icon: '⬡' },
  { id: 'kafka',     name: 'Kafka',     status: 'connected', events: '—',       icon: '⬡' },
  { id: 'snowflake', name: 'Snowflake', status: 'connected', events: '—',       icon: '⬡' },
  { id: 'segment',   name: 'Segment',   status: 'pending',   events: '—',       icon: '⬡' },
  { id: 'mixpanel',  name: 'Mixpanel',  status: 'none',      events: '—',       icon: '⬡' },
];

const TEAM_MEMBERS = [
  { id: 'op1', name: 'Operator 01', email: 'op1@olympus.internal', role: 'Admin',   lastActive: '2m ago' },
  { id: 'an1', name: 'Analyst 01',  email: 'an1@olympus.internal', role: 'Analyst', lastActive: '14m ago' },
  { id: 'an2', name: 'Analyst 02',  email: 'an2@olympus.internal', role: 'Analyst', lastActive: '1h ago' },
  { id: 'an3', name: 'Analyst 03',  email: 'an3@olympus.internal', role: 'Viewer',  lastActive: '3h ago' },
];

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>('workspace');

  const TABS: Array<{ id: Tab; label: string }> = [
    { id: 'workspace',    label: 'Workspace' },
    { id: 'team',         label: 'Team' },
    { id: 'security',     label: 'Security' },
    { id: 'deployment',   label: 'Deployment' },
    { id: 'integrations', label: 'Integrations' },
    { id: 'billing',      label: 'Billing' },
  ];

  return (
    <div className="px-6 py-5">
      <PageHeader eyebrow="Operations" title="Settings" subtitle="Workspace, team, security, and deployment configuration" />

      <div className="flex items-center gap-0 border-b border-border-default mb-6">
        {TABS.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={cn('px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === tab.id ? 'border-b-signal text-steel' : 'border-b-transparent text-text-muted hover:text-text-primary')}>
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'workspace' && (
        <div className="max-w-lg space-y-4">
          {[
            { label: 'Organization', value: 'Olympus' },
            { label: 'Workspace', value: 'Production' },
            { label: 'Region', value: 'us-east-1' },
            { label: 'Plan', value: 'Enterprise' },
            { label: 'Version', value: 'v8.8.0' },
          ].map(item => (
            <div key={item.label} className="flex items-center justify-between panel px-4 py-3">
              <span className="text-sm text-text-secondary">{item.label}</span>
              <span className="font-mono text-sm text-text-primary">{item.value}</span>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'team' && (
        <div className="max-w-2xl">
          <div className="flex items-center justify-between mb-3">
            <p className="label-eyebrow">Team members ({TEAM_MEMBERS.length})</p>
            <button className="text-xs px-3 py-1.5 rounded bg-signal text-stone-white font-medium hover:bg-signal/90 transition-colors">+ Invite</button>
          </div>
          <div className="panel overflow-hidden">
            <div className="divide-y divide-border-subtle">
              {TEAM_MEMBERS.map(m => (
                <div key={m.id} className="flex items-center justify-between px-4 py-3 hover:bg-surface-overlay transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="w-7 h-7 rounded-full bg-signal/10 border border-signal/20 flex items-center justify-center">
                      <span className="font-mono text-2xs text-steel">{m.name.slice(0, 2).toUpperCase()}</span>
                    </div>
                    <div>
                      <p className="text-sm text-text-primary">{m.name}</p>
                      <p className="font-mono text-2xs text-text-muted">{m.email}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <AetherBadge variant={m.role === 'Admin' ? 'info' : 'default'}>{m.role}</AetherBadge>
                    <span className="font-mono text-2xs text-text-muted">{m.lastActive}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'integrations' && (
        <div className="grid grid-cols-3 gap-3 max-w-3xl">
          {INTEGRATIONS.map(int => (
            <div key={int.id} className="panel p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-text-primary">{int.name}</span>
                <AetherBadge variant={int.status === 'connected' ? 'success' : int.status === 'pending' ? 'warning' : 'default'}>
                  {int.status}
                </AetherBadge>
              </div>
              {int.events !== '—' && (
                <p className="font-mono text-xs text-text-muted">{int.events}</p>
              )}
              <button className={cn('mt-3 w-full text-xs px-3 py-1.5 rounded border transition-colors font-medium',
                int.status === 'connected'
                  ? 'border-border-default text-text-secondary hover:text-text-primary'
                  : 'border-signal/30 text-steel hover:bg-signal/5')}>
                {int.status === 'connected' ? 'Configure' : 'Connect'}
              </button>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'deployment' && (
        <div className="max-w-lg space-y-3">
          {[
            { label: 'Deployment mode', value: 'Cloud (managed)', icon: '☁' },
            { label: 'Region', value: 'us-east-1 (Virginia)', icon: '◎' },
            { label: 'Tenant isolation', value: 'Dedicated VPC', icon: '◧' },
            { label: 'Encryption', value: 'AES-256 at rest, TLS 1.3 in transit', icon: '⚿' },
            { label: 'Backup', value: 'Continuous + daily snapshots', icon: '⊟' },
          ].map(item => (
            <div key={item.label} className="flex items-center justify-between panel px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="font-mono text-text-muted">{item.icon}</span>
                <span className="text-sm text-text-secondary">{item.label}</span>
              </div>
              <span className="text-sm text-text-primary">{item.value}</span>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'security' && (
        <div className="max-w-lg space-y-4">
          {[
            { label: 'SSO', value: 'Okta (SAML 2.0)', status: 'active' },
            { label: 'MFA', value: 'Required for all users', status: 'active' },
            { label: 'Session timeout', value: '8 hours', status: null },
            { label: 'IP allowlist', value: '4 ranges configured', status: 'active' },
            { label: 'Audit logging', value: '100% coverage', status: 'active' },
          ].map(item => (
            <div key={item.label} className="flex items-center justify-between panel px-4 py-3">
              <span className="text-sm text-text-secondary">{item.label}</span>
              <div className="flex items-center gap-2">
                <span className="text-sm text-text-primary">{item.value}</span>
                {item.status && <span className="text-verdant font-mono text-xs">✓</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'billing' && (
        <div className="flex flex-col items-center justify-center py-20 text-text-muted">
          <p className="text-sm">Enterprise billing managed by your account team</p>
        </div>
      )}
    </div>
  );
}
