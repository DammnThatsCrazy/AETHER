// =============================================================================
// Aether SDK — Shared Schema Version
// Canonical contract version used by Web, iOS, Android, and React Native SDKs.
// Any breaking change to shared/*.ts MUST bump CONTRACT_SCHEMA_VERSION.
// =============================================================================

/** Semver of the SDK ↔ backend contract surface defined in packages/shared/*.ts */
export const CONTRACT_SCHEMA_VERSION = '1.0.0' as const;

/** Free-form label for human readability (matches CHANGELOG entry). */
export const CONTRACT_SCHEMA_LABEL = 'unified-hybrid-v1' as const;
