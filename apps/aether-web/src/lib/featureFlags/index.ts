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
  /** Immutable Explore snapshot/diff controls (default OFF until enabled). */
  readonly enableExplorationSnapshots: boolean;
  /** Noesis trace/proposal handoff controls (default OFF until enabled). */
  readonly enableNoesisGovernanceControls: boolean;
  /** Tenant model-routing preference panel (ADR-008 D4/D9, model harness). */
  readonly enableModelHarness: boolean;
  /** Identity explainability API (§13.2) — profile identity explanation + decision details. */
  readonly identity_explainability_enabled: boolean;
  /** Tenant identity activation dashboard (§12.1) — activation status surface. */
  readonly tenant_identity_activation_dashboard_enabled: boolean;
  // ── Identity Continuity runtime (blueprint §15) — PR 9 Iota ──────────────
  readonly identity_resolution_enabled: boolean;
  readonly identity_auto_merge_enabled: boolean;
  readonly identity_manual_review_enabled: boolean;
  readonly identity_conflict_detection_enabled: boolean;
  readonly identity_split_enabled: boolean;
  readonly identity_manual_split_enabled: boolean;
  readonly identity_auto_split_candidates_enabled: boolean;
  readonly sdk_late_binding_enabled: boolean;
  readonly anonymous_to_known_binding_enabled: boolean;
  readonly multi_sdk_identity_stitching_enabled: boolean;
  readonly connector_backfill_identity_resolution_enabled: boolean;
  readonly projection_restatement_enabled: boolean;
  readonly campaign_restatement_enabled: boolean;
  readonly value_restatement_enabled: boolean;
  readonly agent_identity_resolution_enabled: boolean;
}

const DEFAULT_FLAGS: AetherFeatureFlags = {
  // D8: default OFF — no runtime behavior change until a later milestone flips it.
  enableContinuations: false,
  enableClientSyncConsumption: false,
  enableExplorationSnapshots: false,
  enableNoesisGovernanceControls: false,
  enableModelHarness: false,
  // PR 8 — Identity continuity UX surfaces. Default OFF until the owning
  // milestone flips them on for a tenant.
  identity_explainability_enabled: false,
  tenant_identity_activation_dashboard_enabled: false,
  // PR 9 — Identity Continuity runtime flags (blueprint §15). All default OFF.
  identity_resolution_enabled: false,
  identity_auto_merge_enabled: false,
  identity_manual_review_enabled: false,
  identity_conflict_detection_enabled: false,
  identity_split_enabled: false,
  identity_manual_split_enabled: false,
  identity_auto_split_candidates_enabled: false,
  sdk_late_binding_enabled: false,
  anonymous_to_known_binding_enabled: false,
  multi_sdk_identity_stitching_enabled: false,
  connector_backfill_identity_resolution_enabled: false,
  projection_restatement_enabled: false,
  campaign_restatement_enabled: false,
  value_restatement_enabled: false,
  agent_identity_resolution_enabled: false,
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
