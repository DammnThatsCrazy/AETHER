/**
 * Device grant API.
 *
 * Approval, suspension and revocation are backend decisions. In particular the
 * backend refuses self-approval — an operator cannot approve the device they
 * are currently sitting at. The UI surfaces that refusal verbatim rather than
 * pre-empting it, so the reason the operator reads is the reason the server
 * actually gave.
 */

import { KYBER_DEVICE_ENDPOINTS, requestJson, requestVoid } from '@kyber/lib/auth';
import type { DeviceProofChallenge, KyberDevice, WebAuthnRegistrationOptions } from '@kyber/types';
import { parseDevice, parseDevices, parseProofChallenge, parseRegistrationOptions } from '@kyber/features/auth/schemas';
import type { WebAuthnAttestationPayload } from './webauthn';

export async function fetchDevices(signal?: AbortSignal): Promise<KyberDevice[]> {
  return requestJson(KYBER_DEVICE_ENDPOINTS.list, parseDevices, { signal });
}

export interface RegistrationOptionsInput {
  readonly display_name: string;
  readonly platform: string;
  readonly browser: string;
  readonly user_agent: string;
}

export async function fetchRegistrationOptions(
  input: RegistrationOptionsInput,
): Promise<WebAuthnRegistrationOptions> {
  return requestJson(KYBER_DEVICE_ENDPOINTS.registrationOptions, parseRegistrationOptions, {
    method: 'POST',
    body: input,
  });
}

export interface RegistrationVerifyInput extends RegistrationOptionsInput {
  readonly attestation: WebAuthnAttestationPayload;
  /** SPKI base64url of the browser-local, non-extractable proof key. */
  readonly proof_public_key_spki: string;
}

export async function verifyRegistration(input: RegistrationVerifyInput): Promise<KyberDevice> {
  return requestJson(KYBER_DEVICE_ENDPOINTS.registrationVerify, parseDevice, {
    method: 'POST',
    body: input,
  });
}

export async function requestProofChallenge(): Promise<DeviceProofChallenge> {
  return requestJson(KYBER_DEVICE_ENDPOINTS.proofChallenge, parseProofChallenge, {
    method: 'POST',
    body: {},
  });
}

export interface ProofVerifyInput {
  readonly challenge_id: string;
  readonly signature: string;
}

export async function verifyProof(input: ProofVerifyInput): Promise<void> {
  await requestVoid(KYBER_DEVICE_ENDPOINTS.proofVerify, { method: 'POST', body: input });
}

export async function approveDevice(deviceId: string, reason: string): Promise<KyberDevice> {
  return requestJson(KYBER_DEVICE_ENDPOINTS.approve(deviceId), parseDevice, {
    method: 'POST',
    body: { reason },
  });
}

export async function suspendDevice(deviceId: string, reason: string): Promise<KyberDevice> {
  return requestJson(KYBER_DEVICE_ENDPOINTS.suspend(deviceId), parseDevice, {
    method: 'POST',
    body: { reason },
  });
}

export async function revokeDevice(deviceId: string, reason: string): Promise<KyberDevice> {
  return requestJson(KYBER_DEVICE_ENDPOINTS.revoke(deviceId), parseDevice, {
    method: 'POST',
    body: { reason },
  });
}

export async function renameDevice(deviceId: string, displayName: string): Promise<KyberDevice> {
  return requestJson(KYBER_DEVICE_ENDPOINTS.rename(deviceId), parseDevice, {
    method: 'POST',
    body: { display_name: displayName },
  });
}
