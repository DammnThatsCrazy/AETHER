/**
 * Persistent session banners.
 *
 * Same contract as the shared mock-mode banner in `@aether/ui`: purely
 * presentational, `role="status"`, data-attributes for tests, rendered above
 * the app chrome.
 * These surface backend session facts that change what the operator is allowed
 * to do — an operator should never discover a restricted session by getting a
 * silent 403 on a button click.
 *
 * Dismissal is deliberate: conditions that *block* work (restricted, revoked,
 * step-up required, active tenant scope) cannot be dismissed. A device pending
 * approval while the session is otherwise usable can be.
 */

import { useState, type ReactNode } from 'react';
import { cn } from '@aether/ui';
import { useKyberDevice, useKyberScope, useKyberSession, useKyberStepUp, formatCountdown } from './hooks';
import { describePurpose } from './scope-client';

type BannerTone = 'danger' | 'warning' | 'info';

const toneStyles: Record<BannerTone, string> = {
  danger: 'border-danger/40 bg-danger/10 text-danger',
  warning: 'border-warning/40 bg-warning/10 text-warning',
  info: 'border-info/40 bg-info/10 text-info',
};

interface SessionBannerProps {
  readonly tone: BannerTone;
  readonly label: string;
  readonly testId: string;
  readonly children: ReactNode;
  readonly onDismiss?: (() => void) | undefined;
  readonly action?: ReactNode;
}

export function SessionBanner({
  tone,
  label,
  testId,
  children,
  onDismiss,
  action,
}: SessionBannerProps) {
  return (
    <div
      role="status"
      data-testid={testId}
      data-session-banner={testId}
      className={cn(
        'flex flex-wrap items-center gap-x-2 gap-y-1 border-b px-4 py-1.5 text-xs font-mono',
        toneStyles[tone],
      )}
    >
      <span className="font-semibold uppercase tracking-wide">{label}</span>
      <span className="text-text-secondary">{children}</span>
      {action}
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label={`Dismiss ${label}`}
          className="ml-auto text-text-muted hover:text-text-primary"
        >
          ✕
        </button>
      )}
    </div>
  );
}

/** Session is `restricted` — identity is proven but the device is not trusted yet. */
export function RestrictedSessionBanner() {
  const { isRestricted } = useKyberSession();
  const { isPendingApproval, isBound } = useKyberDevice();
  if (!isRestricted) return null;
  return (
    <SessionBanner tone="warning" label="⚠ Restricted session" testId="banner-restricted-session">
      {isPendingApproval
        ? 'This device is registered but still awaiting approval from another operator. Reads are limited and mutations are refused until it is approved.'
        : isBound
          ? 'This device is not approved for this environment. Reads are limited and mutations are refused.'
          : 'No trusted device is bound to this session. Enrol this device under Security → Devices to lift the restriction.'}
    </SessionBanner>
  );
}

/** Session is `risk_limited` — the backend narrowed authority mid-session. */
export function RiskLimitedSessionBanner() {
  const { isRiskLimited, riskReasons } = useKyberSession();
  if (!isRiskLimited) return null;
  return (
    <SessionBanner tone="danger" label="⛔ Risk-limited session" testId="banner-risk-limited">
      The backend has narrowed this session&apos;s authority
      {riskReasons.length > 0 ? `: ${riskReasons.join(', ')}` : '.'} Higher action
      classes will be refused until the risk clears.
    </SessionBanner>
  );
}

/** Session is `revoked` / `expired` / `locked`. */
export function TerminatedSessionBanner() {
  const { isRevoked, isExpired, isLocked } = useKyberSession();
  if (!isRevoked && !isExpired && !isLocked) return null;
  const what = isRevoked ? 'revoked' : isExpired ? 'expired' : 'locked';
  return (
    <SessionBanner tone="danger" label="⛔ Session ended" testId="banner-session-terminated">
      This session is {what}. Sign in again to continue; anything still on screen
      is stale.
    </SessionBanner>
  );
}

/** A device is bound but not approved, while the session is otherwise usable. */
export function UnapprovedDeviceBanner() {
  const [dismissed, setDismissed] = useState(false);
  const { isBound, isApproved, isPendingApproval, isRevoked } = useKyberDevice();
  const { isRestricted } = useKyberSession();
  // The restricted banner already says this, louder.
  if (isRestricted || !isBound || isApproved || dismissed) return null;
  return (
    <SessionBanner
      tone="warning"
      label="● Unapproved device"
      testId="banner-unapproved-device"
      onDismiss={() => setDismissed(true)}
    >
      {isRevoked
        ? 'This device grant was revoked or suspended. Re-enrol it to regain device-bound authority.'
        : isPendingApproval
          ? 'This device is awaiting approval from another operator.'
          : 'This device does not hold an approved grant for this environment.'}
    </SessionBanner>
  );
}

/** Backend is asking for a WebAuthn step-up before higher-authority actions. */
export function StepUpRequiredBanner() {
  const { isRequired, isSteppedUp, isSupported, state, error, stepUp } = useKyberStepUp();
  if (!isRequired || isSteppedUp) return null;
  return (
    <SessionBanner
      tone="warning"
      label="⚑ Step-up required"
      testId="banner-step-up-required"
      action={
        isSupported ? (
          <button
            type="button"
            onClick={() => void stepUp()}
            disabled={state === 'challenging' || state === 'verifying'}
            className="rounded border border-current px-2 py-0.5 text-[11px] hover:bg-warning/20 disabled:opacity-50"
          >
            {state === 'challenging' || state === 'verifying' ? 'Verifying…' : 'Verify now'}
          </button>
        ) : null
      }
    >
      {isSupported
        ? (error ?? 'The backend requires a fresh authenticator verification before this action class.')
        : 'This browser has no platform authenticator, so step-up cannot be completed here. Use an enrolled device.'}
    </SessionBanner>
  );
}

/** Active tenant scope, with a live countdown to expiry. */
export function ActiveScopeBanner() {
  const { scope, isActive, msRemaining, isExpiring } = useKyberScope();
  if (!isActive || scope === null) return null;
  return (
    <SessionBanner
      tone={isExpiring ? 'warning' : 'info'}
      label="◉ Tenant scope active"
      testId="banner-active-scope"
    >
      Viewing <strong className="text-inherit">{scope.tenant_id}</strong> for{' '}
      <strong className="text-inherit">{describePurpose(scope.purpose)}</strong>
      {scope.ticket_reference !== null && <> ({scope.ticket_reference})</>} · disclosure L
      {scope.disclosure_level} · expires in{' '}
      <span data-testid="scope-countdown" className="tabular-nums">
        {formatCountdown(msRemaining)}
      </span>
    </SessionBanner>
  );
}

/**
 * All session banners in precedence order. Mount once, high in the tree,
 * directly beneath the mock-mode banner.
 */
export function KyberSessionBanners() {
  return (
    <>
      <TerminatedSessionBanner />
      <RiskLimitedSessionBanner />
      <RestrictedSessionBanner />
      <StepUpRequiredBanner />
      <UnapprovedDeviceBanner />
      <ActiveScopeBanner />
    </>
  );
}
