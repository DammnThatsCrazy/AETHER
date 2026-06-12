/**
 * KYBER: Graph Impact Preview
 * Shows which graph vertices/edges will be written if an approval is approved.
 * Owner: Review page
 * Adapter: GET /v1/approvals/{id}/preview
 */
interface GraphWrite {
  kind: 'vertex' | 'edge';
  label: string;
  properties?: Record<string, unknown>;
}

interface GraphImpactPreviewProps {
  readonly graphWrites: readonly GraphWrite[];
  readonly eventsEmitted?: readonly string[];
  readonly loading?: boolean;
}

export function GraphImpactPreview({ graphWrites, eventsEmitted = [], loading = false }: GraphImpactPreviewProps) {
  if (loading) {
    return <div className="graph-impact graph-impact--loading" aria-busy="true">loading graph preview…</div>;
  }
  if (graphWrites.length === 0) {
    return <div className="graph-impact graph-impact--empty">no graph writes projected</div>;
  }

  const vertices = graphWrites.filter((w) => w.kind === 'vertex');
  const edges = graphWrites.filter((w) => w.kind === 'edge');

  return (
    <div className="graph-impact">
      <div className="graph-impact__header">GRAPH IMPACT PREVIEW</div>
      <div className="graph-impact__summary">
        <span className="graph-impact__stat">{vertices.length} vertices</span>
        <span className="graph-impact__stat">{edges.length} edges</span>
        {eventsEmitted.length > 0 && (
          <span className="graph-impact__stat">{eventsEmitted.length} events</span>
        )}
      </div>
      <ul className="graph-impact__list">
        {graphWrites.map((w, i) => (
          <li key={i} className={`graph-impact__item graph-impact__item--${w.kind}`}>
            <span className="graph-impact__kind">{w.kind}</span>
            <span className="graph-impact__label">{w.label}</span>
          </li>
        ))}
      </ul>
      {eventsEmitted.length > 0 && (
        <div className="graph-impact__events">
          <div className="graph-impact__events-title">events</div>
          <ul className="graph-impact__events-list">
            {eventsEmitted.map((e, i) => (
              <li key={i} className="graph-impact__event">{e}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
