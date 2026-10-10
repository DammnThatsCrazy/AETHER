import type {
  GraphContext,
  GraphObjectRef,
  GraphScope,
} from "@aether/shared/graph-context-contract";
import type { EvidenceRef } from "@aether/shared/operational-intelligence";
import type { TimeWindow } from "@aether/ui";
import type { GraphNode, Profile360EntityType } from "@kyber/types";

/** Make a scoped object reference for the shared graph selection authority. */
export function graphObjectRef(
  scope: GraphScope,
  node: Pick<GraphNode, "id" | "type">,
): GraphObjectRef {
  return {
    tenant_id: scope.tenant_id,
    environment_id: scope.environment_id,
    kind: node.type,
    id: node.id,
  };
}

/** Preserve the canonical exploration query when a Profile360 link changes route. */
export function withGraphContext(path: string, query: string): string {
  const normalized = query.startsWith("?") ? query.slice(1) : query;
  if (!normalized) return path;
  return `${path}${path.includes("?") ? "&" : "?"}${normalized}`;
}

/** Add the opaque, URL-safe focus token understood by the shared codec. */
export function withGraphFocus(path: string, ref: GraphObjectRef): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}focus=${encodeURIComponent(`${ref.kind}:${ref.id}`)}`;
}

/**
 * Convert raw evidence records only when the backend supplied the required
 * identity and source fields. Missing evidence remains missing; the UI never
 * manufactures a citation from a profile or compute timestamp.
 */
export function normalizeEvidence(value: unknown): readonly EvidenceRef[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): EvidenceRef[] => {
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const id = record.id ?? record.evidence_id ?? record.ref;
    const source = record.source ?? record.source_id ?? record.service;
    if (
      typeof id !== "string" ||
      !id.trim() ||
      typeof source !== "string" ||
      !source.trim()
    )
      return [];
    const candidate = {
      id,
      source,
      type: (typeof record.type === "string"
        ? record.type
        : "event") as EvidenceRef["type"],
      ...(typeof record.observed_at === "string"
        ? { observedAt: record.observed_at }
        : {}),
      ...(typeof record.observedAt === "string"
        ? { observedAt: record.observedAt }
        : {}),
      ...(typeof record.confidence === "number"
        ? { confidence: record.confidence }
        : {}),
      ...(typeof record.uri === "string" ? { uri: record.uri } : {}),
    } satisfies EvidenceRef;
    return [candidate];
  });
}

/** Return a canonical Profile360 temporal selection for the toolbar window. */
export function temporalForWindow(
  window: TimeWindow,
  now = new Date(),
): GraphContext["temporal"] {
  const durationMs: Record<TimeWindow, number> = {
    "30d": 30 * 24 * 60 * 60 * 1000,
    "90d": 90 * 24 * 60 * 60 * 1000,
    lifetime: 100 * 365 * 24 * 60 * 60 * 1000,
    "60d": 60 * 24 * 60 * 60 * 1000,
  };
  const end = now.toISOString();
  const start = new Date(now.getTime() - durationMs[window]).toISOString();
  return {
    mode: "window",
    field: "occurred_at",
    timezone: "UTC",
    range: { kind: "instant", start, endExclusive: end },
  };
}

export function refForEntity(
  scope: GraphScope,
  id: string,
  type: Profile360EntityType,
): GraphObjectRef {
  return graphObjectRef(scope, { id, type });
}
