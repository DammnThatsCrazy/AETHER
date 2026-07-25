import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  WebAuthnCancelledError,
  WebAuthnUnsupportedError,
  isWebAuthnSupported,
  performRegistration,
  toCreationOptions,
} from './webauthn';
import {
  makeRegistrationOptions,
  stubWebAuthn,
  stubWebAuthnUnsupported,
} from '@kyber/test/kyber-auth-doubles';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('WebAuthn enrolment', () => {
  it('decodes backend base64url options into binary creation options', () => {
    stubWebAuthn();
    const options = toCreationOptions(makeRegistrationOptions());
    expect(options.challenge).toBeInstanceOf(Uint8Array);
    expect(options.user.id).toBeInstanceOf(Uint8Array);
    expect(options.rp).toEqual({ id: 'kyber.test', name: 'Kyber' });
    expect(options.pubKeyCredParams[0]).toEqual({ type: 'public-key', alg: -7 });
  });

  it('calls navigator.credentials.create and returns a base64url attestation', async () => {
    const credentials = stubWebAuthn();
    const payload = await performRegistration(makeRegistrationOptions());

    expect(credentials.create).toHaveBeenCalledTimes(1);
    expect(payload.credential_id).toBe('cred_test_001');
    expect(payload.client_data_json).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(payload.attestation_object).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(payload.transports).toEqual(['internal']);
  });

  it('fails loudly on an unsupported browser — no silent fallback', async () => {
    stubWebAuthnUnsupported();
    expect(isWebAuthnSupported()).toBe(false);
    await expect(performRegistration(makeRegistrationOptions())).rejects.toBeInstanceOf(
      WebAuthnUnsupportedError,
    );
  });

  it('reports a dismissed prompt as cancelled, not as success', async () => {
    stubWebAuthn({
      create: vi.fn(async (): Promise<unknown> => {
        throw new DOMException('denied', 'NotAllowedError');
      }),
    });
    await expect(performRegistration(makeRegistrationOptions())).rejects.toBeInstanceOf(
      WebAuthnCancelledError,
    );
  });

  it('treats a null credential as cancelled', async () => {
    stubWebAuthn({ create: vi.fn(async () => null) });
    await expect(performRegistration(makeRegistrationOptions())).rejects.toBeInstanceOf(
      WebAuthnCancelledError,
    );
  });
});
