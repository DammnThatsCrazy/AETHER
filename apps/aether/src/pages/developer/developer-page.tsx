import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { StatCard } from '../../components/ui/stat-card';
import { AetherBadge } from '../../components/ui/aether-badge';
import { LiveIndicator } from '../../components/ui/live-indicator';

type Tab = 'overview' | 'api-console' | 'sdk' | 'webhooks' | 'query' | 'logs' | 'schema';

const SDK_EXAMPLES: Record<string, string> = {
  javascript: `// Install
npm install @aether/sdk

// Initialize
import { Aether } from '@aether/sdk';

const aether = new Aether({
  apiKey: 'ak_live_…',
  workspace: 'olympus',
});

// Track events
await aether.track('purchase', {
  entityId: 'usr_9k2f',
  amount: 149.99,
  currency: 'USD',
  itemIds: ['sku_abc', 'sku_xyz'],
});

// Identify entities
await aether.identify({
  entityId: 'usr_9k2f',
  traits: { email: 'user@…', plan: 'pro' },
});`,

  python: `# Install
pip install aether-sdk

# Initialize
from aether import Aether

aether = Aether(
    api_key="ak_live_…",
    workspace="olympus",
)

# Track events
aether.track("purchase", {
    "entity_id": "usr_9k2f",
    "amount": 149.99,
    "currency": "USD",
})

# Identify
aether.identify({
    "entity_id": "usr_9k2f",
    "traits": {"email": "user@…"},
})`,

  curl: `# Track event
curl -X POST https://api.aether.dev/v1/events \\
  -H "Authorization: Bearer ak_live_…" \\
  -H "Content-Type: application/json" \\
  -d '{
    "type": "purchase",
    "entityId": "usr_9k2f",
    "properties": {
      "amount": 149.99,
      "currency": "USD"
    }
  }'

# Query entities
curl https://api.aether.dev/v1/entities/usr_9k2f \\
  -H "Authorization: Bearer ak_live_…"`,
};

const API_ENDPOINTS = [
  { method: 'POST', path: '/v1/events',           desc: 'Ingest events', auth: 'required' },
  { method: 'POST', path: '/v1/entities/identify',desc: 'Identify entity', auth: 'required' },
  { method: 'GET',  path: '/v1/entities/:id',     desc: 'Get entity profile', auth: 'required' },
  { method: 'GET',  path: '/v1/graph/neighbors',  desc: 'Get entity neighbors', auth: 'required' },
  { method: 'POST', path: '/v1/graph/query',      desc: 'Graph query (GQL)', auth: 'required' },
  { method: 'GET',  path: '/v1/intelligence/feed',desc: 'Intelligence feed', auth: 'required' },
  { method: 'POST', path: '/v1/investigations',   desc: 'Create investigation', auth: 'required' },
  { method: 'GET',  path: '/v1/audit/events',     desc: 'Audit log', auth: 'required' },
  { method: 'GET',  path: '/v1/health',           desc: 'Health check', auth: 'none' },
];

const WEBHOOKS = [
  { id: 'wh-001', url: 'https://api.example.com/aether/events', events: ['entity.risk_escalated', 'cluster.detected'], status: 'active', lastDelivery: '2m ago' },
  { id: 'wh-002', url: 'https://slack.example.com/hooks/…', events: ['alert.firing', 'investigation.opened'], status: 'active', lastDelivery: '14m ago' },
];

const METHOD_STYLE: Record<string, string> = {
  GET:    'text-verdant',
  POST:   'text-signal',
  PUT:    'text-amber',
  DELETE: 'text-ember',
  PATCH:  'text-solar',
};

