/**
 * KYBER: Revoke Dialog
 * Confirmation dialog for revoking an entitlement.
 * Owner: Entities page, Command page
 * Permissions: entitlements:write
 */
import { useState } from 'react';
import type { Entitlement } from '@kyber/lib/schemas/commerce';

interface RevokeDialogProps {
  readonly entitlement: Entitlement;
  readonly currentUserId: string;
  readonly onRevoke: (entitlementId: string, reason: string, revokedBy: string) => Promise<Entitlement>;
  readonly onClose: () => void;
}

export function RevokeDialog({ entitlement, currentUserId, onRevoke, onClose }: RevokeDialogProps) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRevoke() {
    if (!reason.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onRevoke(entitlement.entitlement_id, reason.trim(), currentUserId);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'revoke failed');
      setBusy(false);
    }
  }

  return (
    <div className="revoke-dialog" role="dialog" aria-modal="true" aria-labelledby="revoke-dialog-title">
      <div className="revoke-dialog__backdrop" onClick={onClose} />
      <div className="revoke-dialog__panel">
        <h3 id="revoke-dialog-title" className="revoke-dialog__title">Revoke Entitlement</h3>
        <p className="revoke-dialog__warning">
          This will immediately revoke access for <strong>{entitlement.holder_id}</strong> to{' '}
          <strong>{entitlement.resource_id}</strong>.
        </p>
        {error && <div className="revoke-dialog__error" role="alert">{error}</div>}
        <label className="revoke-dialog__label" htmlFor="revoke-reason">
          reason (required)
        </label>
        <textarea
          id="revoke-reason"
          className="revoke-dialog__reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="explain why this entitlement is being revoked…"
          rows={3}
          disabled={busy}
          required
        />
        <div className="revoke-dialog__actions">
          <button
            type="button"
            className="revoke-dialog__btn revoke-dialog__btn--confirm"
            onClick={() => void handleRevoke()}
            disabled={busy || !reason.trim()}
            aria-busy={busy}
          >
            {busy ? 'revoking…' : 'revoke'}
          </button>
          <button
            type="button"
            className="revoke-dialog__btn revoke-dialog__btn--cancel"
            onClick={onClose}
            disabled={busy}
          >
            cancel
          </button>
        </div>
      </div>
    </div>
  );
}
