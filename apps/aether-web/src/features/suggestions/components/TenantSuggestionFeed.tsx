import { EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { TenantSuggestionCard } from './TenantSuggestionCard';

type AnyRecord = Record<string, any>;

interface TenantSuggestionFeedProps {
  readonly suggestions: AnyRecord[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly onFeedback: (id: string, feedback: 'helpful' | 'not_helpful' | 'dismissed') => void;
  readonly feedbackLoadingId?: string;
}

export function TenantSuggestionFeed({
  suggestions,
  loading,
  error,
  onFeedback,
  feedbackLoadingId,
}: TenantSuggestionFeedProps) {
  if (loading) return <LoadingState lines={6} />;

  if (error) {
    return (
      <ErrorState
        title="Failed to load suggestions"
        message={error}
      />
    );
  }

  if (suggestions.length === 0) {
    return (
      <EmptyState
        title="No suggestions"
        description="There are no suggestions for your account at this time."
      />
    );
  }

  return (
    <div className="space-y-3">
      {suggestions.map((s, i) => {
        const id = String(s.id ?? s.suggestion_id ?? i);
        return (
          <TenantSuggestionCard
            key={id}
            suggestion={s}
            feedbackLoading={feedbackLoadingId === id}
            onFeedback={(feedback) => onFeedback(id, feedback)}
          />
        );
      })}
    </div>
  );
}
