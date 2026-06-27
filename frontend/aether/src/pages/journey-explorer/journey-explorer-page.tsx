import { useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Card, CardContent, CardHeader, CardTitle,
  Badge, LoadingState, ErrorState, EmptyState,
} from '@aether/ui';
import {
  useUnifiedJourney,
  JourneyTimeline,
  JourneyFilterBar,
} from '@aether-app/features/journey';
import type { ActivityFamily } from '@aether-app/features/journey';

const QUALITY_BADGE: Record<string, { variant: 'success' | 'warning' | 'danger' | 'default'; label: string }> = {
  complete: { variant: 'success', label: 'Complete' },
  partial: { variant: 'warning', label: 'Partial (older compiler)' },
  empty: { variant: 'default', label: 'Empty' },
  not_provisioned: { variant: 'default', label: 'Not provisioned' },
};

function RailSummary({ meta }: { meta: NonNullable<ReturnType<typeof useUnifiedJourney>['meta']> }) {
  return (
    <div className="flex gap-3 flex-wrap text-xs text-text-muted">
      <span><strong className="text-text">{meta.step_count}</strong> steps</span>
      <span className="text-border">|</span>
      {(() => {
        const entry = QUALITY_BADGE[meta.quality_status] ?? QUALITY_BADGE.complete;
        if (!entry) return null;
        return <Badge variant={entry.variant}>{entry.label}</Badge>;
      })()}
      {meta.compiler_version && (
        <span>compiler <code className="font-mono">{meta.compiler_version}</code></span>
      )}
    </div>
  );
}

export function JourneyExplorerPage() {
  const { profileId } = useParams<{ profileId: string }>();
  const id = profileId ?? '';

  const [family, setFamily] = useState<ActivityFamily | undefined>(undefined);
  const [after, setAfter] = useState('');
  const [before, setBefore] = useState('');

  const journeyParams: Parameters<typeof useUnifiedJourney>[0] = { profileId: id };
  if (family) journeyParams.family = family;
  if (after) journeyParams.after = after;
  if (before) journeyParams.before = before;
  const { steps, meta, hasMore, loading, error, loadMore } = useUnifiedJourney(journeyParams);

  function handleClear() {
    setFamily(undefined);
    setAfter('');
    setBefore('');
  }

  if (!id) {
    return (
      <main className="p-6">
        <EmptyState title="No profile selected" description="Navigate to a profile to view its unified journey." />
      </main>
    );
  }

  return (
    <main className="flex flex-col gap-4 p-4 max-w-3xl mx-auto" aria-label="Unified journey explorer">
      <header>
        <h1 className="text-xl font-semibold text-text">Unified Journey</h1>
        <p className="text-sm text-text-muted mt-0.5">
          Interleaved Web2, Web3, campaign, commerce, agent, and x402 activity for this profile.
        </p>
      </header>

      {meta && <RailSummary meta={meta} />}

      {meta?.quality_status === 'partial' && (
        <div role="alert" className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
          Journey compiled with an older compiler version. Trigger a rebuild from the operator console for full cross-rail coverage.
        </div>
      )}

      {meta?.quality_status === 'not_provisioned' && (
        <div role="status" className="text-xs text-text-muted bg-surface-secondary border border-border rounded px-3 py-2">
          No journey has been compiled for this profile yet. Journey compilation begins automatically when activity is ingested.
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Filter</CardTitle>
        </CardHeader>
        <CardContent>
          <JourneyFilterBar
            family={family}
            after={after}
            before={before}
            onFamilyChange={setFamily}
            onAfterChange={setAfter}
            onBeforeChange={setBefore}
            onClear={handleClear}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Timeline</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <ErrorState title="Unable to load journey" message={error} />
          ) : loading && steps.length === 0 ? (
            <LoadingState lines={6} />
          ) : steps.length === 0 && meta?.quality_status === 'not_provisioned' ? (
            <EmptyState
              title="Journey not yet provisioned"
              description="Ingest events for this profile and the journey will be compiled automatically."
            />
          ) : (
            <JourneyTimeline
              steps={steps}
              hasMore={hasMore}
              loading={loading}
              onLoadMore={loadMore}
            />
          )}
        </CardContent>
      </Card>
    </main>
  );
}
