/**
 * Wires @aether/mobile-core to the Kyber operator app's runtime.
 *
 * Bound to the `kyber` product plane with the workforce auth audience and a distinct
 * secure store. Tenant (Aether) identity and Kyber workforce identity stay separate —
 * an Aether token cannot call Kyber, and this binary carries no Aether tenant code.
 * The operator gateway surfaces are governed by the Kyber command plane (deferred to
 * the Kyber-mobile milestone); C4 wires only identity + continuity + sync.
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

const config: MobileConfig = {
  apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? 'https://operator.aether.example',
  appKind: 'kyber',
  environment: process.env.EXPO_PUBLIC_ENVIRONMENT ?? 'production',
};

// A separate keystore namespace from the Aether app.
const secureStore: SecureStoreInterface = {
  get: (key) => SecureStore.getItemAsync(`kyber.${key}`),
  set: (key, value) => SecureStore.setItemAsync(`kyber.${key}`, value),
  delete: (key) => SecureStore.deleteItemAsync(`kyber.${key}`),
};

export const auth = new SecureStoreAuthProvider(secureStore, 'kyber.operator_token');

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

const deviceFetch: FetchLike = (url, init) => fetch(url, init as RequestInit);

export const client = new AetherMobileClient(config, { fetch: deviceFetch, auth });
