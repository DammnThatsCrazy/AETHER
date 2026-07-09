// =============================================================================
// Aether SDK — Release Version Source of Truth
// =============================================================================

/** Current productized SDK release version across Web, React Native, iOS, Android, package metadata, docs, and release tooling. */
export const SDK_VERSION = '8.12.0' as const;

/** Canonical SDK ingestion endpoint. SDKs MUST post batches here. */
export const SDK_INGESTION_PATH = '/v1/batch' as const;
