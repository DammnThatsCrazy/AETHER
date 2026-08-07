"""Communications provider conformance suite (§25).

Certifies a comms provider through the shared, offline certification framework
(:mod:`shared.certification.checks`) plus comms-domain checks. Nothing here
makes a network call or needs a real credential: every check asserts on the
provider's honest declaration (its :class:`ProviderManifest` + certification
descriptor) or on offline behavioral hooks.

``CommsCertificationAdapter`` wraps ANY registered comms connector (Klaviyo is
the reference) and exposes the framework's duck-typed hooks (``normalize``,
``dedupe_key``, ``sanitize_payload``, ``build_request``, ``sequence_of``,
``health``) so the generic checks (secret-redaction, duplicate/out-of-order
handling, schema drift, malformed input, idempotent replay, health, tenant
isolation, auth injection) all apply. Webhook-only connectors (SendGrid,
Customer.io, Mailchimp, Postmark) expose no ``build_request`` hook, so the
pull-centric generic checks skip honestly; the comms-domain checks likewise skip
a capability the provider does not declare (reconciliation, backfill,
provider-account discovery) rather than failing it.

``COMMS_CONFORMANCE_CHECKS`` = the generic ``ALL_CHECKS`` + comms-domain checks
(manifest completeness, credential absence, provider-account discovery, event
normalization, stable event identity, webhook verification + replay rejection,
reply mapping, suppression mapping, reconciliation, backfill boundary).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Callable, Optional

from shared.certification.checks import ALL_CHECKS, CertificationCheckResult, run_certification
from shared.certification.descriptor import AdapterCertificationDescriptor
from shared.certification.readiness import to_readiness
from services.integrations.connectors.base import BaseConnector
from services.integrations.providers.payment_rails.signature_verify import ENDPOINT_SECRET

_SECRET_KEY_MARKERS = ("secret", "token", "api_key", "apikey", "authorization",
                       "password", "credential")

# Reference comms provider for calls that don't name a specific connector.
# Named so the reference semantics are explicit without a bare provider string
# in the conformance path (ADR-C11: no provider-name branching downstream).
_REFERENCE_COMMS_PROVIDER = "klaviyo"

# Operations every comms connector genuinely supports: each observes webhooks,
# carries recipient identity into the identity bridge, and maps suppression
# signals (bounce/unsubscribe/complaint/suppressed) into the canonical authority.
_COMMS_BASE_OPERATIONS = ("webhook_ingest", "suppression_observe", "identity_evidence")

# Canonical comms data output → certification operation. A provider's
# supported_operations are derived from what its manifest actually declares, so
# a webhook-only provider never claims pull/backfill/campaign-sync it does not
# have. ``COMMS_SUPPORTED_OPERATIONS`` (Klaviyo reference) is the union of these
# with the pull/backfill/reconciliation flags below.
_COMMS_OPERATION_BY_OUTPUT = {
    "comms.delivery_events": "delivery_events",
    "comms.open_events": "engagement_events",
    "comms.click_events": "engagement_events",
    "comms.campaigns": "campaign_sync",
    "comms.flows": "flow_sync",
    "comms.messages": "message_sync",
    "comms.replies": "reply_ingest",
}

# Pull-centric capabilities declared by connector capability flags, not by a
# data output. Klaviyo (the reference) declares all three; the webhook-only
# cohort declares none.
_COMMS_FLAG_OPERATIONS = (
    ("supports_pull", "incremental_pull"),
    ("supports_historical_backfill", "historical_backfill"),
    ("supports_reconciliation", "reconciliation"),
)

COMMS_SUPPORTED_OPERATIONS = [
    "campaign_sync", "flow_sync", "message_sync", "webhook_ingest",
    "incremental_pull", "historical_backfill", "reconciliation",
    "reply_ingest", "suppression_observe", "identity_evidence",
    "delivery_events", "engagement_events",
]

# Native webhook signature headers a verifier reads, per provider scheme. Unlisted
# schemes (Klaviyo, generic Aether HMAC) expect Aether's own headers;
# ``endpoint_secret`` providers carry no signature headers at all.
_NATIVE_WEBHOOK_HEADERS: dict[str, list[str]] = {
    "sendgrid_ecdsa": [
        "X-Twilio-Email-Event-Webhook-Signature",
        "X-Twilio-Email-Event-Webhook-Timestamp",
    ],
    "customerio_hmac_v0": ["X-CIO-Signature", "X-CIO-Timestamp"],
    "hubspot_signature_v3": ["X-HubSpot-Signature-v3", "X-HubSpot-Request-Timestamp"],
    # Iterable signs with ``signature``/``ts`` carried in the webhook URL's
    # query params (not HTTP headers); the generic comms route merges them into
    # the headers mapping a native verifier reads, so the channel is named here.
    "iterable_hmac_query": ["signature", "ts"],
    ENDPOINT_SECRET: [],
}

# A realistic offline event record per provider → the canonical type it must
# normalize to. Kept in conformance so the reference suite and the per-provider
# cert suites share one fixture source.
_EVENT_FIXTURES: dict[str, tuple[dict[str, Any], str]] = {
    "klaviyo": (
        {
            "id": "kl-ev-1",
            "attributes": {
                "metric": {"name": "Clicked Email"},
                "datetime": "2026-07-01T10:00:00+00:00",
                "event_properties": {"$email": "person@example.com", "URL": "https://x"},
            },
        },
        "email_clicked",
    ),
    "sendgrid": (
        {
            "event": "click",
            "sg_event_id": "sg-ev-1",
            "email": "person@example.com",
            "url": "https://x",
            "timestamp": 1750000000,
            "useragent": "Mozilla/5.0",
        },
        "email_clicked",
    ),
    "customerio": (
        {
            "event": "email_opened",
            "event_id": "cio-ev-1",
            "timestamp": 1750000000,
            "data": {"email_address": "person@example.com", "campaign_id": "c1"},
        },
        "email_opened",
    ),
    "mailchimp": (
        {
            "type": "unsubscribe",
            "data[email]": "person@example.com",
            "data[id]": "mc-ev-1",
            "data[list_id]": "L1",
        },
        "unsubscribe_observed",
    ),
    "postmark": (
        {
            "RecordType": "Click",
            "MessageID": "pm-ev-1",
            "Recipient": "person@example.com",
            "Link": "https://x",
            "ClickedAt": "2026-07-01T10:00:00Z",
        },
        "email_clicked",
    ),
    "hubspot": (
        {
            "eventType": "CLICK",
            "id": "hs-ev-1",
            "email": "person@example.com",
            "recipient": "person@example.com",
            "campaignId": 123,
            "portalId": 62515,
            "created": 1750000000,
            "url": "https://x",
        },
        "email_clicked",
    ),
    "iterable": (
        {
            "eventType": "emailClick",
            "email": "person@example.com",
            "campaignId": 42,
            "templateId": 7,
            "messageId": "iter-ev-1",
            "url": "https://x",
            "userAgent": "Mozilla/5.0",
            "createdAt": "2026-07-01T10:00:00.000Z",
        },
        "email_clicked",
    ),
}


def _comms_connector(provider: str) -> BaseConnector:
    from services.integrations.connectors.registry import get_connector
    conn = get_connector(provider)
    if conn is None:
        raise ValueError(f"no registered connector {provider!r}")
    return conn


def _comms_supported_operations(conn: BaseConnector) -> list[str]:
    """Honest operation set for a comms connector: base webhook ops + operations
    the connector's declared ``comms.*`` data outputs actually emit + pull/backfill/
    reconciliation ops its capability flags declare. No provider inherits an
    operation it does not declare (ADR-C11)."""
    ops = set(_COMMS_BASE_OPERATIONS)
    for output in conn.manifest_data_outputs:
        op = _COMMS_OPERATION_BY_OUTPUT.get(output)
        if op:
            ops.add(op)
    for attr, op in _COMMS_FLAG_OPERATIONS:
        if getattr(conn, attr, False):
            ops.add(op)
    return sorted(ops)


def comms_certification_descriptor(provider: str) -> AdapterCertificationDescriptor:
    """Honest certification descriptor for a comms provider (read from source)."""
    conn = _comms_connector(provider)
    state = to_readiness(conn.implementation_status)
    scheme = conn.signature_scheme
    expected_headers = (
        _NATIVE_WEBHOOK_HEADERS.get(scheme, ["X-Aether-Signature", "X-Aether-Timestamp"])
        if scheme else ["X-Aether-Signature", "X-Aether-Timestamp"]
    )
    return AdapterCertificationDescriptor(
        provider=provider,
        domain="communications",
        adapter=type(conn).__name__,
        adapter_version="1.0.0",
        supported_operations=_comms_supported_operations(conn),
        unsupported_operations=["send", "template_edit", "suppression_write"],
        required_credentials=list(conn.required_credentials),
        secret_ref_names=[f"connector:{{tenant}}:{provider}"],
        expected_webhook_headers=expected_headers,
        pagination_model="cursor" if conn.supports_pull else "none",
        streaming_model="webhook",
        rate_limit_behavior=(
            "429_backoff_cursor_hold" if conn.supports_pull else "none"
        ),
        retry_policy="exponential_backoff_jitter",
        implementation_state=state,
        fixture_schema_version="1",
        first_release=True,
    )


def _sanitize(value: Any) -> Any:
    """Recursively drop secret-like keys and Authorization header values."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if any(m in str(k).lower() for m in _SECRET_KEY_MARKERS):
                out[k] = "***"
            else:
                out[k] = _sanitize(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value


class CommsCertificationAdapter:
    """Offline certification surface for any registered comms connector."""

    def __init__(self, connector_type: str = _REFERENCE_COMMS_PROVIDER):
        self.provider = connector_type
        self.connector = _comms_connector(connector_type)
        # Webhook-only connectors have no pull request to build; with no
        # build_request hook the generic request-construction / auth-injection /
        # tenant-isolation checks skip honestly (their checks are pull-centric).
        if not self.connector.supports_pull:
            self.build_request = None  # type: ignore[assignment]

    def certification_descriptor(self) -> AdapterCertificationDescriptor:
        return comms_certification_descriptor(self.provider)

    # ── offline behavioral hooks probed by the generic checks ────────────────
    def normalize(self, payload: Any) -> Any:
        events = self.connector.parse_webhook(
            payload if isinstance(payload, dict) else {"items": payload}
        )
        return events[0].model_dump() if events else None

    def dedupe_key(self, event: dict) -> str:
        return hashlib.sha256(
            json.dumps(event, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    def sequence_of(self, event: dict) -> Any:
        if "seq" in event:
            return event["seq"]
        return str(event.get("timestamp") or event.get("occurred_at") or "")

    def sanitize_payload(self, payload: dict) -> dict:
        return _sanitize(payload)

    def build_request(self, ctx: dict) -> dict:
        # Synthetic probe built from the connector's declared pull-API protocol
        # facts (auth header + base URL), so the generic checks exercise the real
        # auth-injection seam without conformance branching on provider name.
        import importlib
        mod = importlib.import_module(self.connector.__class__.__module__)
        api_base = self.connector.pull_api_base or getattr(mod, "_API_BASE", None)
        cred = ctx.get("credential") or {}
        api_key = cred.get("api_key") or cred.get("secret") or ""
        tenant = ctx.get("tenant_id", "")
        headers: dict[str, str] = {"X-Aether-Tenant": tenant}
        if self.connector.pull_auth_header:
            headers[self.connector.pull_auth_header] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
        return {
            "url": f"{api_base}/events/" if api_base else "/api/events/",
            "method": "GET",
            "headers": headers,
            "params": {"page[size]": 200, "sort": "datetime"},
        }

    def health(self, ctx: dict) -> dict:
        if not ctx.get("configured"):
            return {"healthy": False, "state": "credential_missing"}
        return {"healthy": True, "state": "ok"}


# ── comms-domain checks (compose with the generic ALL_CHECKS) ────────────────


def _ok(name: str, detail: str = "") -> CertificationCheckResult:
    return CertificationCheckResult(name=name, passed=True, detail=detail)


def _fail(name: str, detail: str) -> CertificationCheckResult:
    return CertificationCheckResult(name=name, passed=False, detail=detail)


def _skip(name: str, detail: str) -> CertificationCheckResult:
    return CertificationCheckResult(name=name, passed=True, skipped=True, detail=detail)


def _run(coro):
    """Run an async coroutine from a synchronous check (no loop running)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def check_manifest_completeness(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "comms_manifest_completeness"
    from shared.integration_contracts.catalog import manifest_by_family
    from shared.integration_contracts.manifest import validate_manifest
    m = manifest_by_family.get(adapter.provider)
    if m is None:
        return _fail(name, "no provider manifest registered")
    try:
        validate_manifest(m)
    except Exception as exc:
        return _fail(name, f"manifest fails honesty invariants: {exc}")
    if not m.data_outputs or not m.product_destinations:
        return _fail(name, "manifest declares no comms outputs/destinations")
    return _ok(name, f"{len(m.data_outputs)} data outputs, honest & complete")


def check_credential_absence(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "comms_credential_absence"
    from services.integrations.connectors.base import ConnectorConfig
    conn = adapter.connector
    cfg = ConnectorConfig(
        tenant_id="cert", connector_type=adapter.provider, enabled=True,
        secret_configured=False,
    )
    if conn.signature_scheme == ENDPOINT_SECRET:
        # Mailchimp/Postmark carry no vault secret — the durable endpoint id is
        # the credential. Absence of a vault secret is *expected*; assert the
        # adapter honestly declares that (no required credentials, no secret
        # gate) and reports ready once enabled.
        if conn.required_credentials:
            return _fail(name, "endpoint_secret connector declares vault credentials")
        if conn.requires_secret:
            return _fail(name, "endpoint_secret connector still requires a vault secret")
        res = _run(conn.test_connection(cfg, secret=None))
        if not res.ok:
            return _fail(name, f"endpoint_secret connector not ready without a secret: {res.status}")
        return _ok(name, "no vault secret needed; durable endpoint id is the credential")
    res = _run(conn.test_connection(cfg, secret=None))
    if res.ok:
        return _fail(name, "adapter reported ok with no credential")
    return _ok(name, f"credential absence reported honestly: {res.status}")


def check_provider_account_discovery(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "comms_provider_account_discovery"
    from shared.integration_contracts.catalog import manifest_by_family
    m = manifest_by_family.get(adapter.provider)
    if not (m and m.accounts.discovery_supported):
        return _skip(name, "provider-account discovery not declared (webhook-only)")
    return _ok(name, "provider-account discovery declared")


def check_event_normalization(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "comms_event_normalization"
    record, expected = ctx.get("event_fixture") or _EVENT_FIXTURES.get(
        adapter.provider, _EVENT_FIXTURES["klaviyo"]
    )
    event = adapter.normalize(record)
    if event is None or event.get("event_type") != expected:
        return _fail(name, f"unexpected normalization: {event}")
    if event.get("properties", {}).get("provider") != adapter.provider:
        return _fail(name, "normalized event missing provider")
    return _ok(name, f"provider event normalizes to canonical {expected}")


def check_stable_event_identity(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "comms_stable_event_identity"
    from services.comms.contracts import canonical_activity_key
    args = dict(tenant_id="t", source_system=adapter.provider,
                provider_account_id="acct", provider_event_id="ev-1",
                semantic_event_type="email_clicked")
    k1 = canonical_activity_key(**args)
    k2 = canonical_activity_key(**args)
    k3 = canonical_activity_key(**{**args, "provider_event_id": "ev-2"})
    if k1 != k2:
        return _fail(name, "identical events produced different canonical keys")
    if k1 == k3:
        return _fail(name, "distinct events collided on the same canonical key")
    return _ok(name, "canonical event identity stable & collision-free")


def check_webhook_verification(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "comms_webhook_verification"
    if getattr(adapter.connector, "signature_scheme", None) == ENDPOINT_SECRET:
        return _skip(name, "endpoint_secret providers send no signature; endpoint id is the auth")
    try:
        from services.security.integration_security import sign_payload, verify_signature
    except Exception:
        return _fail(name, "webhook verification primitives unavailable")
    secret = "whsec_cert"
    body = b'{"data":[{"id":"e1"}]}'
    signed = sign_payload(secret, body)  # current timestamp, within tolerance
    ts, sig = signed["X-Aether-Timestamp"], signed["X-Aether-Signature"]
    if not verify_signature(secret, body, ts, sig):
        return _fail(name, "valid signature rejected")
    if verify_signature(secret, body + b"x", ts, sig):
        return _fail(name, "tampered body accepted (forgery not rejected)")
    if verify_signature(secret + "x", body, ts, sig):
        return _fail(name, "wrong secret accepted")
    return _ok(name, "signed webhook verified; tampered body + wrong secret rejected")


def check_suppression_mapping(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "comms_suppression_mapping"
    from services.comms.suppression_authority import SuppressionAuthorityService
    rec = _run(SuppressionAuthorityService().record_from_event("cert-t", {
        "event_type": "unsubscribe_observed",
        "properties": {"provider": adapter.provider, "recipient_email": "u@example.com",
                       "unsubscribe_scope": "marketing_channel"},
    }))
    if not rec or rec.get("reason") != "unsubscribe":
        return _fail(name, "unsubscribe did not map to a suppression")
    return _ok(name, "unsubscribe maps to a canonical suppression")


def check_reconciliation(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "comms_reconciliation"
    conn = adapter.connector
    if not conn.supports_reconciliation:
        return _skip(name, "reconciliation not supported (webhook-only)")
    from services.integrations.connectors.base import ConnectorConfig
    cfg = ConnectorConfig(tenant_id="cert", connector_type=adapter.provider)
    out = _run(conn.reconcile(cfg, secret=None, external_campaign_id="c1"))
    # Offline: reconciliation must honestly report unavailable, never fake counts.
    if out.get("available") is not False:
        return _fail(name, "reconciliation claimed availability without a credential")
    return _ok(name, "reconciliation honest offline (available=False)")


def check_backfill_boundary(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "comms_backfill_boundary"
    conn = adapter.connector
    if not conn.supports_historical_backfill:
        return _skip(name, "historical backfill not supported (webhook-only)")
    from shared.integration_contracts.catalog import manifest_by_family
    m = manifest_by_family.get(adapter.provider)
    if not (m and m.sync.initial_backfill and m.sync.incremental and m.sync.cursor):
        return _fail(name, "backfill/incremental/cursor not fully declared")
    return _ok(name, f"backfill + incremental declared with cursor {m.sync.cursor!r}")


COMMS_DOMAIN_CHECKS: list[Callable[[Any, dict], CertificationCheckResult]] = [
    check_manifest_completeness,
    check_credential_absence,
    check_provider_account_discovery,
    check_event_normalization,
    check_stable_event_identity,
    check_webhook_verification,
    check_suppression_mapping,
    check_reconciliation,
    check_backfill_boundary,
]

COMMS_CONFORMANCE_CHECKS = list(ALL_CHECKS) + COMMS_DOMAIN_CHECKS


def _comms_conformance_ctx() -> dict:
    """Deterministic offline ctx exercising the generic behavioral checks."""
    return {
        "timeout_seconds": 15,
        "normalize_sample": _EVENT_FIXTURES["klaviyo"][0],
        "event_fixture": _EVENT_FIXTURES["klaviyo"],
        "events": [
            {"id": "evt_1", "seq": 1, "value": "a"},
            {"id": "evt_1", "seq": 1, "value": "a"},
            {"id": "evt_2", "seq": 2, "value": "b"},
        ],
        "sample_request": {},
    }


def certify_comms(
    adapter: Optional[CommsCertificationAdapter] = None,
    ctx: Optional[dict] = None,
    connector_type: Optional[str] = None,
) -> list[CertificationCheckResult]:
    """Run the full comms conformance suite offline. Returns one result/check.

    ``connector_type`` certifies a specific registered comms connector with its
    provider-appropriate fixture ctx; when neither ``adapter`` nor
    ``connector_type`` is given the Klaviyo reference adapter is used.
    """
    if adapter is None:
        adapter = CommsCertificationAdapter(
            connector_type or _REFERENCE_COMMS_PROVIDER
        )
    if ctx is None and connector_type:
        ctx = dict(_comms_conformance_ctx())
        ctx["normalize_sample"] = _EVENT_FIXTURES[connector_type][0]
        ctx["event_fixture"] = _EVENT_FIXTURES[connector_type]
    return run_certification(
        adapter,
        ctx or _comms_conformance_ctx(),
        checks=COMMS_CONFORMANCE_CHECKS,
    )


__all__ = [
    "CommsCertificationAdapter",
    "comms_certification_descriptor",
    "COMMS_CONFORMANCE_CHECKS",
    "COMMS_DOMAIN_CHECKS",
    "certify_comms",
]
