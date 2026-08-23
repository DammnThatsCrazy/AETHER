/**
 * Aether frontend feature flags.
 *
 * Every flag defaults OFF (D8): shipping a surface default-on would change
 * runtime behavior for every tenant before the owning milestone flips it. Flags
 * are read lazily from `VITE_FEATURE_FLAGS` (a JSON object, e.g.
 * `{"enableContinuations":true}`) so per-test `vi.stubEnv` can toggle them
 * without a rebuild — the same pattern `isPaymentCanonicalRepairEnabled` uses.
 * Invalid flag JSON falls back to defaults and never crashes the app.
 */
interface AetherFeatureFlags {
  /** Continue-on-phone + recent mobile activity/resume continuation surfaces (M5c). */
  readonly enableContinuations: boolean;
  /** Client-sync change-feed consumption panel (M5c). */
  readonly enableClientSyncConsumption: boolean;
  /** Tenant model-routing preference panel (ADR-008 D4/D9, model harness). */
  readonly enableModelHarness: boolean;
}

const DEFAULT_FLAGS: AetherFeatureFlags = {
  // D8: default OFF — no runtime behavior change until a later milestone flips it.
  enableContinuations: false,
  enableClientSyncConsumption: false,
  enableModelHarness: false,
};

function loadFlags(): AetherFeatureFlags {
  try {
    const raw = import.meta.env.VITE_FEATURE_FLAGS as string | undefined;
    if (raw && raw !== '{}') {
      const parsed = JSON.parse(raw) as Partial<AetherFeatureFlags>;
      return { ...DEFAULT_FLAGS, ...parsed };
    }
  } catch {
    // Invalid flag JSON — fall back to defaults (never crash on flags).
  }
  return DEFAULT_FLAGS;
}

export function isFeatureEnabled(flag: keyof AetherFeatureFlags): boolean {
  return loadFlags()[flag];
}
