import { useState, useCallback, useEffect } from 'react';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  EmptyState, LoadingState, Modal, ModalBody, ModalFooter, ModalHeader,
  Skeleton, TerminalSeparator, useToast,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { PermissionGate } from '@kyber/features/permissions';
import {
  useFleetTenantEnvelope,
  useKyberOperatorEntry,
  type OperatorAccessPurpose,
} from '@kyber/features/noesis';
import { api } from '@kyber/lib/api/endpoints';
import { cn } from '@kyber/lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface TenantRow {
  tenant_id: string;
  name?: string;
  [key: string]: unknown;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function healthVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'healthy') return 'success';
  if (status === 'no_data') return 'warning';
  return 'danger';
}

// ── Tenant envelope row ───────────────────────────────────────────────────────

function TenantEnvelopeRow({
  tenant,
  onEnterTenant,
}: {
  tenant: TenantRow;
  onEnterTenant: (tenantId: string, name: string) => void;
}) {
  const { envelope, isLoading } = useFleetTenantEnvelope(tenant.tenant_id);

  return (
    <div className="flex items-center justify-between border border-border-subtle rounded px-3 py-2.5 text-xs font-mono gap-3">
      {/* Tenant identity */}
      <div className="w-36 shrink-0">
        <div className="text-text-primary font-medium truncate">{fmt(tenant.name ?? tenant.tenant_id)}</div>
        <div className="text-text-muted truncate text-[10px]">{tenant.tenant_id}</div>
      </div>

      {/* Health metrics */}
      {isLoading ? (
        <div className="flex-1">
          <Skeleton className="h-3 w-full" />
        </div>
      ) : envelope ? (
        <>
          <div className="w-20 text-center">
            <div className="text-[10px] text-text-muted">Graph nodes</div>
            <div className={cn('font-bold', envelope.graph.has_data ? 'text-text-primary' : 'text-text-muted')}>
              {envelope.graph.node_count.toLocaleString()}
            </div>
          </div>
          <div className="w-20 text-center">
            <div className="text-[10px] text-text-muted">Edge sample</div>
            <div className="text-text-primary font-bold">{envelope.graph.edge_count_sample.toLocaleString()}</div>
          </div>
          <div className="w-20 text-center">
            <div className="text-[10px] text-text-muted">Fraud nets</div>
            <div className={cn('font-bold', envelope.fraud.fraud_network_count > 0 ? 'text-danger' : 'text-text-muted')}>
              {envelope.fraud.fraud_network_count}
            </div>
          </div>
          <div className="w-20 text-center">
            <div className="text-[10px] text-text-muted">SDK health</div>
            <div className={cn('font-bold', (envelope.sdk.health_score ?? 0) < 0.5 ? 'text-danger' : 'text-success')}>
              {envelope.sdk.health_score != null ? envelope.sdk.health_score.toFixed(2) : '—'}
            </div>
          </div>
          <div className="w-20 text-center">
            <Badge variant={healthVariant(envelope.status)} size="sm">{envelope.status}</Badge>
          </div>
        </>
      ) : (
        <div className="flex-1 text-text-muted text-center">envelope unavailable</div>
      )}

      {/* Enter tenant action */}
      <PermissionGate requires="canCommand">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onEnterTenant(tenant.tenant_id, fmt(tenant.name ?? tenant.tenant_id))}
        >
          Enter [→]
        </Button>
      </PermissionGate>
    </div>
  );
}

// ── Operator entry modal ──────────────────────────────────────────────────────

const PURPOSE_OPTIONS: { value: OperatorAccessPurpose; label: string }[] = [
  { value: 'incident_response', label: 'Incident response' },
  { value: 'customer_support', label: 'Customer support' },
  { value: 'compliance_audit', label: 'Compliance audit' },
  { value: 'security_investigation', label: 'Security investigation' },
  { value: 'data_request', label: 'Data request' },
  { value: 'diagnostics', label: 'Diagnostics' },
  { value: 'break_glass', label: 'Break glass (emergency)' },
];

