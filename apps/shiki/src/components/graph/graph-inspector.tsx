import { cn } from '@shiki/lib/utils';
import {
  Card, CardHeader, CardTitle, CardContent,
  Badge, Button, ScrollArea,
  Tabs, TabsList, TabsTrigger, TabsContent,
} from '@shiki/components/system';
import type { GraphNode, GraphEdge, GraphCluster, GraphInspectorData } from '@shiki/types';

// ---------------------------------------------------------------------------
// Score bar helper
// ---------------------------------------------------------------------------

function ScoreBar({ label, value, colorFn }: { readonly label: string; readonly value: number | undefined; readonly colorFn: (v: number) => string }) {
  const v = value ?? 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-text-secondary">{label}</span>
        <span className="font-mono text-text-primary">{v.toFixed(2)}</span>
      </div>
      <div className="h-1.5 w-full bg-surface-raised rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${v * 100}%`, backgroundColor: colorFn(v) }} />
      </div>
    </div>
  );
}

function trustColor(v: number): string {
  if (v >= 0.8) return '#22c55e';
  if (v >= 0.5) return '#eab308';
  return '#ef4444';
}
function riskColor(v: number): string {
  if (v >= 0.7) return '#ef4444';
  if (v >= 0.4) return '#eab308';
  return '#22c55e';
}
function anomalyColor(v: number): string {
  if (v >= 0.7) return '#ef4444';
  if (v >= 0.4) return '#f97316';
  return '#4a6cf7';
}

// ---------------------------------------------------------------------------
// Sub-views
// ---------------------------------------------------------------------------

