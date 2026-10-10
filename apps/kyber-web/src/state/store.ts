/**
 * Store primitive moved to the shared workspace (`@aether/ui`). This re-export
 * shim keeps the historical `@kyber/state` import path working unchanged.
 */
export { createStore, useStore } from '@aether/ui';
export type { Store } from '@aether/ui';
