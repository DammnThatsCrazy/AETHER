import { useState } from 'react';
import {
  cn, Card, CardHeader, CardTitle, CardContent,
  Badge, Button, ScrollArea,
  Tabs, TabsList, TabsTrigger, TabsContent,
  formatInstant, useTimeContext,
} from '@aether/ui';
import type {
  RelationshipPath,
  PathExplanation,
  PathClassification,
} from '@aether/shared/operational-intelligence';

const CLASSIFICATION_CONFIG: Record<PathClassification, { label: string; variant: 'default' | 'success' | 'warning' | 'danger' | 'info'; icon: string }> = {
  observed:         { label: 'Observed',        variant: 'success',  icon: '●' },
  causal_supported: { label: 'Causal',          variant: 'info',     icon: '◆' },
  attributed:       { label: 'Attributed',      variant: 'info',     icon: '▲' },
  inferred:         { label: 'Inferred',        variant: 'warning',  icon: '◇' },
  correlated:       { label: 'Correlated',      variant: 'danger',   icon: '○' },
  mixed:            { label: 'Mixed',           variant: 'default',  icon: '◈' },
};

function ClassificationBadge({ classification }: { readonly classification: PathClassification }) {
  const cfg = CLASSIFICATION_CONFIG[classification] ?? CLASSIFICATION_CONFIG.mixed;
  return (
    <Badge variant={cfg.variant} aria-label={`Classification: ${cfg.label}`}>
      <span aria-hidden="true">{cfg.icon}</span>
      <span className="ml-1">{cfg.label}</span>
    </Badge>
  );
}

