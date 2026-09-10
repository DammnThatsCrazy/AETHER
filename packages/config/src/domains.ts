/**
 * Domain mapping constants for the product family.
 *
 * Defaults mirror the origins every app's own `src/lib/env.ts` already
 * defaults to (`frontend/olympus-marketing/src/lib/env.ts`,
 * `frontend/aether-marketing/src/lib/env.ts`) and that `seo-data.json` in each
 * app declares as its `host` — this module does not introduce a second,
 * inconsistent domain scheme; it centralizes the one already in effect so
 * deploy tooling and app code read the same mapping. Every value stays
 * overridable per environment through `buildDomainMap`.
 */

export type ProductSubdomain = 'olympus' | 'aetherMarketing' | 'aetherApp' | 'docs' | 'status' | 'kyber';

export interface DomainMap {
  /** Olympus Labs corporate marketing origin. */
  readonly olympus: string;
  /** Aether public marketing origin. */
  readonly aetherMarketing: string;
  /** Protected Aether tenant application origin. */
  readonly aetherApp: string;
  /** Aether documentation origin. */
  readonly docs: string;
  /** Aether public service status origin. */
  readonly status: string;
  /** Olympus Labs internal Kyber origin — never linked from public marketing. */
  readonly kyber: string;
}

/** Production defaults, matching every app's own `env.ts` fallback values. */
export const PRODUCTION_DOMAINS: DomainMap = {
  olympus: 'https://olympuslabsml.com',
  aetherMarketing: 'https://aether.olympuslabsml.com',
  aetherApp: 'https://app.olympuslabsml.com',
  docs: 'https://docs.olympuslabsml.com',
  status: 'https://status.olympuslabsml.com',
  kyber: 'https://kyber.olympuslabsml.com',
};

/**
 * Build a domain map for one deploy, overriding only the origins a caller
 * supplies. Values are used verbatim (no trailing-slash normalization) so a
 * generated map composes the same way `env.ts`'s `VITE_*_URL` overrides do.
 */
export function buildDomainMap(overrides: Partial<DomainMap> = {}): DomainMap {
  return { ...PRODUCTION_DOMAINS, ...overrides };
}

/** Look up one origin from a domain map by its subdomain key. */
export function originFor(domains: DomainMap, subdomain: ProductSubdomain): string {
  return domains[subdomain];
}
