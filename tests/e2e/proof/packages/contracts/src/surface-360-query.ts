import type { ProfileIdentity } from './profile-identity';
import type { Campaign } from './campaign';
import type { Communication } from './communication';
import type { SourceClassification } from './source-classification';

/** Query input for a 360-degree view surface. */
export interface Surface360Query {
  readonly workspace_id: string;
  readonly user_id: string;
  readonly depth: Surface360Depth;
  readonly include_profile: boolean;
  readonly include_campaigns: boolean;
  readonly include_communications: boolean;
  readonly include_journeys: boolean;
  readonly include_conversions: boolean;
  readonly include_value: boolean;
  readonly include_graph: boolean;
  readonly time_window?: {
    readonly start: string;
    readonly end: string;
  };
  readonly filters?: Record<string, unknown>;
  readonly include_edges?: boolean;
  readonly limit_per_surface?: number;
  readonly source?: SourceClassification;
}

/** Depth of a 360 query. */
export type Surface360Depth =
  | 'shallow'
  | 'standard'
  | 'deep';

/** Result of a 360-degree query. */
export interface Surface360Result {
  readonly query: Surface360Query;
  readonly profile?: Surface360Profile;
  readonly campaigns?: readonly Surface360Campaign[];
  readonly communications?: readonly Surface360Communications[];
  readonly journeys?: readonly import('./journey').Journey[];
  readonly conversions?: readonly import('./conversion').Conversion[];
  readonly values?: readonly import('./financial-value').FinancialValue[];
  readonly graph?: {
    readonly nodes: readonly import('./graph-node').GraphNode[];
    readonly edges: readonly import('./graph-edge').GraphEdge[];
  };
  readonly generated_at: string;
  readonly completeness: import('./explanation-envelope').ExplanationCompleteness;
}

/** A 360 profile view. */
export interface Surface360Profile {
  readonly user_id: string;
  readonly profile: ProfileIdentity;
  readonly summary?: string;
}

/** A 360 campaign view. */
export interface Surface360Campaign {
  readonly campaign: Campaign;
  readonly performance?: Record<string, unknown>;
}

/** A 360 communications view. */
export interface Surface360Communications {
  readonly communications: readonly Communication[];
  readonly summary?: {
    readonly total: number;
    readonly by_channel: Record<string, number>;
    readonly by_status: Record<string, number>;
  };
}
