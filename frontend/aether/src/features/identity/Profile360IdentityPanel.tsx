/**
 * Profile 360 Identity Panel — PR 8, blueprint §12.2.
 *
 * Identity panel component for the Profile 360 surface: shows the current
 * canonical entity, confidence band, source identities contributing to the
 * profile, and a brief resolution summary. Wired to the explainability API
 * where the flag is on; degrades gracefully to the legacy profile identity
 * summary when the flag is off.
 */

import { useIdentityProfile } from './use-identity';
import { api } from '@aether-app/lib/api/endpoints';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';
import { useQuery } from '@aether/ui';
import type { FC, ReactNode } from 'react';

const STALE = 60_000;

interface IdentityExplanationData {
  readonly canonical_entity_id: string;
  readonly confidence: number;
  readonly confidence_band: string;
  readonly source_identities: Array<{
    source_identity_id: string;
    source: string;
    source_platform: string;
    source_event_id: string;
    alias_type: string;
    confidence: number;
    first_seen_at: string;
    last_seen_at: string;
    alias_display_value_redacted: string;
  }>;
  readonly positive_evidence: Array<{
    signal: string;
    status: string;
    reason_codes: string[];
    source_events: string[];
    source_connectors: string[];
    decision_type: string;
  }>;
  readonly negative_evidence: Array<{
    signal: string;
    status: string;
    reason_codes: string[];
    source_events: string[];
    source_connectors: string[];
    decision_type: string;
  }>;
  readonly ignored_evidence: Array<{
    signal: string;
    status: string;
    reason_codes: string[];
    source_events: string[];
    source_connectors: string[];
    decision_type: string;
  }>;
  readonly graph_version: string;
  readonly resolution_decision_summary: string;
}

async function fetchIdentityExplanation(profileId: string): Promise<IdentityExplanationData> {
  const r = await api.identity.explanation(profileId);
  return r as IdentityExplanationData;
}

function bandColor(band: string): string {
  switch (band) {
    case 'very_high':
    case 'high':
      return 'text-theme-success';
    case 'medium':
      return 'text-theme-warning';
    case 'low':
      return 'text-theme-warning';
    case 'blocked':
      return 'text-theme-danger';
    default:
      return 'text-text-secondary';
  }
}

function bandLabel(band: string): string {
  return band
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

export const Profile360IdentityPanel: FC<{
  readonly userId: string;
  readonly className?: string;
  readonly children?: ReactNode;
}> = ({ userId, className = '', children }) => {
  const enabled = isFeatureEnabled('identity_explainability_enabled');

  const { data: profileData } = useIdentityProfile(userId);

  const { data: explanation, isLoading, error, refetch } = useQuery<IdentityExplanationData>({
    key: `identity-explanation:${userId}`,
    fetcher: () => fetchIdentityExplanation(userId),
    enabled: enabled && !!userId,
    staleTime: STALE,
  });

  if (!enabled) {
    return (
      <div className={`rounded border border-surface-border bg-surface-surface p-4 text-text-secondary text-sm ${className}`}>
        <div className="text-text-primary text-sm font-medium">Identity</div>
        <div className="mt-1 text-xs">Explainability not enabled — showing legacy summary.</div>
        {children}
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className={`rounded border border-surface-border bg-surface-surface p-4 text-text-secondary text-sm ${className}`}>
        <div className="text-text-primary text-sm font-medium">Identity</div>
        <div className="mt-1 text-xs">Loading identity explanation...</div>
      </div>
    );
  }

  if (error || !explanation) {
    return (
      <div className={`rounded border border-surface-border bg-surface-surface p-4 text-text-secondary text-sm ${className}`}>
        <div className="text-text-primary text-sm font-medium">Identity</div>
        <div className="mt-1 text-xs">
          Unable to load identity explanation. {error ? `(${String(error)})` : ''}
        </div>
      </div>
    );
  }

  const sourceCount = explanation.source_identities.length;
  const posCount = explanation.positive_evidence.length;
  const negCount = explanation.negative_evidence.length;
  const ignCount = explanation.ignored_evidence.length;

  return (
    <div className={`rounded border border-surface-border bg-surface-surface p-4 ${className}`}>
      <div className="text-text-primary text-sm font-medium mb-3">Identity</div>

      {/* Canonical entity + confidence */}
      <div className="flex items-center justify-between gap-4 mb-3">
        <div>
          <div className="text-text-secondary text-xs">Canonical Entity</div>
          <div className="font-mono text-sm font-medium text-text-primary break-all">
            {explanation.canonical_entity_id}
          </div>
        </div>
        <div className="text-right">
          <div className="text-text-secondary text-xs">Confidence Band</div>
          <div className={`text-sm font-semibold ${bandColor(explanation.confidence_band)}`}>
            {bandLabel(explanation.confidence_band)}
          </div>
        </div>
      </div>

      {/* Stats row */}
      <div className="flex flex-wrap gap-3 mb-3 text-xs">
        <span className="rounded bg-surface-elevated px-2 py-1 text-text-secondary">
          Sources: {sourceCount}
        </span>
        <span className="rounded bg-surface-elevated px-2 py-1 text-theme-success">
          Positive: {posCount}
        </span>
        <span className="rounded bg-surface-elevated px-2 py-1 text-theme-danger">
          Negative: {negCount}
        </span>
        <span className="rounded bg-surface-elevated px-2 py-1 text-text-secondary">
          Ignored: {ignCount}
        </span>
        <span className="rounded bg-surface-elevated px-2 py-1 text-text-secondary">
          Graph version: {explanation.graph_version}
        </span>
      </div>

      {/* Summary */}
      <div className="mb-3 rounded bg-surface-elevated p-3 text-xs text-text-secondary">
        {explanation.resolution_decision_summary}
      </div>

      {/* Source identities (top 5, collapses to "+N more") */}
      {explanation.source_identities.length > 0 && (
        <div className="mb-2">
          <div className="text-text-secondary text-xs font-medium mb-1">Source Identities</div>
          <ul className="space-y-1">
            {explanation.source_identities.slice(0, 5).map((s) => (
              <li key={s.source_identity_id} className="text-xs text-text-secondary">
                <span className="text-text-primary">{s.source || s.alias_type}</span>
                {' '}
                <span className="text-text-muted">
                  {s.alias_display_value_redacted || '(redacted)'}
                </span>
                {' '}
                <span className="text-text-muted">(conf {s.confidence.toFixed(2)})</span>
              </li>
            ))}
            {explanation.source_identities.length > 5 && (
              <li className="text-text-muted text-xs">
                + {explanation.source_identities.length - 5} more
              </li>
            )}
          </ul>
        </div>
      )}

      {children}
    </div>
  );
};

export default Profile360IdentityPanel;
