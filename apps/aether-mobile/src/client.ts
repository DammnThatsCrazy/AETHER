/**
 * Wires @aether/mobile-core to the Aether app's runtime.
 *
 * The core SDK is transport-agnostic; here we bind it to the device's `fetch`, a
 * Keychain/Keystore-backed token store (expo-secure-store), and Web Crypto for PKCE.
 * The app is bound to the `aether` product plane — an Aether token can never call
 * Kyber (a separate binary with a separate audience).
 */
import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import {
  AetherMobileClient,
  SecureStoreAuthProvider,
  type CryptoProvider,
  type FetchLike,
  type MobileConfig,
  type SecureStore as SecureStoreInterface,
} from '@aether/mobile-core';

export const config: MobileConfig = {
  // Real base URL is injected at build time (EAS secret / app config extra).
  apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? 'https://api.aether.example',
  appKind: 'aether',
  environment: process.env.EXPO_PUBLIC_ENVIRONMENT ?? 'production',
};

export const secureStore: SecureStoreInterface = {
  get: (key) => SecureStore.getItemAsync(key),
  set: (key, value) => SecureStore.setItemAsync(key, value),
  delete: (key) => SecureStore.deleteItemAsync(key),
};

export const auth = new SecureStoreAuthProvider(secureStore);

/**
 * expo-crypto-backed PKCE primitives — the canonical Hermes-safe implementation.
 * Hermes does not expose Web Crypto / TextEncoder / btoa, so the C4 scaffold's
 * globalThis.crypto provider would fail at runtime on device; this M0 fix replaces
 * it with expo-crypto (native secure random + SHA-256) and a pure base64url codec.
 */
const BASE64URL_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

/** Standard base64url (RFC 4648 §5) — 32 bytes encode to the RFC 7636 43-char verifier. */
function base64Url(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : 0;
    out += BASE64URL_ALPHABET[b0 >> 2];
    out += BASE64URL_ALPHABET[((b0 & 3) << 4) | (b1 >> 4)];
    out += i + 1 < bytes.length ? BASE64URL_ALPHABET[((b1 & 15) << 2) | (b2 >> 6)] : '';
    out += i + 2 < bytes.length ? BASE64URL_ALPHABET[b2 & 63] : '';
  }
  return out;
}

export const crypto: CryptoProvider = {
  randomUrlSafeString: (byteLength) => base64Url(Crypto.getRandomBytes(byteLength)),
  sha256Base64Url: async (input) => {
    const digest = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, input, {
      encoding: Crypto.CryptoEncoding.BASE64,
    });
    // digestStringAsync(BASE64) emits standard base64; map to base64url for PKCE S256.
    return digest.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  },
};

// The device fetch (a WHATWG Response) structurally satisfies FetchResponseLike.
export const deviceFetch: FetchLike = (url, init) => fetch(url, init as RequestInit);

export const client = new AetherMobileClient(config, { fetch: deviceFetch, auth });
