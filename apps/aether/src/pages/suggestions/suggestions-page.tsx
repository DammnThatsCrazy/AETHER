import { useState } from 'react';
import { useTenantSuggestions, useSuggestionFeedback } from '@aether-app/features/suggestions';
import { TenantSuggestionFeed } from '@aether-app/features/suggestions/components/TenantSuggestionFeed';

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'suggested', label: 'Suggested' },
  { value: 'delivered', label: 'Delivered' },
  { value: 'review_required', label: 'Review required' },
] as const;

const PRIORITY_OPTIONS = [
  { value: '', label: 'All priorities' },
  { value: 'P0', label: 'P0' },
  { value: 'P1', label: 'P1' },
  { value: 'P2', label: 'P2' },
  { value: 'P3', label: 'P3' },
] as const;

export function SuggestionsPage() {
  const [status, setStatus] = useState('');
  const [priority, setPriority] = useState('');
  const [feedbackLoadingId, setFeedbackLoadingId] = useState<string | null>(null);

  const params: { status?: string; priority?: string; limit: number } = { limit: 50 };
  if (status) params.status = status;
  if (priority) params.priority = priority;

  const { data, loading, error } = useTenantSuggestions(params);
  const { submit } = useSuggestionFeedback();

  const handleFeedback = (id: string, feedback: 'helpful' | 'not_helpful' | 'dismissed') => {
    setFeedbackLoadingId(id);
    submit(id, feedback).finally(() => setFeedbackLoadingId(null));
  };

  const feedProps = feedbackLoadingId !== null
    ? { feedbackLoadingId }
    : {};

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Suggestions</h1>
        <p className="text-sm text-text-secondary mt-0.5">
          Personalized recommendations and intelligence for your account.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <select
          value={status}
          onChange={e => setStatus(e.target.value)}
          className="text-sm border border-border-default rounded-md px-3 py-1.5 bg-surface-default text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
        >
          {STATUS_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        <select
          value={priority}
          onChange={e => setPriority(e.target.value)}
          className="text-sm border border-border-default rounded-md px-3 py-1.5 bg-surface-default text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
        >
          {PRIORITY_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      <TenantSuggestionFeed
        suggestions={data}
        loading={loading}
        error={error}
        onFeedback={handleFeedback}
        {...feedProps}
      />
    </div>
  );
}
