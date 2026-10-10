import type { Severity, HealthStatus } from './common';

export type EntityType = 'customer' | 'human' | 'wallet' | 'agent' | 'organization' | 'protocol' | 'contract' | 'cluster' | 'journey' | 'delegation' | 'session' | 'platform' | 'browser' | 'device' | 'transaction' | 'execution_trace' | 'reward' | 'financial_activity' | 'relationship';

export interface Entity {
  readonly id: string;
  readonly type: EntityType;
  readonly name: string;
  readonly displayLabel: string;
  readonly createdAt?: string | undefined;
  readonly updatedAt?: string | undefined;
  readonly health: HealthStatus;
  readonly trustScore: number | null;
  readonly riskScore: number | null;
  readonly anomalyScore: number | null;
  readonly needsHelp: boolean | null;
  readonly needsHelpReason?: string | undefined;
  readonly tags: readonly string[];
  readonly metadata: Record<string, unknown>;
}

export interface Profile360Metric {
  readonly label: string;
  readonly value: string | number;
  readonly tone?: 'default' | 'good' | 'warn' | 'bad' | 'info' | undefined;
  readonly detail?: string | undefined;
}

export interface Profile360Summary {
  readonly status?: string | undefined;
  readonly lastSeen?: string | undefined;
  readonly walletCount: number;
  readonly agentCount: number;
  readonly trust: number | null;
  readonly risk: number | null;
  readonly primaryMetrics: readonly Profile360Metric[];
  readonly secondaryMetrics: readonly Profile360Metric[];
}

export type Profile360DrillKind = EntityType | 'transaction' | 'event' | 'execution_trace' | 'flow' | 'analytics';

export interface Profile360DrillItem {
  readonly id: string;
  readonly kind: Profile360DrillKind;
  readonly label: string;
  readonly subtitle?: string | undefined;
  readonly parentId?: string | undefined;
  readonly timestamp?: string | undefined;
  readonly entityId?: string | undefined;
  readonly metadata: Record<string, unknown>;
}

export interface Profile360Relationship {
  readonly id: string;
  readonly sourceId: string;
  readonly targetId: string;
  readonly targetType: EntityType | 'external';
  readonly targetLabel: string;
  readonly relationshipType: string;
  readonly strength: number;
  readonly trustScore?: number | undefined;
  readonly riskScore?: number | undefined;
  readonly firstSeen?: string | undefined;
  readonly lastSeen?: string | undefined;
  readonly metadata: Record<string, unknown>;
}

export interface Profile360Analytics {
  readonly activeHours: readonly Profile360Metric[];
  readonly regions: readonly Profile360Metric[];
  readonly devices: readonly Profile360Metric[];
  readonly browsers: readonly Profile360Metric[];
  readonly protocols: readonly Profile360Metric[];
  readonly platforms: readonly Profile360Metric[];
  readonly spendingPatterns: readonly Profile360Metric[];
  readonly rewardOpportunities: readonly Profile360Metric[];
  readonly trustSignals: readonly Profile360Metric[];
  readonly anomalyIndicators: readonly Profile360Metric[];
}

export interface Profile360StateSlice {
  readonly entitiesById: Record<string, Entity>;
  readonly graphNodesById: Record<string, GraphNode>;
  readonly graphEdgesById: Record<string, GraphEdge>;
  readonly timelineByEntityId: Record<string, readonly TimelineEvent[]>;
  readonly drillStack: readonly Profile360DrillItem[];
  readonly analyticsByEntityId: Record<string, Profile360Analytics>;
  readonly eventFeedsByEntityId: Record<string, readonly TimelineEvent[]>;
  readonly activeSessionIds: readonly string[];
  readonly streamStatus: 'idle' | 'connecting' | 'connected' | 'degraded';
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
  readonly entityId?: string | undefined;
  readonly relatedEntityIds?: readonly string[] | undefined;
  readonly causalityId?: string | undefined;
  readonly parentEventId?: string | undefined;
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
