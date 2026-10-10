import { EmptyState } from '@aether/ui';
import { useState } from 'react';
import { SuggestionCard } from './SuggestionCard';

type AnyRecord = Record<string, any>;

export interface ReviewQueueProps {
  readonly items: AnyRecord[];
  onApprove: (id: string) => void;
  onReject: (id: string, reason: string) => void;
  onSuppress: (id: string, reason: string) => void;
  readonly loading?: boolean;
}

const inputClass =
  'rounded border border-border-default bg-surface-default px-2 py-1 text-xs font-mono text-text-primary focus:outline-none focus:ring-1 focus:ring-brand-default w-full';

function ReasonPrompt({
  label,
  onSubmit,
  onCancel,
}: {
  readonly label: string;
  onSubmit: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState('');

  return (
    <div className="mt-2 space-y-1">
      <input
        type="text"
        placeholder={label}
        className={inputClass}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div className="flex gap-2">
        <button
          className="rounded bg-surface-subtle px-2 py-0.5 text-xs font-mono text-text-primary hover:bg-surface-hover"
          onClick={() => reason.trim() && onSubmit(reason.trim())}
          disabled={!reason.trim()}
        >
          Confirm
        </button>
        <button
          className="rounded px-2 py-0.5 text-xs font-mono text-text-muted hover:text-text-primary"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export function ReviewQueue({ items, onApprove, onReject, onSuppress, loading }: ReviewQueueProps) {
  const [pendingReject, setPendingReject] = useState<string | null>(null);
  const [pendingSuppress, setPendingSuppress] = useState<string | null>(null);

  if (!loading && items.length === 0) {
    return <EmptyState title="No items in review queue" />;
  }

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const id: string = item.suggestion_id ?? item.id ?? '';
        const isRejectPending = pendingReject === id;
        const isSuppressPending = pendingSuppress === id;

        const cardProps = {
          suggestion: item,
          onApprove: () => onApprove(id),
          ...(!isRejectPending ? { onReject: () => setPendingReject(id) } : {}),
          ...(!isSuppressPending ? { onSuppress: () => setPendingSuppress(id) } : {}),
        };

        return (
          <div key={id}>
            <SuggestionCard {...cardProps} />
            {isRejectPending && (
              <ReasonPrompt
                label="Reason for rejection"
                onSubmit={(reason) => {
                  setPendingReject(null);
                  onReject(id, reason);
                }}
                onCancel={() => setPendingReject(null)}
              />
            )}
            {isSuppressPending && (
              <ReasonPrompt
                label="Reason for suppression"
                onSubmit={(reason) => {
                  setPendingSuppress(null);
                  onSuppress(id, reason);
                }}
                onCancel={() => setPendingSuppress(null)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
