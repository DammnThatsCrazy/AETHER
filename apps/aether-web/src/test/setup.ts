import '@testing-library/jest-dom';
import { transferableAbortController } from 'node:util';

// Vitest runs Aether components in jsdom while Node supplies the native fetch
// implementation. Node 24 rejects a jsdom-realm AbortSignal before MSW can
// intercept the request, so keep fetch and its abort primitives in one realm.
// This is deliberately test-only: production cancellation remains unchanged.
const nativeController = transferableAbortController();
Object.defineProperties(globalThis, {
  AbortController: {
    configurable: true,
    writable: true,
    value: nativeController.constructor,
  },
  AbortSignal: {
    configurable: true,
    writable: true,
    value: nativeController.signal.constructor,
  },
});