export function DeveloperPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>('overview');
  const [sdkLang, setSdkLang] = useState<'javascript' | 'python' | 'curl'>('javascript');
  const [apiKey] = useState('ak_live_••••••••••••••••2x8k');

  const TABS: Array<{ id: Tab; label: string }> = [
    { id: 'overview',   label: 'Overview' },
    { id: 'api-console',label: 'API Console' },
    { id: 'sdk',        label: 'SDK' },
    { id: 'webhooks',   label: 'Webhooks' },
    { id: 'query',      label: 'Query Explorer' },
    { id: 'logs',       label: 'API Logs' },
    { id: 'schema',     label: 'Schema' },
  ];

  return (
    <div className="px-6 py-5">
      <PageHeader
        eyebrow="Developer"
        title="Developer Console"
        subtitle="API, SDK, webhooks, and query infrastructure"
        actions={
          <div className="flex items-center gap-2">
            <LiveIndicator />
            <button className="text-xs px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors">
              API docs →
            </button>
          </div>
        }
      />

      <div className="grid grid-cols-4 gap-3 mb-5">
        <StatCard label="API calls / h"    value="48.2k"  delta={{ value: '8%', positive: true }}  mono />
        <StatCard label="Error rate"       value="0.02%"  accent="success" mono />
        <StatCard label="Avg latency"      value="18ms"   accent="success" mono sub="p50" />
        <StatCard label="Active webhooks"  value={WEBHOOKS.length} mono />
      </div>

      <div className="flex items-center gap-0 border-b border-border-default mb-4">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap',
              activeTab === tab.id
                ? 'border-b-signal text-steel'
                : 'border-b-transparent text-text-muted hover:text-text-primary',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && (
        <div className="grid grid-cols-3 gap-4">
          {/* API Key */}
          <div className="col-span-3 panel p-4">
            <p className="label-eyebrow mb-2">API Key</p>
            <div className="flex items-center gap-3">
              <code className="flex-1 font-mono text-sm text-text-accent">{apiKey}</code>
              <button className="text-xs px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary transition-colors">
                Copy
              </button>
              <button className="text-xs px-3 py-1.5 rounded border border-ember/30 text-ember hover:bg-ember/5 transition-colors">
                Rotate
              </button>
            </div>
          </div>

          {/* SDK quickstart */}
          <div className="col-span-2 panel overflow-hidden">
            <div className="panel-header">
              <span className="panel-title">SDK Quickstart</span>
              <div className="flex items-center gap-1">
                {(['javascript', 'python', 'curl'] as const).map(lang => (
                  <button
                    key={lang}
                    onClick={() => setSdkLang(lang)}
                    className={cn(
                      'px-2 py-1 rounded text-2xs font-mono font-medium transition-colors',
                      sdkLang === lang ? 'bg-signal/10 text-steel' : 'text-text-muted hover:text-text-primary',
                    )}
                  >
                    {lang}
                  </button>
                ))}
              </div>
            </div>
            <pre className="m-4 text-xs overflow-x-auto max-h-64 overflow-y-auto">
              <code>{SDK_EXAMPLES[sdkLang]}</code>
            </pre>
          </div>

          {/* Endpoints */}
          <div className="panel overflow-hidden">
            <div className="panel-header"><span className="panel-title">API Surface</span></div>
            <div className="divide-y divide-border-subtle max-h-80 overflow-y-auto">
              {API_ENDPOINTS.map(ep => (
                <div key={ep.path} className="flex items-center gap-3 px-3 py-2 hover:bg-surface-overlay cursor-pointer transition-colors">
                  <span className={cn('font-mono text-2xs font-medium w-10 flex-shrink-0', METHOD_STYLE[ep.method])}>{ep.method}</span>
                  <span className="font-mono text-2xs text-text-primary flex-1 truncate">{ep.path}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'sdk' && (
        <div className="space-y-4 max-w-3xl">
          <div className="grid grid-cols-3 gap-3 mb-4">
            {[
              { lang: 'JavaScript/TypeScript', pkg: '@aether/sdk', version: '8.8.0', downloads: '12k/mo' },
              { lang: 'Python',               pkg: 'aether-sdk',   version: '8.8.0', downloads: '4k/mo' },
              { lang: 'Go',                   pkg: 'aether-go',    version: '8.8.0', downloads: '2k/mo' },
            ].map(sdk => (
              <div key={sdk.lang} className="panel p-4">
                <p className="text-sm font-medium text-text-primary mb-1">{sdk.lang}</p>
                <code className="text-2xs">{sdk.pkg}</code>
                <div className="flex items-center justify-between mt-2">
                  <AetherBadge variant="success" mono>{sdk.version}</AetherBadge>
                  <span className="font-mono text-2xs text-text-muted">{sdk.downloads}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="panel overflow-hidden">
            <div className="panel-header">
              <span className="panel-title">Code example</span>
              <div className="flex items-center gap-1">
                {(['javascript', 'python', 'curl'] as const).map(lang => (
                  <button key={lang} onClick={() => setSdkLang(lang)} className={cn('px-2 py-1 rounded text-2xs font-mono transition-colors', sdkLang === lang ? 'bg-signal/10 text-steel' : 'text-text-muted hover:text-text-primary')}>
                    {lang}
                  </button>
                ))}
              </div>
            </div>
            <pre className="m-4 max-h-96 overflow-auto"><code>{SDK_EXAMPLES[sdkLang]}</code></pre>
          </div>
        </div>
      )}

      {activeTab === 'webhooks' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between mb-2">
            <p className="label-eyebrow">Configured webhooks</p>
            <button className="text-xs px-3 py-1.5 rounded bg-signal text-stone-white font-medium hover:bg-signal/90 transition-colors">+ Add webhook</button>
          </div>
          {WEBHOOKS.map(wh => (
            <div key={wh.id} className="panel p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <AetherBadge variant="success">{wh.status}</AetherBadge>
                    <span className="font-mono text-2xs text-text-muted">{wh.id}</span>
                  </div>
                  <code className="text-sm">{wh.url}</code>
                  <div className="flex items-center gap-2 mt-2">
                    {wh.events.map(e => <AetherBadge key={e} variant="default" mono>{e}</AetherBadge>)}
                  </div>
                  <p className="text-xs text-text-muted mt-1">Last delivery: {wh.lastDelivery}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button className="text-xs px-2 py-1 rounded border border-border-default text-text-muted hover:text-text-primary transition-colors">Test</button>
                  <button className="text-xs px-2 py-1 rounded border border-border-default text-text-muted hover:text-text-primary transition-colors">Edit</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'api-console' && (
        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2 panel overflow-hidden">
            <div className="panel-header"><span className="panel-title">Request</span></div>
            <div className="p-4 space-y-3">
              <div className="flex items-center gap-2">
                <select className="bg-surface-overlay border border-border-default rounded px-2 py-1.5 text-xs font-mono text-text-primary outline-none">
                  {['GET', 'POST', 'PUT', 'DELETE'].map(m => <option key={m}>{m}</option>)}
                </select>
                <input
                  defaultValue="/v1/entities/usr_9k2f"
                  className="flex-1 bg-surface-raised border border-border-default rounded px-3 py-1.5 text-sm font-mono text-text-primary outline-none focus:border-signal transition-colors"
                />
                <button className="px-4 py-1.5 rounded bg-signal text-stone-white text-xs font-medium hover:bg-signal/90 transition-colors">
                  Send
                </button>
              </div>
              <div>
                <p className="label-eyebrow mb-1.5">Request body</p>
                <textarea
                  defaultValue='{\n  "entityId": "usr_9k2f"\n}'
                  className="w-full h-28 bg-deep-stone-dark border border-border-default rounded p-3 font-mono text-xs text-text-primary outline-none resize-none"
                />
              </div>
            </div>
          </div>
          <div className="panel overflow-hidden">
            <div className="panel-header">
              <span className="panel-title">Endpoints</span>
            </div>
            <div className="divide-y divide-border-subtle overflow-y-auto max-h-80">
              {API_ENDPOINTS.map(ep => (
                <div key={ep.path} className="flex items-center gap-2 px-3 py-2 hover:bg-surface-overlay cursor-pointer transition-colors">
                  <span className={cn('font-mono text-2xs w-10 font-medium flex-shrink-0', METHOD_STYLE[ep.method])}>{ep.method}</span>
                  <span className="font-mono text-2xs text-text-primary truncate">{ep.path}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {!['overview', 'sdk', 'webhooks', 'api-console'].includes(activeTab) && (
        <div className="flex flex-col items-center justify-center py-20 text-text-muted">
          <span className="font-mono text-3xl mb-3">⌘</span>
          <p className="text-sm capitalize">{activeTab.replace('-', ' ')}</p>
        </div>
      )}
    </div>
  );
}
