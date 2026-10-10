/**
 * WebAuthn enrolment.
 *
 * Unsupported browsers fail LOUDLY. There is deliberately no password / OTP /
 * "skip for now" fallback: a device that cannot present an authenticator does
 * not get a device-bound session, and the operator is told exactly that.
 */

import { base64UrlToBytes, bytesToBase64Url } from '@kyber/lib/auth/encoding';
import type { WebAuthnRegistrationOptions } from '@kyber/types';

export class WebAuthnUnsupportedError extends Error {
  constructor(
    message = 'This browser does not support WebAuthn, so this device cannot be enrolled here.',
  ) {
    super(message);
    this.name = 'WebAuthnUnsupportedError';
  }
}

export class WebAuthnCancelledError extends Error {
  constructor(message = 'Device enrolment was dismissed before it completed.') {
    super(message);
    this.name = 'WebAuthnCancelledError';
  }
}

export function isWebAuthnSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    typeof navigator.credentials?.create === 'function' &&
    typeof window.PublicKeyCredential !== 'undefined'
  );
}

/** Decode the backend's base64url-encoded options into browser binary form. */
export function toCreationOptions(
  options: WebAuthnRegistrationOptions,
): PublicKeyCredentialCreationOptions {
  const authenticatorSelection: AuthenticatorSelectionCriteria = {
    userVerification: (options.userVerification as UserVerificationRequirement | null) ?? 'required',
  };
  if (options.residentKey !== null) {
    authenticatorSelection.residentKey = options.residentKey as ResidentKeyRequirement;
  }

  return {
    challenge: base64UrlToBytes(options.challenge) as unknown as BufferSource,
    rp: options.rp.id === null ? { name: options.rp.name } : { id: options.rp.id, name: options.rp.name },
    user: {
      id: base64UrlToBytes(options.user.id) as unknown as BufferSource,
      name: options.user.name,
      displayName: options.user.displayName,
    },
    pubKeyCredParams: options.pubKeyCredParams.map((param) => ({
      type: 'public-key' as const,
      alg: param.alg,
    })),
    ...(options.timeout === null ? {} : { timeout: options.timeout }),
    ...(options.attestation === null
      ? {}
      : { attestation: options.attestation as AttestationConveyancePreference }),
    excludeCredentials: options.excludeCredentials.map((descriptor) => ({
      id: base64UrlToBytes(descriptor.id) as unknown as BufferSource,
      type: 'public-key' as const,
    })),
    authenticatorSelection,
  };
}

export interface WebAuthnAttestationPayload {
  readonly credential_id: string;
  readonly client_data_json: string;
  readonly attestation_object: string;
  readonly transports: readonly string[];
}

/**
 * Run `navigator.credentials.create()` and return the attestation in the
 * base64url shape the backend expects.
 */
export async function performRegistration(
  options: WebAuthnRegistrationOptions,
): Promise<WebAuthnAttestationPayload> {
  if (!isWebAuthnSupported()) throw new WebAuthnUnsupportedError();

  let credential: PublicKeyCredential | null;
  try {
    credential = (await navigator.credentials.create({
      publicKey: toCreationOptions(options),
    })) as PublicKeyCredential | null;
  } catch (err) {
    if (err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'AbortError')) {
      throw new WebAuthnCancelledError();
    }
    if (err instanceof DOMException && err.name === 'NotSupportedError') {
      throw new WebAuthnUnsupportedError(
        'No authenticator on this device satisfies the required algorithms.',
      );
    }
    throw err;
  }

  if (credential === null) throw new WebAuthnCancelledError();

  const response = credential.response as AuthenticatorAttestationResponse;
  const transports =
    typeof response.getTransports === 'function' ? response.getTransports() : [];

  return {
    credential_id: credential.id,
    client_data_json: bytesToBase64Url(response.clientDataJSON),
    attestation_object: bytesToBase64Url(response.attestationObject),
    transports,
  };
}

/** Best-effort platform/browser labels so approvers know what they are approving. */
export function describeUserAgent(): { platform: string; browser: string; userAgent: string } {
  if (typeof navigator === 'undefined') {
    return { platform: 'unknown', browser: 'unknown', userAgent: '' };
  }
  const ua = navigator.userAgent ?? '';
  const platform =
    /Mac/i.test(ua) ? 'macOS'
    : /Windows/i.test(ua) ? 'Windows'
    : /Android/i.test(ua) ? 'Android'
    : /iPhone|iPad|iPod/i.test(ua) ? 'iOS'
    : /Linux/i.test(ua) ? 'Linux'
    : 'unknown';
  const browser =
    /Edg\//i.test(ua) ? 'Edge'
    : /OPR\//i.test(ua) ? 'Opera'
    : /Chrome\//i.test(ua) ? 'Chrome'
    : /Firefox\//i.test(ua) ? 'Firefox'
    : /Safari\//i.test(ua) ? 'Safari'
    : 'unknown';
  return { platform, browser, userAgent: ua };
}
