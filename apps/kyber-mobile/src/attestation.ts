/**
 * Kyber Mobile — proof-key lifecycle + step-up elevation (M6b).
 *
 * The mobile equivalent of the browser-profile proof-key path. A P-256 keypair
 * is generated once per install; the PRIVATE key is persisted in the platform
 * keystore under its own namespace (`kyber.step_up_*`), separate from the
 * operator token's (`kyber.kyber.operator_token`). The public half is re-derived
 * or cached in memory — never stored as a key in its own right. On first run
 * (or when the registered proof key is gone from the server) the public key is
 * enrolled via `client.registerProofKey` for the operator's session-bound
 * `device_id`.
 *
 * Elevation is the challenge → sign → verify flow against the session plane:
 *   `requestStepUpOptions(deviceId)` → `P256Signer.signChallenge(privateKey,
 *   challenge)` → `client.verifyStepUp({ challenge_id, signature })`.
 * A grant is narrowed to the capability it was raised for when the caller names
 * one, so a grant taken for `kyber.command.pause` does not authorise
 * `kyber.tenant.raw.read`.
 *
 * READ-ONLY posture: the only non-GET calls here are proof-key *enrollment*
 * (attestation, not a governed action) and step-up *verify* (raises the
 * session's authentication strength; it dispatches nothing and mutates no
 * platform state). This app never issues a command.
 */
import * as SecureStore from 'expo-secure-store';

import { P256Signer } from '@aether/mobile-core';

import { client } from './client';

// Separate SecureStore namespace from `kyber.kyber.operator_token` (which the
// wrapper in `client.ts` namespaces with a `kyber.` prefix). These keys are the
// attestation plane's own.
const PRIVATE_KEY_STORE_KEY = 'kyber.step_up_private_key';
const PROOF_KEY_ID_STORE_KEY = 'kyber.step_up_proof_key_id';

/** The algorithm the proof-key route validates (base64url SPKI ECDSA P-256). */
const KEY_ALGORITHM = 'ES256';

/** Informational label carried on the registration audit event. */
const KEY_LABEL = 'kyber-mobile';

/** Raw expo-secure-store surface, mirroring `client.ts`'s wrapper shape. */
interface SecretStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  delete(key: string): Promise<void>;
}

const secretStore: SecretStore = {
  get: (key) => SecureStore.getItemAsync(key),
  set: (key, value) => SecureStore.setItemAsync(key, value),
  delete: (key) => SecureStore.deleteItemAsync(key),
};

/** The key material this install holds. `publicKey` is null only on a cold
 * start when the stored private key's public half cannot be re-derived yet. */
interface KeyMaterial {
  privateKey: string;
  publicKey: string | null;
}

// The public key can be re-derived from the private key deterministically; some
// SDK builds expose that directly. Keep the pair in memory for the process
// lifetime so signing never re-reads the keystore.
let cachedMaterial: KeyMaterial | null = null;

type DerivingP256Signer = typeof P256Signer & {
  /** Deterministic private→public derivation when this SDK build exposes it. */
  derivePublicKey?: (privateKey: string) => string;
};

function maybeDerivePublicKey(privateKey: string): string | null {
  const derive = (P256Signer as DerivingP256Signer).derivePublicKey;
  return typeof derive === 'function' ? derive(privateKey) : null;
}

/** Load the private key (generating + persisting it on first run), and the
 * public half when it can be derived or is still cached in memory. */
async function loadKeyMaterial(): Promise<KeyMaterial> {
  if (cachedMaterial !== null) return cachedMaterial;
  const privateKey = await secretStore.get(PRIVATE_KEY_STORE_KEY);
  if (privateKey !== null) {
    const publicKey = maybeDerivePublicKey(privateKey);
    cachedMaterial = { privateKey, publicKey };
    return cachedMaterial;
  }
  const pair = P256Signer.generateP256KeyPair();
  await secretStore.set(PRIVATE_KEY_STORE_KEY, pair.privateKey);
  cachedMaterial = { privateKey: pair.privateKey, publicKey: pair.publicKey };
  return cachedMaterial;
}

