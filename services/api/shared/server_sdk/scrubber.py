"""Sensitive field scrubbing for server-side event payloads."""

from __future__ import annotations

_SENSITIVE_PATTERNS: frozenset[str] = frozenset({
    "password", "passwd", "secret", "token", "api_key", "apikey", "access_key",
    "auth", "credential", "private_key", "ssn", "sin", "tax_id", "passport",
    "card_number", "cvv", "cvc", "expiry", "pin", "passphrase", "form_value",
    "clipboard", "keystroke", "raw_message", "message_body", "email_body",
    "totp_secret", "otp_secret", "recovery_code", "client_secret", "webhook_secret",
    "iban", "routing_number", "account_number", "bank_account", "swift_bic",
    "date_of_birth", "dob", "mother_maiden", "biometric", "health_record",
    "medical", "salary", "income", "credit_score", "social_security",
})


def _is_sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(p in normalized for p in _SENSITIVE_PATTERNS)


def scrub_sensitive_fields(obj: object) -> object:
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if _is_sensitive(k) else scrub_sensitive_fields(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [scrub_sensitive_fields(item) for item in obj]
    return obj
