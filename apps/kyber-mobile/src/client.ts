/**
 * Wires @aether/mobile-core to the Kyber operator app's runtime.
 *
 * Bound to the `kyber` product plane with the workforce auth audience and a distinct
 * secure store. Tenant (Aether) identity and Kyber workforce identity stay separate —
 * an Aether token cannot call Kyber, and this binary carries no Aether tenant code.
 * The operator gateway surfaces are governed by the Kyber command plane (deferred to
 * the Kyber-mobile milestone); C4 wires only identity + continuity + sync.
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

export const crypto: CryptoProvider = {
  randomUrlSafeString: (byteLength) => base64Url(globalThis.crypto.getRandomValues(new Uint8Array(byteLength))),
  sha256Base64Url: async (input) => {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
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

const deviceFetch: FetchLike = (url, init) => fetch(url, init as RequestInit);

export const client = new AetherMobileClient(config, { fetch: deviceFetch, auth });
