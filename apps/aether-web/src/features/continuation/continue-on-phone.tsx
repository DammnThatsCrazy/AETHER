/**
 * "Continue on phone" affordance (M5c).
 *
 * Materializes a continuation from the current Noesis exploration context
 * (POST /v1/continuations), mints a deep-link handoff token for mobile resume
 * (POST /v1/continuations/{id}/handoff), and offers a copy affordance. Renders
 * nothing and fires no requests while `enableContinuations` is OFF (D8).
 */
import { useState } from 'react';
import { useExplorationContext } from '@aether/ui/exploration';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';
import { useCreateContinuation, useHandoffContinuation } from './use-continuations';

export function ContinueOnPhone() {
  const enabled = isFeatureEnabled('enableContinuations');
  const exploration = useExplorationContext();
  const create = useCreateContinuation();
  const handoff = useHandoffContinuation();
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!enabled) return null;

  async function handleContinue() {
    setBusy(true);
    setStatus(null);
    setToken(null);
    try {
      const selected = exploration.selection?.selected ?? [];
      const created = await create.mutate({
        source_client: 'web',
        surface: 'noesis',
        summary: {
          title: 'Noesis exploration',
          subtitle: window.location.pathname,
        },
        canonical_context: {
          route: window.location.pathname,
          filters: exploration,
        },
        resource_references: selected.map(s => ({ kind: s.kind, id: s.id })),
        sensitivity: 'standard',
        freshness: 'live',
      });
      if (created === null) {
        setStatus('Continue-on-phone could not be started.');
        return;
      }
      const selection = await handoff.mutate({
        continuation_id: created.id,
        body: {
          mode: selected.length > 0 ? 'explicit' : 'query',
          resource_ids: selected.map(s => s.id),
        },
      });
      if (selection === null) {
        setStatus('The resume link could not be minted.');
        return;
      }
      setToken(selection.token);
      setStatus('Ready — open Aether on your phone to resume.');
    } catch {
      setStatus('Continue-on-phone is unavailable right now.');
    } finally {
      setBusy(false);
    }
  }

  async function copyToken() {
    if (!token) return;
    try {
      await navigator.clipboard?.writeText(token);
      setStatus('Resume link copied.');
    } catch {
      setStatus('Copy failed — select the link manually.');
    }
  }

  return (
    <section
      aria-label="Continue on phone"
      className="mb-3 rounded border border-border-subtle bg-surface-raised/60 p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <div className="mr-auto">
          <div className="text-xs font-medium text-text-primary">Continue on phone</div>
          <div className="mt-0.5 text-[10px] text-text-muted">
            Materializes this exact exploration context into a handoff token for mobile resume.
          </div>
        </div>
        <button
          type="button"
          onClick={() => void handleContinue()}
          disabled={busy}
          className="h-8 rounded bg-accent px-3 text-xs font-medium text-white disabled:opacity-60"
        >
          {busy ? 'Minting…' : 'Create resume link'}
        </button>
      </div>
      {status && <div role="status" className="mt-2 text-xs text-text-secondary">{status}</div>}
      {token && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded border border-border-subtle bg-surface px-2 py-1.5">
          <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-accent">{token}</code>
          <button
            type="button"
            onClick={() => void copyToken()}
            className="h-6 rounded bg-surface-raised px-2 text-[11px] text-text-secondary hover:text-text-primary"
          >
            Copy
          </button>
        </div>
      )}
    </section>
  );
}
