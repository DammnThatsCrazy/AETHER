// =============================================================================
// Aether INGESTION — DELEGATION GUARD
// Hot-path check that an event carrying `On-Behalf-Of-Actor` (or
// `context.delegationId`) is covered by an active, unrevoked grant whose
// scope ⊇ the action scope. Mirrors the Python middleware in
// `Backend Architecture/services/delegation/middleware.py`.
// =============================================================================

import { createLogger } from '@aether/logger';

const logger = createLogger('aether.ingestion.delegation');

export interface DelegationGrant {
  delegationId: string;
  delegatorActorId: string;
  delegateeActorId: string;
  scope: string[];
  expiresAt?: string | null;
  revokedAt?: string | null;
}

export interface DelegationGuardConfig {
  /** Look up grants for a delegatee (cached). */
  loadGrants: (delegateeActorId: string) => Promise<DelegationGrant[]>;
  /** TTL of cached grant set, seconds. Bust on `aether.delegation.revoked`. */
  cacheTtlSec?: number;
  now?: () => number;
}

export class DelegationDenied extends Error {
  constructor(public readonly delegateeActorId: string, public readonly scope: string[]) {
    super(`actor ${delegateeActorId} not authorized for scope [${scope.join(', ')}]`);
    this.name = 'DelegationDenied';
  }
}

export class DelegationGuard {
  private readonly cache = new Map<string, { grants: DelegationGrant[]; exp: number }>();
  private readonly ttlMs: number;
  private readonly now: () => number;
  private readonly load: DelegationGuardConfig['loadGrants'];

  constructor(cfg: DelegationGuardConfig) {
    this.load = cfg.loadGrants;
    this.ttlMs = (cfg.cacheTtlSec ?? 60) * 1000;
    this.now = cfg.now ?? Date.now;
  }

  /** Bust the cache for a delegatee — call from a Kafka revocation handler. */
  invalidate(delegateeActorId: string): void {
    this.cache.delete(delegateeActorId);
  }

  /**
   * Returns the resolved grant, or throws DelegationDenied.
   * If `delegationId` is supplied, that exact grant must match and cover
   * the scope. Otherwise any active grant whose scope covers wins.
   */
  async authorize(input: {
    delegateeActorId: string;
    requiredScope: string[];
    delegationId?: string;
  }): Promise<DelegationGrant> {
    const grants = await this.getGrants(input.delegateeActorId);
    const nowIso = new Date(this.now()).toISOString();
    const required = new Set(input.requiredScope);

    for (const g of grants) {
      if (input.delegationId && g.delegationId !== input.delegationId) continue;
      if (g.revokedAt) continue;
      if (g.expiresAt && g.expiresAt < nowIso) continue;
      if ([...required].every(s => g.scope.includes(s))) {
        return g;
      }
    }

    logger.warn('delegation:denied', {
      delegatee: input.delegateeActorId,
      scope: input.requiredScope,
      delegationId: input.delegationId,
    });
    throw new DelegationDenied(input.delegateeActorId, input.requiredScope);
  }

  private async getGrants(delegateeActorId: string): Promise<DelegationGrant[]> {
    const hit = this.cache.get(delegateeActorId);
    if (hit && hit.exp > this.now()) return hit.grants;

    const grants = await this.load(delegateeActorId);
    this.cache.set(delegateeActorId, { grants, exp: this.now() + this.ttlMs });
    return grants;
  }
}
