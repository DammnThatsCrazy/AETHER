import { useState } from 'react';
import { Button } from '@aether/ui';
import { ApprovalModal } from './approval-modal';
import { PermissionGate } from '@kyber/features/permissions';
import type { ReviewStatus } from '@kyber/types';

interface RevertButtonProps {
  readonly itemTitle: string;
  readonly reversible: boolean;
  readonly onRevert: (reason: string) => void;
  readonly className?: string;
}

export function RevertButton({ itemTitle, reversible, onRevert, className }: RevertButtonProps) {
  const [showModal, setShowModal] = useState(false);

  if (!reversible) return null;

  return (
    <PermissionGate requires="canRevert">
      <Button
        variant="danger"
        size="sm"
        onClick={() => setShowModal(true)}
        className={className}
      >
        Revert
      </Button>
      <ApprovalModal
        open={showModal}
        onClose={() => setShowModal(false)}
        onConfirm={(_status: ReviewStatus, reason: string) => onRevert(reason)}
        action="reverted"
        itemTitle={itemTitle}
      />
    </PermissionGate>
  );
}
