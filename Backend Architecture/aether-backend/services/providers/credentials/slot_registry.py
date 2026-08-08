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
    "signing_private_key": dict(
        display_name="Signing private key",
        purpose="Sign proofs/claims; validated by deriving the public identity.",
        secret_type="signing_private_key",
        required_for=("proof_signing",),
        scope_policy="sign_only",
        needs_endpoint=False,
        validation_strategy="key_derivation_check",
        rotation_policy="replace",
        sensitive=True,
    ),
    "rpc_endpoint_pair": dict(
        display_name="RPC endpoint + key pair",
        purpose=(
            "Atomic JSON document {url, api_key, auth_mode} — one credential "
            "version is one endpoint+key pair, so a rotated endpoint can never "
            "mix with a stale key."
        ),
        secret_type="endpoint_keyed_url",
        required_for=("chain_verification", "connection_test"),
        scope_policy="read_only",
        needs_endpoint=False,
        validation_strategy="rpc_chain_probe",
        rotation_policy="replace",
        sensitive=True,
    ),
    "facilitator_api_key": dict(
        display_name="Facilitator API key",
        purpose="Authenticate verification calls to an external x402 facilitator.",
        secret_type="bearer_token",
        required_for=("payment_verification", "connection_test"),
        scope_policy="verify_only",
        needs_endpoint=True,
        validation_strategy="live_probe",
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


def _safe_host(url: str) -> str | None:
    """Return just the hostname of a provider base URL (never path/query)."""
    if not url:
        return None
    try:
        host = urlparse(url).hostname
    except (ValueError, TypeError):
        return None
    return f"host={host}; scheme=https; read_only" if host else None


# Static, server-owned slot-declaration sources beyond the payment adapters.
# Each module exposes ``declared_slots() -> {provider: (slot-dict, ...)}``.
# Listed modules MUST import — a missing source is a build error, never a
# silently smaller registry.
_STATIC_SOURCE_MODULES: tuple[str, ...] = (
    "services.rewards.signer_slots",
)


def _static_declarations() -> dict[str, tuple[dict, ...]]:
    import importlib

    merged: dict[str, tuple[dict, ...]] = {}
    for module_path in _STATIC_SOURCE_MODULES:
        module = importlib.import_module(module_path)
        for provider, slots in module.declared_slots().items():
            if provider in merged:
                raise ValueError(
                    f"provider {provider!r} declared by two static slot sources"
                )
            merged[provider] = slots
    return merged


@lru_cache(maxsize=1)
def build_slot_registry() -> dict[str, tuple[CredentialSlot, ...]]:
    """Merge ``{provider: (CredentialSlot, ...)}`` from every slot source.

    Sources: (1) the payment-rail adapters' own
    ``certification_descriptor().required_credentials`` (adapters stay the
    source of truth for which secrets they need); (2) static server-owned
    domain declarations (reward signing, x402/RPC). Provider names are
    globally unique across domains — a collision is a build error. Cached —
    all sources are static. Imported lazily so this module stays cheap and
    avoids an import cycle with the payment-rails package.
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

    for provider, slot_dicts in _static_declarations().items():
        if provider in registry:
            raise ValueError(
                f"static slot source redeclares adapter provider {provider!r}"
            )
        slots = []
        for spec in slot_dicts:
            spec = dict(spec)
            spec.pop("needs_endpoint", False)
            slots.append(
                CredentialSlot(
                    provider=provider,
                    environment="any",
                    endpoint_policy=spec.pop("endpoint_policy", None),
                    **spec,
                )
            )
        registry[provider] = tuple(slots)
    return registry


def providers_for_domain(domain: str) -> tuple[str, ...]:
    """Providers whose slots belong to ``domain`` (sorted, deterministic)."""
    return tuple(
        sorted(
            provider
            for provider, slots in build_slot_registry().items()
            if any(slot.domain == domain for slot in slots)
        )
    )


def slots_for(provider: str, environment: str | None = None) -> tuple[CredentialSlot, ...]:
    """All declared slots for ``provider`` (environment-agnostic templates).

    ``environment`` is accepted for symmetry with the version-level binding and
    to leave room for future per-environment slots; today every environment
    requires the same slot set.
    """
    return build_slot_registry().get(provider, ())


def get_slot(provider: str, slot_name: str, environment: str | None = None) -> CredentialSlot | None:
    """Return the declared slot, or ``None`` if the provider never declared it."""
    for slot in slots_for(provider, environment):
        if slot.slot_name == slot_name:
            return slot
    return None


def known_providers() -> tuple[str, ...]:
    """Providers that declare at least one credential slot."""
    return tuple(build_slot_registry().keys())


__all__ = [
    "CredentialSlot",
    "build_slot_registry",
    "providers_for_domain",
    "slots_for",
    "get_slot",
    "known_providers",
]
