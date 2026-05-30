import type { ActionClass, Severity, ActionAttribution } from './common';

export type ReviewStatus = 'pending' | 'approved' | 'rejected' | 'deferred' | 'reverted';

export interface ReviewBatch {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly items: readonly ReviewItem[];
  readonly createdAt: string;
  readonly status: ReviewStatus;
  readonly submittedBy: string;
  readonly controller: string;
}

export interface ReviewItem {
  readonly id: string;
  readonly batchId: string;
  readonly title: string;
  readonly description: string;
  readonly mutationClass: ActionClass;
  readonly severity: Severity;
  readonly before: Record<string, unknown>;
  readonly after: Record<string, unknown>;
  readonly graphDiff?: GraphDiff | undefined;
  readonly evidence: readonly string[];
  readonly rationale: string;
  readonly confidence: number;
  readonly downstreamImpact: string;
  readonly reversible: boolean;
  readonly status: ReviewStatus;
  readonly resolution?: ReviewResolution | undefined;
}

export interface GraphDiff {
  readonly addedNodes: readonly string[];
  readonly removedNodes: readonly string[];
  readonly addedEdges: readonly string[];
  readonly removedEdges: readonly string[];
  readonly modifiedNodes: readonly { readonly id: string; readonly changes: Record<string, unknown> }[];
}

export interface ReviewResolution {
  readonly status: ReviewStatus;
  readonly resolvedBy: ActionAttribution;
  readonly reason: string;
  readonly revertId?: string | undefined;
}

export interface AuditEntry {
  readonly id: string;
  readonly action: string;
  readonly timestamp: string;
  readonly actor: ActionAttribution;
  readonly itemId: string;
  readonly batchId: string;
  readonly previousStatus: ReviewStatus;
  readonly newStatus: ReviewStatus;
  readonly reason: string;
}
