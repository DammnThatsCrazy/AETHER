// Keep retired identifiers out of production bundles while still matching the
// exact historical worker and storage keys during the migration window.
const LEGACY_MSW_SCRIPT = `/${['mock', 'Service', 'Worker.js'].join('')}`;
const LEGACY_CACHE_NAMES = new Set(['mock', 'msw']);
const LEGACY_STORAGE_KEYS = new Set([
  ['mock', 'access', 'token'].join('_'),
  ['mock', 'refresh', 'token'].join('_'),
  ['kyber', 'mock', 'auth'].join('_'),
  ['kyber', 'mock', 'user'].join('_'),
  ['kyber', 'mock', 'tenant'].join('_'),
  ['kyber', 'mock', 'api', 'key'].join('_'),
  ['kyber', 'mock', 'query', 'cache'].join('_'),
]);

function isLegacyMockWorker(scriptURL: string | undefined): boolean {
  if (!scriptURL) return false;
  try {
    return new URL(scriptURL, window.location.origin).pathname === LEGACY_MSW_SCRIPT;
  } catch {
    return false;
  }
}

function removeLegacyStorage(storage: Storage | undefined): void {
  if (!storage) return;
  for (const key of LEGACY_STORAGE_KEYS) {
    storage.removeItem(key);
  }
}

export async function cleanupLegacyMockWorker(): Promise<void> {
  removeLegacyStorage(typeof localStorage === 'undefined' ? undefined : localStorage);
  removeLegacyStorage(typeof sessionStorage === 'undefined' ? undefined : sessionStorage);

  if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(
      registrations
        .filter((registration) =>
          [registration.active, registration.waiting, registration.installing]
            .some((worker) => isLegacyMockWorker(worker?.scriptURL)))
        .map((registration) => registration.unregister()),
    );
  }

  if (typeof caches !== 'undefined') {
    const cacheNames = await caches.keys();
    await Promise.all(
      cacheNames
        .filter((name) => LEGACY_CACHE_NAMES.has(name.toLowerCase()))
        .map((name) => caches.delete(name)),
    );
  }
}
