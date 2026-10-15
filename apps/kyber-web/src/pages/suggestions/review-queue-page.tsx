import { PageWrapper } from '@kyber/components/layout';
import { useReviewQueue, useSuggestionActions } from '@kyber/features/suggestions';
import { ReviewQueue } from '@kyber/features/suggestions/components/ReviewQueue';

export function ReviewQueuePage() {
  const { data, loading, refresh } = useReviewQueue();
  const { approve, reject, suppress } = useSuggestionActions();

  const handleApprove = async (id: string) => {
    await approve(id);
    refresh();
  };

  const handleReject = async (id: string, reason: string) => {
    await reject(id, reason);
    refresh();
  };

  const handleSuppress = async (id: string, reason: string) => {
    await suppress(id, reason);
    refresh();
  };

  return (
    <PageWrapper
      title="Review Queue"
      subtitle="Suggestions awaiting operator review."
      actions={
        <a href="/intelligence/suggestions" className="text-xs text-brand-default hover:underline font-mono">
          ← Back to Suggestions
        </a>
      }
    >
      <ReviewQueue
        items={data}
        loading={loading}
        onApprove={handleApprove}
        onReject={handleReject}
        onSuppress={handleSuppress}
      />
    </PageWrapper>
  );
}
