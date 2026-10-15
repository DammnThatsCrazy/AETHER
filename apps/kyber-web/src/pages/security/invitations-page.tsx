/**
 * Security → Invitations.
 *
 * Invite an operator and revoke pending invitations. The invite form is only
 * offered when the backend granted `kyber.workforce.invite`; posting it anyway
 * simply returns the backend's 403, which is displayed verbatim.
 */

import { useCallback, useState } from 'react';
import { Badge, Button, DataTable, Input } from '@aether/ui';
import { createInvitation, fetchInvitations, revokeInvitation } from '@kyber/features/auth';
import { PermissionGate, useCapabilities } from '@kyber/features/permissions';
import { describeAuthError } from '@kyber/lib/auth';
import type { InvitationStatus, WorkforceInvitation } from '@kyber/types';
import { AdvisoryNote, AsyncSection, SecurityCard, SecurityPageShell, fieldOrDash } from './security-shell';
import { useSecurityResource } from './use-security-resource';

export const INVITE_CAPABILITY = 'kyber.workforce.invite';

const STATUS_VARIANT: Record<InvitationStatus, 'success' | 'warning' | 'danger' | 'default'> = {
  pending: 'warning',
  accepted: 'success',
  revoked: 'danger',
  expired: 'default',
};

export function InvitationsPage() {
  const { data, isLoading, error, isForbidden, refresh } = useSecurityResource((signal) =>
    fetchInvitations(signal),
  );
  const capabilities = useCapabilities();

  const [email, setEmail] = useState('');
  const [roles, setRoles] = useState('');
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingRevoke, setPendingRevoke] = useState<string | null>(null);

  const submit = useCallback(async () => {
    setSubmitting(true);
    setFormError(null);
    setNotice(null);
    try {
      const created = await createInvitation({
        email: email.trim(),
        role_template_ids: roles
          .split(',')
          .map((value) => value.trim())
          .filter((value) => value.length > 0),
        reason: reason.trim(),
      });
      setNotice(`Invitation sent to ${created.email}.`);
      setEmail('');
      setRoles('');
      setReason('');
      await refresh();
    } catch (err) {
      setFormError(describeAuthError(err));
    } finally {
      setSubmitting(false);
    }
  }, [email, roles, reason, refresh]);

  const revoke = useCallback(
    async (invitationId: string) => {
      setPendingRevoke(invitationId);
      setFormError(null);
      try {
        await revokeInvitation(invitationId);
        await refresh();
      } catch (err) {
        setFormError(describeAuthError(err));
      } finally {
        setPendingRevoke(null);
      }
    },
    [refresh],
  );

  const invitations = data ?? [];
  const canInvite = capabilities.has(INVITE_CAPABILITY);

  return (
    <SecurityPageShell
      title="Invitations"
      description="Pending and historical workforce invitations. Acceptance binds an identity to a role template on the backend; nothing is granted here."
      actions={
        <Button variant="secondary" size="sm" onClick={() => void refresh()}>
          Refresh
        </Button>
      }
    >
      <PermissionGate
        capability={INVITE_CAPABILITY}
        fallback={
          <p className="text-xs text-text-muted" data-testid="invite-not-permitted">
            Your session does not hold <code className="font-mono">{INVITE_CAPABILITY}</code>, so
            inviting operators is not available.
          </p>
        }
      >
        <SecurityCard title="Invite an operator">
          <div className="flex flex-wrap items-end gap-3">
            <Input
              label="Email"
              type="email"
              placeholder="operator@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-64"
            />
            <Input
              label="Role templates (comma separated)"
              placeholder="kyber.role.support, kyber.role.oncall"
              value={roles}
              onChange={(e) => setRoles(e.target.value)}
              className="w-80"
            />
            <Input
              label="Reason"
              placeholder="ticket or justification"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="w-64"
            />
            <Button
              size="sm"
              disabled={submitting || email.trim() === '' || !canInvite}
              onClick={() => void submit()}
              data-testid="invite-submit"
            >
              {submitting ? 'Sending…' : 'Send invitation'}
            </Button>
          </div>
          {formError !== null && (
            <p role="alert" className="text-xs text-danger" data-testid="invite-error">
              {formError}
            </p>
          )}
          {notice !== null && <p className="text-xs text-success">{notice}</p>}
        </SecurityCard>
      </PermissionGate>

      <AsyncSection
        isLoading={isLoading}
        error={error}
        isForbidden={isForbidden}
        isEmpty={invitations.length === 0}
        emptyTitle="No invitations"
        emptyDescription="Invitations you send will appear here until they are accepted, revoked or expire."
        onRetry={() => void refresh()}
      >
        <DataTable<WorkforceInvitation>
          data={invitations}
          keyExtractor={(row) => row.invitation_id}
          columns={[
            { key: 'email', header: 'Email', render: (row) => <span className="font-mono">{row.email}</span> },
            {
              key: 'status',
              header: 'Status',
              render: (row) => (
                <Badge variant={STATUS_VARIANT[row.status]} size="sm">
                  {row.status}
                </Badge>
              ),
            },
            {
              key: 'roles',
              header: 'Role templates',
              render: (row) => (
                <div className="flex flex-wrap gap-1">
                  {row.role_template_ids.map((roleId) => (
                    <Badge key={roleId} size="sm">
                      {roleId}
                    </Badge>
                  ))}
                </div>
              ),
            },
            { key: 'invited_by', header: 'Invited by', render: (row) => fieldOrDash(row.invited_by) },
            { key: 'expires', header: 'Expires', render: (row) => <span className="font-mono">{fieldOrDash(row.expires_at)}</span> },
            {
              key: 'actions',
              header: '',
              render: (row) =>
                row.status === 'pending' ? (
                  <PermissionGate capability={INVITE_CAPABILITY}>
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={pendingRevoke === row.invitation_id}
                      onClick={() => void revoke(row.invitation_id)}
                    >
                      {pendingRevoke === row.invitation_id ? 'Revoking…' : 'Revoke'}
                    </Button>
                  </PermissionGate>
                ) : null,
            },
          ]}
        />
      </AsyncSection>

      <AdvisoryNote />
    </SecurityPageShell>
  );
}
