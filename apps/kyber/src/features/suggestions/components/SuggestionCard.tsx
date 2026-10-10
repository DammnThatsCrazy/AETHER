import { useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from '@aether/ui';
import { TargetingEvidenceDrawer, isTargetingSuggestion } from './TargetingEvidenceDrawer';

type AnyRecord = Record<string, any>;

function priorityVariant(priority?: string): 'danger' | 'warning' | 'default' {
  if (priority === 'P0') return 'danger';
  if (priority === 'P1') return 'warning';
  return 'default';
}

function statusVariant(status?: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'approved' || status === 'executed' || status === 'delivered' || status === 'measured' || status === 'learned') return 'success';
  if (status === 'review_required' || status === 'oriented' || status === 'suggested') return 'warning';
  if (status === 'rejected' || status === 'failed' || status === 'expired') return 'danger';
  return 'default';
}

function pct(v: unknown): string {
  return typeof v === 'number' ? `${Math.round(v * 100)}%` : '—';
}

export interface SuggestionCardProps {
  readonly suggestion: AnyRecord;
  onApprove?: () => void;
  onReject?: () => void;
  onSuppress?: () => void;
}

export function SuggestionCard({ suggestion, onApprove, onReject, onSuppress }: SuggestionCardProps) {
  const isActionable = suggestion.status === 'review_required';
  const isTargeting = isTargetingSuggestion(suggestion);
  const [evidenceOpen, setEvidenceOpen] = useState(false);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm font-semibold">
            {suggestion.title ?? suggestion.suggestion_id ?? 'Untitled'}
          </CardTitle>
          <div className="flex items-center gap-1 shrink-0">
            {suggestion.priority && (
              <Badge variant={priorityVariant(suggestion.priority)}>{suggestion.priority}</Badge>
            )}
            {suggestion.suggestion_class && (
              <Badge variant="default">{suggestion.suggestion_class}</Badge>
            )}
            {suggestion.status && (
              <Badge variant={statusVariant(suggestion.status)}>{suggestion.status}</Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {suggestion.summary && (
            <p className="text-xs text-text-muted">{suggestion.summary}</p>
          )}
          {suggestion.recommended_action && (
            <div className="rounded border border-border-default bg-surface-subtle px-2 py-1 text-xs font-mono">
              {suggestion.recommended_action}
            </div>
          )}
          <div className="text-xs text-text-muted">
            Confidence: {pct(suggestion.confidence_score)}
          </div>
          {isTargeting && (
            <div className="flex items-center gap-2">
              <Badge variant="accent" size="sm">targeting</Badge>
              <Button size="sm" variant="ghost" onClick={() => setEvidenceOpen(true)}>
                Targeting evidence
              </Button>
            </div>
          )}
          {isActionable && (onApprove || onReject || onSuppress) && (
            <div className="flex items-center gap-2 pt-1">
              {onApprove && (
                <Button size="sm" variant="primary" onClick={onApprove}>Approve</Button>
              )}
              {onReject && (
                <Button size="sm" variant="danger" onClick={onReject}>Reject</Button>
              )}
              {onSuppress && (
                <Button size="sm" variant="ghost" onClick={onSuppress}>Suppress</Button>
              )}
            </div>
          )}
        </div>
      </CardContent>
      {evidenceOpen && (
        <TargetingEvidenceDrawer suggestion={suggestion} onClose={() => setEvidenceOpen(false)} />
      )}
    </Card>
  );
}
