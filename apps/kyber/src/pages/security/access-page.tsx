/**
 * Security → Tenant access scopes.
 *
 * Entering a scope is a request, not a grant: the backend decides the TTL and
 * the disclosure level it will actually serve, and can refuse outright. The
 * live countdown here is a mirror of `active_scope.expires_at` — when it hits
 * zero the frontend clears tenant access locally and re-asks the backend
 * rather than assuming the scope is still good.
 */

import { useCallback, useState } from 'react';
import { Badge, Button, DataTable, Input, Select } from '@aether/ui';
import {
  SCOPE_PURPOSES,
  describePurpose,
  enterScope,
  exitScope,
  fetchScopeHistory,
  formatCountdown,
  useAuth,
  useKyberScope,
} from '@kyber/features/auth';
import { useCapabilities } from '@kyber/features/permissions';
import { describeAuthError } from '@kyber/lib/auth';
import type { AccessScope, ScopePurpose } from '@kyber/types';
import { AdvisoryNote, AsyncSection, SecurityCard, SecurityPageShell, fieldOrDash } from './security-shell';
import { useSecurityResource } from './use-security-resource';

const PURPOSE_OPTIONS = SCOPE_PURPOSES.map((purpose) => ({
  value: purpose,
  label: describePurpose(purpose),
}));

export function AccessPage() {
  const history = useSecurityResource((signal) => fetchScopeHistory(signal));
  const scope = useKyberScope();
  const { refresh: refreshSession } = useAuth();
  const capabilities = useCapabilities();

  const [tenantId, setTenantId] = useState('');
  const [purpose, setPurpose] = useState<ScopePurpose>('customer_support');
  const [reason, setReason] = useState('');
  const [ticket, setTicket] = useState('');
  const [disclosure, setDisclosure] = useState('1');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const requestedDisclosure = Number.parseInt(disclosure, 10) || 0;
  const disclosureCheck = capabilities.checkDisclosure(requestedDisclosure);

  const submit = useCallback(async () => {
    setBusy(true);
    setFormError(null);
    try {
      await enterScope({
        tenant_id: tenantId.trim(),
        purpose,
        reason: reason.trim(),
        ticket_reference: ticket.trim() === '' ? null : ticket.trim(),
        disclosure_level: requestedDisclosure,
        requested_ttl_seconds: null,
      });
      await refreshSession();
      await history.refresh();
      setTenantId('');
      setReason('');
      setTicket('');
    } catch (err) {
      setFormError(describeAuthError(err));
    } finally {
      setBusy(false);
    }
  }, [tenantId, purpose, reason, ticket, requestedDisclosure, refreshSession, history]);

  const leave = useCallback(
    async (scopeId: string) => {
      setBusy(true);
      setFormError(null);
      try {
        await exitScope(scopeId);
        await refreshSession();
        await history.refresh();
      } catch (err) {
        setFormError(describeAuthError(err));
      } finally {
        setBusy(false);
      }
    },
    [refreshSession, history],
  );

  const rows = history.data ?? [];

  return (
    <SecurityPageShell
      title="Tenant access"
      description="Purpose-bound, time-boxed access to a single tenant. Every entry is recorded, and expiry is enforced by the backend."
      actions={
        <Button variant="secondary" size="sm" onClick={() => void history.refresh()}>
          Refresh
        </Button>
      }
    >
      <SecurityCard title="Active scope">
        {scope.isActive && scope.scope !== null ? (
          <div className="flex flex-wrap items-center gap-3 text-xs" data-testid="active-scope">
            <Badge variant="accent" size="sm">
              {scope.scope.tenant_id}
            </Badge>
            <span>{describePurpose(scope.scope.purpose)}</span>
            <span className="text-text-muted">{scope.scope.reason}</span>
            <span>
              disclosure L<span className="font-mono">{scope.scope.disclosure_level}</span>
            </span>
            <span className="font-mono tabular-nums" data-testid="access-countdown">
              {formatCountdown(scope.msRemaining)}
            </span>
            <Button
              variant="danger"
              size="sm"
              disabled={busy}
              onClick={() => void leave(scope.scope?.scope_id ?? '')}
              data-testid="exit-scope"
            >
              Exit scope
            </Button>
          </div>
        ) : (
          <p className="text-xs text-text-muted" data-testid="no-active-scope">
            No tenant scope is active. Tenant-scoped data is not being served to this session.
          </p>
        )}
      </SecurityCard>

      <SecurityCard title="Enter a scope">
        <div className="flex flex-wrap items-end gap-3">
          <Input
            label="Tenant id"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            className="w-56"
          />
          <Select
            label="Purpose"
            options={PURPOSE_OPTIONS}
            value={purpose}
            onChange={(value) => setPurpose(value as ScopePurpose)}
          />
          <Input
            label="Reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="w-72"
          />
          <Input
            label="Ticket reference"
            value={ticket}
            onChange={(e) => setTicket(e.target.value)}
            className="w-48"
          />
          <Input
            label="Disclosure level"
            type="number"
            min={0}
            max={5}
            value={disclosure}
            onChange={(e) => setDisclosure(e.target.value)}
            className="w-32"
          />
          <Button
            size="sm"
            disabled={busy || tenantId.trim() === '' || reason.trim() === ''}
            onClick={() => void submit()}
            data-testid="enter-scope"
          >
            {busy ? 'Requesting…' : 'Enter scope'}
          </Button>
        </div>
        {!disclosureCheck.allowed && (
          <p className="text-xs text-warning" data-testid="disclosure-warning">
            {disclosureCheck.reason} — the backend will refuse this request.
          </p>
        )}
        {formError !== null && (
          <p role="alert" className="text-xs text-danger" data-testid="scope-error">
            {formError}
          </p>
        )}
      </SecurityCard>

      <AsyncSection
        isLoading={history.isLoading}
        error={history.error}
        isForbidden={history.isForbidden}
        isEmpty={rows.length === 0}
        emptyTitle="No scope history"
        emptyDescription="Scopes you enter are recorded here with their purpose and expiry."
        onRetry={() => void history.refresh()}
      >
        <DataTable<AccessScope>
          data={rows}
          keyExtractor={(row) => row.scope_id}
          columns={[
            { key: 'tenant', header: 'Tenant', render: (row) => <span className="font-mono">{row.tenant_id}</span> },
            { key: 'purpose', header: 'Purpose', render: (row) => describePurpose(row.purpose) },
            { key: 'reason', header: 'Reason', render: (row) => <span className="text-text-secondary">{row.reason}</span> },
            { key: 'ticket', header: 'Ticket', render: (row) => fieldOrDash(row.ticket_reference) },
            {
              key: 'disclosure',
              header: 'Disclosure',
              render: (row) => <span className="font-mono">L{row.disclosure_level}</span>,
            },
            {
              key: 'status',
              header: 'Status',
              render: (row) => (
                <Badge size="sm" variant={row.status === 'active' ? 'success' : 'default'}>
                  {row.status}
                </Badge>
              ),
            },
            { key: 'entered', header: 'Entered', render: (row) => <span className="font-mono">{row.entered_at}</span> },
            { key: 'expires', header: 'Expires', render: (row) => <span className="font-mono">{fieldOrDash(row.expires_at)}</span> },
          ]}
        />
      </AsyncSection>

      <AdvisoryNote />
    </SecurityPageShell>
  );
}
