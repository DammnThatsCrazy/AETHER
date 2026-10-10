import type { GraphNode } from './graph-node';

/** A directed edge in the entity graph. */
export interface GraphEdge {
  readonly edge_id: string;
  readonly source: string;
  readonly target: string;
  readonly relation: GraphEdgeRelation;
  readonly label?: string;
  readonly created_at: string;
  readonly updated_at?: string;
  readonly properties?: Record<string, unknown>;
  readonly weight?: number;
  readonly confidence?: number;
  readonly source_system?: string;
  readonly provenance?: readonly string[];
  readonly metadata?: {
    readonly derived_from?: readonly string[];
  };
}

/** Allowed edge relationship types. */
export type GraphEdgeRelation =
  | 'identified'
  | 'alias'
  | 'session_on'
  | 'event_in'
  | 'conversion_from'
  | 'touchpoint_in'
  | 'communication_sent'
  | 'device_of'
  | 'journey_step'
  | 'journey_participant'
  | 'campaign_member'
  | 'attributed_to'
  | 'value_from'
  | 'contains'
  | 'belongs_to'
  | 'connected_to'
  | 'transferred_to'
  | 'authorized_by'
  | 'observed_by';

/** A complete graph structure with nodes and edges. */
export interface Graph {
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
  readonly updated_at?: string;
  readonly version?: string;
  readonly metadata?: {
    readonly source?: string;
    readonly generated_by?: string;
  };
}
