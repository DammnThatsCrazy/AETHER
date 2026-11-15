import { useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import type { PatternLens } from '@aether/shared';
import { Link } from 'react-router-dom';
import { markPatternsSeen, usePatternDiscoveryEnabled, usePatternLens, type PatternSummaryRow } from './use-patterns';

const LENS_TITLE: Record<PatternLens, string> = {
  campaign360: 'Patterns in this campaign',
  geographic360: 'Patterns in this region',
  communication360: 'Patterns in communications',
  journey360: 'Patterns in this journey',
};

function Row({ row }: { row: PatternSummaryRow }) {
  return (
    <li className="flex flex-wrap items-center gap-2 text-sm">
      {row.is_new && <Badge size="sm" variant="accent">new</Badge>}
      {row.is_changed && <Badge size="sm" variant="info">changed</Badge>}
      {row.pinned && <Badge size="sm">pinned</Badge>}
      <Badge size="sm">{row.severity ?? 'low'}</Badge>
      <Link className="hover:underline" to={`/patterns?pattern=${encodeURIComponent(row.pattern_id)}`}>{row.title}</Link>
      <span className="text-xs" style={{ color: 'var(--ae-mute)' }}>{row.affected_entity_count} entities</span>
    </li>
  );
}

/** Campaign / Geographic / Communications / Journey 360 discovered-pattern lens. */
export function PatternLensPanel({ lens, subject }: { readonly lens: PatternLens; readonly subject: string }) {
  const enabled = usePatternDiscoveryEnabled();
  const view = usePatternLens(lens, subject);
  const [marking, setMarking] = useState(false);
  if (!enabled || !subject) return null;
  const data = view.data;
  return (
    <Card data-testid={`pattern-lens-${lens}`}>
      <CardHeader><CardTitle>{LENS_TITLE[lens]}{data ? ` · ${data.counts.total}` : ''}</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs" style={{ color: 'var(--ae-mute)' }}>
          Surfaced automatically from behaviour concentrated here. Hide, pin or rename any of them on the Patterns page.
        </p>
        {view.isLoading && !data && <LoadingState lines={3} />}
        {view.error && <ErrorState title="Patterns unavailable" message={view.error} onRetry={view.refetch} />}
        {data?.withheld && <EmptyState title="Withheld" description="No affirmative analytics consent for this profile." />}
        {data && !data.withheld && data.counts.total === 0 && (
          <EmptyState title="No patterns here yet" description="Nothing surfaced so far concentrates in this view." />
        )}
        {data && !data.withheld && (data.new_count ?? 0) > 0 && (
          <div className="flex items-center gap-2 text-xs">
            <span>{data.new_count} new since you last looked</span>
            <Button size="sm" variant="ghost" disabled={marking} onClick={async () => {
              setMarking(true);
              try { await markPatternsSeen(data.scope ?? `lens:${lens}:${subject}`); view.refetch(); } finally { setMarking(false); }
            }}>Mark seen</Button>
          </div>
        )}
        {data && !data.withheld && data.groups.map(g => (
          <section key={g.kind} className="space-y-1.5">
            <h4 className="text-xs font-medium">{g.heading} · {g.patterns.length}</h4>
            <ul className="space-y-1.5">{g.patterns.slice(0, 6).map(r => <Row key={r.pattern_id} row={r} />)}</ul>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}
