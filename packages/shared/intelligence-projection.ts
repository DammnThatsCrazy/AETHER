// =============================================================================
// Aether Intelligence Projection — shared request / context / result contracts.
//
// A 360 is an intelligence projection over canonical Aether truth — never a
// competing system of record. These contracts are the stable boundary the
// projection runtime (provider protocol + registry) and future 360 providers
// implement against.
//
// Reuse, never redefine: PageRequest / EvidenceRef / TimeRangeFilter / PageInfo
// come from ./operational-intelligence. Projection ids, section states, subject
// kinds and implementation states are derived from the generated registry
// (./intelligence-projections_generated) so the typed vocabulary can never
// drift from the canonical JSON.
// =============================================================================

import type { PageRequest, EvidenceRef, TimeRangeFilter, PageInfo } from './operational-intelligence';
import {
  intelligenceProjectionIds,
  intelligenceProjectionImplementationStates,
  intelligenceProjectionSectionStates,
  intelligenceProjectionSubjectKinds,
} from './intelligence-projections_generated';

/** A registered section state a projection result section may carry (from the generated registry). */
export type SectionState = (typeof intelligenceProjectionSectionStates)[number];

/** A registered intelligence projection id (from the generated registry). */
export type ProjectionId = (typeof intelligenceProjectionIds)[number];

/** A registered implementation state — repo metadata, NOT readiness (from the generated registry). */
export type ProjectionRegistryState = (typeof intelligenceProjectionImplementationStates)[number];

/** A subject kind a projection may be asked about (from the generated registry's top-level subjectKinds vocab). */
export type ProjectionSubjectKind = (typeof intelligenceProjectionSubjectKinds)[number];

/** The subject a projection is asked about. Distinct from EntityRef by design: projections are asked about campaigns, episodes, populations, sources, connections, clusters and relationships too, which EntityKind does not cover. */
export interface ProjectionSubject {
  kind: ProjectionSubjectKind;
  id: string;
}

/** Request to run an intelligence projection over canonical Aether truth. */
export interface ProjectionRequest {
  /** Which registered projection to run. */
  projectionId: ProjectionId;
  /** Tenant scope — projections are tenant-scoped by contract. */
  tenantId: string;
  /** The subject the projection is asked about. */
  subject: ProjectionSubject;
  /** Optional pagination for section content. */
  page?: PageRequest;
  /** Optional temporal window for the projection. */
  timeRange?: TimeRangeFilter;
  /** Only render these sections (by section id). Omit to render all. */
  includeSections?: string[];
  /** Include claim envelopes in the result. */
  includeClaims?: boolean;
  /** Projection-engine (A8) extension: ordered lens ids to compose over the projection. Strictly optional. */
  lensIds?: string[];
  /** Projection-engine (A8) extension: registry-surface temporal mode ("window" | "as_of" | "compare" | "relative"). Strictly optional. */
  temporalMode?: string;
}

/** Dependency state of a sibling projection this projection depends on. */
export interface ProjectionDependencyState {
  projectionId: ProjectionId;
  state: SectionState;
  reason?: string;
}

/** Build-time context the runtime computes for a projection request. */
export interface ProjectionContext {
  projectionId: ProjectionId;
  tenantId: string;
  /** Registry state for the projection (e.g. "in_flight" / "implemented"). */
  registryState: ProjectionRegistryState;
  dependencyState: ProjectionDependencyState[];
  /** Effective as-of snapshot time for the projection run (ISO-8601). */
  asOf?: string;
  warnings: string[];
}

/** One rendered section of a projection result. */
export interface ProjectionSection {
  id: string;
  state: SectionState;
  title?: string;
  content?: unknown;
  warnings?: string[];
}

/** One claim a projection makes about its subject, backed by evidence refs. */
export interface ClaimEnvelope {
  id: string;
  kind: string;
  subject: ProjectionSubject;
  evidenceRefs: EvidenceRef[];
  claims: string[];
  confidence?: number;
}

/** Engine-level (A8) degradation summary for a projection result. */
export interface ProjectionDegradation {
  /** "none" | "partial" | "full" */
  level: 'none' | 'partial' | 'full';
  /** Engine-computed, content-free with respect to provider diagnostics. */
  reasons: string[];
  /** Lens ids that conflicted during composition, if any. */
  conflictedLenses?: string[];
  /** Projection dependencies that could not be satisfied. */
  missingDependencies?: string[];
}

/** The result of running a projection over canonical Aether truth. */
export interface ProjectionResult {
  projectionId: ProjectionId;
  tenantId: string;
  /** Contract version of the projection contract surface used (e.g. "1.0.0"). */
  contractVersion: string;
  sections: ProjectionSection[];
  claims: ClaimEnvelope[];
  dependencyState: ProjectionDependencyState[];
  asOf?: string;
  /** ISO-8601 timestamp of when the result was generated. */
  generatedAt: string;
  page?: PageInfo;
  /** Human-readable reasons the result is degraded, if any. */
  degradedReasons: string[];
  /** Projection-engine (A8) extension: deterministic content digest. Strictly optional. */
  digest?: string;
  /** Projection-engine (A8) extension: composed lens ids, in application order. Strictly optional. */
  lensIds?: string[];
  /** Projection-engine (A8) extension: dispatched registry-surface temporal mode. Strictly optional. */
  temporalMode?: string;
  /** Projection-engine (A8) extension: degradation summary. Strictly optional. */
  degradation?: ProjectionDegradation;
  /** Projection-engine (A8) extension: section ids suppressed by lens conflict / policy. Strictly optional. */
  suppressedSections?: string[];
}
