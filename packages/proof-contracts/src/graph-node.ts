import type { SourceClassification } from './source-classification';

/** A node in the entity graph. */
export interface GraphNode {
  readonly node_id: string;
  readonly type: GraphNodeType;
  readonly labels: readonly string[];
  readonly properties: Record<string, unknown>;
  readonly created_at: string;
  readonly updated_at?: string;
  readonly source?: string;
  readonly confidence?: number;
  readonly provenance?: readonly string[];
  readonly metadata?: {
    readonly derived_from?: readonly string[];
    readonly version?: string;
  };
  /** Optional reference to an associated value record. */
  readonly value_record_id?: string;
}

/** Allowed graph node types. */
export type GraphNodeType =
  | 'user'
  | 'session'
  | 'event'
  | 'campaign'
  | 'conversion'
  | 'touchpoint'
  | 'communication'
  | 'device'
  | 'journey'
  | 'profile'
  | 'value'
  | 'revenue'
  | 'cohort'
  | 'segment'
  | 'tenant'
  | 'organization'
  | 'application'
  | 'wallet'
  | 'contract'
  | 'agent'
  | 'service'
  | 'product'
  | 'order'
  | 'invoice'
  | 'subscription';

/** A read-only view of graph node labels. */
export type GraphNodeLabels = readonly string[];
