import { useState } from 'react';
import { Modal, ModalHeader, ModalBody, ModalFooter, Button, Input } from '@aether/ui';
import type { ReviewStatus } from '@kyber/types';
import { useAuth } from '@kyber/features/auth';
import { getEnvironment } from '@kyber/lib/env';
import type { ActionAttribution } from '@kyber/types';

interface ApprovalModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onConfirm: (status: ReviewStatus, reason: string, attribution: ActionAttribution) => void;
  readonly action: 'approved' | 'rejected' | 'deferred' | 'reverted';
  readonly itemTitle: string;
}

export function ApprovalModal({ open, onClose, onConfirm, action, itemTitle }: ApprovalModalProps) {
  const [reason, setReason] = useState('');
  const { principal } = useAuth();

  const actionLabels: Record<string, { label: string; variant: string }> = {
    approved: { label: 'Approve', variant: 'text-success' },
    rejected: { label: 'Reject', variant: 'text-danger' },
    deferred: { label: 'Defer', variant: 'text-warning' },
    reverted: { label: 'Revert', variant: 'text-warning' },
  };

  const { label, variant } = actionLabels[action] ?? { label: action, variant: 'text-text-primary' };

  function handleConfirm() {
    if (!reason.trim() || !principal) return;
    const attribution: ActionAttribution = {
      userId: principal.operator_id,
      displayName: principal.display_name ?? principal.email,
      email: principal.email,
      role: principal.role_template_ids[0] ?? '',
      timestamp: new Date().toISOString(),
      environment: getEnvironment(),
      reason: reason.trim(),
      correlationId: `action-${Date.now()}`,
    };
    onConfirm(action, reason.trim(), attribution);
    setReason('');
    onClose();
  }

  return (
    <Modal open={open} onClose={onClose}>
      <ModalHeader>
        <div className="text-sm font-medium">
          <span className={variant}>{label}</span>: {itemTitle}
        </div>
      </ModalHeader>
      <ModalBody>
        <div className="space-y-3">
          <div className="text-xs text-text-secondary">
            Acting as: <span className="text-text-primary">{principal?.display_name ?? principal?.email}</span> ({principal?.role_template_ids[0] ?? 'no role'})
          </div>
          <div>
            <label className="text-xs text-text-secondary block mb-1">Reason (required)</label>
            <textarea
              value={reason}
              onChange={e => setReason(e.target.value)}
              className="w-full bg-surface-raised text-text-primary border border-border-default rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus min-h-[80px]"
              placeholder="Explain your decision..."
            />
          </div>
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
        <Button variant={action === 'approved' ? 'primary' : action === 'rejected' ? 'danger' : 'secondary'} size="sm" onClick={handleConfirm} disabled={!reason.trim()}>
          {label}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
