/**
 * Kyber Mobile route map — the typed screen registry (M4a).
 *
 * Mirrors the Aether Mobile pattern: every operator-companion surface is a root
 * tab with no params. All screens are READ-ONLY (M2 "no offline mutation"
 * invariant); governed actions (approve / suspend / revoke / resolve /
 * suppress / acknowledge) arrive in M5/M6 and are deliberately absent here.
 */
import type { RouteMap } from '@aether/mobile-ui';

export interface KyberRoutes extends RouteMap {
  Pulse: undefined;
  Exceptions: undefined;
  Incidents: undefined;
  Runs: undefined;
  Reviews: undefined;
  Briefings: undefined;
  Account: undefined;
}

/** The seven root tabs. */
export type KyberTab = keyof KyberRoutes;
