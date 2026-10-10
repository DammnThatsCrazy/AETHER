import type { ProfileIdentity } from './profile-identity';
import type { Campaign } from './campaign';
import type { Communication } from './communication';
import type { Conversion } from './conversion';
import type { AttributionCredit } from './attribution-credit';
import type { Journey } from './journey';
import type { GraphNode } from './graph-node';
import type { GraphEdge } from './graph-edge';
import type { FinancialValue } from './financial-value';
import type { SourceClassification } from './source-classification';

/** Envelope for a full explanation/result of a 360 query. */
export interface ExplanationEnvelope {
  readonly workspace_id: string;
  readonly user_id: string;
  readonly profile_360: ProfileIdentity;
  readonly campaign_360?: readonly Campaign[];
  readonly communications_360?: readonly Communication[];
  readonly conversions_360?: readonly Conversion[];
  readonly attribution_360?: readonly AttributionCredit[];
  readonly journeys_360?: readonly Journey[];
  readonly graph_360?: {
    readonly nodes: readonly GraphNode[];
    readonly edges: readonly GraphEdge[];
  };
  readonly value_360?: readonly FinancialValue[];
  readonly generated_at: string;
  readonly generation_time_ms?: number;
  readonly summary?: string;
  readonly completeness: ExplanationCompleteness;
  readonly missing_data?: readonly string[];
  readonly notes?: readonly string[];
  readonly source?: SourceClassification;
}

/** Completeness status of a 360 explanation. */
export type ExplanationCompleteness =
  | 'complete'
  | 'partial'
  | 'empty';
