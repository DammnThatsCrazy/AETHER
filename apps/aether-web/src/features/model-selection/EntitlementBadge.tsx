/**
 * Entitlement display badge for the tenant model-selection feature (ADR-008 D4).
 *
 * Pure presentation: given a model + its server-authoritative entitlement
 * status, render the right badge. This component is never a decision source —
 * entitlement is resolved server-side and only displayed here. It never renders
 * credentials, and any reason string is sanitized so secret-shaped material
 * falls back to a generic message.
 */

export const GENERIC_ENTITLEMENT_REASON = 'Entitlement details unavailable.';

/** Secret-shaped markers that must never appear in rendered UI text. */
const SECRET_MARKERS = [
  'sk-',
  'pk_',
  'rk_live_',
  'whsec_',
  'AKIA',
  'Bearer ',
  'Authorization:',
  'X-Api-Key:',
  'password=',
  'secret=',
  'key=',
];

/** True when `value` looks like a credential or JWT payload fragment. */
function looksLikeSecret(value: string): boolean {
  const lowered = value.toLowerCase();
  if (SECRET_MARKERS.some((marker) => lowered.includes(marker.toLowerCase()))) {
    return true;
  }
  // JWT-shaped payload: three dot-separated segments where the middle is
  // base64url with a `{"` (decoded JSON object start) — cheap structural check.
  if (value.split('.').length >= 3 && value.includes('eyJ')) {
    return true;
  }
  return false;
}

/**
 * Sanitize an entitlement reason for display. Empty or secret-shaped reasons
 * fall back to {@link GENERIC_ENTITLEMENT_REASON}.
 */
export function sanitizeEntitlementReason(
  reason: string | null | undefined,
): string {
  if (!reason || !reason.trim()) {
    return GENERIC_ENTITLEMENT_REASON;
  }
  return looksLikeSecret(reason) ? GENERIC_ENTITLEMENT_REASON : reason;
}

export interface EntitlementBadgeProps {
  modelId: string;
  entitled: boolean;
  reason?: string | null;
}

export function EntitlementBadge({
  modelId,
  entitled,
  reason = null,
}: EntitlementBadgeProps) {
  const displayReason = !entitled ? sanitizeEntitlementReason(reason) : null;

  return (
    <div
      className="inline-flex items-center gap-2"
      role="status"
      data-testid="entitlement-badge"
      data-model-id={modelId}
      data-entitled={String(entitled)}
    >
      <span
        className={`status-badge inline-block rounded-full border px-2 py-0.5 text-xs ${
          entitled
            ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
            : 'bg-red-100 text-red-800 border-red-200'
        }`}
      >
        {entitled ? 'Entitled' : 'Not entitled'}
      </span>
      {displayReason !== null && (
        <span
          className="text-xs text-text-muted"
          title={displayReason}
          data-testid="entitlement-reason"
        >
          {displayReason}
        </span>
      )}
    </div>
  );
}

export default EntitlementBadge;
