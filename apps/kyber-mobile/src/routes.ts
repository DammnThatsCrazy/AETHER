/**
 * Kyber Mobile route map — the typed screen registry (M4a, extended M6b).
 *
 * Mirrors the Aether Mobile pattern: every operator-companion surface is a root
 * tab with no params. All screens are READ-ONLY (M2 "no offline mutation"
 * invariant): governed actions (approve / suspend / revoke / resolve /
 * suppress / acknowledge) live on the desktop command plane and are NEVER
 * dispatched from this binary. M6b adds the two read-only governed-action
 * surfaces — Actions (tier 0-3 availability digest + device-bound step-up) and
 * Receipts (durable command-receipt visibility) — still with no endpoint that
 * names an arbitrary action and no offline mutation.
 */
import type { RouteMap } from '@aether/mobile-ui';

export interface KyberRoutes extends RouteMap {
  Pulse: undefined;
  Exceptions: undefined;
  Incidents: undefined;
  Runs: undefined;
  Reviews: undefined;
  Briefings: undefined;
  Actions: undefined;
  Receipts: undefined;
  Account: undefined;
}

/** The nine root tabs. */
export type KyberTab = keyof KyberRoutes;
