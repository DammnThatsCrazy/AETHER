// Sensitive field scrubbing for server-side event payloads.
// Mirrors the recursive logic in the backend ingestion validator.

const SENSITIVE_PATTERNS = [
  'password', 'passwd', 'secret', 'token', 'api_key', 'apikey', 'access_key',
  'auth', 'credential', 'private_key', 'ssn', 'sin', 'tax_id', 'passport',
  'card_number', 'cvv', 'cvc', 'expiry', 'pin', 'passphrase', 'form_value',
  'clipboard', 'keystroke', 'raw_message', 'message_body', 'email_body',
  'totp_secret', 'otp_secret', 'recovery_code', 'client_secret', 'webhook_secret',
  'iban', 'routing_number', 'account_number', 'bank_account', 'swift_bic',
  'date_of_birth', 'dob', 'mother_maiden', 'biometric', 'health_record',
  'medical', 'salary', 'income', 'credit_score', 'social_security',
];

function isSensitiveKey(key: string): boolean {
  const normalized = key.toLowerCase().replace(/[-\s]/g, '_');
  return SENSITIVE_PATTERNS.some((p) => normalized.includes(p));
}

function scrubValue(value: unknown): unknown {
  if (value === null || value === undefined || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(scrubValue);
  return scrubObject(value as Record<string, unknown>);
}

function scrubObject(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    out[k] = isSensitiveKey(k) ? '[REDACTED]' : scrubValue(v);
  }
  return out;
}

export function scrubSensitiveFields(properties: Record<string, unknown>): Record<string, unknown> {
  return scrubObject(properties);
}
