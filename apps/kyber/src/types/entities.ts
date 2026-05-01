import type { Severity, HealthStatus } from './common';

export type EntityType = 'customer' | 'wallet' | 'agent' | 'protocol' | 'contract' | 'cluster';

export interface Entity {
  readonly id: string;
  readonly type: EntityType;
  readonly name: string;
  readonly displayLabel: string;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly health: HealthStatus;
  readonly trustScore: number;
  readonly riskScore: number;
  readonly anomalyScore: number;
  readonly needsHelp: boolean;
  readonly needsHelpReason?: string | undefined;
  readonly tags: readonly string[];
  readonly metadata: Record<string, unknown>;
}

export interface NeedsHelpCard {
  readonly entityId: string;
  readonly entityType: EntityType;
  readonly entityName: string;
  readonly reason: string;
  readonly evidence: readonly string[];
  readonly confidence: number;
  readonly recommendedAction: string;
  readonly reversible: boolean;
  readonly owner?: string | undefined;
  readonly traceLink: string;
  readonly severity: Severity;
  readonly flaggedAt: string;
}

export interface EntityTimeline {
  readonly entityId: string;
  readonly events: readonly TimelineEvent[];
}

export interface TimelineEvent {
  readonly id: string;
  readonly timestamp: string;
  readonly type: string;
  readonly title: string;
  readonly description: string;
  readonly severity: Severity;
  readonly controller?: string | undefined;
  readonly traceId?: string | undefined;
  readonly metadata: Record<string, unknown>;
}

export interface EntityNeighborhood {
  readonly entityId: string;
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
}

export interface GraphNode {
  readonly id: string;
  readonly type: EntityType | 'external';
  readonly label: string;
  readonly trustScore?: number | undefined;
  readonly riskScore?: number | undefined;
  readonly anomalyScore?: number | undefined;
  readonly metadata: Record<string, unknown>;
}

export interface GraphEdge {
  readonly id: string;
  readonly source: string;
  readonly target: string;
  readonly type: string;
  readonly weight: number;
  readonly label?: string | undefined;
  readonly metadata: Record<string, unknown>;
}

export interface Entity360 {
  readonly entity: Entity;
  readonly timeline: EntityTimeline;
  readonly neighborhood: EntityNeighborhood;
  readonly interventions: readonly Intervention[];
  readonly recommendations: readonly EntityRecommendation[];
  readonly notes: readonly EntityNote[];
}

export interface Intervention {
  readonly id: string;
  readonly entityId: string;
  readonly type: string;
  readonly description: string;
  readonly performedBy: string;
  readonly performedAt: string;
  readonly reversible: boolean;
  readonly revertId?: string | undefined;
  readonly outcome?: string | undefined;
}

export interface EntityRecommendation {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly confidence: number;
  readonly rationale: string;
  readonly actionClass: number;
  readonly reversible: boolean;
}

export interface EntityNote {
  readonly id: string;
  readonly entityId: string;
  readonly author: string;
  readonly content: string;
  readonly createdAt: string;
  readonly updatedAt: string;
}
