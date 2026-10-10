import '@testing-library/jest-dom';
import { transferableAbortController } from 'node:util';

// Node supplies fetch in Vitest while jsdom supplies a different-realm
// AbortController. Keep the test transport primitives in Node's realm so MSW
// can receive cancellable requests exactly as the browser runtime does.
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
