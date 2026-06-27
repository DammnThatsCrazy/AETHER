import { useState } from 'react';
import {
  Badge, Button, Card, CardContent, CardHeader,
  EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import { useMappingReviews, useResolveReview, useIgnoreReview } from '@aether-app/features/campaigns/use-mapping-review';

type Review = Record<string, unknown>;

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function relTime(iso: string | undefined | null): string {
  if (!iso) return '—';
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (d === 0) return 'Today';
  if (d === 1) return 'Yesterday';
  if (d < 30) return `${d}d ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

function EvidenceTag({ label, value }: { label: string; value: string | undefined | null }) {
  if (!value) return null;
  return (
    <div className="flex items-center gap-1 text-xs">
      <span className="text-text-muted">{label}:</span>
      <code className="bg-surface-overlay px-1 rounded text-text-primary">{value}</code>
    </div>
  );
}

function ReviewCard({
  review,
  onResolve,
  onIgnore,
}: {
  review: Review;
  onResolve: (reviewId: string) => void;
  onIgnore: (reviewId: string) => void;
}) {
  const reviewId = fmt(review.review_id ?? review.id);
  const evidence = (review.evidence ?? {}) as Record<string, unknown>;
  const count = review.observed_count as number | undefined;
  const affected = review.affected_touchpoints as number | undefined;
  const firstSeen = review.first_seen_at as string | undefined;
  const lastSeen = review.last_seen_at as string | undefined;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Badge variant="warning" size="sm">open</Badge>
            {count !== undefined && (
              <span className="text-xs text-text-muted">{count.toLocaleString()} observation{count !== 1 ? 's' : ''}</span>
            )}
            {affected !== undefined && affected > 0 && (
              <span className="text-xs text-text-muted">{affected.toLocaleString()} touchpoint{affected !== 1 ? 's' : ''}</span>
            )}
          </div>
          <span className="text-xs text-text-muted font-mono">{reviewId.slice(0, 8)}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Evidence signals */}
        <div className="flex flex-wrap gap-2">
          <EvidenceTag label="platform" value={fmt(evidence.platform)} />
          <EvidenceTag label="ext_campaign_id" value={fmt(evidence.external_campaign_id)} />
          <EvidenceTag label="utm_id" value={fmt(evidence.utm_id)} />
          <EvidenceTag label="utm_campaign" value={fmt(evidence.utm_campaign)} />
          <EvidenceTag label="utm_source" value={fmt(evidence.utm_source)} />
          <EvidenceTag label="utm_medium" value={fmt(evidence.utm_medium)} />
        </div>

        <div className="flex items-center justify-between text-xs text-text-muted">
          <span>First seen {relTime(firstSeen)}</span>
          {lastSeen && firstSeen !== lastSeen && <span>Last seen {relTime(lastSeen)}</span>}
        </div>

        <div className="flex items-center gap-2 pt-1">
          <Button
            variant="primary"
            size="sm"
            onClick={() => onResolve(reviewId)}
            aria-label="Resolve this review by mapping to a campaign"
          >
            Resolve
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              if (window.confirm('Ignore this mapping review? It will be hidden from the queue.')) {
                onIgnore(reviewId);
              }
            }}
            aria-label="Ignore this review"
          >
            Ignore
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ResolveModal({
  reviewId,
  onClose,
  onConfirm,
}: {
  reviewId: string;
  onClose: () => void;
  onConfirm: (campaignId: string, note: string) => void;
}) {
  const [campaignId, setCampaignId] = useState('');
  const [note, setNote] = useState('');
  const valid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(campaignId.trim());

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="resolve-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="bg-surface-base border border-border-default rounded-lg shadow-xl p-6 w-full max-w-md space-y-4">
        <h2 id="resolve-modal-title" className="text-base font-semibold text-text-primary">
          Resolve mapping review
        </h2>
        <p className="text-sm text-text-secondary">
          Assign this unresolved evidence to a canonical Aether campaign UUID.
          This will create a durable alias and trigger touchpoint reprocessing.
        </p>
        <div className="space-y-2">
          <label htmlFor="campaign-id-input" className="text-xs text-text-secondary font-medium">
            Canonical campaign UUID
          </label>
          <input
            id="campaign-id-input"
            type="text"
            value={campaignId}
            onChange={e => setCampaignId(e.target.value)}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            className="w-full font-mono text-sm border border-border-default rounded px-3 py-2 bg-surface-raised text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            aria-describedby={!valid && campaignId ? 'uuid-error' : undefined}
          />
          {!valid && campaignId && (
            <p id="uuid-error" className="text-xs text-danger" role="alert">
              Must be a valid UUID (canonical Aether campaign ID).
            </p>
          )}
        </div>
        <div className="space-y-2">
          <label htmlFor="note-input" className="text-xs text-text-secondary font-medium">
            Resolution note (optional)
          </label>
          <input
            id="note-input"
            type="text"
            value={note}
            onChange={e => setNote(e.target.value)}
            placeholder="Why this campaign matches"
            className="w-full text-sm border border-border-default rounded px-3 py-2 bg-surface-raised text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
          />
        </div>
        <div className="flex items-center justify-end gap-2 pt-2">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!valid}
            onClick={() => valid && onConfirm(campaignId.trim(), note)}
          >
            Confirm resolution
          </Button>
        </div>
      </div>
    </div>
  );
}

export function MappingReviewPage() {
  const [statusFilter, setStatusFilter] = useState<'open' | 'resolved' | 'ignored'>('open');
  const { data, isLoading, error, refetch } = useMappingReviews({ status: statusFilter, limit: 50 });
  const resolveMutation = useResolveReview();
  const ignoreMutation = useIgnoreReview();
  const [resolving, setResolving] = useState<string | null>(null);

  const raw = data as Record<string, unknown> | null;
  const reviews: Review[] = Array.isArray(raw?.items) ? (raw!.items as Review[]) : Array.isArray(data) ? (data as Review[]) : [];

  async function handleIgnore(reviewId: string) {
    await ignoreMutation.mutate({ reviewId });
    refetch();
  }

  async function handleResolve(reviewId: string, campaignId: string, note: string) {
    await resolveMutation.mutate({ reviewId, campaignId, ...(note ? { note } : {}) });
    setResolving(null);
    refetch();
  }

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Mapping Review</h1>
        <p className="text-sm text-text-secondary mt-0.5">
          Unresolved and ambiguous campaign evidence requiring manual assignment.
          Resolving a review creates a durable alias and reprocesses affected touchpoints.
        </p>
      </div>

      {/* Status filter */}
      <div className="flex items-center gap-2" role="group" aria-label="Review status filter">
        {(['open', 'resolved', 'ignored'] as const).map(s => (
          <Button
            key={s}
            variant={statusFilter === s ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setStatusFilter(s)}
            aria-pressed={statusFilter === s}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </Button>
        ))}
      </div>

      {error && <ErrorState title="Failed to load reviews" message={String(error)} />}
      {isLoading && <LoadingState lines={6} />}

      {!isLoading && !error && reviews.length === 0 && (
        <EmptyState
          title={`No ${statusFilter} reviews`}
          description={
            statusFilter === 'open'
              ? 'All campaign evidence has been resolved. Good work!'
              : `No ${statusFilter} reviews found.`
          }
        />
      )}

      <div className="space-y-4">
        {reviews.map((review, i) => (
          <ReviewCard
            key={fmt(review.review_id ?? review.id ?? i)}
            review={review}
            onResolve={id => setResolving(id)}
            onIgnore={handleIgnore}
          />
        ))}
      </div>

      {resolving && (
        <ResolveModal
          reviewId={resolving}
          onClose={() => setResolving(null)}
          onConfirm={(cid, note) => handleResolve(resolving, cid, note)}
        />
      )}
    </div>
  );
}
