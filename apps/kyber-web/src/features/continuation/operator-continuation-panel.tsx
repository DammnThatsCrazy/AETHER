/**
 * Operator "Continue on phone / Resume" panel (M5d).
 *
 * Shows recent operator continuations (GET /v1/kyber/continuations/recent) and lets
 * an operator mint a handoff selection (POST /v1/kyber/continuations/{id}/handoff) —
 * the deep-link token they copy to a phone to resume the work there. Read-only except
 * create + handoff.
 *
 * Renders NOTHING while `enableKyberContinuations` is off (D8): no dead surface, and
 * the underlying hooks fire no HTTP request while the flag is off.
 */
import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@aether/ui';
import {
  isContinuationRoutingEnabled,
  useHandoffOperatorContinuation,
  useOperatorContinuations,
  type OperatorHandoffSelection,
} from './use-continuations';

function HandoffTokenCard({
  selection,
}: {
  readonly selection: OperatorHandoffSelection;
}): React.JSX.Element {
  const [copied, setCopied] = useState(false);

  function copy(): void {
    const clipboard = navigator.clipboard;
    if (!clipboard) return;
    void clipboard
      .writeText(selection.token)
      .then(() => setCopied(true))
      .catch(() => undefined);
  }

  return (
    <div className="rounded border border-border-default bg-surface-raised p-2 space-y-1" role="status">
      <div className="text-[10px] text-text-muted font-mono">Deep-link token (handoff)</div>
      <div className="flex items-center gap-2">
        <code className="flex-1 text-[11px] font-mono text-text-primary break-all">{selection.token}</code>
        <Button size="sm" variant="secondary" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <div className="text-[10px] text-text-muted font-mono">
        scope {selection.tenant_scope} · {selection.mode ?? 'selection'}
        {selection.expires_at ? ` · expires ${selection.expires_at}` : ''}
      </div>
    </div>
  );
}

export function OperatorContinuationPanel(): React.JSX.Element | null {
  const { data, isLoading, error, refetch } = useOperatorContinuations();
  const handoff = useHandoffOperatorContinuation();
  // Which row's handoff result is on screen (the handoff mutation is single-valued).
  const [handoffFor, setHandoffFor] = useState<string | null>(null);

  if (!isContinuationRoutingEnabled()) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Continue on phone / Resume</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[11px] text-text-secondary">
          Operator continuations let you resume an investigation on a phone. Pick one to
          mint a handoff token you can deep-link into the mobile app. This surface is
          read-only except creating and handing off continuations.
        </p>

        {isLoading && data.length === 0 ? (
          <LoadingState lines={3} />
        ) : error !== null ? (
          <ErrorState
            title="Unable to load continuations"
            message={error}
            onRetry={refetch}
          />
        ) : data.length === 0 ? (
          <EmptyState title="No operator continuations yet" />
        ) : (
          <ul className="space-y-2">
            {data.map(continuation => (
              <li
                key={continuation.id}
                className="border border-border-default rounded p-2 space-y-1"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-mono text-text-primary">
                    {continuation.summary?.title ?? continuation.id}
                  </span>
                  <Badge size="sm" variant="default">
                    {continuation.surface}
                  </Badge>
                </div>
                {continuation.summary?.subtitle ? (
                  <div className="text-[11px] text-text-secondary">
                    {continuation.summary.subtitle}
                  </div>
                ) : null}
                <div className="text-[10px] text-text-muted font-mono">
                  {continuation.source_client} · {continuation.updated_at}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={handoff.isLoading}
                    onClick={() => {
                      setHandoffFor(continuation.id);
                      void handoff.handoff({ continuation_id: continuation.id });
                    }}
                  >
                    Hand off to phone
                  </Button>
                  {handoff.error !== null && handoffFor === continuation.id && (
                    <span className="text-[11px] text-danger font-mono">{handoff.error}</span>
                  )}
                </div>
                {handoffFor === continuation.id &&
                  handoff.data !== null &&
                  !handoff.data.skipped &&
                  handoff.data.selection !== undefined && (
                    <HandoffTokenCard selection={handoff.data.selection} />
                  )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
