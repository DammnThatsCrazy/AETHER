"""First-release provider certification registry.

Declares the first-release provider scope as data and resolves each provider's
CURRENT, HONEST ``CredentialReadiness`` by reading the live adapter descriptors
from source (read-only imports). Where a domain adapter already carries an
``ImplementationStatus`` (interop, derivatives adapters) the state is mapped
through ``IMPLEMENTATION_STATUS_TO_READINESS``; where an adapter exists but
carries no formal status (payment rails, stablecoin-chain observers, the
Hyperliquid connector) the state is *derived* from honest evidence via
``ReadinessDimensions.derive`` — never assumed optimistic. Providers with no
implementation at all resolve to ``SCAFFOLDED``.

Everything here is pure and deterministic: no timestamps, no randomness, module
imports are cached, so ``build_capability_matrix()`` returns byte-identical
output across calls. A generator (owned elsewhere) renders it to a doc.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.certification.descriptor import AdapterCertificationDescriptor
from shared.certification.readiness import (
    CredentialReadiness,
    ReadinessDimensions,
    readiness_rank,
    to_readiness,
)

# Interop scope token -> concrete interop provider_id in the source registry.
_INTEROP_PROVIDER_IDS: dict[str, str] = {
    "layerzero": "layerzero_v2",
    "wormhole": "wormhole",
    "axelar": "axelar",
    "chainlink_ccip": "chainlink_ccip",
    "hyperlane": "hyperlane",
    "ibc": "ibc",
    "debridge": "debridge",
}

# Payment scope token -> (module, class) in payment_rails.
_PAYMENT_ADAPTERS: dict[str, tuple[str, str]] = {
    "privy": ("services.integrations.providers.payment_rails.privy", "PrivyAdapter"),
    "stripe_onramp": (
        "services.integrations.providers.payment_rails.stripe_onramp",
        "StripeOnrampAdapter",
    ),
    "coinbase": ("services.integrations.providers.payment_rails.coinbase", "CoinbaseAdapter"),
    "moonpay": ("services.integrations.providers.payment_rails.moonpay", "MoonPayAdapter"),
    "bridge": ("services.integrations.providers.payment_rails.bridge", "BridgeAdapter"),
}

# Stablecoin-chain scope token -> (module, verifier class, capabilities).
_STABLECOIN_OBSERVERS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "evm": (
        "services.stablecoins.rpc_observer",
        "StablecoinEVMReceiptVerifier",
        ("receipt_observation", "finality_confirmation"),
    ),
    "svm": (
        "services.stablecoins.solana_observer",
        "StablecoinSolanaTransactionVerifier",
        ("transaction_observation", "finality_confirmation"),
    ),
}


# Import failures observed while resolving adapters, keyed by "module:attr".
# A broken import must be distinguishable from an unimplemented provider: an
# entry here means the provider's SCAFFOLDED state is a resolution *failure*,
# not an honest absence. Healthy builds keep this empty; certification gates
# fail when it is not.
_IMPORT_ERRORS: dict[str, str] = {}


def _record_import_error(key: str, exc: Exception) -> None:
    _IMPORT_ERRORS[key] = f"{type(exc).__name__}: {exc}"


def import_errors() -> dict[str, str]:
    """Sorted copy of the adapter-resolution failures seen so far."""
    return dict(sorted(_IMPORT_ERRORS.items()))


def _import(module: str, attr: str) -> Optional[Any]:
    key = f"{module}:{attr}"
    try:
        mod = __import__(module, fromlist=[attr])
    except Exception as exc:
        _record_import_error(key, exc)
        return None
    value = getattr(mod, attr, None)
    if value is None:
        _IMPORT_ERRORS[key] = "AttributeError: attribute missing"
    else:
        _IMPORT_ERRORS.pop(key, None)
    return value


# ── per-domain resolvers ─────────────────────────────────────────────────────


def _resolve_interop() -> list[AdapterCertificationDescriptor]:
    descriptors: list[AdapterCertificationDescriptor] = []
    providers: dict[str, Any] = {}
    try:
        from services.interop.providers import INTEROP_PROVIDERS

        providers = INTEROP_PROVIDERS
    except Exception as exc:  # pragma: no cover
        _record_import_error("services.interop.providers:INTEROP_PROVIDERS", exc)
        providers = {}

    for token, provider_id in _INTEROP_PROVIDER_IDS.items():
        adapter = providers.get(provider_id)
        if adapter is not None:
            state = to_readiness(adapter.implementation_status)
            capabilities = list(getattr(adapter, "capabilities", ()) or ())
            adapter_name = provider_id
        else:  # pragma: no cover - registry present in this repo
            state = CredentialReadiness.SCAFFOLDED
            capabilities = []
            adapter_name = provider_id
        descriptors.append(
            AdapterCertificationDescriptor(
                provider=token,
                domain="interop",
                adapter=adapter_name,
                adapter_version="1.0.0" if provider_id == "layerzero_v2" else "0.1.0",
                supported_operations=capabilities,
                required_endpoints=["per_network_json_rpc"],
                pagination_model="none",
                streaming_model="none",
                implementation_state=state,
                fixture_schema_version="1" if provider_id == "layerzero_v2" else "0",
                first_release=True,
            )
        )
    return descriptors


def _resolve_derivatives() -> list[AdapterCertificationDescriptor]:
    descriptors: list[AdapterCertificationDescriptor] = []

    # Registered read-only venue adapters carry an honest ImplementationStatus.
    # VENUE_ADAPTERS holds the real Hyperliquid/dYdX/GMX/Drift adapters (keyed by
    # adapter_id) and wins over the simulator-only DERIVATIVES_ADAPTERS.
    registered: dict[str, Any] = {}
    try:
        from services.derivatives.adapters import (
            DERIVATIVES_ADAPTERS,
            VENUE_ADAPTERS,
        )

        registered = {**DERIVATIVES_ADAPTERS, **VENUE_ADAPTERS}
    except Exception as exc:  # pragma: no cover
        _record_import_error("services.derivatives.adapters:VENUE_ADAPTERS", exc)
        registered = {}

    # Hyperliquid ships as a production-shaped connector (fixture-injected
    # transport, no live validation) with no formal status → credential-waiting.
    hyperliquid_connector = _import(
        "services.derivatives.connectors.hyperliquid", "HyperliquidConnector"
    )

    specs: dict[str, dict[str, Any]] = {
        "hyperliquid": {
            "capabilities": [
                "markets", "account_snapshot", "fills", "funding",
                "realtime_account_stream",
            ],
            "streaming_model": "websocket",
            "pagination_model": "cursor",
        },
        "dydx": {"capabilities": [], "streaming_model": "none", "pagination_model": "none"},
        "gmx": {"capabilities": [], "streaming_model": "none", "pagination_model": "none"},
        "drift": {"capabilities": [], "streaming_model": "none", "pagination_model": "none"},
    }

    for token, spec in specs.items():
        adapter = registered.get(token)
        if adapter is not None:
            state = to_readiness(adapter.implementation_status)
            capabilities = list(getattr(adapter, "capabilities", ()) or ())
            adapter_name = getattr(adapter, "adapter_id", token)
        elif token == "hyperliquid" and hyperliquid_connector is not None:
            # code complete + infra defined, credential-gated, not yet validated.
            state = ReadinessDimensions.derive(
                code_complete=True, infra_defined=True, credential_required=True
            ).state
            capabilities = spec["capabilities"]
            adapter_name = "HyperliquidConnector"
        else:
            state = CredentialReadiness.SCAFFOLDED  # no adapter/connector exists yet
            capabilities = spec["capabilities"]
            adapter_name = f"{token}(unimplemented)"
        descriptors.append(
            AdapterCertificationDescriptor(
                provider=token,
                domain="derivatives",
                adapter=adapter_name,
                adapter_version="0.1.0",
                supported_operations=capabilities,
                required_credentials=["read_only_api_key"] if capabilities else [],
                pagination_model=spec["pagination_model"],
                streaming_model=spec["streaming_model"],
                implementation_state=state,
                first_release=True,
            )
        )
    return descriptors


def _resolve_payments() -> list[AdapterCertificationDescriptor]:
    descriptors: list[AdapterCertificationDescriptor] = []
    for token, (module, cls) in _PAYMENT_ADAPTERS.items():
        adapter_cls = _import(module, cls)
        if adapter_cls is not None:
            try:
                inst = adapter_cls()
            except Exception:  # pragma: no cover
                inst = None
            flows = list(getattr(inst, "flows", ()) or ()) if inst else []
            webhook = bool(getattr(inst, "webhook_supported", False)) if inst else False
            polling = bool(getattr(inst, "polling_supported", False)) if inst else False
            vault = getattr(inst, "vault_provider_name", "") if inst else ""
            capabilities = flows + (["webhook"] if webhook else []) + (
                ["polling"] if polling else []
            )
            # Fully implemented observation adapter, credential-gated, offline-safe.
            state = ReadinessDimensions.derive(
                code_complete=True, infra_defined=True, credential_required=True
            ).state
            descriptors.append(
                AdapterCertificationDescriptor(
                    provider=token,
                    domain="payments",
                    adapter=cls,
                    adapter_version="1.0.0",
                    supported_operations=capabilities,
                    required_credentials=["webhook_signing_secret"],
                    secret_ref_names=[vault] if vault else [],
                    expected_webhook_headers=["signature", "timestamp"] if webhook else [],
                    streaming_model="webhook" if webhook else "none",
                    pagination_model="none",
                    implementation_state=state,
                    first_release=True,
                )
            )
        else:  # pragma: no cover - adapters present in this repo
            descriptors.append(
                AdapterCertificationDescriptor(
                    provider=token,
                    domain="payments",
                    adapter=f"{cls}(unresolved)",
                    implementation_state=CredentialReadiness.SCAFFOLDED,
                    first_release=True,
                )
            )
    return descriptors


def _resolve_stablecoin_chain() -> list[AdapterCertificationDescriptor]:
    descriptors: list[AdapterCertificationDescriptor] = []
    for token, (module, cls, capabilities) in _STABLECOIN_OBSERVERS.items():
        verifier = _import(module, cls)
        if verifier is not None:
            # Implemented on-chain observer; requires configured RPC endpoints.
            state = ReadinessDimensions.derive(
                code_complete=True, infra_defined=True, credential_required=True
            ).state
            adapter_name = cls
        else:  # pragma: no cover
            state = CredentialReadiness.SCAFFOLDED
            adapter_name = f"{cls}(unresolved)"
        descriptors.append(
            AdapterCertificationDescriptor(
                provider=token,
                domain="stablecoin_chain",
                adapter=adapter_name,
                adapter_version="0.1.0",
                supported_operations=list(capabilities),
                required_endpoints=["json_rpc"],
                pagination_model="none",
                streaming_model="none",
                implementation_state=state,
                first_release=True,
            )
        )
    return descriptors


def _resolve_communications() -> list[AdapterCertificationDescriptor]:
    """Communications provider descriptors (read from the comms conformance
    module, which resolves state from the live Klaviyo connector)."""
    try:
        from services.comms.conformance import comms_certification_descriptor

        return [comms_certification_descriptor("klaviyo")]
    except Exception as exc:  # pragma: no cover - comms module present in this repo
        _record_import_error(
            "services.comms.conformance:comms_certification_descriptor", exc
        )
        return [
            AdapterCertificationDescriptor(
                provider="klaviyo",
                domain="communications",
                adapter="KlaviyoConnector(unresolved)",
                implementation_state=CredentialReadiness.SCAFFOLDED,
                first_release=True,
            )
        ]


_RESOLVERS = (
    _resolve_payments,
    _resolve_interop,
    _resolve_derivatives,
    _resolve_stablecoin_chain,
    _resolve_communications,
)


def iter_first_release_descriptors() -> list[AdapterCertificationDescriptor]:
    """Every first-release provider descriptor, resolved from source, sorted
    deterministically by (domain, provider)."""
    descriptors: list[AdapterCertificationDescriptor] = []
    for resolver in _RESOLVERS:
        descriptors.extend(resolver())
    descriptors.sort(key=lambda d: (d.domain, d.provider))
    return descriptors


def build_capability_matrix() -> dict:
    """Deterministic, JSON-serializable capability matrix.

    Shape::

        {
          "providers": { "<domain>:<provider>": { ... }, ... },
          "summary": {
            "total": int,
            "first_release": int,
            "by_state": { "<state>": int, ... },
            "by_domain": { "<domain>": int, ... },
          },
        }

    Keys are sorted; no timestamps or randomness are included so repeated calls
    are byte-identical.
    """
    providers: dict[str, dict] = {}
    by_state: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    first_release_count = 0

    for d in iter_first_release_descriptors():
        key = f"{d.domain}:{d.provider}"
        providers[key] = {
            "provider": d.provider,
            "domain": d.domain,
            "adapter": d.adapter,
            "adapter_version": d.adapter_version,
            "state": d.implementation_state.value,
            "state_rank": readiness_rank(d.implementation_state),
            "first_release": d.first_release,
            "capabilities": sorted(d.supported_operations),
            "unsupported": sorted(d.unsupported_operations),
            "required_credentials": sorted(d.required_credentials),
            "required_endpoints": sorted(d.required_endpoints),
            "secret_ref_names": sorted(d.secret_ref_names),
            "pagination_model": d.pagination_model,
            "streaming_model": d.streaming_model,
        }
        by_state[d.implementation_state.value] = by_state.get(d.implementation_state.value, 0) + 1
        by_domain[d.domain] = by_domain.get(d.domain, 0) + 1
        if d.first_release:
            first_release_count += 1

    return {
        "providers": dict(sorted(providers.items())),
        "summary": {
            "total": len(providers),
            "first_release": first_release_count,
            "by_state": dict(sorted(by_state.items())),
            "by_domain": dict(sorted(by_domain.items())),
            # Non-empty means a SCAFFOLDED entry above is an import failure,
            # not an honest absence — certification gates must fail on it.
            "import_errors": import_errors(),
        },
    }


__all__ = [
    "iter_first_release_descriptors",
    "build_capability_matrix",
    "import_errors",
]
