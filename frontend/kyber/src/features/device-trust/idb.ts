/**
 * Minimal typed IndexedDB wrapper — no external dependency.
 *
 * IndexedDB is used (rather than localStorage) for exactly one reason: it is
 * the only browser store that can hold a `CryptoKey` object. A non-extractable
 * `CryptoKey` can be *stored and retrieved* through the structured clone
 * algorithm but never serialised out of the browser — which is precisely the
 * property the device-proof key depends on.
 */

const DB_NAME = 'kyber-device-trust';
const DB_VERSION = 1;
const STORE_NAME = 'proof-keys';

export function isIndexedDbAvailable(): boolean {
  return typeof indexedDB !== 'undefined' && indexedDB !== null;
}

export class DeviceStoreUnavailableError extends Error {
  constructor(message = 'IndexedDB is unavailable in this browser context') {
    super(message);
    this.name = 'DeviceStoreUnavailableError';
  }
}

function openDatabase(): Promise<IDBDatabase> {
  if (!isIndexedDbAvailable()) return Promise.reject(new DeviceStoreUnavailableError());
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(request.error ?? new DeviceStoreUnavailableError('IndexedDB open failed'));
    request.onblocked = () =>
      reject(new DeviceStoreUnavailableError('IndexedDB open blocked by another tab'));
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest,
): Promise<T> {
  const db = await openDatabase();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, mode);
      const request = operation(tx.objectStore(STORE_NAME));
      request.onsuccess = () => resolve(request.result as T);
      request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
      tx.onabort = () => reject(tx.error ?? new Error('IndexedDB transaction aborted'));
    });
  } finally {
    db.close();
  }
}

export async function idbGet<T>(key: string): Promise<T | null> {
  const value = await withStore<T | undefined>('readonly', (store) => store.get(key));
  return value ?? null;
}

export async function idbPut<T>(key: string, value: T): Promise<void> {
  await withStore<IDBValidKey>('readwrite', (store) => store.put(value, key));
}

export async function idbDelete(key: string): Promise<void> {
  await withStore<undefined>('readwrite', (store) => store.delete(key));
}

export const DEVICE_TRUST_DB = { name: DB_NAME, version: DB_VERSION, store: STORE_NAME } as const;
