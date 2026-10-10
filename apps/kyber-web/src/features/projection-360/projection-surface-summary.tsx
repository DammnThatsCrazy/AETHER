/**
 * Typed renderer for a projection-surface summary — the S6 surface seam (Kyber).
 *
 * Renders ONLY fields the typed projection envelope declares (digest, lens
 * frame, temporal mode, degradation state, per-section typed SectionState,
 * suppressed sections, content-free unavailable reason). Section state words
 * are shown verbatim from the server; the client never recomputes a state and
 * never formats a synthesized metric. Suppressed sections are hidden, matching
 * the engine's suppression semantics.
 */

import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, cn } from '@aether/ui';
import type { SectionState } from '@aether/shared/intelligence-projection';
import {
  projectionDisplayName,
  type ProjectionSurfaceSummary,
} from './projection-360-types';

/** Map a server SectionState to a UI badge variant — the label stays the raw typed word. */
function stateVariant(state: SectionState): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  switch (state) {
    case 'available':
      return 'success';
    case 'degraded':
    case 'stale':
      return 'warning';
    case 'missing':
      return 'danger';
    case 'empty':
    case 'not_applicable':
    case 'unknown':
    default:
      return 'default';
  }
}

/**
 * Suppressed sections (policy / lens conflict) are withheld — hidden, never
 * rendered as content. The withheld set is the union of the engine's
 * `suppressedSections` ids and any section that itself carries a `suppressed`
 * typed state, so a section can never be double counted.
 */
function withheldSections(summary: ProjectionSurfaceSummary): Set<string> {
  const suppressed = new Set<string>(summary.suppressedSections ?? []);
  for (const section of summary.sections) {
    if (section.state === 'suppressed') suppressed.add(section.id);
  }
  return suppressed;
}

function visibleSections(summary: ProjectionSurfaceSummary, withheld: Set<string>) {
  return summary.sections.filter(section => !withheld.has(section.id));
}

function SectionRow({ section }: { section: { id: string; state: SectionState } }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border-subtle last:border-b-0">
      <span className="text-xs text-text-primary font-medium">{section.id}</span>
      <Badge variant={stateVariant(section.state)} size="sm" className="font-mono">
        {section.state}
      </Badge>
    </div>
  );
}

function Provenance({ summary }: { summary: ProjectionSurfaceSummary }) {
  const items: Array<{ label: string; value: string }> = [];
  if (summary.digest) items.push({ label: 'digest', value: summary.digest });
  if (summary.lensIds?.length) items.push({ label: 'lenses', value: summary.lensIds.join(', ') });
  if (summary.temporalMode) items.push({ label: 'temporal mode', value: summary.temporalMode });
  if (summary.asOf) items.push({ label: 'as of', value: summary.asOf });
  if (summary.degradationState && summary.degradationState !== 'none') {
    items.push({ label: 'degradation', value: summary.degradationState });
  }
  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2 border-b border-border-subtle bg-surface-overlay/40">
      {items.map(item => (
        <span key={item.label} className="text-[10px] text-text-muted font-mono">
          <span className="text-text-secondary">{item.label}:</span> {item.value}
        </span>
      ))}
    </div>
  );
}

export interface ProjectionSurfaceSummaryProps {
  readonly summary: ProjectionSurfaceSummary;
}

/**
 * Presentational projection-surface summary. Pure over the typed envelope so it
 * can be unit-tested with a fabricated (server-shaped) summary — the numbers and
 * states still come only from what a server envelope would carry.
 */
export function ProjectionSurfaceSummary({ summary }: ProjectionSurfaceSummaryProps) {
  const label = projectionDisplayName(summary.projectionId);

  // Fail-isolated, content-free unavailable result — render the typed reason,
  // never a fabricated metric or section body.
  if (!summary.available) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{label} — unavailable</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-xs text-text-secondary">
            The {label} projection is not available in this release.
          </p>
          {summary.reason && (
            <Badge variant="warning" size="sm" className="font-mono normal-case">
              {summary.reason}
            </Badge>
          )}
        </CardContent>
      </Card>
    );
  }

  const withheld = withheldSections(summary);
  const sections = visibleSections(summary, withheld);
  const suppressedCount = withheld.size;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{label}</CardTitle>
      </CardHeader>
      <Provenance summary={summary} />
      <CardContent className="pt-4">
        {sections.length === 0 ? (
          <EmptyState
            title={`No ${label} sections`}
            description="This projection returned no renderable sections."
          />
        ) : (
          <div role="list" aria-label={`${label} sections`}>
            {sections.map(section => (
              <SectionRow key={section.id} section={section} />
            ))}
          </div>
        )}
        {suppressedCount > 0 && (
          <p className={cn('text-[10px] text-text-muted', sections.length > 0 && 'mt-2')}>
            {suppressedCount} section{suppressedCount === 1 ? ' is' : 's are'} suppressed by projection policy.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
