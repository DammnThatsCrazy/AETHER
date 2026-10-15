import type { GraphNode, GraphEdge, EntityType } from './entities';

export type GraphLayer = 'h2h' | 'h2a' | 'a2h' | 'a2a' | 'all';

export type GraphOverlay = 'trust' | 'risk' | 'anomaly' | 'none';

export interface GraphState {
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
  readonly selectedNodeId: string | null;
  readonly selectedEdgeId: string | null;
  readonly activeLayer: GraphLayer;
  readonly activeOverlay: GraphOverlay;
  readonly visibleEntityTypes: readonly EntityType[];
  readonly timeWindow: { readonly start: Date; readonly end: Date } | null;
  readonly isReplayMode: boolean;
  readonly replayTimestamp: Date | null;
  readonly clusters: readonly GraphCluster[];
  readonly pathHighlight: readonly string[] | null;
}

export interface GraphCluster {
  readonly id: string;
  readonly label: string;
  readonly nodeIds: readonly string[];
  readonly centroidNodeId: string;
  readonly size: number;
  readonly avgTrustScore: number;
  readonly avgRiskScore: number;
  readonly anomalyCount: number;
}

export interface GraphInspectorData {
  readonly type: 'node' | 'edge' | 'cluster';
  readonly data: GraphNode | GraphEdge | GraphCluster;
  readonly neighbors?: readonly GraphNode[] | undefined;
  readonly paths?: readonly string[][] | undefined;
}
