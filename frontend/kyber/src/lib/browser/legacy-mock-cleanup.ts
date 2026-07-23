const LEGACY_MSW_SCRIPT = '/mockServiceWorker.js';
const LEGACY_CACHE_PREFIXES = ['mock', 'msw'];

export async function cleanupLegacyMockWorker(): Promise<void> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
  const registrations = await navigator.serviceWorker.getRegistrations();
  await Promise.all(
    registrations
      .filter((registration) => registration.active?.scriptURL.endsWith(LEGACY_MSW_SCRIPT))
      .map((registration) => registration.unregister()),
  );
  if (typeof caches === 'undefined') return;
  const cacheNames = await caches.keys();
  await Promise.all(
    cacheNames
      .filter((name) => LEGACY_CACHE_PREFIXES.some((prefix) => name.toLowerCase().startsWith(prefix)))
      .map((name) => caches.delete(name)),
  );
}