/**
 * Re-enroll with a fresh pair. Used only when re-registration is required and
 * the stored key's public half cannot be recovered — the backend's per-device
 * upsert replaces the old key in place, and the fresh private key is what the
 * signer will use, so the pair stays consistent. The stale registration marker
 * is cleared so enrollment always runs after regeneration.
 */
async function regenerateKeyMaterial(): Promise<KeyMaterial & { publicKey: string }> {
  const pair = P256Signer.generateP256KeyPair();
  await secretStore.set(PRIVATE_KEY_STORE_KEY, pair.privateKey);
  await secretStore.delete(PROOF_KEY_ID_STORE_KEY);
  cachedMaterial = { privateKey: pair.privateKey, publicKey: pair.publicKey };
  return { privateKey: pair.privateKey, publicKey: pair.publicKey };
}

/** Outcome of {@link ensureProofKey}. */
export interface AttestationReady {
  device_id: string;
  proof_key_id: string;
  /** False when a fresh proof key was enrolled just now. */
  already_registered: boolean;
}

/**
 * Ensure a proof key exists for this install's session-bound device: generate
 * the keypair if needed, then register the public key unless the stored
 * registration marker is still live on the server. Throws on a session with no
 * bound device or a failed enrollment.
 */
export async function ensureProofKey(): Promise<AttestationReady> {
  const material = await loadKeyMaterial();
  const session = await client.getSession();
  const device_id = session.device_id;
  if (!device_id) {
    throw new Error('Step-up requires a device-bound session; no device is bound to this session.');
  }

  const proofKeys = await client.listProofKeys();
  const storedId = await secretStore.get(PROOF_KEY_ID_STORE_KEY);
  if (
    storedId !== null &&
    proofKeys.some((key) => key.proof_key_id === storedId && key.device_id === device_id)
  ) {
    return { device_id, proof_key_id: storedId, already_registered: true };
  }

  let publicKey = material.publicKey;
  if (publicKey === null) {
    const fresh = await regenerateKeyMaterial();
    publicKey = fresh.publicKey;
  }
  const registered = await client.registerProofKey({
    device_id,
    public_key: publicKey,
    algorithm: KEY_ALGORITHM,
    label: KEY_LABEL,
  });
  await secretStore.set(PROOF_KEY_ID_STORE_KEY, registered.proof_key_id);
  return { device_id, proof_key_id: registered.proof_key_id, already_registered: false };
}

/** The step-up state carried on the session / digest (`{ fresh, grant_id, expires_at }`). */
export interface StepUpState {
  fresh: boolean;
  grant_id: string | null;
  expires_at: string | null;
}

/** Read the live step-up state from the current session (null when absent). */
export async function getStepUpState(): Promise<StepUpState | null> {
  const session = await client.getSession();
  return session.step_up ?? null;
}

/** Result of {@link elevate} — a structured outcome, never a thrown error. */
export interface ElevationResult {
  ok: boolean;
  grant_id?: string;
  capability_id?: string | null;
  expires_at?: string;
  error?: string;
}

/**
 * Run the device-bound step-up flow end to end: enroll the proof key if needed,
 * request an authenticator challenge, sign it with the persisted private key,
 * and verify the assertion to raise the session. A grant narrowed to
 * `capabilityId` is requested when one is named. Returns a structured result
 * so screens can render success / failure without try/catch plumbing.
 */
export async function elevate(capabilityId?: string): Promise<ElevationResult> {
  try {
    const ready = await ensureProofKey();
    const options = await client.requestStepUpOptions(ready.device_id, capabilityId);
    const material = await loadKeyMaterial();
    const signature = P256Signer.signChallenge(material.privateKey, options.challenge);
    const result = await client.verifyStepUp({
      challenge_id: options.challenge_id,
      signature,
      capability_id: capabilityId,
      reason: 'kyber-mobile governed action step-up',
    });
    return {
      ok: true,
      grant_id: result.grant_id,
      capability_id: result.capability_id,
      expires_at: result.expires_at,
    };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
