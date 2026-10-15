/**
 * Barrel for the Kyber model-runtime admin surfaces (ADR-008 D8/D9).
 *
 * Re-exports the typed contract (server-shaped, no credentials) and the five
 * operator pages: model registry, runtime health, entitlements, usage, traces.
 * The typed fetch client (`defaultModelRuntimeAdminApi`) fails cleanly until
 * real backend wiring lands in a later integration step.
 */

export * from './types';

export { ModelRegistryPage } from './ModelRegistryPage';
export { ModelRuntimeHealthPage } from './ModelRuntimeHealthPage';
export { EntitlementsPage } from './entitlements-page';
export { UsagePage } from './UsagePage';
export { TracesPage } from './TracesPage';
