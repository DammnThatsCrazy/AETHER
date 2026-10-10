import { describe, expect, it } from 'vitest';

import { createPkcePair, SecureStoreAuthProvider } from '../index';
import type { CryptoProvider, SecureStore } from '../index';

function stubCrypto(): CryptoProvider {
  let n = 0;
  return {
    randomUrlSafeString: (byteLength) => `verifier-${byteLength}-${n++}`,
    // Deterministic stand-in for base64url(SHA-256(input)) so the transform is testable.
    sha256Base64Url: async (input) => `hash(${input})`,
  };
}

function memoryStore(): SecureStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    get: async (k) => data.get(k) ?? null,
    set: async (k, v) => {
      data.set(k, v);
    },
    delete: async (k) => {
      data.delete(k);
    },
  };
}

describe('PKCE', () => {
  it('derives the challenge from the verifier via S256', async () => {
    const pair = await createPkcePair(stubCrypto());
    expect(pair.method).toBe('S256');
    expect(pair.verifier).toBe('verifier-32-0');
    expect(pair.challenge).toBe('hash(verifier-32-0)');
  });

  it('produces a distinct verifier each call', async () => {
    const crypto = stubCrypto();
    const a = await createPkcePair(crypto);
    const b = await createPkcePair(crypto);
    expect(a.verifier).not.toBe(b.verifier);
  });
});

describe('SecureStoreAuthProvider', () => {
  it('reads null before a token is set', async () => {
    const provider = new SecureStoreAuthProvider(memoryStore());
    expect(await provider.getAccessToken()).toBeNull();
  });

  it('round-trips and clears the token through the store', async () => {
    const store = memoryStore();
    const provider = new SecureStoreAuthProvider(store);
    await provider.setAccessToken('tok-abc');
    expect(await provider.getAccessToken()).toBe('tok-abc');
    // Stored under the namespaced key, not a bare value.
    expect(store.data.has('aether.access_token')).toBe(true);
    await provider.clear();
    expect(await provider.getAccessToken()).toBeNull();
  });
});
