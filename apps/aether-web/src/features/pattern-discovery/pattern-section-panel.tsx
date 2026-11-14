import {
  Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import type { PatternSurface } from '@aether/shared';
import { Link } from 'react-router-dom';
import {
  SECTION_LAYOUT, usePatternDiscoveryEnabled, usePatternSection, type PatternSummaryRow,
} from './use-patterns';

const TITLES: Record<PatternSurface, string> = {
  profile360: 'Discovered patterns involving this profile',
  agent360: 'Discovered patterns involving this agent',
  risk360: 'Pattern-based risk findings',
};

type Variant = 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info';
const SEVERITY: Record<string, Variant> = { critical: 'danger', high: 'warning', medium: 'info', low: 'default' };

function pct(v: unknown): string {
  return typeof v === 'number' ? `${Math.round(v * 100)}%` : '—';
}

function PatternRow({ row }: { row: PatternSummaryRow }) {
  return (
    <li className="space-y-0.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge size="sm" variant={SEVERITY[row.severity ?? 'low'] ?? 'default'}>{row.severity ?? 'low'}</Badge>
        <Badge size="sm">{row.status.replace(/_/g, ' ')}</Badge>
        <Link className="text-sm text-text-primary hover:underline" to={`/patterns?pattern=${encodeURIComponent(row.pattern_id)}`}>
          {row.title}
        </Link>
      </div>
      <p className="text-xs text-text-secondary">
        {row.affected_entity_count} entities · confidence {pct(row.confidence)} · novelty {pct(row.novelty)}
        {row.risk_categories.length > 0 ? ` · ${row.risk_categories.join(', ')}` : ''}
      </p>
    </li>
  );
}

/** Profile 360 / Agent 360 / Risk 360 discovered-pattern section. Renders
 *  nothing unless the tenant has pattern discovery enabled. */
export function PatternSectionPanel({ surface, entityId, riskKind }: {
  readonly surface: PatternSurface;
  readonly entityId: string;
  readonly riskKind?: string;
}) {
  const enabled = usePatternDiscoveryEnabled();
  const section = usePatternSection(surface, entityId, riskKind);
  if (!enabled) return null;
  const data = section.data as Record<string, unknown> | undefined;
  return (
    <Card data-testid={`pattern-section-${surface}`}>
      <CardHeader><CardTitle>{TITLES[surface]}</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-text-secondary">
          Patterns are inferred review material with capped confidence. They never merge identities or change decisions on their own.
        </p>
        {section.isLoading && !data && <LoadingState lines={3} />}
        {section.error && <ErrorState title="Discovered patterns unavailable" message={section.error} onRetry={section.refetch} />}
        {data?.withheld === true && (
          <EmptyState title="Withheld" description="This entity has no affirmative analytics consent, so its discovered patterns are not shown." />
        )}
        {data && data.withheld === false && (data.counts as { total: number }).total === 0 && (
          <EmptyState title="No discovered patterns" description="No pattern discovered so far involves this entity." />
        )}
        {data && data.withheld === false && (data.counts as { total: number }).total > 0 && SECTION_LAYOUT[surface].map(([key, heading, shape]) => {
          const items = (data[key] as unknown[] | undefined) ?? [];
          if (items.length === 0) return null;
          return (
            <section key={key} className="space-y-1.5">
              <h4 className="text-xs font-medium text-text-primary">{heading} · {items.length}</h4>
              {shape === 'patterns' ? (
                <ul className="space-y-2">{(items as PatternSummaryRow[]).slice(0, 8).map(row => <PatternRow key={row.pattern_id} row={row} />)}</ul>
              ) : (
                <ul className="flex flex-wrap gap-1.5">
                  {(items as Array<{ entity: string; shared_patterns: number }>).slice(0, 12).map(e => (
                    <li key={e.entity} className="rounded border border-border-default px-1.5 text-xs">{e.entity} · {e.shared_patterns}</li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </CardContent>
    </Card>
  );
}
