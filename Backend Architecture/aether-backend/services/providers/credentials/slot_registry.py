"""Server-owned credential-slot registry.

A provider is not a single undifferentiated key. Each provider declares one or
more *slots* — e.g. a ``webhook_signing_secret`` used only to verify inbound
webhook signatures and a separate ``server_api_key`` used only for read-only
polling — and each slot rotates, validates, and revokes independently.

The slot set is **derived** from the payment-rail adapters' own
``certification_descriptor().required_credentials`` (the adapters are the source
of truth for *which* secrets they need) and enriched with a small server-owned
augmentation map that supplies the operational policy for each slot name
(secret type, what it is required for, how it validates, how it rotates). This
guarantees the registry and the adapters cannot disagree: adding a required
credential to an adapter automatically surfaces a slot here.

Clients may only ever supply values for server-declared slots. The API validates
every client-provided ``slot_name`` against this registry and rejects anything
it did not declare.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from services.providers.credentials.schema import PAYMENTS_DOMAIN


@dataclass(frozen=True)
class CredentialSlot:
    """One server-declared credential slot for a provider.

    ``environment`` is ``"any"`` on the *template*: sandbox and live need the
    same slot names, and the concrete environment is bound at the credential
    *version* level (and into the encryption context). ``endpoint_policy`` is a
    safe hostname/scheme hint for slots whose secret authenticates calls to a
    provider host — never a full URL that could carry credentials.
    """

    provider: str
    domain: str
    slot_name: str
    display_name: str
    purpose: str
    environment: str
    required: bool
    secret_type: str
    required_for: tuple[str, ...]
    scope_policy: str
    endpoint_policy: str | None
    validation_strategy: str
    rotation_policy: str
    sensitive: bool

    def public_dict(self) -> dict:
        """Body-safe descriptor for API responses — declaration only, no value."""
        return {
            "provider": self.provider,
            "domain": self.domain,
            "slot_name": self.slot_name,
            "display_name": self.display_name,
            "purpose": self.purpose,
            "environment": self.environment,
            "required": self.required,
            "secret_type": self.secret_type,
            "required_for": list(self.required_for),
            "scope_policy": self.scope_policy,
            "endpoint_policy": self.endpoint_policy,
            "validation_strategy": self.validation_strategy,
            "rotation_policy": self.rotation_policy,
            "sensitive": self.sensitive,
        }


# ── Server-owned augmentation: policy for each known slot NAME ────────────────
# Adapters only *name* their required credentials; the operational policy for
# each name lives here (server-owned, not client-supplied). The endpoint host is
# filled per-adapter from the adapter's declared poll base URL.
_SLOT_AUGMENTATION: dict[str, dict] = {
    "webhook_signing_secret": dict(
        display_name="Webhook signing secret",
        purpose="Verify the HMAC signature of inbound provider webhooks.",
        secret_type="hmac_secret",
        required_for=("webhook_verification",),
        scope_policy="verify_only",
        needs_endpoint=False,
        validation_strategy="signature_selfcheck",
        rotation_policy="overlap",
        sensitive=True,
    ),
    "onramp_api_key": dict(
        display_name="Onramp server API key",
        purpose="Authenticate read-only polling of onramp transactions.",
        secret_type="bearer_token",
        required_for=("status_poll", "backfill", "connection_test"),
        scope_policy="read_only",
        needs_endpoint=True,
        validation_strategy="live_probe",
        rotation_policy="replace",
        sensitive=True,
    ),
    "server_api_key": dict(
        display_name="Server API key",
        purpose="Authenticate read-only polling of provider transactions.",
        secret_type="bearer_token",
        required_for=("status_poll", "backfill", "connection_test"),
        scope_policy="read_only",
        needs_endpoint=True,
        validation_strategy="live_probe",
        rotation_policy="replace",
        sensitive=True,
    ),
    "api_key": dict(
        display_name="API key",
        purpose="Authenticate read-only polling of provider records.",
        secret_type="bearer_token",
        required_for=("status_poll", "backfill", "connection_test"),
        scope_policy="read_only",
        needs_endpoint=True,
        validation_strategy="live_probe",
        rotation_policy="replace",
        sensitive=True,
    ),
    "webhook_secret": dict(
        display_name="Webhook secret",
        purpose="Verify the HMAC signature of inbound provider webhooks.",
        secret_type="hmac_secret",
        required_for=("webhook_verification",),
        scope_policy="verify_only",
        needs_endpoint=False,
        validation_strategy="signature_selfcheck",
        rotation_policy="overlap",
        sensitive=True,
    ),
    "signer_key": dict(
        display_name="Signer key",
        purpose="Sign outbound payloads (payouts, claims); key reference only.",
        secret_type="signing_key",
        required_for=("payout_signing", "payload_signing"),
        scope_policy="sign_only",
        needs_endpoint=False,
        validation_strategy="signature_selfcheck",
        rotation_policy="replace",
        sensitive=True,
    ),
    "signing_key": dict(
        display_name="Signing key",
        purpose="Signing key reference for message/transaction signing.",
        secret_type="signing_key",
        required_for=("payload_signing",),
        scope_policy="sign_only",
        needs_endpoint=False,
        validation_strategy="signature_selfcheck",
        rotation_policy="replace",
        sensitive=True,
    ),
    "token_ref": dict(
        display_name="OAuth token reference",
        purpose="OAuth access/refresh token reference for authorized API access.",
        secret_type="oauth_token",
        required_for=("authorized_api_access",),
        scope_policy="authorized_scopes",
        needs_endpoint=True,
        validation_strategy="token_probe",
        rotation_policy="replace",
        sensitive=True,
    ),
}

# Fallback policy for a slot name an adapter declares that we have not enriched.
# Conservative: sensitive, read-only, replace-on-rotate, no self-check.
_DEFAULT_AUGMENTATION: dict = dict(
    display_name="Provider credential",
    purpose="Authenticate read-only observation of provider activity.",
    secret_type="bearer_token",
    required_for=("connection_test",),
    scope_policy="read_only",
    needs_endpoint=False,
    validation_strategy="live_probe",
    rotation_policy="replace",
    sensitive=True,
)


# ── Domain slot declarations ────────────────────────────────────────────────
# Payment-rail slots are DERIVED from the adapters (see ``build_slot_registry``).
# The additional credentialed domains have no adapter to derive from yet, so
# their slots are DECLARED here by the server — no live values, no concrete
# provider hosts, just the operational policy each slot will enforce. Each entry
# is ``(slot_name, overrides)`` merged over the ``_SLOT_AUGMENTATION`` entry of
# that name. ``environment`` stays ``"any"`` on the template: sandbox and live
# bind the concrete value at the credential-version level.
_DOMAIN_SLOT_DECLARATIONS: dict[str, tuple[tuple[str, dict], ...]] = {
    "stablecoin_rpc": (
        (
            "api_key",
            dict(
                purpose=(
                    "Authenticate read-only polling of a stablecoin RPC/API "
                    "endpoint (balance, transfer history)."
                ),
                required_for=("rpc_call", "status_poll", "connection_test"),
            ),
        ),
    ),
    "derivatives": (
        (
            "api_key",
            dict(
                purpose=(
                    "Authenticate read-only market-data access to a derivatives "
                    "venue (order book, positions, funding)."
                ),
                required_for=("market_data", "status_poll", "connection_test"),
            ),
        ),
    ),
    "interop": (
        (
            "api_key",
            dict(
                purpose=(
                    "Authenticate read-only bridge/relayer API and RPC access "
                    "(transfer status, message relay)."
                ),
                required_for=("relay_status", "rpc_call", "connection_test"),
            ),
        ),
    ),
    "rewards": (
        (
            "signer_key",
            dict(
                purpose=(
                    "Sign reward payout payloads; a key REFERENCE slot, never "
                    "raw key material in a response."
                ),
            ),
        ),
        (
            "webhook_secret",
            dict(
                purpose="Verify inbound rewards-rail webhook signatures.",
            ),
        ),
    ),
    "x402": (
        (
            "api_key",
            dict(
                purpose="Authenticate to an x402 payment facilitator.",
            ),
        ),
        (
            "webhook_secret",
            dict(
                purpose="Verify inbound x402 facilitator webhook signatures.",
            ),
        ),
    ),
    "signing": (
        (
            "signing_key",
            dict(
                purpose=(
                    "Signing key reference for message/transaction signing; "
                    "the reference rotates without exposing key material."
                ),
            ),
        ),
    ),
    "webhook": (
        (
            "webhook_signing_secret",
            dict(
                purpose="Verify the HMAC signature of inbound provider webhooks.",
            ),
        ),
    ),
    "oauth": (
        (
            "token_ref",
            dict(
                purpose=(
                    "OAuth access/refresh token reference for authorized API "
                    "access; refresh rotates the token independently."
                ),
            ),
        ),
    ),
}


def _domain_slot(domain: str, slot_name: str, overrides: dict) -> CredentialSlot:
    """Build one domain-declaration slot from the shared slot augmentation."""
    aug = dict(_SLOT_AUGMENTATION.get(slot_name, _DEFAULT_AUGMENTATION))
    aug.update(overrides)
    needs_endpoint = aug.pop("needs_endpoint", False)
    endpoint_policy = aug.pop("endpoint_policy", None)
    if needs_endpoint and not endpoint_policy:
        # Declaration hint only — never a concrete host (no live values).
        endpoint_policy = "endpoint required; read_only"
    return CredentialSlot(
        provider=domain,
        domain=domain,
        slot_name=slot_name,
        display_name=aug["display_name"],
        purpose=aug["purpose"],
        environment="any",
        required=True,
        secret_type=aug["secret_type"],
        required_for=tuple(aug["required_for"]),
        scope_policy=aug["scope_policy"],
        endpoint_policy=endpoint_policy,
        validation_strategy=aug["validation_strategy"],
        rotation_policy=aug["rotation_policy"],
        sensitive=aug["sensitive"],
    )


@lru_cache(maxsize=1)
def _domain_slots_cache() -> dict[str, tuple[CredentialSlot, ...]]:
    """Cached domain -> declared slots (static declarations)."""
    return {
        domain: tuple(
            _domain_slot(domain, slot_name, overrides)
            for slot_name, overrides in declarations
        )
        for domain, declarations in _DOMAIN_SLOT_DECLARATIONS.items()
    }


def slots_for_domain(domain: str) -> tuple[CredentialSlot, ...]:
    """Declared credential slots for a credentialed *domain* (not a specific
    payment adapter). ``payments`` aggregates every payment-adapter slot; the
    additional domains resolve from the server-owned domain declarations.
    """
    if domain == PAYMENTS_DOMAIN:
        out: list[CredentialSlot] = []
        for provider_slots in build_slot_registry().values():
            out.extend(provider_slots)
        return tuple(out)
    return _domain_slots_cache().get(domain, ())


def declared_domains() -> tuple[str, ...]:
    """Every credentialed domain with at least one declared slot."""
    return tuple(sorted({PAYMENTS_DOMAIN, *_DOMAIN_SLOT_DECLARATIONS.keys()}))


def _safe_host(url: str) -> str | None:
    """Return just the hostname of a provider base URL (never path/query)."""
    if not url:
        return None
    try:
        host = urlparse(url).hostname
    except (ValueError, TypeError):
        return None
    return f"host={host}; scheme=https; read_only" if host else None


@lru_cache(maxsize=1)
def build_slot_registry() -> dict[str, tuple[CredentialSlot, ...]]:
    """Derive ``{provider: (CredentialSlot, ...)}`` from the payment adapters.

    Cached — the adapter descriptors are static. Imported lazily so this module
    stays cheap and avoids an import cycle with the payment-rails package.
    """
    from services.integrations.providers.payment_rails import ADAPTERS

    registry: dict[str, tuple[CredentialSlot, ...]] = {}
    for provider_name, entry in ADAPTERS.items():
        # ADAPTERS holds ready instances; tolerate a class too (import-safe, offline).
        adapter = entry() if isinstance(entry, type) else entry
        descriptor = adapter.certification_descriptor()
        endpoint_hint = _safe_host(getattr(adapter, "poll_base_url", ""))

        slots: list[CredentialSlot] = []
        for slot_name in descriptor.required_credentials:
            aug = dict(_SLOT_AUGMENTATION.get(slot_name, _DEFAULT_AUGMENTATION))
            needs_endpoint = aug.pop("needs_endpoint", False)
            slots.append(
                CredentialSlot(
                    provider=adapter.provider_name,
                    domain=getattr(descriptor, "domain", PAYMENTS_DOMAIN),
                    slot_name=slot_name,
                    environment="any",
                    required=True,
                    endpoint_policy=endpoint_hint if needs_endpoint else None,
                    **aug,
                )
            )
        registry[adapter.provider_name] = tuple(slots)
    return registry


def slots_for(provider: str, environment: str | None = None) -> tuple[CredentialSlot, ...]:
    """All declared slots for ``provider`` (environment-agnostic templates).

    Payment adapters resolve from the derived registry; a domain token (e.g.
    ``stablecoin_rpc``) resolves from the server-owned domain declarations.
    ``environment`` is accepted for symmetry with the version-level binding and
    to leave room for future per-environment slots; today every environment
    requires the same slot set.
    """
    registry = build_slot_registry()
    if provider in registry:
        return registry[provider]
    return slots_for_domain(provider)


def get_slot(provider: str, slot_name: str, environment: str | None = None) -> CredentialSlot | None:
    """Return the declared slot, or ``None`` if the provider never declared it."""
    for slot in slots_for(provider, environment):
        if slot.slot_name == slot_name:
            return slot
    return None


def known_providers() -> tuple[str, ...]:
    """Payment providers that declare at least one credential slot.

    Deliberately payment-adapter-scoped: the additional domain slots are served
    through ``slots_for_domain`` / ``declared_domains`` until those domains are
    wired as enableable providers by the integration pass.
    """
    return tuple(build_slot_registry().keys())


__all__ = [
    "CredentialSlot",
    "build_slot_registry",
    "declared_domains",
    "get_slot",
    "known_providers",
    "slots_for",
    "slots_for_domain",
]
