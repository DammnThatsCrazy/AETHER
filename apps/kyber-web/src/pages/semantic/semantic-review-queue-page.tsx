import { useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, FreshnessIndicator, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { PermissionGate } from '@kyber/features/permissions';
import {
  NOT_YET_INSTRUMENTED_FIELDS,
  SEMANTIC_QUEUE_TYPES,
  useSemanticFleetHealth,
  useSemanticReviewQueue,
  type SemanticReviewQueueItem,
} from '@kyber/features/semantic';

const SEMANTIC_COPY =
  'Semantic classification fleet across all tenants. Read-only surface — review items are dispositioned by backend workers, not from Kyber.';

function humanize(value: unknown): string {
  return String(value ?? '—').replace(/_/g, ' ');
}

function formatRate(rate: unknown): string {
  if (rate === null || rate === undefined) return '—';
  return `${(Number(rate) * 100).toFixed(1)}%`;
}

function formatAge(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(diff)) return '—';
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 1) return '<1h';
  if (hours < 48) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function queueTypeVariant(queueType: string): 'success' | 'warning' | 'danger' | 'info' | 'default' {
  if (queueType === 'ambiguous_subject') return 'warning';
  if (queueType === 'campaign_mapping') return 'info';
  if (queueType === 'graph_promotion_candidate') return 'success';
  return 'default';
}

function Metric({ label, value }: { readonly label: string; readonly value: unknown }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? 0)}</div>
      </CardContent>
    </Card>
  );
}

// ── Fleet health scorecard ─────────────────────────────────────────────────────

