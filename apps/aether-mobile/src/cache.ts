/**
 * Read-only projection cache for the Aether mobile screens (M3b).
 *
 * Built on `createOfflineCache` from `@aether/mobile-core`, backed by the same
 * Keychain/Keystore store as auth. It stores successful network READS only — there
 * is no offline mutation path (M2 "no offline mutation" invariant). Screens read
 * the last fetched projection and surface `fresh` / `offline` / `stale` state.
 *
 * The cache is typed as `unknown` at the storage boundary; screens recover their
 * concrete type through `useProjection`, which owns the typed `get`/`put` cast.
 */
import { createOfflineCache } from '@aether/mobile-core';

import { secureStore } from './client';

/** 5-minute TTL for projections (config + today + briefing + alerts + profile). */
const DEFAULT_TTL_MS = 5 * 60 * 1000;

export const projectionCache = createOfflineCache<unknown>({
  storage: secureStore,
  defaultTtlMs: DEFAULT_TTL_MS,
  namespace: 'aether.projection',
});
