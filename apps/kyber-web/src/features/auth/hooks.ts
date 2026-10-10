/**
 * Small composable readers over the backend-authoritative auth context.
 *
 * Every value returned here originated in a backend response. None of it is
 * derived from a token, a claim, or a local role table. Treat all of it as
 * ADVISORY display state: it decides what the UI shows, never what the system
 * permits.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type {
  AccessScope,
  AuthenticationStrength,
  CapabilityId,
  DeviceApprovalState,
  KyberPrincipalView,
  KyberSessionStatus,
  KyberSessionView,
} from '@kyber/types';
import { base64UrlToBytes, bytesToBase64Url } from '@kyber/lib/auth/encoding';
import { describeAuthError } from '@kyber/lib/auth';
import { useAuth, type KyberAuthStatus } from './auth-context';
import { requestStepUpOptions, verifyStepUp } from './session-client';

// ── Session ──────────────────────────────────────────────────────────────────

export interface KyberSessionSnapshot {
  readonly session: KyberSessionView | null;
  readonly status: KyberSessionStatus | null;
  readonly authStatus: KyberAuthStatus;
  readonly isRestricted: boolean;
  readonly isRiskLimited: boolean;
  readonly isRevoked: boolean;
  readonly isExpired: boolean;
  readonly isLocked: boolean;
  readonly isHealthy: boolean;
  readonly riskReasons: readonly string[];
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly refresh: () => Promise<void>;
}

export function useKyberSession(): KyberSessionSnapshot {
  const { session, principal, status, isLoading, error, refresh } = useAuth();
  // The principal carries the canonical session status; `session` adds detail.
  const sessionStatus = principal?.session_status ?? session?.status ?? null;
  return useMemo(
    () => ({
      session,
      status: sessionStatus,
      authStatus: status,
      isRestricted: sessionStatus === 'restricted',
      isRiskLimited: sessionStatus === 'risk_limited',
      isRevoked: sessionStatus === 'revoked',
      isExpired: sessionStatus === 'expired',
      isLocked: sessionStatus === 'locked',
      isHealthy: sessionStatus === 'active',
      riskReasons: session?.risk_reasons ?? [],
      isLoading,
      error,
      refresh,
    }),
    [session, sessionStatus, status, isLoading, error, refresh],
  );
}

// ── Principal ────────────────────────────────────────────────────────────────

export function useKyberPrincipal(): KyberPrincipalView | null {
  return useAuth().principal;
}

// ── Capabilities ─────────────────────────────────────────────────────────────

export interface KyberCapabilitySnapshot {
  readonly capabilities: readonly CapabilityId[];
  readonly roleTemplateIds: readonly string[];
  readonly maxActionClass: number;
  readonly maxDisclosure: number;
  readonly isLoading: boolean;
}

/**
 * The raw capability grant from the backend. An unauthenticated or still
 * loading principal grants NOTHING — the empty list is the safe default.
 */
export function useKyberCapabilities(): KyberCapabilitySnapshot {
  const { principal, isLoading } = useAuth();
  return useMemo(
    () => ({
      capabilities: principal?.capabilities ?? [],
      roleTemplateIds: principal?.role_template_ids ?? [],
      maxActionClass: principal?.max_action_class ?? 0,
      maxDisclosure: principal?.max_disclosure ?? 0,
      isLoading,
    }),
    [principal, isLoading],
  );
}

// ── Device binding ───────────────────────────────────────────────────────────

export interface KyberDeviceSnapshot {
  readonly deviceId: string | null;
  readonly approvalState: DeviceApprovalState | null;
  readonly isBound: boolean;
  readonly isApproved: boolean;
  readonly isPendingApproval: boolean;
  readonly isRevoked: boolean;
  readonly authenticationStrength: AuthenticationStrength;
  readonly mayApproveDevices: boolean;
}

export function useKyberDevice(): KyberDeviceSnapshot {
  const { principal, session } = useAuth();
  const deviceId = principal?.device_id ?? session?.device_id ?? null;
  const approvalState = principal?.device_approval_state ?? session?.device_approval_state ?? null;
  return useMemo(
    () => ({
      deviceId,
      approvalState,
      isBound: deviceId !== null,
      isApproved: approvalState === 'approved',
      isPendingApproval: approvalState === 'pending',
      isRevoked: approvalState === 'revoked' || approvalState === 'suspended',
      authenticationStrength: principal?.authentication_strength ?? 'none',
      mayApproveDevices: principal?.may_approve_devices ?? false,
    }),
    [deviceId, approvalState, principal],
  );
}

// ── Tenant access scope (with live countdown) ────────────────────────────────

