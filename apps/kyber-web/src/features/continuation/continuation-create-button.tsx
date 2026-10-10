/**
 * Continuation affordance — rendered ONLY while `enableKyberContinuations` is on.
 *
 * Calls the real M5d create hook (POST /v1/kyber/continuations). When the flag is
 * off this renders nothing at all, and the underlying hook resolves `{ skipped:
 * true }` without firing any request — so no dead surface and no HTTP traffic can
 * originate here while the operator router is gated off (D8).
 *
 * Optional props let the embedding console attach command context: a `reason` (the
 * natural selection token the commands console already holds) and a capability
 * gate (`canCreate`). When no command context exists the continuation is created
 * with the reason only.
 */
import { useState } from 'react';
import { Button } from '@aether/ui';
import { isContinuationRoutingEnabled, useCreateOperatorContinuation } from './use-continuations';

export interface ContinuationCreateButtonProps {
  /** Capability gate — e.g. the command console's `canReadCommands`. */
  readonly canCreate?: boolean;
  /** Why this continuation exists (attached to the create request). */
  readonly reason?: string;
  /** The command this continuation resumes from, when one is selected. */
  readonly sourceCommandId?: string;
}

export function ContinuationCreateButton({
  canCreate = true,
  reason,
  sourceCommandId,
}: ContinuationCreateButtonProps): React.JSX.Element | null {
  const { create } = useCreateOperatorContinuation();
  const [notice, setNotice] = useState<string | null>(null);

  if (!isContinuationRoutingEnabled()) return null;
  if (!canCreate) return null;

  return (
    <div className="space-y-1">
      <Button
        size="sm"
        variant="secondary"
        onClick={() => {
          setNotice('Requesting…');
          void create({
            ...(sourceCommandId ? { source_command_id: sourceCommandId } : {}),
            ...(reason ? { objective: reason } : {}),
          }).then(result =>
            setNotice(
              result.skipped
                ? 'Continuation routing is not wired yet (M5) — nothing was dispatched.'
                : 'Continuation created.',
            ),
          );
        }}
      >
        Create continuation
      </Button>
      {notice !== null && (
        <div className="text-[11px] font-mono text-text-muted">{notice}</div>
      )}
    </div>
  );
}
