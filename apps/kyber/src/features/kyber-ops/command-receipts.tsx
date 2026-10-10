/**
 * Command receipts — a read-only visibility stub for the durable command lifecycle.
 *
 * Renders the backend's own command-status vocabulary (the raw values from
 * `CommandStatus` in `services/kyber/ops/contracts.py`) and marks where a durable
 * receipt does not exist yet with a "receipt: …" placeholder. This panel governs
 * nothing — there are no approve / execute / verify / dry-run controls here, and an
 * off flag or a failed fetch renders nothing that breaks the page.
 */
import { useState } from 'react';
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@aether/ui';
import {
  RECEIPT_STATE_LABEL,
  commandReceiptState,
  useCommandReceipt,
  useCommandReceipts,
} from './use-command-receipts';
import type { CommandReceiptDetail } from './use-command-receipts';

const STATUS_CHIP_VARIANT: Record<string, 'default' | 'success' | 'warning' | 'danger'> = {
  // `verified` is the only success; `executed_unverified` is a warning — the call
  // returned and the postconditions did not confirm, which is neither success nor
  // failure, matching the treatment on the command queue itself.
  verified: 'success',
  executed_unverified: 'warning',
  failed: 'danger',
  rejected: 'danger',
  rolled_back: 'danger',
  cancelled: 'danger',
  expired: 'danger',
};

function CommandReceiptStatusChip({ status }: { readonly status: string }) {
  return <Badge variant={STATUS_CHIP_VARIANT[status] ?? 'default'}>{status}</Badge>;
}

function CommandReceiptDetailRow({ receiptId }: { readonly receiptId: string }) {
  const { data, loading, error, refresh } = useCommandReceipt(receiptId);

  if (loading && data === null) return <LoadingState lines={2} />;
  if (error !== null) {
    return <ErrorState title="Unable to load the receipt" message={error} onRetry={refresh} />;
  }
  if (data === null) return <EmptyState title="No receipt detail returned" />;

  const detail: CommandReceiptDetail = data;
  const receipt = detail.command;
  return (
    <div
      className="rounded border border-border-default bg-surface-raised p-2 text-[11px] font-mono space-y-0.5"
      role="group"
      aria-label={`Receipt for ${receipt.command_id}`}
    >
      <div className="text-text-primary">
        {RECEIPT_STATE_LABEL[commandReceiptState(receipt.status)]}
      </div>
      <div className="text-text-secondary">
        execution attempt {detail.execution?.attempt ?? '—'}
      </div>
      <div className="text-text-secondary">
        verification outcome {detail.verification?.outcome ?? 'none'}
      </div>
      {detail.verification?.failure_reason !== null &&
        detail.verification?.failure_reason !== undefined && (
          <div className="text-danger">failure {detail.verification.failure_reason}</div>
        )}
    </div>
  );
}

export function CommandReceiptsPanel() {
  const { data, loading, error, refresh } = useCommandReceipts();
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Command receipts</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[11px] text-text-secondary">
          The durable lifecycle of each open command, read-only. A status chip is the
          backend&apos;s own vocabulary; the receipt line states where a durable receipt
          does and does not exist yet. Nothing here dispatches — governed actions live on
          the queue.
        </p>

        {loading && data === null ? (
          <LoadingState lines={3} />
        ) : error !== null ? (
          <ErrorState
            title="Unable to load command receipts"
            message={error}
            onRetry={refresh}
          />
        ) : data === null || data.commands.length === 0 ? (
          <EmptyState title="No open command receipts" />
        ) : (
          <div className="space-y-2">
            {data.commands.map(command => (
              <div key={command.command_id} className="space-y-1">
                <button
                  type="button"
                  aria-expanded={selected === command.command_id}
                  onClick={() =>
                    setSelected(selected === command.command_id ? null : command.command_id)
                  }
                  className="w-full text-left border border-border-default rounded p-2 hover:bg-surface-raised"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] text-text-muted">
                      {command.command_id}
                    </span>
                    <CommandReceiptStatusChip status={command.status} />
                    <span className="font-mono text-[11px] text-text-muted">
                      {command.command_type}
                    </span>
                  </div>
                  <div className="mt-1 text-[11px] font-mono text-text-secondary">
                    {RECEIPT_STATE_LABEL[commandReceiptState(command.status)]}
                  </div>
                </button>
                {selected === command.command_id && (
                  <CommandReceiptDetailRow receiptId={command.command_id} />
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
