/**
 * Small, dependency-free field validators shared by the Olympus Labs waitlist
 * and demo-request forms. Kept intentionally minimal — shape validation only,
 * no network round trip, no external validation service.
 */

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** True when `value` has the basic local@domain.tld shape. Not a mailbox check. */
export function isValidEmail(value: string): boolean {
  return EMAIL_PATTERN.test(value);
}

/** Required-field message helper: returns an error string, or undefined when present. */
export function requiredError(value: string, message: string): string | undefined {
  return value.trim().length === 0 ? message : undefined;
}

/** Required + shape validation for an email field. Returns an error message, or
 * undefined when the trimmed value is a plausible email address. */
export function emailFieldError(value: string, emptyMessage: string, invalidMessage: string): string | undefined {
  const trimmed = value.trim();
  if (trimmed.length === 0) return emptyMessage;
  if (!isValidEmail(trimmed)) return invalidMessage;
  return undefined;
}
