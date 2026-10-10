/**
 * Device-trust hooks.
 *
 * Three states the UI must distinguish and never conflate:
 *   1. NO KEY        — this browser profile has never enrolled. Offer enrolment.
 *   2. KEY + REVOKED — a proof key exists but the backend grant is gone
 *                      (revoked/suspended/expired, or the device row is
 *                      missing entirely). The stale key is cleared and
 *                      re-enrolment offered; we do not silently retry proofs.
 *   3. KEY + ACTIVE  — prove possession on demand.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KyberDevice } from '@kyber/types';
import { KyberAuthError, describeAuthError } from '@kyber/lib/auth';
import { useAuth, useKyberDevice } from '@kyber/features/auth';
import {
  approveDevice,
  fetchDevices,
  fetchRegistrationOptions,
  renameDevice,
  requestProofChallenge,
  revokeDevice,
  suspendDevice,
  verifyProof,
  verifyRegistration,
} from './device-client';
import {
  ProofKeyUnsupportedError,
  clearProofKey,
  ensureProofKey,
  exportPublicKeySpki,
  isProofKeySupported,
  loadProofKey,
  signProofChallenge,
} from './proof-key';
import {
  WebAuthnUnsupportedError,
  describeUserAgent,
  isWebAuthnSupported,
  performRegistration,
} from './webauthn';

// ── Device list ──────────────────────────────────────────────────────────────

export interface DeviceListState {
  readonly devices: readonly KyberDevice[];
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly isForbidden: boolean;
  readonly refresh: () => Promise<void>;
}

export function useDeviceList(): DeviceListState {
  const [devices, setDevices] = useState<readonly KyberDevice[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isForbidden, setIsForbidden] = useState(false);
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const next = await fetchDevices();
      if (!mountedRef.current) return;
      setDevices(next);
      setError(null);
      setIsForbidden(false);
    } catch (err) {
      if (!mountedRef.current) return;
      setIsForbidden(err instanceof KyberAuthError && err.isForbidden);
      setError(describeAuthError(err));
    } finally {
      if (mountedRef.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();
    return () => {
      mountedRef.current = false;
    };
  }, [refresh]);

  return { devices, isLoading, error, isForbidden, refresh };
}

// ── Device administration (approve / suspend / revoke / rename) ──────────────

export interface DeviceAdminState {
  readonly pendingDeviceId: string | null;
  readonly error: string | null;
  readonly clearError: () => void;
  readonly approve: (deviceId: string, reason: string) => Promise<boolean>;
  readonly suspend: (deviceId: string, reason: string) => Promise<boolean>;
  readonly revoke: (deviceId: string, reason: string) => Promise<boolean>;
  readonly rename: (deviceId: string, displayName: string) => Promise<boolean>;
}

export function useDeviceAdmin(onChanged: () => void | Promise<void>): DeviceAdminState {
  const [pendingDeviceId, setPendingDeviceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (deviceId: string, operation: () => Promise<KyberDevice>): Promise<boolean> => {
      setPendingDeviceId(deviceId);
      setError(null);
      try {
        await operation();
        await onChanged();
        return true;
      } catch (err) {
        // Surface the backend's own refusal text — e.g. self-approval, which is
        // rejected server-side and must be reported in the server's words.
        setError(describeAuthError(err));
        return false;
      } finally {
        setPendingDeviceId(null);
      }
    },
    [onChanged],
  );

  return {
    pendingDeviceId,
    error,
    clearError: () => setError(null),
    approve: (deviceId, reason) => run(deviceId, () => approveDevice(deviceId, reason)),
    suspend: (deviceId, reason) => run(deviceId, () => suspendDevice(deviceId, reason)),
    revoke: (deviceId, reason) => run(deviceId, () => revokeDevice(deviceId, reason)),
    rename: (deviceId, displayName) => run(deviceId, () => renameDevice(deviceId, displayName)),
  };
}

// ── Enrolment ────────────────────────────────────────────────────────────────

export type EnrolmentState =
  | 'idle'
  | 'unsupported'
  | 'requesting-options'
  | 'awaiting-authenticator'
  | 'binding-proof-key'
  | 'verifying'
  | 'enrolled'
  | 'error';

export interface DeviceEnrolmentState {
  readonly state: EnrolmentState;
  readonly error: string | null;
  readonly device: KyberDevice | null;
  readonly isSupported: boolean;
  readonly unsupportedReason: string | null;
  readonly enrol: (displayName: string) => Promise<KyberDevice | null>;
  readonly reset: () => void;
}

export function useDeviceEnrolment(onEnrolled?: () => void | Promise<void>): DeviceEnrolmentState {
  const { refresh: refreshSession } = useAuth();
  const [state, setState] = useState<EnrolmentState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [device, setDevice] = useState<KyberDevice | null>(null);

  const webauthnOk = isWebAuthnSupported();
  const proofKeyOk = isProofKeySupported();
  const isSupported = webauthnOk && proofKeyOk;
  const unsupportedReason = isSupported
    ? null
    : !webauthnOk
      ? 'This browser has no WebAuthn authenticator, so it cannot be enrolled as a trusted device.'
      : 'This browser cannot store a non-extractable device key (WebCrypto or IndexedDB unavailable, e.g. private browsing).';

  const enrol = useCallback(
    async (displayName: string): Promise<KyberDevice | null> => {
      if (!isSupported) {
        setState('unsupported');
        setError(unsupportedReason);
        return null;
      }
      setError(null);
      const agent = describeUserAgent();
      const descriptor = {
        display_name: displayName.trim() || `${agent.browser} on ${agent.platform}`,
        platform: agent.platform,
        browser: agent.browser,
        user_agent: agent.userAgent,
      };

      try {
        setState('requesting-options');
        const options = await fetchRegistrationOptions(descriptor);

        setState('awaiting-authenticator');
        const attestation = await performRegistration(options);

        // Re-enrolment: drop any stale local key before minting a new one so a
        // half-finished previous attempt cannot leave an orphaned key behind.
        setState('binding-proof-key');
        await clearProofKey();
        const proofKey = await ensureProofKey();
        const spki = await exportPublicKeySpki(proofKey.publicKey);

        setState('verifying');
        const enrolled = await verifyRegistration({
          ...descriptor,
          attestation,
          proof_public_key_spki: spki,
        });

        setDevice(enrolled);
        setState('enrolled');
        await refreshSession();
        if (onEnrolled) await onEnrolled();
        return enrolled;
      } catch (err) {
        if (err instanceof WebAuthnUnsupportedError || err instanceof ProofKeyUnsupportedError) {
          setState('unsupported');
        } else {
          setState('error');
        }
        setError(describeAuthError(err));
        // Never leave a local key bound to a registration the backend rejected.
        await clearProofKey().catch(() => undefined);
        return null;
      }
    },
    [isSupported, unsupportedReason, refreshSession, onEnrolled],
  );

  return {
    state,
    error,
    device,
    isSupported,
    unsupportedReason,
    enrol,
    reset: () => {
      setState('idle');
      setError(null);
      setDevice(null);
    },
  };
}

// ── Proof of possession ──────────────────────────────────────────────────────

export type ProofKeyState = 'checking' | 'unsupported' | 'missing' | 'present' | 'revoked';

export interface DeviceProofState {
  readonly keyState: ProofKeyState;
  readonly isProving: boolean;
  readonly error: string | null;
  readonly lastProvedAt: number | null;
  readonly prove: () => Promise<boolean>;
  readonly forget: () => Promise<void>;
  readonly recheck: () => Promise<void>;
}

export function useDeviceProof(): DeviceProofState {
  const { isRevoked, isBound } = useKyberDevice();
  const [keyState, setKeyState] = useState<ProofKeyState>('checking');
  const [isProving, setIsProving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastProvedAt, setLastProvedAt] = useState<number | null>(null);

  const recheck = useCallback(async () => {
    if (!isProofKeySupported()) {
      setKeyState('unsupported');
      return;
    }
    const record = await loadProofKey();
    if (record === null) {
      setKeyState('missing');
      return;
    }
    // A key that outlived its backend grant is worthless and misleading.
    setKeyState(isRevoked || !isBound ? 'revoked' : 'present');
  }, [isRevoked, isBound]);

  useEffect(() => {
    void recheck();
  }, [recheck]);

  const prove = useCallback(async (): Promise<boolean> => {
    setError(null);
    const record = await loadProofKey();
    if (record === null) {
      setKeyState('missing');
      setError('No device proof key is present in this browser. Enrol this device first.');
      return false;
    }
    setIsProving(true);
    try {
      const challenge = await requestProofChallenge();
      const signature = await signProofChallenge(challenge.challenge, record.privateKey);
      await verifyProof({ challenge_id: challenge.challenge_id, signature });
      setLastProvedAt(Date.now());
      setKeyState('present');
      return true;
    } catch (err) {
      if (err instanceof KyberAuthError && (err.isForbidden || err.status === 404 || err.status === 410)) {
        setKeyState('revoked');
      }
      setError(describeAuthError(err));
      return false;
    } finally {
      setIsProving(false);
    }
  }, []);

  const forget = useCallback(async () => {
    await clearProofKey();
    setKeyState('missing');
    setLastProvedAt(null);
  }, []);

  return useMemo(
    () => ({ keyState, isProving, error, lastProvedAt, prove, forget, recheck }),
    [keyState, isProving, error, lastProvedAt, prove, forget, recheck],
  );
}
