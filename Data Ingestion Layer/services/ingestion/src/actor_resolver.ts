// =============================================================================
// Aether INGESTION — ACTOR RESOLVER
// Resolves the principal performing each event into an `actor_id` of kind
// human | agent | system. Backed by Redis-cached lookups against the
// Postgres `actors` table (managed by the journey-service).
// =============================================================================

import { createLogger } from '@aether/logger';

const logger = createLogger('aether.ingestion.actor');

export type ActorKind = 'human' | 'agent' | 'system';

export interface ResolvedActor {
  actorId: string;
  kind: ActorKind;
  identifier: string;          // user_id | worker_id | system_name
  tenantId?: string;
  orgId?: string;
}

export interface ActorResolverConfig {
  /** Redis-like cache. In tests, pass a Map. */
  cache?: { get(k: string): Promise<string | undefined>; set(k: string, v: string, ttlSec: number): Promise<void> };
  /** Lookup against `actors` table. Returns null if unknown. */
  lookup?: (kind: ActorKind, identifier: string) => Promise<ResolvedActor | null>;
  /** Insert a new actor row when none exists. */
  create?: (kind: ActorKind, identifier: string, meta: { tenantId?: string; orgId?: string }) => Promise<ResolvedActor>;
  ttlSec?: number;
}

const CACHE_TTL = 3600;

export class ActorResolver {
  private readonly cfg: Required<ActorResolverConfig>;
  private readonly memCache = new Map<string, ResolvedActor>();

  constructor(cfg: ActorResolverConfig = {}) {
    this.cfg = {
      cache: cfg.cache ?? this.defaultCache(),
      lookup: cfg.lookup ?? (async () => null),
      create: cfg.create ?? this.defaultCreate(),
      ttlSec: cfg.ttlSec ?? CACHE_TTL,
    };
  }

  /**
   * Resolve the actor responsible for an inbound event.
   *
   * Resolution order:
   *   1. Explicit `context.actorId` + `context.actorKind` (set by SDK).
   *   2. Auth context (apiKey carrying an `actor` claim — pre-validated
   *      by the API-key validator).
   *   3. Heuristic from event type (`agent_*` → agent, else human).
   */
  async resolve(input: {
    explicitActorId?: string;
    explicitActorKind?: ActorKind;
    apiKeyActor?: { actorId: string; kind: ActorKind; identifier: string };
    userId?: string;
    anonymousId?: string;
    eventType?: string;
    tenantId?: string;
    orgId?: string;
  }): Promise<ResolvedActor> {
    if (input.apiKeyActor) {
      return this.cacheAndReturn({
        actorId: input.apiKeyActor.actorId,
        kind: input.apiKeyActor.kind,
        identifier: input.apiKeyActor.identifier,
        tenantId: input.tenantId,
        orgId: input.orgId,
      });
    }

    const kind: ActorKind =
      input.explicitActorKind ??
      (input.eventType?.startsWith('agent_') || input.eventType === 'agent_task' || input.eventType === 'agent_decision'
        ? 'agent'
        : 'human');

    const identifier =
      input.explicitActorId ?? input.userId ?? input.anonymousId ?? 'anonymous';

    const cacheKey = `actor:${kind}:${identifier}`;
    const memHit = this.memCache.get(cacheKey);
    if (memHit) return memHit;

    const cached = await this.cfg.cache.get(cacheKey);
    if (cached) {
      const parsed = JSON.parse(cached) as ResolvedActor;
      this.memCache.set(cacheKey, parsed);
      return parsed;
    }

    let actor = await this.cfg.lookup(kind, identifier);
    if (!actor) {
      actor = await this.cfg.create(kind, identifier, {
        tenantId: input.tenantId,
        orgId: input.orgId,
      });
      logger.info('actor:created', { kind, identifier, actorId: actor.actorId });
    }
    return this.cacheAndReturn(actor);
  }

  private async cacheAndReturn(actor: ResolvedActor): Promise<ResolvedActor> {
    const cacheKey = `actor:${actor.kind}:${actor.identifier}`;
    this.memCache.set(cacheKey, actor);
    await this.cfg.cache.set(cacheKey, JSON.stringify(actor), this.cfg.ttlSec);
    return actor;
  }

  private defaultCache() {
    const map = new Map<string, { v: string; exp: number }>();
    return {
      async get(k: string) {
        const e = map.get(k);
        if (!e) return undefined;
        if (e.exp < Date.now()) { map.delete(k); return undefined; }
        return e.v;
      },
      async set(k: string, v: string, ttlSec: number) {
        map.set(k, { v, exp: Date.now() + ttlSec * 1000 });
      },
    };
  }

  private defaultCreate() {
    // Stub: synthesize a deterministic actor_id locally. Production wires
    // this to journey-service `POST /v1/actors` (idempotent upsert).
    return async (kind: ActorKind, identifier: string, meta: { tenantId?: string; orgId?: string }): Promise<ResolvedActor> => ({
      actorId: `act_${kind}_${identifier}`,
      kind,
      identifier,
      tenantId: meta.tenantId,
      orgId: meta.orgId,
    });
  }
}
