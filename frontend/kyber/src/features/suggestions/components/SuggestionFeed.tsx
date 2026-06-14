import { EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { SuggestionCard } from './SuggestionCard';

type AnyRecord = Record<string, any>;

export interface SuggestionFeedProps {
  readonly suggestions: AnyRecord[];
  readonly loading: boolean;
  readonly error: string | null;
}

export function SuggestionFeed({ suggestions, loading, error }: SuggestionFeedProps) {
  if (loading) return <LoadingState lines={6} />;
  if (error) return <ErrorState title="Unable to load suggestions" message={error} />;
  if (suggestions.length === 0) return <EmptyState title="No suggestions found" />;

  return (
    <div className="space-y-3">
      {suggestions.map((s) => (
        <SuggestionCard key={s.suggestion_id ?? s.id ?? Math.random()} suggestion={s} />
      ))}
    </div>
  );
}
