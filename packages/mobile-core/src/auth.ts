/**
 * Native auth primitives — PKCE + a secure-storage-backed token provider.
 *
 * Platform-agnostic: the cryptographic primitives (secure random + SHA-256) and the
 * secure store (Keychain / Keystore) are INJECTED by the host app, so this module
 * never depends on Web Crypto, Node crypto, or a native module. A raw token is only
 * ever held by the host's secure store; nothing here logs it.
 */
import type { AuthProvider } from './http';

/** Host-supplied crypto. The device implementation uses Web Crypto / SubtleCrypto. */
export interface CryptoProvider {
  /** A URL-safe, unguessable string built from `byteLength` bytes of CSPRNG output. */
  randomUrlSafeString(byteLength: number): string;
  /** base64url( SHA-256( input ) ) — the PKCE S256 challenge transform. */
  sha256Base64Url(input: string): Promise<string>;
}

export interface PkcePair {
  verifier: string;
  challenge: string;
  method: 'S256';
}

/**
 * Build a PKCE verifier/challenge pair (RFC 7636, S256). The verifier is a
 * high-entropy random string; the challenge is its base64url SHA-256. The verifier
 * stays on device (paired with the auth request) and is never sent until token
 * exchange.
 */
export async function createPkcePair(crypto: CryptoProvider): Promise<PkcePair> {
  const verifier = crypto.randomUrlSafeString(32);
  const challenge = await crypto.sha256Base64Url(verifier);
  return { verifier, challenge, method: 'S256' };
}

/** Platform secure storage (iOS Keychain / Android Keystore-backed). */
export interface SecureStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  delete(key: string): Promise<void>;
}

const DEFAULT_TOKEN_KEY = 'aether.access_token';

/**
 * An {@link AuthProvider} backed by a {@link SecureStore}. The access token lives in
 * the platform keystore; callers read it through `getAccessToken()` without the token
 * ever passing through logs or in-memory globals.
 */
export class SecureStoreAuthProvider implements AuthProvider {
  constructor(private readonly store: SecureStore, private readonly key: string = DEFAULT_TOKEN_KEY) {}

  getAccessToken(): Promise<string | null> {
    return this.store.get(this.key);
  }

  async setAccessToken(token: string): Promise<void> {
    await this.store.set(this.key, token);
  }

  async clear(): Promise<void> {
    await this.store.delete(this.key);
  }
}