function NodeDetails({ node, neighbors }: { readonly node: GraphNode; readonly neighbors?: readonly GraphNode[] | undefined }) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Badge variant="accent">{node.type}</Badge>
          <span className="text-sm font-mono text-text-primary truncate">{node.label}</span>
        </div>
        <div className="text-xs text-text-muted font-mono break-all">{node.id}</div>
      </div>

      <div className="space-y-3">
        <ScoreBar label="Trust" value={node.trustScore} colorFn={trustColor} />
        <ScoreBar label="Risk" value={node.riskScore} colorFn={riskColor} />
        <ScoreBar label="Anomaly" value={node.anomalyScore} colorFn={anomalyColor} />
      </div>

      {Object.keys(node.metadata).length > 0 && (
        <div>
          <div className="text-xs font-medium text-text-secondary mb-2">Metadata</div>
          <div className="space-y-1">
            {Object.entries(node.metadata).map(([key, value]) => (
              <div key={key} className="flex justify-between text-xs">
                <span className="text-text-muted">{key}</span>
                <span className="text-text-primary font-mono truncate max-w-[140px]">{String(value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {neighbors && neighbors.length > 0 && (
        <div>
          <div className="text-xs font-medium text-text-secondary mb-2">Neighbors ({neighbors.length})</div>
          <ScrollArea maxHeight="200px">
            <div className="space-y-1">
              {neighbors.map((n) => (
                <div key={n.id} className="flex items-center gap-2 py-1 px-2 rounded bg-surface-raised text-xs">
                  <Badge>{n.type}</Badge>
                  <span className="text-text-primary truncate">{n.label}</span>
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  );
}

function EdgeDetails({ edge }: { readonly edge: GraphEdge }) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Badge variant="info">edge</Badge>
          {edge.label && <span className="text-sm font-mono text-text-primary">{edge.label}</span>}
        </div>
        <div className="text-xs text-text-muted font-mono">{edge.id}</div>
      </div>

      <div className="space-y-2 text-xs">
        <div className="flex justify-between">
          <span className="text-text-secondary">Source</span>
          <span className="text-text-primary font-mono truncate max-w-[160px]">{edge.source}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-text-secondary">Target</span>
          <span className="text-text-primary font-mono truncate max-w-[160px]">{edge.target}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-text-secondary">Type</span>
          <Badge>{edge.type}</Badge>
        </div>
        <div className="flex justify-between">
          <span className="text-text-secondary">Weight</span>
          <span className="font-mono text-text-primary">{edge.weight.toFixed(2)}</span>
        </div>
      </div>

      {Object.keys(edge.metadata).length > 0 && (
        <div>
          <div className="text-xs font-medium text-text-secondary mb-2">Metadata</div>
          <div className="space-y-1">
            {Object.entries(edge.metadata).map(([key, value]) => (
              <div key={key} className="flex justify-between text-xs">
                <span className="text-text-muted">{key}</span>
                <span className="text-text-primary font-mono truncate max-w-[140px]">{String(value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ClusterDetails({ cluster }: { readonly cluster: GraphCluster }) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Badge variant="warning">cluster</Badge>
          <span className="text-sm font-mono text-text-primary">{cluster.label}</span>
        </div>
        <div className="text-xs text-text-muted font-mono">{cluster.id}</div>
      </div>

      <div className="space-y-2 text-xs">
        <div className="flex justify-between">
          <span className="text-text-secondary">Node Count</span>
          <span className="font-mono text-text-primary font-bold">{cluster.size}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-text-secondary">Anomaly Count</span>
          <span className={cn('font-mono font-bold', cluster.anomalyCount > 0 ? 'text-danger' : 'text-text-primary')}>
            {cluster.anomalyCount}
          </span>
        </div>
      </div>

      <div className="space-y-3">
        <ScoreBar label="Avg Trust" value={cluster.avgTrustScore} colorFn={trustColor} />
        <ScoreBar label="Avg Risk" value={cluster.avgRiskScore} colorFn={riskColor} />
      </div>

      {cluster.nodeIds.length > 0 && (
        <div>
          <div className="text-xs font-medium text-text-secondary mb-2">Member IDs ({cluster.nodeIds.length})</div>
          <ScrollArea maxHeight="160px">
            <div className="space-y-1">
              {cluster.nodeIds.map((nid) => (
                <div key={nid} className="py-1 px-2 rounded bg-surface-raised text-xs font-mono text-text-primary truncate">
                  {nid}
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Inspector
// ---------------------------------------------------------------------------

interface GraphInspectorProps {
  readonly data: GraphInspectorData | null;
  readonly onClose: () => void;
  readonly className?: string | undefined;
}

export function GraphInspector({ data, onClose, className }: GraphInspectorProps) {
  if (!data) return null;

  return (
    <Card className={cn('w-80 flex-shrink-0 overflow-hidden', className)}>
      <CardHeader>
        <CardTitle>
          <div className="flex items-center justify-between w-full">
            <span>Inspector</span>
            <Button variant="ghost" size="sm" onClick={onClose}>
              x
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ScrollArea maxHeight="calc(100vh - 260px)">
          <Tabs defaultValue="details">
            <TabsList>
              <TabsTrigger value="details">Details</TabsTrigger>
              {data.type === 'node' && data.neighbors && data.neighbors.length > 0 && (
                <TabsTrigger value="neighbors">Neighbors</TabsTrigger>
              )}
              {data.paths && data.paths.length > 0 && (
                <TabsTrigger value="paths">Paths</TabsTrigger>
              )}
            </TabsList>

            <TabsContent value="details">
              {data.type === 'node' && (
                <NodeDetails node={data.data as GraphNode} neighbors={data.neighbors} />
              )}
              {data.type === 'edge' && (
                <EdgeDetails edge={data.data as GraphEdge} />
              )}
              {data.type === 'cluster' && (
                <ClusterDetails cluster={data.data as GraphCluster} />
              )}
            </TabsContent>

            {data.type === 'node' && data.neighbors && data.neighbors.length > 0 && (
              <TabsContent value="neighbors">
                <div className="space-y-2">
                  {data.neighbors.map((n) => (
                    <div key={n.id} className="flex items-center gap-2 py-2 px-2 rounded bg-surface-raised text-xs border border-border-subtle">
                      <Badge>{n.type}</Badge>
                      <div className="flex-1 min-w-0">
                        <div className="text-text-primary truncate">{n.label}</div>
                        <div className="text-text-muted font-mono truncate">{n.id}</div>
                      </div>
                      {n.trustScore !== undefined && (
                        <span className="font-mono text-text-secondary">{n.trustScore.toFixed(2)}</span>
                      )}
                    </div>
                  ))}
                </div>
              </TabsContent>
            )}

            {data.paths && data.paths.length > 0 && (
              <TabsContent value="paths">
                <div className="space-y-3">
                  {data.paths.map((path, idx) => (
                    <div key={idx} className="space-y-1">
                      <div className="text-xs text-text-secondary font-medium">Path {idx + 1} ({path.length} hops)</div>
                      <div className="flex flex-wrap items-center gap-1">
                        {path.map((nodeId, i) => (
                          <span key={`${nodeId}-${i}`} className="inline-flex items-center gap-1">
                            <span className="text-xs font-mono text-accent bg-accent/10 px-1.5 py-0.5 rounded">{nodeId}</span>
                            {i < path.length - 1 && <span className="text-text-muted">-&gt;</span>}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </TabsContent>
            )}
          </Tabs>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
