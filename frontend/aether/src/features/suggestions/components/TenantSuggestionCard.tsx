import { Badge, Button } from '@aether/ui';

type AnyRecord = Record<string, any>;

const BLOCKED_KEYS = new Set([
  'source_ref', 'evidence', 'audit_trail', 'policy_decision',
  'operator_notes', 'graph_refs', 'profile_refs', 'journey_refs',
  'lineage_event_ids',
]);

function relTime(iso: string | undefined | null): string {
  if (!iso) return '—';
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (d === 0) return 'Today';
  if (d === 1) return 'Yesterday';
  if (d < 30) return `${d} days ago`;
  if (d < 365) return `${Math.floor(d / 30)} months ago`;
  return `${Math.floor(d / 365)} years ago`;
}

function priorityVariant(priority: unknown): 'warning' | 'default' {
  return priority === 'P0' || priority === 'P1' ? 'warning' : 'default';
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

interface TenantSuggestionCardProps {
  readonly suggestion: AnyRecord;
  readonly onFeedback?: (feedback: 'helpful' | 'not_helpful' | 'dismissed') => void;
  readonly feedbackLoading?: boolean;
}

export function TenantSuggestionCard({
  suggestion,
  onFeedback,
  feedbackLoading = false,
}: TenantSuggestionCardProps) {
  const safe: AnyRecord = Object.fromEntries(
    Object.entries(suggestion).filter(([k]) => !BLOCKED_KEYS.has(k)),
  );

  const title = fmt(safe.title);
  const priority = fmt(safe.priority, '');
  const status = fmt(safe.status, '');
  const summary = fmt(safe.summary, '');
  const what = fmt(safe.what, '');
  const why = fmt(safe.why, '');
  const impact = fmt(safe.impact, '');
  const recommendedAction = fmt(safe.recommended_action ?? safe.recommendedAction, '');
  const confidenceScore = safe.confidence_score ?? safe.confidenceScore;
  const createdAt = fmt(safe.created_at ?? safe.createdAt, '');

  const confidencePct =
    confidenceScore !== undefined && confidenceScore !== null
      ? `${Math.round(Number(confidenceScore) * 100)}%`
      : null;

  return (
    <div className="border border-border-default rounded-lg p-4 space-y-3 bg-surface-default">
      <div className="flex items-start gap-2 flex-wrap">
        <h3 className="text-sm font-semibold text-text-primary flex-1 min-w-0">{title}</h3>
        <div className="flex items-center gap-1.5 shrink-0">
          {priority && (
            <Badge variant={priorityVariant(safe.priority)} size="sm">
              {priority}
            </Badge>
          )}
          {status && (
            <Badge variant="default" size="sm">
              {status}
            </Badge>
          )}
        </div>
      </div>

      {summary && (
        <p className="text-sm text-text-secondary">{summary}</p>
      )}

      <div className="space-y-2">
        {what && (
          <div>
            <p className="text-xs font-medium text-text-muted uppercase tracking-wide">What</p>
            <p className="text-sm text-text-primary">{what}</p>
          </div>
        )}
        {why && (
          <div>
            <p className="text-xs font-medium text-text-muted uppercase tracking-wide">Why</p>
            <p className="text-sm text-text-primary">{why}</p>
          </div>
        )}
        {impact && (
          <div>
            <p className="text-xs font-medium text-text-muted uppercase tracking-wide">Impact</p>
            <p className="text-sm text-text-primary">{impact}</p>
          </div>
        )}
        {recommendedAction && (
          <div>
            <p className="text-xs font-medium text-text-muted uppercase tracking-wide">Recommended action</p>
            <p className="text-sm text-text-primary">{recommendedAction}</p>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center gap-3 text-xs text-text-muted">
          {confidencePct !== null && (
            <span>Confidence: <span className="text-text-secondary font-medium">{confidencePct}</span></span>
          )}
          {createdAt && <span>{relTime(createdAt)}</span>}
        </div>

        {onFeedback && (
          <div className="flex items-center gap-1.5">
            <Button
              variant="ghost"
              size="sm"
              disabled={feedbackLoading}
              onClick={() => onFeedback('helpful')}
            >
              Helpful
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={feedbackLoading}
              onClick={() => onFeedback('not_helpful')}
            >
              Not Helpful
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={feedbackLoading}
              onClick={() => onFeedback('dismissed')}
            >
              Dismiss
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
