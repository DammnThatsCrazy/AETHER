/**
 * Aether Mobile route map — the typed screen registry (M3b).
 *
 * Mirrors the Aether routes anticipated by `packages/mobile-ui`
 * (`src/__tests__/navigation.test.ts`). Every screen is a root tab with no params;
 * typed params can be added here (e.g. `Account: { section?: string }`) without
 * touching the navigator.
 */
import type { RouteMap } from '@aether/mobile-ui';

export interface AppRoutes extends RouteMap {
  Today: undefined;
  Copilot: undefined;
  Explore: undefined;
  Alerts: undefined;
  Account: undefined;
}

/** The five root tabs. */
export type AppTab = keyof AppRoutes;
