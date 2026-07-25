/**
 * Security → Devices.
 *
 * Enrol this browser as a trusted device and administer device grants.
 *
 * Approval deliberately does not pre-filter "your own device": the backend
 * refuses self-approval and its refusal text is what the operator sees. That
 * keeps one authority, not two subtly different ones.
 */

import { useCallback, useState } from 'react';
import { Badge, Button, DataTable, Input } from '@aether/ui';
import { useKyberDevice } from '@kyber/features/auth';
import { useDeviceAdmin, useDeviceEnrolment, useDeviceList, useDeviceProof } from '@kyber/features/device-trust';
import type { DeviceApprovalState, KyberDevice } from '@kyber/types';
import { AdvisoryNote, AsyncSection, SecurityCard, SecurityPageShell, fieldOrDash } from './security-shell';

const APPROVAL_VARIANT: Record<DeviceApprovalState, 'success' | 'warning' | 'danger' | 'default'> = {
  approved: 'success',
  pending: 'warning',
  suspended: 'danger',
  revoked: 'danger',
  expired: 'default',
};

function EnrolmentCard({ onEnrolled }: { readonly onEnrolled: () => Promise<void> }) {
  const enrolment = useDeviceEnrolment(onEnrolled);
  const [name, setName] = useState('');

  if (!enrolment.isSupported) {
    return (
      <SecurityCard title="Enrol this device">
        <p className="text-xs text-danger" data-testid="enrolment-unsupported">
          {enrolment.unsupportedReason}
        </p>
        <p className="text-[11px] text-text-muted">
          There is no fallback. Use a browser with a platform authenticator and persistent
          storage, or work from an already-approved device.
        </p>
      </SecurityCard>
    );
  }

  return (
    <SecurityCard title="Enrol this device">
      <p className="text-xs text-text-secondary">
        Enrolment registers a passkey with the backend and generates a
        non-extractable ECDSA P-256 key that never leaves this browser profile.
        Passkeys sync between an operator&apos;s machines; the local proof key does
        not — which is why a second machine still needs its own approval.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Input
          label="Device name"
          placeholder="e.g. work laptop"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-64"
        />
        <Button
          size="sm"
          data-testid="enrol-device"
          disabled={
            enrolment.state === 'requesting-options' ||
            enrolment.state === 'awaiting-authenticator' ||
            enrolment.state === 'binding-proof-key' ||
            enrolment.state === 'verifying'
          }
          onClick={() => void enrolment.enrol(name)}
        >
          {enrolment.state === 'idle' || enrolment.state === 'error' || enrolment.state === 'enrolled'
            ? 'Enrol this device'
            : 'Enrolling…'}
        </Button>
      </div>
      {enrolment.state === 'awaiting-authenticator' && (
        <p className="text-xs text-text-secondary">Waiting for your authenticator…</p>
      )}
      {enrolment.state === 'enrolled' && (
        <p className="text-xs text-success" data-testid="enrolment-success">
          Device registered. It stays in <strong>pending</strong> until another operator approves it.
        </p>
      )}
      {enrolment.error !== null && (
        <p role="alert" className="text-xs text-danger" data-testid="enrolment-error">
          {enrolment.error}
        </p>
      )}
    </SecurityCard>
  );
}

function ProofKeyCard() {
  const proof = useDeviceProof();
  const label: Record<string, string> = {
    checking: 'Checking local key…',
    unsupported: 'This browser cannot hold a device proof key.',
    missing: 'No device proof key in this browser profile.',
    present: 'Device proof key present.',
    revoked: 'A local proof key exists but its backend grant is gone.',
  };

  return (
    <SecurityCard title="Device proof key">
      <p className="text-xs text-text-secondary" data-testid="proof-key-state">
        {label[proof.keyState] ?? proof.keyState}
      </p>
      {proof.keyState === 'revoked' && (
        <p className="text-xs text-warning">
          Re-enrol this device to mint a fresh key; the stale one proves nothing.
        </p>
      )}
      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={proof.keyState !== 'present' || proof.isProving}
          onClick={() => void proof.prove()}
          data-testid="prove-device"
        >
          {proof.isProving ? 'Proving…' : 'Prove possession'}
        </Button>
        {(proof.keyState === 'present' || proof.keyState === 'revoked') && (
          <Button variant="ghost" size="sm" onClick={() => void proof.forget()}>
            Forget local key
          </Button>
        )}
      </div>
      {proof.lastProvedAt !== null && (
        <p className="text-[11px] text-success">
          Last proved {new Date(proof.lastProvedAt).toISOString()}
        </p>
      )}
      {proof.error !== null && (
        <p role="alert" className="text-xs text-danger" data-testid="proof-error">
          {proof.error}
        </p>
      )}
    </SecurityCard>
  );
}