function ScoreBar({ label, value }: { readonly label: string; readonly value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.8 ? '#22c55e' : value >= 0.5 ? '#eab308' : '#ef4444';
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-text-secondary">{label}</span>
        <span className="font-mono text-text-primary">{pct}%</span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
        className="h-1.5 w-full bg-surface-raised rounded-full overflow-hidden"
      >
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

export interface PathInspectorProps {
  readonly path: RelationshipPath;
  readonly explanation?: PathExplanation;
  readonly onLoadExplanation?: () => Promise<void>;
  readonly onSaveToInvestigation?: (pathId: string, snapshotId?: string) => void;
  readonly onClose: () => void;
  readonly className?: string;
}

export function PathInspector({
  path,
  explanation,
  onLoadExplanation,
  onSaveToInvestigation,
  onClose,
  className,
}: PathInspectorProps) {
  const timeCtx = useTimeContext();
  const [loadingExplanation, setLoadingExplanation] = useState(false);
  const shortId = path.path_id.slice(0, 8);

  async function handleLoadExplanation() {
    if (!onLoadExplanation) return;
    setLoadingExplanation(true);
    try { await onLoadExplanation(); } finally { setLoadingExplanation(false); }
  }

  return (
    <Card className={cn('flex flex-col h-full', className)}>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">
          Path <span className="font-mono text-xs text-text-secondary">#{shortId}</span>
        </CardTitle>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close path inspector">✕</Button>
      </CardHeader>

      <CardContent className="flex-1 overflow-hidden p-0">
        <Tabs defaultValue="overview" className="flex flex-col h-full">
          <TabsList className="mx-4 mb-0">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="hops">Hops</TabsTrigger>
            <TabsTrigger value="evidence">Evidence</TabsTrigger>
            <TabsTrigger value="score">Score</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="flex-1 overflow-auto px-4 pb-4 space-y-4">
            <div className="flex flex-wrap gap-2 pt-2">
              <ClassificationBadge classification={path.classification} />
              {path.layer_sequence.map((layer, i) => (
                <Badge key={i} variant="default" aria-label={`Layer: ${layer}`}>{layer}</Badge>
              ))}
            </div>
            <div className="space-y-2">
              <ScoreBar label="Path confidence" value={path.path_confidence} />
              <ScoreBar label="Evidence coverage" value={path.evidence_coverage} />
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <dt className="text-text-secondary">Hops</dt>
              <dd className="font-mono">{path.hop_count}</dd>
              <dt className="text-text-secondary">Source</dt>
              <dd className="font-mono truncate" title={path.source_id}>{path.source_id}</dd>
              <dt className="text-text-secondary">Target</dt>
              <dd className="font-mono truncate" title={path.target_id}>{path.target_id}</dd>
              <dt className="text-text-secondary">Computed</dt>
              <dd className="font-mono">{formatInstant(path.computed_at, timeCtx)}</dd>
            </dl>
          </TabsContent>

          <TabsContent value="hops" className="flex-1 overflow-hidden px-4 pb-4">
            <ScrollArea className="h-full">
              <ol className="space-y-2 pt-2">
                {path.nodes.map((node, i) => (
                  <li key={node.id} className="flex items-start gap-2">
                    <span className="shrink-0 mt-0.5 w-5 h-5 rounded-full bg-surface-raised flex items-center justify-center text-xs font-mono">{i}</span>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1 flex-wrap">
                        <Badge variant="default" className="text-[10px] py-0">{node.kind}</Badge>
                        <span className="text-xs text-text-primary truncate" title={node.id}>{node.label ?? node.id}</span>
                      </div>
                      {i < path.edges.length && (
                        <div className="mt-1 ml-1 text-xs text-text-secondary flex items-center gap-1">
                          <span aria-hidden="true">↓</span>
                          <span>{path.edges[i]!.type}</span>
                          <span className="font-mono">({Math.round(path.edges[i]!.confidence * 100)}%)</span>
                          <Badge variant="default" className="text-[10px] py-0">{path.edges[i]!.layer}</Badge>
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="evidence" className="flex-1 overflow-hidden px-4 pb-4">
            <ScrollArea className="h-full">
              <div className="pt-2 space-y-4">
                {!explanation ? (
                  <div className="text-center py-6">
                    <p className="text-xs text-text-secondary mb-3">Explanation not loaded yet.</p>
                    {onLoadExplanation && (
                      <Button size="sm" variant="secondary" onClick={handleLoadExplanation} disabled={loadingExplanation} aria-busy={loadingExplanation}>
                        {loadingExplanation ? 'Loading…' : 'Load explanation'}
                      </Button>
                    )}
                  </div>
                ) : (
                  <>
                    <div>
                      <p className="text-xs font-medium text-text-primary mb-1">Why connected</p>
                      <p className="text-xs text-text-secondary">{explanation.why_connected}</p>
                    </div>
                    {explanation.supporting_evidence.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-text-primary mb-1">Supporting evidence</p>
                        <ul className="text-xs text-text-secondary space-y-1">
                          {explanation.supporting_evidence.map((e, i) => <li key={i} className="truncate">{JSON.stringify(e)}</li>)}
                        </ul>
                      </div>
                    )}
                    {explanation.contradictory_evidence.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-text-danger mb-1">Contradictory evidence</p>
                        <ul className="text-xs text-text-secondary space-y-1">
                          {explanation.contradictory_evidence.map((e, i) => <li key={i} className="truncate">{JSON.stringify(e)}</li>)}
                        </ul>
                      </div>
                    )}
                    {!explanation.causal_language_allowed && (
                      <p className="text-xs text-warning-text bg-warning-surface px-2 py-1 rounded">
                        Causal language not permitted for this path classification.
                      </p>
                    )}
                  </>
                )}
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="score" className="flex-1 overflow-auto px-4 pb-4">
            <div className="pt-2 space-y-3">
              <ScoreBar label="Geometric mean confidence" value={path.score_breakdown.geometric_mean_confidence} />
              <ScoreBar label="Min edge confidence" value={path.score_breakdown.min_edge_confidence} />
              <ScoreBar label="Hop penalty" value={path.score_breakdown.hop_penalty} />
              <ScoreBar label="Overall score" value={path.score_breakdown.overall} />
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs mt-2">
                <dt className="text-text-secondary">Causality penalty</dt>
                <dd className="font-mono">{path.score_breakdown.causality_penalty.toFixed(2)}</dd>
                <dt className="text-text-secondary">Scoring version</dt>
                <dd className="font-mono">v{path.score_breakdown.scoring_version}</dd>
              </dl>
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>

      {onSaveToInvestigation && (
        <div className="px-4 pb-4 pt-2 border-t border-border">
          <Button className="w-full" size="sm" onClick={() => onSaveToInvestigation(path.path_id)} aria-label={`Save path ${shortId} to investigation`}>
            Save to investigation
          </Button>
        </div>
      )}
    </Card>
  );
}
