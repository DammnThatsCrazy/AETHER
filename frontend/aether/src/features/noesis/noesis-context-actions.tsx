import { useState } from 'react';
import { useExploration, useExplorationClient, useExplorationContext } from '@aether/ui/exploration';
import { exactContextHandoffLimitations } from './exploration-context';

export function NoesisContextActions() {
  const context = useExplorationContext();
  const { toQuery } = useExploration();
  const client = useExplorationClient();
  const [name, setName] = useState('Noesis context');
  const [status, setStatus] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const limitations = exactContextHandoffLimitations(context);
  const selectedCount = context.selection?.selected?.length ?? 0;

  async function saveExactContext() {
    setIsSaving(true);
    setStatus(null);
    try {
      const saved = await client.saveView({ name: name.trim() || 'Noesis context', context });
      setStatus(`Saved exact context as “${saved.name}”.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'The exact context could not be saved.');
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section
      aria-label="Noesis exploration context"
      className="mb-3 rounded border border-border-subtle bg-surface-raised/60 p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <div className="mr-auto">
          <div className="text-xs font-medium text-text-primary">Exact exploration context</div>
          <div className="mt-0.5 text-[10px] text-text-muted">
            {context.temporal.mode} time · {selectedCount} selected subject{selectedCount === 1 ? '' : 's'}
          </div>
        </div>
        <label className="sr-only" htmlFor="noesis-context-name">Saved view name</label>
        <input
          id="noesis-context-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          className="h-8 min-w-40 rounded border border-border-subtle bg-surface px-2 text-xs text-text-primary"
        />
        <button
          type="button"
          onClick={() => void saveExactContext()}
          disabled={isSaving}
          className="h-8 rounded bg-accent px-3 text-xs font-medium text-white disabled:opacity-60"
        >
          {isSaving ? 'Saving…' : 'Save exact context'}
        </button>
        <a
          href={`/explore?${toQuery()}`}
          className="inline-flex h-8 items-center rounded border border-border-default px-3 text-xs font-medium text-text-secondary hover:border-accent/50 hover:text-text-primary"
        >
          Open in Explore
        </a>
        <a
          href="/settings/data-exchange"
          className="inline-flex h-8 items-center rounded border border-border-default px-3 text-xs font-medium text-text-secondary hover:border-accent/50 hover:text-text-primary"
        >
          Open reporting
        </a>
      </div>
      <div className="mt-2 grid gap-1 text-[10px] text-text-muted lg:grid-cols-2">
        <div>Investigation: {limitations.investigation}</div>
        <div>Query export: {limitations.export}</div>
      </div>
      <p className="mt-2 text-[10px] text-text-muted">
        Reports are created only from the capability-gated Data Exchange surface. Watch-to-automation registration and collaboration actions are not available from Noesis yet.
      </p>
      {status && <div role="status" className="mt-2 text-xs text-text-secondary">{status}</div>}
    </section>
  );
}
