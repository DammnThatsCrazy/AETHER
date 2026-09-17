// @aether/proof-runner — fixture loading bridge to @aether/proof-fixtures
import type { ProofContext } from "./contracts";
import {
  loadRawFixture,
  loadExpectedNormalized,
  loadExpectedGraphOutputs,
  loadExpected360Outputs,
  loadExpectedLensOutput,
  listAvailableFixtures,
  findFixtureDir,
} from "@aether/proof-fixtures";

// ---------------------------------------------------------------------------
// Typed fixture access
// ---------------------------------------------------------------------------

/** Load a raw fixture by key and merge it into a ProofContext.fixtures snapshot. */
export async function loadFixturesIntoContext(
  ctx: ProofContext,
  fixtureKeys: string[],
): Promise<void> {
  const loaded: Record<string, unknown> = { ...(ctx.fixtures || {}) };
  for (const key of fixtureKeys) {
    try {
      loaded[key] = await loadRawFixture(key);
    } catch (err) {
      // Keep going — a single missing fixture should not abort the whole proof.
      loaded[key] = { _loadError: (err as Error).message };
    }
  }
  // Create a new context-ish object; in practice callers re-create the context.
  // We mutate a shallow copy the caller can spread back into their context.
  Object.assign(ctx.fixtures, loaded);
}

/** Convenience: load every fixture key the 24-step spine cares about. */
export const DEFAULT_PROOF_FIXTURE_KEYS = [
  "sdk-heartbeat",
  "trackEventFixture",
  "identifyEventFixture",
  "conversionEventFixture",
  "stripeCustomerFixture",
  "stripePaymentFixture",
  "shopifyOrderFixture",
  "shopifyCustomerFixture",
  "emailSentFixture",
  "emailOpenFixture",
  "graphProfileNodeFixture",
  "graphJourneyNodeFixture",
  "graphCampaignNodeFixture",
  "graphCommunicationNodeFixture",
  "graphConversionNodeFixture",
  "graphValueNodeFixture",
  "graphTouchpointEdgeFixture",
  "graphAttributionEdgeFixture",
  "provenanceFixture",
  "lensInputFixture",
  "lensOutputFixture",
  "surface360QueryFixture",
  "profile360Fixture",
  "campaign360Fixture",
  "communications360Fixture",
];

/** Returns the resolved file path for a fixture key (for debugging / reporting). */
export function resolveFixturePath(fixtureKey: string): string {
  return findFixtureDir(fixtureKey);
}

/** Check whether a fixture key resolves without throwing. */
export function hasFixture(fixtureKey: string): boolean {
  try {
    findFixtureDir(fixtureKey);
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// ProofContext factory
// ---------------------------------------------------------------------------

/** Build a bare ProofContext for running the proof spine locally. */
export function createProofContext(options: {
  tenantId?: string;
  workspaceId?: string;
  platformId?: string;
  environment?: "development" | "staging" | "production";
  fixtures?: Record<string, unknown>;
} = {}): ProofContext {
  return {
    tenantId: options.tenantId ?? "aether-proof-tenant",
    workspaceId: options.workspaceId ?? "proof-lab",
    platformId: options.platformId ?? "web",
    environment: options.environment ?? "staging",
    fixtures: options.fixtures ?? {},
    fixtureLoader: {
      loadRawFixture,
      loadExpectedNormalized,
      loadExpectedGraphOutputs,
      loadExpected360Outputs,
      loadExpectedLensOutput,
      listAvailableFixtures,
    },
  };
}
