/**
 * Device-proof key.
 *
 * WHY THIS EXISTS, given we already do WebAuthn:
 *
 *   Platform passkeys SYNC. A passkey enrolled on an operator's laptop shows
 *   up on their phone and on a second laptop through the OS credential
 *   manager. That is good for account recovery and useless for device
 *   binding: a synced passkey cannot tell us *which machine* is talking to us.
 *
 *   So each browser profile additionally generates its own ECDSA P-256
 *   keypair that is NON-EXTRACTABLE (`extractable: false`) and lives only in
 *   this profile's IndexedDB. It cannot be exported, copied to another
 *   machine, or read by any script — including this one. The public key is
 *   registered with the backend against a device grant; the backend then
 *   challenges the browser to sign a nonce with the private key.
 *
 *   The pair — a browser-local proof key plus a server-side device grant that
 *   another operator must approve — is what makes a second machine require its
 *   own approval even though the operator's passkey followed them there.
 *
 * The private key never leaves the browser and never leaves IndexedDB in a
 * form anything can serialise. There is no export path in this module for it,
 * on purpose.
 */

import { bytesToBase64Url, base64UrlToBytes } from '@kyber/lib/auth/encoding';
import { idbDelete, idbGet, idbPut, isIndexedDbAvailable } from './idb';

const PROOF_KEY_RECORD = 'device-proof-key';

const ALGORITHM: EcKeyGenParams = { name: 'ECDSA', namedCurve: 'P-256' };
const SIGN_PARAMS: EcdsaParams = { name: 'ECDSA', hash: { name: 'SHA-256' } };

export class ProofKeyUnsupportedError extends Error {
  constructor(message = 'This browser cannot store a device proof key (WebCrypto/IndexedDB unavailable)') {
    super(message);
    this.name = 'ProofKeyUnsupportedError';
  }
}

export interface DeviceProofKeyRecord {
  readonly privateKey: CryptoKey;
  readonly publicKey: CryptoKey;
  readonly created_at: string;
}

export function isProofKeySupported(): boolean {
  return (
    isIndexedDbAvailable() &&
    typeof crypto !== 'undefined' &&
    typeof crypto.subtle?.generateKey === 'function' &&
    typeof crypto.subtle?.sign === 'function'
  );
}

/**
 * Generate and persist a fresh proof key.
 *
 * `extractable` is `false` — this is the security property of the whole
 * mechanism and must never be relaxed to make debugging easier. Per the
 * WebCrypto spec the *public* half of an ECDSA pair is always extractable, so
 * SPKI export below still works while the private half stays sealed.
 */
export async function generateProofKey(): Promise<DeviceProofKeyRecord> {
  if (!isProofKeySupported()) throw new ProofKeyUnsupportedError();
  const pair = (await crypto.subtle.generateKey(ALGORITHM, false, ['sign', 'verify'])) as CryptoKeyPair;
  const record: DeviceProofKeyRecord = {
    privateKey: pair.privateKey,
    publicKey: pair.publicKey,
    created_at: new Date().toISOString(),
  };
  await idbPut(PROOF_KEY_RECORD, record);
  return record;
}

export async function loadProofKey(): Promise<DeviceProofKeyRecord | null> {
  if (!isProofKeySupported()) return null;
  try {
    return await idbGet<DeviceProofKeyRecord>(PROOF_KEY_RECORD);
  } catch {
    return null;
  }
}

/** Drops the local key. Used on revocation and before a re-enrolment. */
export async function clearProofKey(): Promise<void> {
  if (!isIndexedDbAvailable()) return;
  try {
    await idbDelete(PROOF_KEY_RECORD);
  } catch {
    // A store we cannot open holds nothing we need to clear.
  }
}

/** Existing key if present, otherwise a freshly generated one. */
export async function ensureProofKey(): Promise<DeviceProofKeyRecord> {
  const existing = await loadProofKey();
  if (existing !== null) return existing;
  return generateProofKey();
}

/** SPKI → base64url. Public half only; there is no private-key export. */
export async function exportPublicKeySpki(publicKey: CryptoKey): Promise<string> {
  const spki = await crypto.subtle.exportKey('spki', publicKey);
  return bytesToBase64Url(spki);
}

/** Sign a backend-issued base64url challenge with ECDSA P-256 / SHA-256. */
export async function signProofChallenge(
  challengeB64Url: string,
  privateKey: CryptoKey,
): Promise<string> {
  const signature = await crypto.subtle.sign(
    SIGN_PARAMS,
    privateKey,
    base64UrlToBytes(challengeB64Url) as unknown as BufferSource,
  );
  return bytesToBase64Url(signature);
}

export const PROOF_KEY_ALGORITHM = ALGORITHM;
export const PROOF_KEY_SIGN_PARAMS = SIGN_PARAMS;
export const PROOF_KEY_RECORD_ID = PROOF_KEY_RECORD;
