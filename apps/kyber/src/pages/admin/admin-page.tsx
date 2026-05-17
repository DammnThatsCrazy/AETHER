import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { PageWrapper } from '@kyber/components/layout';
import {
  Card, CardContent, CardHeader, CardTitle,
  Badge, Button, Tabs, TabsList, TabsTrigger, TabsContent,
  LoadingState, EmptyState, ScrollArea,
} from '@aether/ui';
import { formatRelativeTime } from '@kyber/lib/utils';
import { useTenantAdminView } from '@kyber/features/operator';

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function asList(v: unknown): unknown[] { return Array.isArray(v) ? v : []; }
function fmt(v: unknown, fallback = '—'): string { return v == null || v === '' ? fallback : String(v); }
function fmtUsd(v: unknown): string { return v == null ? '—' : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`; }

export function AdminPage() {
  const { tenantId = '' } = useParams<{ tenantId: string }>();
  const [inputTenantId, setInputTenantId] = useState(tenantId);
  const [activeTenantId, setActiveTenantId] = useState(tenantId);

  const { tenant, apiKeys, billingInfo, billingUsage, invoices, revokeApiKey } = useTenantAdminView(activeTenantId);

  const tenantData = asRecord(tenant.data);
  const keysList = asList(apiKeys.data);
  const billingData = asRecord(billingInfo.data);
  const usageData = asRecord(billingUsage.data);
  const invoiceList = asList(invoices.data);

  return (
    <PageWrapper title="Admin" subtitle="Tenant management, API keys, and billing">
      {/* Tenant lookup */}
      <div className="flex items-center gap-2 mb-4">
        <input
          type="text"
          value={inputTenantId}
          onChange={e => setInputTenantId(e.target.value)}
          placeholder="tenant_..."
          className="bg-surface-sunken border border-border-default rounded px-2 py-1.5 text-xs font-mono text-text-primary focus:outline-none focus:border-accent w-64"
          onKeyDown={e => e.key === 'Enter' && setActiveTenantId(inputTenantId)}
        />
        <Button size="sm" variant="secondary" onClick={() => setActiveTenantId(inputTenantId)}>
          Load
        </Button>
      </div>

      {!activeTenantId ? (
        <EmptyState title="Enter tenant ID" description="Enter a tenant ID above to load their data." icon="⌕" />
      ) : (
        <Tabs defaultValue="overview">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="keys">API Keys <Badge variant="default" className="ml-1.5">{keysList.length}</Badge></TabsTrigger>
            <TabsTrigger value="billing">Billing</TabsTrigger>
            <TabsTrigger value="invoices">Invoices</TabsTrigger>
          </TabsList>

          {/* Overview */}
          <TabsContent value="overview">
            {tenant.isLoading ? <LoadingState lines={4} /> : (
              <Card>
                <CardHeader><CardTitle className="font-mono text-xs">Tenant: {fmt(tenantData.name)}</CardTitle></CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 gap-2">
                    {Object.entries(tenantData).map(([k, v]) => (
                      <div key={k} className="flex flex-col text-xs font-mono">
                        <span className="text-text-muted capitalize">{k.replace(/_/g, ' ')}</span>
                        <span className="text-text-primary">{fmt(v)}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* API Keys */}
          <TabsContent value="keys">
            {apiKeys.isLoading ? <LoadingState lines={3} /> : keysList.length === 0 ? (
              <EmptyState title="No API keys" description="No API keys issued for this tenant." icon="○" />
            ) : (
              <div className="space-y-2">
                {keysList.map((k, i) => {
                  const key = asRecord(k);
                  const keyId = fmt(key.key_id ?? key.id);
                  return (
                    <Card key={i}>
                      <CardContent className="flex items-center justify-between py-2">
                        <div className="space-y-0.5">
                          <div className="text-xs font-mono font-bold text-text-primary">{fmt(key.name)}</div>
                          <div className="text-[10px] font-mono text-text-muted">{keyId} · created {formatRelativeTime(fmt(key.created_at))}</div>
                        </div>
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => revokeApiKey.mutate(keyId)}
                          disabled={revokeApiKey.isLoading}
                        >
                          Revoke
                        </Button>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </TabsContent>

          {/* Billing */}
          <TabsContent value="billing">
            {billingInfo.isLoading ? <LoadingState lines={3} /> : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Card>
                  <CardHeader><CardTitle className="font-mono text-xs">Plan</CardTitle></CardHeader>
                  <CardContent className="space-y-1">
                    {Object.entries(billingData).map(([k, v]) => (
                      <div key={k} className="flex justify-between text-xs font-mono">
                        <span className="text-text-muted capitalize">{k.replace(/_/g, ' ')}</span>
                        <span className="text-text-primary">{fmt(v)}</span>
                      </div>
                    ))}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="font-mono text-xs">Usage</CardTitle></CardHeader>
                  <CardContent className="space-y-1">
                    {Object.entries(usageData).map(([k, v]) => (
                      <div key={k} className="flex justify-between text-xs font-mono">
                        <span className="text-text-muted capitalize">{k.replace(/_/g, ' ')}</span>
                        <span className="text-text-primary">{fmt(v)}</span>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              </div>
            )}
          </TabsContent>

          {/* Invoices */}
          <TabsContent value="invoices">
            {invoices.isLoading ? <LoadingState lines={3} /> : invoiceList.length === 0 ? (
              <EmptyState title="No invoices" description="No invoices found." icon="○" />
            ) : (
              <div className="space-y-2">
                {invoiceList.map((inv, i) => {
                  const invoice = asRecord(inv);
                  return (
                    <Card key={i}>
                      <CardContent className="flex items-center justify-between py-2">
                        <div className="space-y-0.5">
                          <div className="text-xs font-mono font-bold text-text-primary">{fmt(invoice.invoice_id ?? invoice.id)}</div>
                          <div className="text-[10px] font-mono text-text-muted">{formatRelativeTime(fmt(invoice.created_at))}</div>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono text-text-primary">{fmtUsd(invoice.amount_usd ?? invoice.amount)}</span>
                          <Badge variant={fmt(invoice.status) === 'paid' ? 'success' : 'warning'}>{fmt(invoice.status)}</Badge>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </TabsContent>
        </Tabs>
      )}
    </PageWrapper>
  );
}