export function DevicesPage() {
  const list = useDeviceList();
  const { mayApproveDevices } = useKyberDevice();
  const refreshList = useCallback(async () => {
    await list.refresh();
  }, [list]);
  const admin = useDeviceAdmin(refreshList);
  const [reason, setReason] = useState('');

  const devices = list.devices;
  const pendingCount = devices.filter((device) => device.approval_state === 'pending').length;

  return (
    <SecurityPageShell
      title="Devices"
      description="Device grants for your Kyber workforce. A device is trusted only when the backend says approved — enrolment alone is not trust."
      actions={
        <Button variant="secondary" size="sm" onClick={() => void list.refresh()}>
          Refresh
        </Button>
      }
    >
      <EnrolmentCard onEnrolled={refreshList} />
      <ProofKeyCard />

      {pendingCount > 0 && (
        <p className="text-xs text-warning" data-testid="pending-summary">
          {pendingCount} device{pendingCount === 1 ? '' : 's'} awaiting approval.
        </p>
      )}

      {mayApproveDevices && (
        <div className="flex items-end gap-3">
          <Input
            label="Reason (recorded with every device decision)"
            placeholder="ticket or justification"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="w-96"
          />
        </div>
      )}

      {admin.error !== null && (
        <p role="alert" className="text-xs text-danger" data-testid="device-admin-error">
          {admin.error}
        </p>
      )}

      <AsyncSection
        isLoading={list.isLoading}
        error={list.error}
        isForbidden={list.isForbidden}
        isEmpty={devices.length === 0}
        emptyTitle="No devices registered"
        emptyDescription="Enrol this browser above to create the first device grant."
        onRetry={() => void list.refresh()}
      >
        <DataTable<KyberDevice>
          data={devices}
          keyExtractor={(row) => row.device_id}
          columns={[
            {
              key: 'device',
              header: 'Device',
              render: (row) => (
                <div>
                  <div className="text-text-primary">
                    {fieldOrDash(row.display_name)}
                    {row.is_current_device && (
                      <Badge variant="accent" size="sm" className="ml-2">
                        this device
                      </Badge>
                    )}
                  </div>
                  <div className="text-text-muted font-mono text-[11px]">{row.device_id}</div>
                </div>
              ),
            },
            {
              key: 'platform',
              header: 'Platform / browser',
              render: (row) => (
                <div>
                  <div>
                    {fieldOrDash(row.platform)} · {fieldOrDash(row.browser)}
                  </div>
                  <div
                    className="text-text-muted text-[11px] truncate max-w-xs"
                    title={row.user_agent ?? ''}
                  >
                    {fieldOrDash(row.user_agent)}
                  </div>
                </div>
              ),
            },
            {
              key: 'requested',
              header: 'Requested by',
              render: (row) => (
                <div>
                  <div className="font-mono text-[11px]">{fieldOrDash(row.requested_by)}</div>
                  <div className="text-text-muted text-[11px]">{fieldOrDash(row.requested_at)}</div>
                </div>
              ),
            },
            {
              key: 'state',
              header: 'State',
              render: (row) => (
                <div className="space-y-1">
                  <Badge variant={APPROVAL_VARIANT[row.approval_state]} size="sm">
                    {row.approval_state}
                  </Badge>
                  {row.approval_state === 'approved' && (
                    <div className="text-text-muted text-[11px]">
                      by {fieldOrDash(row.approved_by)}
                    </div>
                  )}
                  {!row.has_proof_key && (
                    <div className="text-warning text-[11px]">no proof key</div>
                  )}
                </div>
              ),
            },
            {
              key: 'actions',
              header: '',
              render: (row) => {
                if (!mayApproveDevices) return null;
                const busy = admin.pendingDeviceId === row.device_id;
                return (
                  <div className="flex gap-1">
                    {row.approval_state === 'pending' && (
                      <Button
                        size="sm"
                        disabled={busy}
                        onClick={() => void admin.approve(row.device_id, reason)}
                        data-testid={`approve-${row.device_id}`}
                      >
                        {busy ? '…' : 'Approve'}
                      </Button>
                    )}
                    {row.approval_state === 'approved' && (
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        onClick={() => void admin.suspend(row.device_id, reason)}
                      >
                        Suspend
                      </Button>
                    )}
                    {row.approval_state !== 'revoked' && (
                      <Button
                        variant="danger"
                        size="sm"
                        disabled={busy}
                        onClick={() => void admin.revoke(row.device_id, reason)}
                      >
                        Revoke
                      </Button>
                    )}
                  </div>
                );
              },
            },
          ]}
        />
      </AsyncSection>

      <AdvisoryNote />
    </SecurityPageShell>
  );
}
