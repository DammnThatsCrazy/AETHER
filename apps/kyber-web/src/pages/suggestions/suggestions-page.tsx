import {
  Card,
  CardContent,
  LoadingState,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import {
  useReviewQueue,
  useSuggestionActions,
  useSuggestions,
  useSuggestionsSummary,
} from '@kyber/features/suggestions';
import { ReviewQueue } from '@kyber/features/suggestions/components/ReviewQueue';
import { SuggestionFeed } from '@kyber/features/suggestions/components/SuggestionFeed';
import { SuggestionFilters } from '@kyber/features/suggestions/components/SuggestionFilters';
import { useState } from 'react';

type AnyRecord = Record<string, any>;

function Metric({ label, value }: { readonly label: string; readonly value: unknown }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? '—')}</div>
      </CardContent>
    </Card>
  );
}

export function SuggestionsPage() {
  const [filters, setFilters] = useState<AnyRecord>({});
  const { data: suggestions, loading: feedLoading, error: feedError, refresh: refreshFeed } = useSuggestions(filters);
  const { data: summary, loading: summaryLoading } = useSuggestionsSummary();
  const { data: queue, loading: queueLoading, refresh: refreshQueue } = useReviewQueue();
  const { approve, reject, suppress } = useSuggestionActions();

  const handleApprove = async (id: string) => {
    await approve(id);
    refreshQueue();
    refreshFeed();
  };

  const handleReject = async (id: string, reason: string) => {
    await reject(id, reason);
    refreshQueue();
    refreshFeed();
  };

  const handleSuppress = async (id: string, reason: string) => {
    await suppress(id, reason);
    refreshQueue();
    refreshFeed();
  };

  return (
    <PageWrapper
      title="OODA Suggestion Intelligence"
      subtitle="Unified observe-orient-suggest-review-approve-execute-measure-learn lifecycle across all tenants."
    >
      {summaryLoading ? (
        <LoadingState lines={2} />
      ) : (
        <div className="grid gap-3 md:grid-cols-4 mb-4">
          <Metric label="Total" value={(summary as AnyRecord).total} />
          <Metric label="Open" value={(summary as AnyRecord).open} />
          <Metric label="Review required" value={(summary as AnyRecord).review_required} />
          <Metric label="Closed" value={(summary as AnyRecord).closed} />
        </div>
      )}

      <Tabs defaultValue="feed">
        <TabsList>
          <TabsTrigger value="feed">Feed</TabsTrigger>
          <TabsTrigger value="review-queue">Review Queue</TabsTrigger>
          <TabsTrigger value="quality">Quality</TabsTrigger>
          <TabsTrigger value="outcomes">Outcomes</TabsTrigger>
        </TabsList>

        <TabsContent value="feed">
          <SuggestionFilters filters={filters} onChange={setFilters} />
          <SuggestionFeed suggestions={suggestions} loading={feedLoading} error={feedError} />
        </TabsContent>

        <TabsContent value="review-queue">
          <ReviewQueue
            items={queue}
            loading={queueLoading}
            onApprove={handleApprove}
            onReject={handleReject}
            onSuppress={handleSuppress}
          />
        </TabsContent>

        <TabsContent value="quality">
          <Card>
            <CardContent>
              <div className="py-8 text-center text-sm text-text-muted font-mono">
                Quality dashboard coming soon
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="outcomes">
          <Card>
            <CardContent>
              <div className="py-8 text-center text-sm text-text-muted font-mono">
                Outcomes tracker coming soon
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
