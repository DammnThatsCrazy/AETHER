import type { Entity, EntityType, GraphEdge, GraphNode, TimelineEvent } from './entities';
import type { WebSocketStatus } from '@kyber/lib/api';

export type Profile360EntityType = EntityType | 'human' | 'organization' | 'journey' | 'delegation' | 'session' | 'platform' | 'browser' | 'device' | 'transaction' | 'execution_trace' | 'reward' | 'financial_activity' | 'relationship';

export type Profile360ViewId = 'identity' | 'system' | 'financial' | 'graph' | 'timeline' | 'analytics' | 'debug';

export interface Profile360Reference {
  readonly id: string;
  readonly type: Profile360EntityType;
  readonly label: string;
  readonly description?: string;
  readonly metadata?: Record<string, unknown>;
}

export interface Profile360SectionMetric {
  readonly id: string;
  readonly label: string;
  readonly value: string | number;
  readonly unit?: string;
  readonly trend?: 'up' | 'down' | 'flat';
  readonly tone?: 'default' | 'good' | 'warning' | 'danger';
  readonly detail?: string;
}

export interface Profile360Section {
  readonly id: string;
  readonly title: string;
  readonly summary?: string;
  readonly metrics?: readonly Profile360SectionMetric[];
  readonly references?: readonly Profile360Reference[];
  readonly data?: Record<string, unknown>;
}

export interface Profile360PanelDrillItem extends Profile360Reference {
  readonly depth: number;
  readonly parentId?: string;
  readonly openedAt: string;
  readonly loading?: boolean;
}

export interface Profile360Graph {
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
  readonly clusters?: readonly { id: string; label: string; nodeIds: readonly string[] }[];
  readonly alignmentAudit?: Record<string, unknown>;
}

export interface Profile360Payload {
  readonly entity: Entity;
  readonly tenantId?: string;
  readonly surface?: 'kyber_internal' | 'end_user';
  readonly visibility?: 'internal_full' | 'redacted';
  readonly sections: Partial<Record<Profile360ViewId, readonly Profile360Section[]>>;
  readonly timeline: readonly TimelineEvent[];
  readonly graph: Profile360Graph;
  readonly alignmentAudit?: Record<string, unknown>;
  readonly live?: Record<string, unknown>;
  readonly raw?: Record<string, unknown>;
}

export interface Profile360State {
  readonly entities: Record<string, Entity>;
  readonly payloads: Record<string, Profile360Payload>;
  readonly timelines: Record<string, readonly TimelineEvent[]>;
  readonly graphs: Record<string, Profile360Graph>;
  readonly drillStack: readonly Profile360PanelDrillItem[];
  readonly highlightedNodeIds: readonly string[];
  readonly activeTimelineFilters: readonly string[];
  readonly websocketStatus: WebSocketStatus;
  readonly liveEvents: readonly TimelineEvent[];
}

export interface Profile360LiveMessage {
  readonly entityId?: string;
  readonly entityType?: Profile360EntityType;
  readonly event?: TimelineEvent;
  readonly node?: GraphNode;
  readonly edge?: GraphEdge;
  readonly patch?: Record<string, unknown>;
  readonly type?: string;
}