function OperatorEntryModal({
  tenantId,
  tenantName,
  isEntering,
  enterTenantError,
  onClose,
  onSubmit,
}: {
  tenantId: string;
  tenantName: string;
  isEntering: boolean;
  enterTenantError: string | null;
  onClose: () => void;
  onSubmit: (params: { tenant_id: string; access_reason: string; purpose: OperatorAccessPurpose; duration_minutes: number }) => Promise<void> | void;
}) {
  const { toast } = useToast();
  const [reason, setReason] = useState('');
  const [purpose, setPurpose] = useState<OperatorAccessPurpose>('diagnostics');
  const [duration, setDuration] = useState(60);

  function handleSubmit() {
    if (reason.trim().length < 10) {
      toast.info('Access reason must be at least 10 characters');
      return;
    }
    onSubmit({ tenant_id: tenantId, access_reason: reason.trim(), purpose, duration_minutes: duration });
  }

  return (
    <Modal open onClose={onClose}>
      <ModalHeader>
        <h2 className="font-mono text-sm font-medium text-text-primary">
          Privileged tenant access — {tenantName}
        </h2>
        <p className="text-xs text-text-muted mt-0.5">All actions taken during this session will be immutably audited.</p>
      </ModalHeader>
      <ModalBody className="space-y-4">
        <div>
          <label className="text-xs text-text-muted font-mono block mb-1">Access reason (required, min 10 chars)</label>
          <textarea
            className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent resize-none"
            rows={2}
            placeholder="Describe why you need access to this tenant's data…"
            value={reason}
            onChange={e => setReason(e.target.value)}
          />
        </div>
        <div>
          <label className="text-xs text-text-muted font-mono block mb-1">Access purpose</label>
          <select
            className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent"
            value={purpose}
            onChange={e => setPurpose(e.target.value as OperatorAccessPurpose)}
          >
            {PURPOSE_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-text-muted font-mono block mb-1">Duration (minutes, 1–480)</label>
          <input
            type="number"
            min={1}
            max={480}
            className="w-32 rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent"
            value={duration}
            onChange={e => setDuration(Math.min(480, Math.max(1, Number(e.target.value))))}
          />
        </div>
        {enterTenantError && <p className="text-xs text-danger font-mono">{enterTenantError}</p>}
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
        <Button
          variant="danger"
          size="sm"
          onClick={handleSubmit}
          disabled={isEntering || reason.trim().length < 10}
        >
          {isEntering ? '[···]' : 'Enter tenant — all actions audited'}
        </Button>
      </ModalFooter>
    </Modal>
  );
}

// ── Active operator session banner ────────────────────────────────────────────

function OperatorSessionBanner({
  session,
  onExit,
  isExiting,
}: {
  session: { session_id: string; tenant_id: string; purpose: string; entered_at: string };
  onExit: () => void;
  isExiting: boolean;
}) {
  return (
    <div className="flex items-center justify-between px-4 py-2 bg-danger/10 border border-danger/40 rounded text-xs font-mono">
      <div className="flex items-center gap-3">
        <Badge variant="danger" size="sm">OPERATOR SESSION ACTIVE</Badge>
        <span className="text-text-secondary">Tenant: <span className="text-text-primary font-bold">{session.tenant_id}</span></span>
        <span className="text-text-muted">Purpose: {session.purpose}</span>
        <span className="text-text-muted">Entered: {new Date(session.entered_at).toLocaleTimeString()}</span>
      </div>
      <Button variant="danger" size="sm" onClick={onExit} disabled={isExiting}>
        {isExiting ? '[···]' : 'Exit tenant'}
      </Button>
    </div>
  );
}

// ── Fleet graph page ──────────────────────────────────────────────────────────

export function FleetGraphPage() {
  const { toast } = useToast();
  const [tenants, setTenants] = useState<TenantRow[]>([]);
  const [isLoadingTenants, setIsLoadingTenants] = useState(true);
  const [entryTarget, setEntryTarget] = useState<{ tenantId: string; name: string } | null>(null);

  const { session, isEntering, isExiting, error: operatorError, enterTenant, exitTenant } = useKyberOperatorEntry();

  // Load tenant list on mount
  useEffect(() => {
    api.admin.tenants.list({ limit: 100 })
      .then((raw: { tenants: unknown[]; total: number }) => {
        const list = Array.isArray(raw.tenants) ? (raw.tenants as TenantRow[]) : [];
        setTenants(list);
        setIsLoadingTenants(false);
      })
      .catch(() => {
        setIsLoadingTenants(false);
      });
  }, []);

  const handleEnterTenant = useCallback((tenantId: string, name: string) => {
    setEntryTarget({ tenantId, name });
  }, []);

  async function handleExitTenant() {
    try {
      await exitTenant();
      toast.success('Operator session ended — audit log sealed');
    } catch {
      toast.error('Failed to exit tenant session');
    }
  }

  return (
    <PageWrapper
      title="Fleet Graph"
      subtitle="Platform universe — tenant operational health and privileged access"
    >
      {/* Active operator session banner */}
      {session && (
        <OperatorSessionBanner
          session={session}
          onExit={() => void handleExitTenant()}
          isExiting={isExiting}
        />
      )}

      <TerminalSeparator className="my-4" />

      {/* Tenant portfolio comparison */}
      <Card>
        <CardHeader>
          <CardTitle>Tenant Portfolio</CardTitle>
          <p className="text-xs text-text-muted mt-0.5">
            Operational envelope per tenant — graph size, fraud volume, SDK health, status
          </p>
        </CardHeader>
        <CardContent>
          {isLoadingTenants ? (
            <LoadingState lines={6} />
          ) : tenants.length === 0 ? (
            <EmptyState
              title="No tenants found"
              description="Tenant registry is empty or you lack permission to view it."
            />
          ) : (
            <div className="space-y-1.5">
              {/* Column headers */}
              <div className="flex items-center px-3 py-1.5 text-[10px] font-mono text-text-muted gap-3">
                <div className="w-36 shrink-0">Tenant</div>
                <div className="w-20 text-center">Graph nodes</div>
                <div className="w-20 text-center">Edge sample</div>
                <div className="w-20 text-center">Fraud nets</div>
                <div className="w-20 text-center">SDK health</div>
                <div className="w-20 text-center">Status</div>
                <div className="w-20 text-right">Action</div>
              </div>
              <TerminalSeparator />
              {tenants.map(t => (
                <TenantEnvelopeRow
                  key={t.tenant_id}
                  tenant={t}
                  onEnterTenant={handleEnterTenant}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Operator entry modal */}
      {entryTarget && (
        <OperatorEntryModal
          tenantId={entryTarget.tenantId}
          tenantName={entryTarget.name}
          isEntering={isEntering}
          enterTenantError={operatorError}
          onClose={() => setEntryTarget(null)}
          onSubmit={async (params) => {
            try {
              await enterTenant(params);
              toast.success(`Entered tenant ${entryTarget.name} — all actions audited`);
              setEntryTarget(null);
            } catch {
              // error shown in modal
            }
          }}
        />
      )}
    </PageWrapper>
  );
}
