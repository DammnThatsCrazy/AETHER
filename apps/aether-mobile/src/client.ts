/**
 * Wires @aether/mobile-core to the Aether app's runtime.
 *
 * The core SDK is transport-agnostic; here we bind it to the device's `fetch`, a
 * Keychain/Keystore-backed token store (expo-secure-store), and Web Crypto for PKCE.
 * The app is bound to the `aether` product plane — an Aether token can never call
 * Kyber (a separate binary with a separate audience).
 */
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
  // Real base URL is injected at build time (EAS secret / app config extra).
  apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? 'https://api.aether.example',
  appKind: 'aether',
  environment: process.env.EXPO_PUBLIC_ENVIRONMENT ?? 'production',
};

const secureStore: SecureStoreInterface = {
  get: (key) => SecureStore.getItemAsync(key),
  set: (key, value) => SecureStore.setItemAsync(key, value),
  delete: (key) => SecureStore.deleteItemAsync(key),
};

export const auth = new SecureStoreAuthProvider(secureStore);

/** Web Crypto-backed PKCE primitives (available in the RN Hermes runtime). */
export const crypto: CryptoProvider = {
  randomUrlSafeString: (byteLength) => {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(byteLength));
    return base64Url(bytes);
  },
  sha256Base64Url: async (input) => {
    const data = new TextEncoder().encode(input);
    const digest = await globalThis.crypto.subtle.digest('SHA-256', data);
    return base64Url(new Uint8Array(digest));
  },
};

function base64Url(bytes: Uint8Array): string {
  let binary = '';
  for (const b of bytes) {
    binary += String.fromCharCode(b);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

// The device fetch (a WHATWG Response) structurally satisfies FetchResponseLike.
const deviceFetch: FetchLike = (url, init) => fetch(url, init as RequestInit);

export const client = new AetherMobileClient(config, { fetch: deviceFetch, auth });
