import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  DataTable, EmptyState, ErrorState, GlyphIcon, LoadingState, Modal,
  ModalBody, ModalFooter, ModalHeader, Skeleton, TerminalSeparator, useToast,
  formatCount, formatDate, useTimeContext, type TimeContext,
} from '@aether/ui';
import { PermissionGate } from '@kyber/features/permissions';
import {
  useTenantList, useTenantDetail, useTenantApiKeys, useTenantBilling,
  useTenantUsage, useTenantInvoices, useProvisionKey, useRevokeKey,
  useDeactivateTenant,
} from '@kyber/features/admin/use-tenant-admin';

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function fmtDate(iso: unknown, ctx: TimeContext): string {
  if (!iso) return '—';
  try { return formatDate(String(iso), ctx); } catch { return String(iso); }
}

function planVariant(plan: unknown): 'accent' | 'success' | 'warning' | 'default' {
  const p = String(plan ?? '').toLowerCase();
  if (p.includes('p4') || p.includes('enterprise')) return 'accent';
  if (p.includes('p3') || p.includes('pro')) return 'success';
  if (p.includes('p2')) return 'warning';
  return 'default';
}

// ── Tenant list ────────────────────────────────────────────────────────────────

type TenantRow = Record<string, unknown>;

function TenantListView() {
  const navigate = useNavigate();
  const timeCtx = useTimeContext();
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error } = useTenantList({ limit: 25, offset });
  const tenants = (data?.tenants ?? []) as TenantRow[];
  const total = data?.total ?? 0;

  return (
    <div className="p-6 max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold font-mono text-text-primary">Tenant Registry</h1>
          <p className="text-xs text-text-muted mt-0.5">All Aether tenants — {formatCount(total, timeCtx)} total</p>
        </div>
        <PermissionGate requires="canCommand">
          <Button variant="secondary" size="sm" onClick={() => navigate('/tenants/new')}>
            <GlyphIcon glyph="[+]" className="mr-1" /> New tenant
          </Button>
        </PermissionGate>
      </div>

      <TerminalSeparator />

      {isLoading ? (
        <div className="space-y-2">{[1,2,3,4,5].map(i => <Skeleton key={i} className="h-10" />)}</div>
      ) : error ? (
        <ErrorState title="Tenant registry unavailable" message={error} />
      ) : (
        <DataTable<TenantRow>
          keyExtractor={t => String(t.tenant_id ?? t.id ?? `${t.name ?? 'unknown'}:${t.created_at ?? 'undated'}`)}
          data={tenants}
          emptyMessage="No tenants found"
          columns={[
            {
              key: 'name',
              header: 'Tenant',
              render: t => (
                <button
                  onClick={() => navigate(`/tenants/${String(t.tenant_id ?? t.id)}`)}
                  className="text-accent underline hover:no-underline font-mono text-sm"
                >
                  {fmt(t.name ?? t.tenant_name)}
                </button>
              ),
            },
            {
              key: 'plan',
              header: 'Plan',
              render: t => <Badge variant={planVariant(t.plan ?? t.plan_tier)} size="sm">{fmt(t.plan ?? t.plan_tier)}</Badge>,
            },
            {
              key: 'status',
              header: 'Status',
              render: t => {
                const s = String(t.status ?? 'active');
                return <Badge variant={s === 'active' ? 'success' : s === 'suspended' ? 'warning' : 'danger'} size="sm">{s}</Badge>;
              },
            },
            { key: 'email', header: 'Contact', render: t => <span className="text-xs font-mono text-text-muted">{fmt(t.contact_email ?? t.email)}</span> },
            { key: 'created', header: 'Created', render: t => <span className="text-xs text-text-muted">{fmtDate(t.created_at, timeCtx)}</span> },
            {
              key: 'action',
              header: '',
              render: t => (
                <Button variant="ghost" size="sm" onClick={() => navigate(`/tenants/${String(t.tenant_id ?? t.id)}`)}>
                  <GlyphIcon glyph="[>]" />
                </Button>
              ),
            },
          ]}
        />
      )}

      {total > 25 && (
        <div className="flex items-center justify-between font-mono text-xs text-text-muted mt-3">
          <span>{offset + 1}–{Math.min(offset + 25, total)} of {total}</span>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>{'<'} Prev</Button>
            <Button variant="ghost" size="sm" disabled={offset + 25 >= total} onClick={() => setOffset(offset + 25)}>Next {'>'}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tenant detail ──────────────────────────────────────────────────────────────

function TenantDetailView({ tenantId }: { tenantId: string }) {
  const navigate = useNavigate();
  const { toast } = useToast();
  const timeCtx = useTimeContext();
  const [deactivateModal, setDeactivateModal] = useState(false);
  const [provisionModal, setProvisionModal] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');

  const { data: tenant, isLoading: tenantLoading, error: tenantError } = useTenantDetail(tenantId);
  const { data: apiKeys, isLoading: keysLoading } = useTenantApiKeys(tenantId);
  const { data: billing } = useTenantBilling(tenantId);
  const { data: usage } = useTenantUsage(tenantId);
  const { data: invoices, isLoading: invoicesLoading } = useTenantInvoices(tenantId);

  const deactivate = useDeactivateTenant();
  const provisionKey = useProvisionKey();
  const revokeKey = useRevokeKey();

  if (tenantLoading) return <LoadingState lines={8} className="p-6" />;
  if (tenantError) return <ErrorState title="Tenant unavailable" message={tenantError} />;
  if (!tenant) return <EmptyState title="Tenant not found" description={`No tenant exists with ID: ${tenantId}`} />;

  const t = asRec(tenant);
  const b = asRec(billing);
  const u = asRec(usage);
  const keys = Array.isArray(apiKeys) ? apiKeys as Record<string, unknown>[] : [];
  const inv = Array.isArray(invoices) ? invoices as Record<string, unknown>[] : [];

  async function handleDeactivate() {
    try {
      await deactivate.mutate(tenantId);
      toast.success('Tenant deactivated — session cache cleared');
      setDeactivateModal(false);
    } catch {
      toast.error('Deactivation failed');
    }
  }

  async function handleProvisionKey() {
    if (!newKeyName.trim()) return;
    try {
      await provisionKey.mutate({ tenantId, name: newKeyName.trim() });
      toast.success('API key provisioned');
      setProvisionModal(false);
      setNewKeyName('');
    } catch {
      toast.error('Key provisioning failed');
    }
  }

  async function handleRevokeKey(keyId: string) {
    try {
      await revokeKey.mutate(keyId);
      toast.success('Key revoked');
    } catch {
      toast.error('Revocation failed');
    }
  }

  return (
    <div className="p-6 max-w-4xl space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <button onClick={() => navigate('/tenants')} className="text-xs text-text-muted hover:text-accent font-mono">← Tenants</button>
          </div>
          <h1 className="text-lg font-bold font-mono text-text-primary">{fmt(t.name ?? t.tenant_name)}</h1>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs font-mono text-text-muted">{tenantId}</span>
            <Badge variant={planVariant(t.plan ?? t.plan_tier)} size="sm">{fmt(t.plan ?? t.plan_tier)}</Badge>
            <Badge variant={(String(t.status ?? 'active')) === 'active' ? 'success' : 'warning'} size="sm">{fmt(t.status ?? 'active')}</Badge>
          </div>
        </div>
        <PermissionGate requires="canCommand">
          <Button variant="danger" size="sm" onClick={() => setDeactivateModal(true)}>Deactivate</Button>
        </PermissionGate>
      </div>

      <TerminalSeparator />

      {/* Metrics grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Contact', value: fmt(t.contact_email ?? t.email) },
          { label: 'Created', value: fmtDate(t.created_at, timeCtx) },
          { label: 'Plan', value: fmt(b.plan_name ?? t.plan) },
          { label: 'Monthly events', value: fmt(u.events_this_period ?? u.monthly_events) },
        ].map(m => (
          <Card key={m.label}>
            <CardContent className="p-3">
              <div className="text-[10px] uppercase text-text-muted font-mono">{m.label}</div>
              <div className="text-sm font-mono text-text-primary mt-0.5 truncate">{m.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* API Keys */}
      <Card>
        <CardHeader>
          <CardTitle>API Keys</CardTitle>
          <PermissionGate requires="canApprove">
            <Button variant="secondary" size="sm" onClick={() => setProvisionModal(true)}>
              <GlyphIcon glyph="[+]" className="mr-1" /> Provision key
            </Button>
          </PermissionGate>
        </CardHeader>
        <CardContent>
          {keysLoading ? <LoadingState lines={2} /> : keys.length === 0 ? (
            <p className="text-xs text-text-muted font-mono">No API keys</p>
          ) : (
            <div className="space-y-2">
              {keys.map((k, i) => (
                <div key={String(k.id ?? i)} className="flex items-center justify-between border border-border-subtle rounded px-3 py-2">
                  <div>
                    <span className="text-sm font-mono text-text-primary">{fmt(k.name)}</span>
                    <span className="ml-3 text-xs font-mono text-text-muted">{fmt(k.prefix ?? k.key_prefix)}…</span>
                    {Boolean(k.last_used_at) && <span className="ml-3 text-[10px] text-text-muted">last used {fmtDate(k.last_used_at, timeCtx)}</span>}
                  </div>
                  <PermissionGate requires="canApprove">
                    <Button variant="ghost" size="sm" onClick={() => void handleRevokeKey(String(k.id))}>
                      Revoke
                    </Button>
                  </PermissionGate>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Billing */}
      {Boolean(billing) && (
        <Card>
          <CardHeader><CardTitle>Billing</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-3 mb-4">
              {[
                { label: 'Status', value: fmt(b.status ?? b.subscription_status) },
                { label: 'Current period', value: `${fmtDate(b.current_period_start, timeCtx)} → ${fmtDate(b.current_period_end, timeCtx)}` },
                { label: 'MRR', value: b.mrr != null ? `$${Number(b.mrr).toFixed(2)}` : '—' },
              ].map(m => (
                <div key={m.label}>
                  <div className="text-[10px] uppercase text-text-muted font-mono">{m.label}</div>
                  <div className="text-xs font-mono text-text-primary mt-0.5">{m.value}</div>
                </div>
              ))}
            </div>

            {inv.length > 0 && (
              <>
                <TerminalSeparator label="invoices" className="mb-3" />
                <div className="space-y-1.5">
                  {inv.slice(0, 5).map((inv, i) => {
                    const ir = asRec(inv);
                    return (
                      <div key={String(ir.id ?? i)} className="flex items-center justify-between text-xs font-mono border border-border-subtle rounded px-2 py-1.5">
                        <span className="text-text-muted">{fmtDate(ir.created_at ?? ir.date, timeCtx)}</span>
                        <span className="text-text-primary">{ir.amount != null ? `$${Number(ir.amount).toFixed(2)}` : '—'}</span>
                        <Badge variant={String(ir.status ?? '') === 'paid' ? 'success' : 'warning'} size="sm">{fmt(ir.status)}</Badge>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {invoicesLoading && <LoadingState lines={3} />}

      {/* Deactivate modal */}
      {deactivateModal && (
        <Modal open onClose={() => setDeactivateModal(false)}>
          <ModalHeader><h2 className="font-mono text-sm font-medium">Deactivate tenant</h2></ModalHeader>
          <ModalBody>
            <p className="text-sm text-text-secondary">
              This will immediately evict <strong>{fmt(t.name)}</strong> from the session cache. All active API calls will begin failing. The tenant record is not deleted.
            </p>
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => setDeactivateModal(false)}>Cancel</Button>
            <Button variant="danger" size="sm" onClick={() => void handleDeactivate()} disabled={deactivate.isLoading}>
              {deactivate.isLoading ? '[···]' : 'Confirm deactivation'}
            </Button>
          </ModalFooter>
        </Modal>
      )}

      {/* Provision key modal */}
      {provisionModal && (
        <Modal open onClose={() => setProvisionModal(false)}>
          <ModalHeader><h2 className="font-mono text-sm font-medium">Provision API key</h2></ModalHeader>
          <ModalBody>
            <input
              className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
              placeholder="Key name (e.g. production-ingestion)"
              value={newKeyName}
              onChange={e => setNewKeyName(e.target.value)}
              autoFocus
            />
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => setProvisionModal(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={() => void handleProvisionKey()} disabled={!newKeyName.trim() || provisionKey.isLoading}>
              {provisionKey.isLoading ? '[···]' : 'Provision'}
            </Button>
          </ModalFooter>
        </Modal>
      )}
    </div>
  );
}

// ── Page entry ─────────────────────────────────────────────────────────────────

export function TenantsPage() {
  const { tenantId } = useParams<{ tenantId?: string }>();
  return tenantId ? <TenantDetailView tenantId={tenantId} /> : <TenantListView />;
}
