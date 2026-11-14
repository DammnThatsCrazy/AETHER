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

// Exact keys that are non-secret contract references even though they contain a
// sensitive substring ('auth'). `authorizationId` names an approval record; redacting
// it collapses distinct approvals into one value downstream. Credentials such as
// `authorization`, `authToken` or `auth_header` still match the patterns above.
const NON_SECRET_REFERENCE_KEYS = new Set(['authorizationid', 'authorization_id', 'authorizationref', 'authorization_ref']);

function isSensitiveKey(key: string, value: unknown): boolean {
  const normalized = key.toLowerCase().replace(/[-\s]/g, '_');
  if (NON_SECRET_REFERENCE_KEYS.has(normalized) && typeof value === 'string') return false;
  return SENSITIVE_PATTERNS.some((p) => normalized.includes(p));
}

// Real payloads are shallow; the depth cap keeps a pathological (or adversarial)
// object from exhausting the call stack. Cycles are handled by the ancestor path.
const MAX_SCRUB_DEPTH = 32;

function scrubValue(value: unknown, depth: number, path: WeakSet<object>): unknown {
  if (value === null || value === undefined || typeof value !== 'object') return value;
  if (depth >= MAX_SCRUB_DEPTH) return '[TRUNCATED]';
  if (path.has(value as object)) return '[CYCLE]'; // back-reference to an ancestor
  path.add(value as object);
  try {
    if (Array.isArray(value)) return value.map((item) => scrubValue(item, depth + 1, path));
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = isSensitiveKey(k, v) ? '[REDACTED]' : scrubValue(v, depth + 1, path);
    }
    return out;
  } finally {
    path.delete(value as object);
  }
}

export function scrubSensitiveFields(properties: Record<string, unknown>): Record<string, unknown> {
  return scrubValue(properties, 0, new WeakSet<object>()) as Record<string, unknown>;
}
