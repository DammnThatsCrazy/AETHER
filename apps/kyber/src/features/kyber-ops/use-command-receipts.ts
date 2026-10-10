/**
 * KYBER command receipts — read-only visibility of the durable command lifecycle.
 *
 * This is a visibility STUB: it renders backend-provided command state and governs
 * nothing. There are no approve / execute / verify / dry-run controls here — those
 * are governed actions and belong to the command queue, not a receipts surface.
 * Where the backend has no durable receipt yet (a command that never executed, or
 * one whose postconditions were never confirmed) the panel says so instead of
 * inventing a receipt.
 *
 * snake_case wire fields (D6) throughout.
 */
import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';
import type { QueryState } from './use-kyber-ops';

const STALE = 15_000;

/**
 * The backend's command-status vocabulary, verbatim from
 * `services/kyber/ops/contracts.py`:
 *
 *   CommandStatus = Literal[
 *     "requested", "awaiting_approval", "approved", "rejected", "dry_run_complete",
 *     "executing", "executed_unverified", "verified", "failed", "rolled_back",
 *     "cancelled", "expired",
 *   ]
 *
 * Chips render the raw backend value — not a label we invented — so the screen
 * can never drift from what the model reports. Unknown future values fall through
 * to the default treatment rather than being dropped.
 */
export const COMMAND_STATUS_VOCABULARY = [
  'requested',
  'awaiting_approval',
  'approved',
  'rejected',
  'dry_run_complete',
  'executing',
  'executed_unverified',
  'verified',
  'failed',
  'rolled_back',
  'cancelled',
  'expired',
] as const;

export type CommandReceiptStatus = (typeof COMMAND_STATUS_VOCABULARY)[number];

/** Where a durable receipt exists for a command, derived from its status. */
export type CommandReceiptState =
  | 'issued'
  | 'pending_verification'
  | 'in_flight'
  | 'not_issued';

export function commandReceiptState(status: string | null | undefined): CommandReceiptState {
  switch (status) {
    case 'verified':
      return 'issued';
    case 'executed_unverified':
      return 'pending_verification';
    case 'executing':
      return 'in_flight';
    default:
      return 'not_issued';
  }
}

/** The "receipt: …" line rendered beside each command's status chip. */
export const RECEIPT_STATE_LABEL: Record<CommandReceiptState, string> = {
  issued:
    'receipt: issued — postconditions confirmed',
  pending_verification:
    'receipt: pending verification — the call returned and the postconditions did not confirm',
  in_flight:
    'receipt: not yet issued — the command is still in flight',
  not_issued:
    'receipt: not yet issued — no durable receipt on record',
};

export interface CommandReceipt {
  readonly command_id: string;
  readonly command_type: string;
  readonly status: string;
  readonly requested_by: string;
  readonly reason: string;
  readonly created_at?: string | null | undefined;
  readonly updated_at?: string | null | undefined;
}

export interface CommandReceiptList {
  readonly commands: readonly CommandReceipt[];
  readonly count: number | null;
  readonly status_filter?: string | null | undefined;
}

export interface CommandReceiptExecution {
  readonly execution_id: string;
  readonly attempt?: number | null | undefined;
  readonly started_at?: string | null | undefined;
  readonly completed_at?: string | null | undefined;
  readonly error?: string | null | undefined;
}

export interface CommandReceiptVerification {
  readonly verification_id: string;
  readonly outcome: string;
  readonly failure_reason?: string | null | undefined;
  readonly started_at?: string | null | undefined;
  readonly completed_at?: string | null | undefined;
}

export interface CommandReceiptDetail {
  readonly command: CommandReceipt;
  readonly execution: CommandReceiptExecution | null;
  readonly verification: CommandReceiptVerification | null;
  readonly verified: boolean;
}

export function useCommandReceipts(): QueryState<CommandReceiptList> {
  const { data, isLoading, error, refetch } = useQuery<CommandReceiptList>({
    key: 'kyber-ops:command-receipts:open',
    fetcher: () => api.kyberOps.commandReceipts({ status: 'open', limit: 100 }),
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Disabled until a receipt is named — there is nothing to read without one. */
export function useCommandReceipt(commandId: string | null): QueryState<CommandReceiptDetail> {
  const { data, isLoading, error, refetch } = useQuery<CommandReceiptDetail>({
    key: `kyber-ops:command-receipt:${commandId ?? 'none'}`,
    fetcher: () => api.kyberOps.commandReceipt(commandId as string),
    staleTime: STALE,
    enabled: commandId !== null && commandId !== '',
  });
  return { data, loading: isLoading, error, refresh: refetch };
}