function FleetHealthSection() {
  const { data, fetchedAt, loading, error, refresh } = useSemanticFleetHealth();

  if (loading) return <LoadingState lines={4} />;
  if (error) {
    return <EmptyState title="Unable to load semantic fleet health" description={error} />;
  }
  if (!data) return null;

  const statusBreakdown = data.status_breakdown;

  return (
    <>
      <div className="flex items-center justify-between">
        <div className="text-xs text-text-muted font-mono">Fleet health</div>
        <FreshnessIndicator computedAt={fetchedAt} onRefresh={refresh} />
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Metric label="Enabled tenants" value={data.enabled_tenants} />
        <Metric label="Classified observations" value={data.classified_observations} />
        <Metric label="Abstention rate" value={formatRate(data.abstention_rate)} />
        <Metric label="Quarantined observations" value={data.quarantined_observations} />
        <Metric label="Consent-restricted observations" value={data.consent_restricted_observations} />
        <Metric label="Sentiment observations" value={data.sentiment_observations ?? '—'} />
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Status breakdown</CardTitle></CardHeader>
          <CardContent className="text-xs font-mono space-y-1">
            {Object.keys(statusBreakdown).length === 0 ? (
              <p className="text-text-muted">No classified observations yet.</p>
            ) : (
              Object.entries(statusBreakdown).map(([status, count]) => (
                <div key={status} className="flex justify-between">
                  <span className="text-text-muted">{humanize(status)}</span>
                  <span className="text-text-primary">{count}</span>
                </div>
              ))
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Model versions</CardTitle></CardHeader>
          <CardContent>
            {data.model_versions.length === 0 ? (
              <p className="text-xs text-text-muted font-mono">No models registered.</p>
            ) : (
              <div className="flex items-center gap-1.5 flex-wrap">
                {data.model_versions.map(version => (
                  <Badge key={version} size="sm">{version}</Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Not yet instrumented</CardTitle></CardHeader>
          <CardContent className="text-xs font-mono space-y-2">
            <div className="flex items-center gap-1.5 flex-wrap">
              {NOT_YET_INSTRUMENTED_FIELDS.map(field => (
                <Badge key={field.key} size="sm" variant="default">{field.label}</Badge>
              ))}
            </div>
            <p className="text-text-muted">
              The backend reports hardcoded placeholder values for these fields — they are
              not shown as live metrics until real instrumentation lands.
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}

// ── Review queue ───────────────────────────────────────────────────────────────

function ReviewQueueRow({ item }: { readonly item: SemanticReviewQueueItem }) {
  return (
    <tr className="border-b border-border-default/50 hover:bg-surface-raised">
      <td className="py-2 px-2 text-text-primary">{item.id}</td>
      <td className="py-2 px-2 text-text-primary">{item.tenant_id}</td>
      <td className="py-2 px-2">
        <Badge size="sm" variant={queueTypeVariant(item.queue_type)}>{humanize(item.queue_type)}</Badge>
      </td>
      <td className="py-2 px-2 text-text-secondary">{item.subject_ref ?? '—'}</td>
      <td className="py-2 px-2 text-text-secondary">{item.source_event_id ?? '—'}</td>
      <td className="py-2 px-2 text-text-secondary">{humanize(item.status)}</td>
      <td className="py-2 px-2 text-right text-text-secondary">{formatAge(item.created_at)}</td>
    </tr>
  );
}

function ReviewQueueSection() {
  const [queueType, setQueueType] = useState<string | undefined>(undefined);
  const { data, loading, error } = useSemanticReviewQueue(queueType);

  const queues = data?.queues ?? [...SEMANTIC_QUEUE_TYPES];
  const countsByQueue = data?.counts_by_queue ?? {};
  const items = data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <CardTitle>Review queue</CardTitle>
          <div className="flex gap-1 flex-wrap" role="tablist" aria-label="Filter review queue by type">
            <button
              role="tab"
              aria-selected={queueType === undefined}
              onClick={() => setQueueType(undefined)}
              className={`rounded px-2 py-1 text-xs font-mono border ${
                queueType === undefined
                  ? 'border-accent text-accent bg-accent/10'
                  : 'border-border-default text-text-secondary hover:text-text-primary'
              }`}
            >
              All
            </button>
            {queues.map(queue => (
              <button
                key={queue}
                role="tab"
                aria-selected={queueType === queue}
                onClick={() => setQueueType(queue)}
                className={`rounded px-2 py-1 text-xs font-mono border ${
                  queueType === queue
                    ? 'border-accent text-accent bg-accent/10'
                    : 'border-border-default text-text-secondary hover:text-text-primary'
                }`}
              >
                {humanize(queue)} ({countsByQueue[queue] ?? 0})
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? <LoadingState lines={4} /> : error ? (
          <EmptyState title="Unable to load review queue" description={error} />
        ) : items.length === 0 ? (
          <EmptyState
            title="Review queue is empty"
            description="Low-confidence subject and campaign resolutions, and graph promotion candidates, appear here when semantic workers enqueue them."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono border-collapse">
              <thead>
                <tr className="border-b border-border-default text-text-muted">
                  <th className="py-2 px-2 text-left">Item</th>
                  <th className="py-2 px-2 text-left">Tenant</th>
                  <th className="py-2 px-2 text-left">Queue</th>
                  <th className="py-2 px-2 text-left">Subject</th>
                  <th className="py-2 px-2 text-left">Source event</th>
                  <th className="py-2 px-2 text-left">Status</th>
                  <th className="py-2 px-2 text-right">Age</th>
                </tr>
              </thead>
              <tbody>
                {items.map(item => <ReviewQueueRow key={item.id} item={item} />)}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export function SemanticReviewQueuePage() {
  return (
    <PageWrapper title="Semantic Operations" subtitle={SEMANTIC_COPY}>
      <PermissionGate
        requires="canApprove"
        fallback={
          <EmptyState
            title="Operator approval permissions required"
            description="The semantic review queue is restricted to operators with approval permissions."
          />
        }
      >
        <div className="space-y-4">
          <FleetHealthSection />
          <ReviewQueueSection />
        </div>
      </PermissionGate>
    </PageWrapper>
  );
}
