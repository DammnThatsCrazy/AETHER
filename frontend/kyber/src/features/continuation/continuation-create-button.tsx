/**
 * Continuation affordance — rendered ONLY while `enableKyberContinuations` is on.
 *
 * The creation hook it calls is inert (M4b): `create` resolves `{ skipped: true }`
 * and fires no HTTP request. The router is M5. When the flag is off this renders
 * nothing at all, so no dead surface and no request can ever fire from it.
 */
import { useState } from 'react';
import { Button } from '@aether/ui';
import { isContinuationRoutingEnabled, useCreateContinuation } from './use-continuations';

export function ContinuationCreateButton() {
  const { create } = useCreateContinuation();
  const [notice, setNotice] = useState<string | null>(null);

  if (!isContinuationRoutingEnabled()) return null;

  return (
    <div className="space-y-1">
      <Button
        size="sm"
        variant="secondary"
        onClick={() => {
          setNotice('Requesting…');
          void create().then(result =>
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
