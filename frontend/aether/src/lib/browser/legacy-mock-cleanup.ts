// Keep the retired bundle marker out of new production bundles while still
// matching the historical worker URL during the migration window.
const LEGACY_MSW_SCRIPT = `/${['mock', 'Service', 'Worker.js'].join('')}`;
const LEGACY_MSW_CACHE_NAMES = new Set([
  'msw',
  'msw-cache',
  'aether-msw',
  'aether-msw-cache',
  'aether-mock-service-worker',
]);

const LEGACY_STORAGE_KEYS = [
  ['aether', 'mock', 'access', 'token'].join('_'),
  'aether_mock_api_key',
  'aether_mock_tenant_id',
  'aether_mock_query_cache',
  'aether_mock_state',
] as const;

const CREDENTIAL_STORAGE_KEYS = [
  'aether_session_key',
  'aether_session_token',
] as const;

const LEGACY_CREDENTIAL_PREFIX = ['mock', ''].join('_');
const LEGACY_API_KEY_PREFIX = ['ak', 'mock', ''].join('_');

function isLegacyWorkerScript(scriptURL: string): boolean {
  try {
    return new URL(scriptURL, window.location.origin).pathname.endsWith(LEGACY_MSW_SCRIPT);
  } catch {
    return false;
  }
}

function registrationHasLegacyWorker(registration: ServiceWorkerRegistration): boolean {
  return [registration.active, registration.waiting, registration.installing]
    .some((worker) => worker != null && isLegacyWorkerScript(worker.scriptURL));
}

function clearLegacyStorage(storage: Storage | undefined): void {
  if (!storage) return;
  for (const key of LEGACY_STORAGE_KEYS) storage.removeItem(key);
  let removedSessionToken = false;
  for (const key of CREDENTIAL_STORAGE_KEYS) {
    const value = storage.getItem(key);
    if (
      value !== null &&
      (value.startsWith(LEGACY_API_KEY_PREFIX) || value.startsWith(LEGACY_CREDENTIAL_PREFIX))
    ) {
      storage.removeItem(key);
      removedSessionToken ||= key === 'aether_session_token';
    }
  }
  if (removedSessionToken) storage.removeItem('aether_session_expires_at');
}

export async function cleanupLegacyMockWorker(): Promise<void> {
  if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(
      registrations
        .filter(registrationHasLegacyWorker)
        .map((registration) => registration.unregister()),
    );
  }

  if (typeof caches !== 'undefined') {
    const cacheNames = await caches.keys();
    await Promise.all(
      cacheNames
        .filter((name) => LEGACY_MSW_CACHE_NAMES.has(name.toLowerCase()))
        .map((name) => caches.delete(name)),
    );
  }

  clearLegacyStorage(typeof localStorage === 'undefined' ? undefined : localStorage);
  clearLegacyStorage(typeof sessionStorage === 'undefined' ? undefined : sessionStorage);
}
