/** Canonical validation for ISO instants accepted by shareable UI state. */
export function isValidInstant(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && Number.isFinite(Date.parse(value));
}

/** Validate an IANA time-zone identifier through the platform formatter. */
export function isValidTimeZone(value: string): boolean {
  if (value.includes('..') || value.startsWith('/')) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: value }).format();
    return true;
  } catch {
    return false;
  }
}
