import { z } from 'zod';

// Common schemas for validating API responses

export const healthStatusSchema = z.object({
  status: z.enum(['healthy', 'degraded', 'unhealthy', 'unknown']),
  message: z.string().optional(),
  lastChecked: z.string(),
});

export const severitySchema = z.enum(['P0', 'P1', 'P2', 'P3', 'info']);

export const entityTypeSchema = z.enum(['customer', 'wallet', 'agent', 'protocol', 'contract', 'cluster']);

export const paginatedResponseSchema = <T extends z.ZodType>(itemSchema: T) =>
  z.object({
    data: z.array(itemSchema),
    total: z.number(),
    offset: z.number(),
    limit: z.number(),
    hasMore: z.boolean(),
  });

export const dashboardSummarySchema = z.object({
  sessionsLast24h: z.number(),
  eventsLast24h: z.number(),
  uniqueUsersLast24h: z.number(),
  topEvents: z.array(z.object({ name: z.string(), count: z.number() })),
});

export const liveEventSchema = z.object({
  id: z.string(),
  type: z.enum(['analytics', 'graph-mutation', 'agent-lifecycle', 'controller', 'onboarding', 'support', 'stuck-loop', 'anomaly', 'alert', 'system']),
  timestamp: z.string(),
  severity: severitySchema,
  title: z.string(),
  description: z.string(),
  source: z.string(),
  controller: z.string().optional(),
  entityId: z.string().optional(),
  entityType: z.string().optional(),
  traceId: z.string().optional(),
  pinned: z.boolean(),
  metadata: z.record(z.unknown()),
});

export const entitySchema = z.object({
  id: z.string(),
  type: entityTypeSchema,
  name: z.string(),
  displayLabel: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
  health: healthStatusSchema,
  trustScore: z.number(),
  riskScore: z.number(),
  anomalyScore: z.number(),
  needsHelp: z.boolean(),
  needsHelpReason: z.string().optional(),
  tags: z.array(z.string()),
  metadata: z.record(z.unknown()),
});

export const controllerSchema = z.object({
  name: z.enum(['governance', 'char', 'intake', 'gouf', 'zeong', 'triage', 'verification', 'commit', 'recovery', 'chronicle', 'trigger', 'relay']),
  health: healthStatusSchema,
  queueDepth: z.number(),
  activeObjectives: z.number(),
  blockedItems: z.number(),
  lastActivity: z.string(),
  uptime: z.string(),
  stagedMutations: z.number(),
  recoveryState: z.enum(['idle', 'active', 'pending']),
});

export const reviewItemSchema = z.object({
  id: z.string(),
  batchId: z.string(),
  title: z.string(),
  description: z.string(),
  mutationClass: z.number(),
  severity: severitySchema,
  before: z.record(z.unknown()),
  after: z.record(z.unknown()),
  graphDiff: z.object({
    addedNodes: z.array(z.string()),
    removedNodes: z.array(z.string()),
    addedEdges: z.array(z.string()),
    removedEdges: z.array(z.string()),
    modifiedNodes: z.array(z.object({ id: z.string(), changes: z.record(z.unknown()) })),
  }).optional(),
  evidence: z.array(z.string()),
  rationale: z.string(),
  confidence: z.number(),
  downstreamImpact: z.string(),
  reversible: z.boolean(),
  status: z.enum(['pending', 'approved', 'rejected', 'deferred', 'reverted']),
  resolution: z.object({
    status: z.enum(['pending', 'approved', 'rejected', 'deferred', 'reverted']),
    resolvedBy: z.object({
      userId: z.string(),
      displayName: z.string(),
      email: z.string(),
      role: z.string(),
      timestamp: z.string(),
      environment: z.string(),
      reason: z.string(),
      correlationId: z.string(),
      revertId: z.string().optional(),
    }),
    reason: z.string(),
    revertId: z.string().optional(),
  }).optional(),
});