export interface KyberScopeSnapshot {
  readonly scope: AccessScope | null;
  readonly isActive: boolean;
  readonly tenantId: string | null;
  readonly expiresAt: string | null;
  /** Milliseconds until expiry; null when the scope has no expiry or is absent. */
  readonly msRemaining: number | null;
  readonly isExpiring: boolean;
  readonly refresh: () => Promise<void>;
}

/** Ticks once a second only while a scope with an expiry is active. */
function useCountdown(expiresAt: string | null): number | null {
  const target = useMemo(() => {
    if (expiresAt === null) return null;
    const parsed = Date.parse(expiresAt);
    return Number.isNaN(parsed) ? null : parsed;
  }, [expiresAt]);

  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (target === null) return undefined;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, [target]);

  if (target === null) return null;
  return Math.max(0, target - now);
}

export function useKyberScope(): KyberScopeSnapshot {
  const { principal, refresh } = useAuth();
  const scope = principal?.active_scope ?? null;
  const expiresAt = scope?.expires_at ?? null;
  const msRemaining = useCountdown(expiresAt);
  const expired = msRemaining !== null && msRemaining <= 0;
  const isActive = scope !== null && scope.status === 'active' && !expired;

  // When the countdown hits zero the local view of tenant access must clear
  // itself and re-ask the backend rather than keep showing a dead scope.
  useEffect(() => {
    if (scope !== null && expired) void refresh();
  }, [scope, expired, refresh]);

  return useMemo(
    () => ({
      scope: isActive ? scope : null,
      isActive,
      tenantId: isActive ? (scope?.tenant_id ?? null) : null,
      expiresAt,
      msRemaining,
      isExpiring: msRemaining !== null && msRemaining > 0 && msRemaining <= 120_000,
      refresh,
    }),
    [scope, isActive, expiresAt, msRemaining, refresh],
  );
}

/** `01:23:45` / `04:12` formatting for a countdown. */
export function formatCountdown(msRemaining: number | null): string {
  if (msRemaining === null) return '—';
  const total = Math.max(0, Math.floor(msRemaining / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return hours > 0 ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

// ── Step-up (WebAuthn assertion) ─────────────────────────────────────────────

export type StepUpState = 'idle' | 'unsupported' | 'challenging' | 'verifying' | 'satisfied' | 'error';

export interface KyberStepUpSnapshot {
  readonly state: StepUpState;
  readonly isSteppedUp: boolean;
  readonly isRequired: boolean;
  readonly expiresAt: string | null;
  readonly error: string | null;
  readonly isSupported: boolean;
  readonly stepUp: () => Promise<boolean>;
}

function isWebAuthnAvailable(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    typeof navigator.credentials?.get === 'function' &&
    typeof window.PublicKeyCredential !== 'undefined'
  );
}

export function useKyberStepUp(): KyberStepUpSnapshot {
  const { principal, session, refresh } = useAuth();
  const [state, setState] = useState<StepUpState>('idle');
  const [error, setError] = useState<string | null>(null);

  const isSteppedUp = principal?.authentication_strength === 'stepped_up';
  const isRequired = session?.step_up_required ?? false;
  const supported = isWebAuthnAvailable();

  const stepUp = useCallback(async (): Promise<boolean> => {
    if (!supported) {
      setState('unsupported');
      setError('This browser does not support the platform authenticator required for step-up.');
      return false;
    }
    setError(null);
    setState('challenging');
    try {
      const options = await requestStepUpOptions();
      const credential = (await navigator.credentials.get({
        publicKey: {
          challenge: base64UrlToBytes(options.challenge),
          ...(options.rpId === null ? {} : { rpId: options.rpId }),
          ...(options.timeout === null ? {} : { timeout: options.timeout }),
          userVerification:
            (options.userVerification as UserVerificationRequirement | null) ?? 'required',
          allowCredentials: options.allowCredentials.map((descriptor) => ({
            id: base64UrlToBytes(descriptor.id),
            type: 'public-key' as const,
          })),
        },
      })) as PublicKeyCredential | null;

      if (credential === null) {
        setState('error');
        setError('Step-up was dismissed.');
        return false;
      }

      const assertion = credential.response as AuthenticatorAssertionResponse;
      setState('verifying');
      await verifyStepUp({
        credential_id: credential.id,
        client_data_json: bytesToBase64Url(assertion.clientDataJSON),
        authenticator_data: bytesToBase64Url(assertion.authenticatorData),
        signature: bytesToBase64Url(assertion.signature),
        user_handle: assertion.userHandle ? bytesToBase64Url(assertion.userHandle) : null,
      });
      await refresh();
      setState('satisfied');
      return true;
    } catch (err) {
      setState('error');
      setError(describeAuthError(err));
      return false;
    }
  }, [supported, refresh]);

  return {
    state,
    isSteppedUp,
    isRequired,
    expiresAt: principal?.step_up_expires_at ?? session?.step_up_expires_at ?? null,
    error,
    isSupported: supported,
    stepUp,
  };
}
