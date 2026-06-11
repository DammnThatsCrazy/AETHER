import type { Entity, EntityType, GraphEdge, GraphNode, TimelineEvent } from './entities';

export type Profile360EntityType = EntityType | 'human' | 'organization' | 'journey' | 'delegation' | 'session' | 'platform' | 'browser' | 'device' | 'transaction' | 'execution_trace' | 'reward' | 'financial_activity' | 'relationship';

export type Profile360ViewId =
  | 'identity'
  | 'system'
  | 'financial'
  | 'graph'
  | 'timeline'
  | 'analytics'
  | 'debug'
  | 'sessions'
  | 'journeys'
  | 'wallets'
  | 'behavioral'
  | 'attribution'
  | 'cluster'
  | 'agents'
  | 'consent'
  | 'quality'
  | 'recommendations'
  | 'outcomes'
  | 'intelligence'
  | 'provenance';

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
  readonly websocketStatus: 'connecting' | 'connected' | 'disconnected' | 'error';
  readonly liveEvents: readonly TimelineEvent[];
  // Extended dimension caches
  readonly summariesById: Record<string, Record<string, unknown>>;
  readonly clustersByEntityId: Record<string, Record<string, unknown>>;
  readonly journeysByEntityId: Record<string, readonly unknown[]>;
  readonly campaignsByEntityId: Record<string, readonly unknown[]>;
  readonly attributionByEntityId: Record<string, Record<string, unknown>>;
  readonly walletsByEntityId: Record<string, readonly unknown[]>;
  readonly agentsByEntityId: Record<string, readonly unknown[]>;
  readonly sessionsByEntityId: Record<string, readonly unknown[]>;
  readonly devicesByEntityId: Record<string, readonly unknown[]>;
  readonly recommendationsByEntityId: Record<string, readonly unknown[]>;
  readonly qualityByEntityId: Record<string, Profile360Quality>;
  readonly consentByEntityId: Record<string, Profile360Consent>;
  readonly provenanceByEntityId: Record<string, Profile360Provenance>;
  readonly streamStatusByEntityId: Record<string, Profile360StreamStatus>;
  readonly loadingByKey: Record<string, boolean>;
  readonly errorsByKey: Record<string, string | null>;
  readonly staleByKey: Record<string, boolean>;
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

export interface Profile360Quality {
  readonly readiness_status: 'empty' | 'partial' | 'usable' | 'strong' | 'release_grade';
  readonly completeness_score: number;
  readonly freshness_score: number;
  readonly confidence_score: number;
  readonly source_coverage_score: number;
  readonly relationship_density_score: number;
  readonly journey_coverage_score: number;
  readonly attribution_coverage_score: number;
  readonly consent_coverage_score: number;
  readonly provenance_coverage_score: number;
  readonly missing_dimensions: readonly string[];
  readonly stale_dimensions: readonly string[];
  readonly contradiction_count: number;
  readonly legacy_unscoped_row_count: number;
  readonly cross_tenant_rows_excluded: number;
  readonly last_enriched_at: string | null;
}

export interface Profile360Consent {
  readonly consent_status: 'unknown' | 'granted' | 'partial' | 'restricted' | 'revoked' | 'expired';
  readonly activation_eligibility: 'allowed' | 'observe_only' | 'restricted' | 'blocked';
  readonly allowed_use_cases: readonly string[];
  readonly restricted_use_cases: readonly string[];
  readonly blocked_use_cases: readonly string[];
  readonly consent_sources: readonly string[];
  readonly last_consent_update: string | null;
  readonly retention_status: 'active' | 'expiring' | 'expired' | 'delete_requested' | 'unknown';
  readonly redaction_state: 'none' | 'partial' | 'full';
  readonly dsr_state: 'none' | 'export_requested' | 'delete_requested' | 'deleted';
}

export interface Profile360Provenance {
  readonly sources: readonly string[];
  readonly source_count: number;
  readonly primary_source: string | null;
  readonly last_source_update: string | null;
  readonly computed_at: string;
  readonly freshness_status: 'fresh' | 'aging' | 'stale' | 'unknown';
  readonly stale_after_seconds: number;
  readonly source_warnings: readonly string[];
}

export interface Profile360GraphNodePreview {
  readonly id: string;
  readonly profile_id: string;
  readonly entity_type: string;
  readonly display_label: string;
  readonly profile_links: {
    readonly summary: string;
    readonly full: string;
    readonly drill: string | null;
  };
  readonly quality?: Partial<Profile360Quality>;
  readonly consent?: Partial<Profile360Consent>;
}

export interface Profile360StreamStatus {
  readonly status: 'connected' | 'connecting' | 'disconnected' | 'error' | 'stale';
  readonly last_event_at: string | null;
  readonly reconnect_count: number;
}
