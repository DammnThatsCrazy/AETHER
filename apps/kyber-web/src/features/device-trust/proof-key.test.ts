import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  clearProofKey,
  ensureProofKey,
  exportPublicKeySpki,
  generateProofKey,
  isProofKeySupported,
  loadProofKey,
  signProofChallenge,
} from './proof-key';
import { stubIndexedDb, stubSubtleCrypto, type SubtleCryptoStub } from '@kyber/test/kyber-auth-doubles';

let subtle: SubtleCryptoStub;
let store: Map<string, unknown>;

beforeEach(() => {
  store = stubIndexedDb();
  subtle = stubSubtleCrypto();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('device proof key', () => {
  it('generates a NON-EXTRACTABLE ECDSA P-256 keypair', async () => {
    await generateProofKey();

    expect(subtle.generateKey).toHaveBeenCalledTimes(1);
    const [algorithm, extractable, usages] = subtle.generateKey.mock.calls[0] as [
      EcKeyGenParams,
      boolean,
      string[],
    ];
    expect(algorithm).toEqual({ name: 'ECDSA', namedCurve: 'P-256' });
    // This is the whole point of the mechanism: the private key can never be
    // exported, so it cannot follow the operator to a second machine.
    expect(extractable).toBe(false);
    expect(usages).toEqual(['sign', 'verify']);
  });

  it('persists the CryptoKey in IndexedDB and reads it back', async () => {
    const generated = await generateProofKey();
    expect(store.size).toBe(1);

    const loaded = await loadProofKey();
    expect(loaded).not.toBeNull();
    expect(loaded?.privateKey).toBe(generated.privateKey);
  });

  it('reuses an existing key rather than minting a second one', async () => {
    await ensureProofKey();
    await ensureProofKey();
    expect(subtle.generateKey).toHaveBeenCalledTimes(1);
  });

  it('exports only the public half, as SPKI base64url', async () => {
    const record = await generateProofKey();
    const spki = await exportPublicKeySpki(record.publicKey);

    expect(subtle.exportKey).toHaveBeenCalledWith('spki', record.publicKey);
    expect(spki).toMatch(/^[A-Za-z0-9_-]+$/);
    // No private-key export path exists anywhere in this module.
    expect(subtle.exportKey).not.toHaveBeenCalledWith('spki', record.privateKey);
    expect(subtle.exportKey).not.toHaveBeenCalledWith('pkcs8', expect.anything());
  });

  it('signs a backend challenge with ECDSA + SHA-256', async () => {
    const record = await generateProofKey();
    const signature = await signProofChallenge('Y2hhbGxlbmdl', record.privateKey);

    const [params, key] = subtle.sign.mock.calls[0] as [EcdsaParams, CryptoKey];
    expect(params).toEqual({ name: 'ECDSA', hash: { name: 'SHA-256' } });
    expect(key).toBe(record.privateKey);
    expect(signature).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it('clears the local key on demand', async () => {
    await generateProofKey();
    await clearProofKey();
    expect(await loadProofKey()).toBeNull();
  });

  it('reports unsupported when WebCrypto is missing', async () => {
    vi.stubGlobal('crypto', undefined);
    expect(isProofKeySupported()).toBe(false);
    expect(await loadProofKey()).toBeNull();
    await expect(generateProofKey()).rejects.toThrow(/cannot store a device proof key/i);
  });

  it('reports unsupported when IndexedDB is missing', async () => {
    vi.stubGlobal('indexedDB', undefined);
    expect(isProofKeySupported()).toBe(false);
  });
});
