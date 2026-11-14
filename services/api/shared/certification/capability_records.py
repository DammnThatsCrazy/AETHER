"""Financial capability records — typed evidence contracts for financial sources.

The provider certification matrix answers "what can this adapter do, and how
ready is it?".  This module adds the financial-domain join that was previously
implicit: one typed record per provider/adapter, bound to the release domain,
service classification, route surface, canonical event vocabulary, data rights,
and deployment profiles that govern it.

Design rules:

- The canonical provider facts stay in ``shared.certification.registry``.  This
  module projects descriptors; it does not re-author readiness.
- Domain surfaces are explicit because no existing registry maps a provider
  capability to its release domain, route surface, and event vocabulary as one
  record.  The validator cross-checks every surface against the real configs.
- Unknown event types, rights, profiles, routes, or production claims fail
  closed.  Financial domains are not part of the production release surface
  today, so any record claiming ``production`` is a validation error until the
  release manifest, route registry, and descriptor all move together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, Field

from shared.certification.descriptor import AdapterCertificationDescriptor
from shared.certification.readiness import CredentialReadiness, readiness_rank

_DERIVATIVES_OPERATION_EVENT_TYPES: dict[str, tuple[str, ...]] = {
    "reference_data": ("derivatives_price_observation_recorded",),
    "markets": ("derivatives_price_observation_recorded",),
    "orders": (
        "derivatives_order_observed",
        "derivatives_order_updated_observed",
    ),
    "fills": ("derivatives_fill_observed",),
    "funding": ("derivatives_funding_payment_observed",),
    "margin_snapshot": ("derivatives_margin_snapshot_observed",),
    "account_snapshot": (
        "derivatives_balance_snapshot_observed",
        "derivatives_margin_snapshot_observed",
        "derivatives_collateral_change_observed",
    ),
    "realtime_account_stream": (
        "derivatives_position_opened_observed",
        "derivatives_position_increased_observed",
        "derivatives_position_reduced_observed",
        "derivatives_position_closed_observed",
        "derivatives_position_liquidated_observed",
        "derivatives_position_adl_observed",
        "derivatives_position_settled_observed",
        "derivatives_balance_snapshot_observed",
        "derivatives_margin_snapshot_observed",
        "derivatives_collateral_change_observed",
    ),
}

# On-chain observers classify movements; they do not own payment lifecycle,
# deposit/withdrawal orchestration, or execution capabilities.
_STABLECOIN_OBSERVER_EVENT_TYPES: tuple[str, ...] = (
    "transfer",
    "mint",
    "burn",
    "swap",
    "bridge_deposit",
    "bridge_mint",
    "bridge_burn",
    "bridge_release",
    "liquidity_addition",
    "liquidity_removal",
    "collateral_deposit",
    "collateral_withdrawal",
    "treasury_transfer",
    "reward",
    "fee",
    "unknown_stablecoin_movement",
)


@dataclass(frozen=True)
class FinancialDomainSurface:
    """The non-provider half of a financial capability record."""

    adapter_domain: str
    release_domain: str
    service_classification: tuple[str, ...]
    route_prefixes: tuple[str, ...]
    route_registry_prefixes: tuple[str, ...]
    gated_route_prefixes: tuple[str, ...]
    owner_path: str
    requires_event_types: bool = False


FINANCIAL_DOMAIN_SURFACES: dict[str, FinancialDomainSurface] = {
    "derivatives": FinancialDomainSurface(
        adapter_domain="derivatives",
        release_domain="derivatives",
        service_classification=("derivatives",),
        route_prefixes=("/v1/derivatives",),
        route_registry_prefixes=("/v1/derivatives",),
        gated_route_prefixes=(),
        owner_path="services/api/value/derivatives",
        requires_event_types=True,
    ),
    "interop": FinancialDomainSurface(
        adapter_domain="interop",
        release_domain="financial",
        service_classification=("interop",),
        route_prefixes=("/v1/interoperability",),
        route_registry_prefixes=(),
        gated_route_prefixes=("/v1/interoperability",),
        owner_path="services/api/graph/interop",
    ),
    "payments": FinancialDomainSurface(
        adapter_domain="payments",
        release_domain="payments",
        service_classification=("card_linked_payments", "integrations", "payment_catalog"),
        route_prefixes=("/v1/integrations",),
        route_registry_prefixes=(),
        gated_route_prefixes=("/v1/integrations",),
        owner_path="services/api/connectors/integrations/providers/payment_rails",
        requires_event_types=True,
    ),
    "prediction_market": FinancialDomainSurface(
        adapter_domain="prediction_market",
        release_domain="financial",
        service_classification=("prediction_markets",),
        route_prefixes=("/v1/prediction-markets",),
        route_registry_prefixes=("/v1/prediction-markets",),
        gated_route_prefixes=(),
        owner_path="services/api/value/prediction_markets",
    ),
    "stablecoin_chain": FinancialDomainSurface(
        adapter_domain="stablecoin_chain",
        release_domain="stablecoin",
        service_classification=("stablecoin", "stablecoins"),
        route_prefixes=("/v1/stablecoin", "/v1/stablecoins"),
        route_registry_prefixes=("/v1/stablecoin", "/v1/stablecoins"),
        gated_route_prefixes=(),
        owner_path="services/api/value/stablecoins",
        requires_event_types=True,
    ),
}


class FinancialCapabilityRecord(BaseModel):
    """One typed financial provider/domain capability record."""

    record_id: str
    provider: str
    domain: str
    release_domain: str
    service_classification: list[str] = Field(default_factory=list)
    owner_path: str

    adapter: str
    adapter_version: str
    state: str
    state_rank: int
    first_release: bool
    production_eligible: bool

    supported_operations: list[str] = Field(default_factory=list)
    unsupported_operations: list[str] = Field(default_factory=list)
    supported_event_types: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    required_data_rights: list[str] = Field(default_factory=list)
    deployment_profiles: list[str] = Field(default_factory=list)

    route_prefixes: list[str] = Field(default_factory=list)
    gated_route_prefixes: list[str] = Field(default_factory=list)
    required_credentials: list[str] = Field(default_factory=list)
    required_endpoints: list[str] = Field(default_factory=list)
    secret_ref_names: list[str] = Field(default_factory=list)

    pagination_model: str = "none"
    streaming_model: str = "none"
    rate_limit_behavior: str = "unspecified"
    retry_policy: str = "unspecified"
    idempotency_model: str = "unspecified"
    retry_classification: str = "unspecified"
    custody_boundary: str = "no_custody"
    evidence_requirements: list[str] = Field(default_factory=list)


def _sorted_unique(values: Iterable[str]) -> list[str]:
    return sorted({str(value) for value in values})


def domain_event_vocabulary(domain: str) -> tuple[str, ...]:
    """Canonical event vocabulary a financial adapter domain may advertise."""
    if domain == "payments":
        from connectors.integrations.providers.payment_rails.base import (
            PAYMENT_CANONICAL_EVENT_TYPES,
        )

        return PAYMENT_CANONICAL_EVENT_TYPES
    if domain == "derivatives":
        from value.derivatives.topic_contract import DERIVATIVES_TOPIC_CONTRACTS

        return tuple(
            sorted(
                {
                    event_type
                    for contract in DERIVATIVES_TOPIC_CONTRACTS
                    for event_type in contract.event_types
                }
            )
        )
    if domain == "stablecoin_chain":
        return _STABLECOIN_OBSERVER_EVENT_TYPES
    return ()


def events_for_operations(domain: str, operations: Iterable[str]) -> tuple[str, ...]:
    """Events a domain adapter may claim for its declared operations.

    Payments and on-chain observers expose a domain-level event vocabulary.
    Derivatives capabilities are finer-grained, so only the events mapped to
    the adapter's declared observation operations are claimable.
    """
    vocabulary = domain_event_vocabulary(domain)
    declared = tuple(operations)
    if not declared:
        return ()
    if domain == "derivatives":
        claimed = {
            event_type
            for operation in declared
            for event_type in _DERIVATIVES_OPERATION_EVENT_TYPES.get(operation, ())
        }
        return tuple(sorted(claimed & set(vocabulary)))
    return vocabulary


def _release_surface(release_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    surface = release_manifest.get("release_surface")
    return surface if isinstance(surface, Mapping) else release_manifest


def production_eligible(
    surface: FinancialDomainSurface, release_manifest: Mapping[str, Any]
) -> bool:
    """A financial domain is production-eligible only when its release domain
    is not excluded AND one of its route prefixes is enabled for production."""
    release = _release_surface(release_manifest)
    excluded = set(release.get("excluded_domains") or ())
    enabled = set(release.get("enabled_route_prefixes") or ())
    if surface.release_domain in excluded:
        return False
    return any(prefix in enabled for prefix in surface.route_prefixes)


def _record_for(
    descriptor: AdapterCertificationDescriptor,
    surface: FinancialDomainSurface,
    *,
    is_production_eligible: bool,
) -> FinancialCapabilityRecord:
    return FinancialCapabilityRecord(
        record_id=f"{descriptor.domain}:{descriptor.provider}",
        provider=descriptor.provider,
        domain=descriptor.domain,
        release_domain=surface.release_domain,
        service_classification=list(surface.service_classification),
        owner_path=surface.owner_path,
        adapter=descriptor.adapter,
        adapter_version=descriptor.adapter_version,
        state=descriptor.implementation_state.value,
        state_rank=readiness_rank(descriptor.implementation_state),
        first_release=descriptor.first_release,
        production_eligible=is_production_eligible,
        supported_operations=_sorted_unique(descriptor.supported_operations),
        unsupported_operations=_sorted_unique(descriptor.unsupported_operations),
        supported_event_types=_sorted_unique(descriptor.supported_event_types),
        permissions=_sorted_unique(descriptor.permissions),
        required_data_rights=_sorted_unique(descriptor.required_data_rights),
        deployment_profiles=_sorted_unique(descriptor.deployment_profiles),
        route_prefixes=list(surface.route_prefixes),
        gated_route_prefixes=list(surface.gated_route_prefixes),
        required_credentials=_sorted_unique(descriptor.required_credentials),
        required_endpoints=_sorted_unique(descriptor.required_endpoints),
        secret_ref_names=_sorted_unique(descriptor.secret_ref_names),
        pagination_model=descriptor.pagination_model,
        streaming_model=descriptor.streaming_model,
        rate_limit_behavior=descriptor.rate_limit_behavior,
        retry_policy=descriptor.retry_policy,
        idempotency_model=descriptor.idempotency_model,
        retry_classification=descriptor.retry_classification,
        custody_boundary=descriptor.custody_boundary,
        evidence_requirements=_sorted_unique(descriptor.evidence_requirements),
    )


def _surface_payload(surface: FinancialDomainSurface) -> dict[str, Any]:
    return {
        "adapter_domain": surface.adapter_domain,
        "release_domain": surface.release_domain,
        "service_classification": list(surface.service_classification),
        "route_prefixes": list(surface.route_prefixes),
        "route_registry_prefixes": list(surface.route_registry_prefixes),
        "gated_route_prefixes": list(surface.gated_route_prefixes),
        "owner_path": surface.owner_path,
        "requires_event_types": surface.requires_event_types,
        "event_vocabulary": list(domain_event_vocabulary(surface.adapter_domain)),
    }


def build_financial_capability_matrix(
    descriptors: Iterable[AdapterCertificationDescriptor],
    *,
    release_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Deterministic financial capability matrix projected from descriptors."""
    records: dict[str, dict[str, Any]] = {}
    by_domain: dict[str, int] = {}
    by_state: dict[str, int] = {}
    by_release_domain: dict[str, int] = {}

    for descriptor in descriptors:
        surface = FINANCIAL_DOMAIN_SURFACES.get(descriptor.domain)
        if surface is None:
            raise ValueError(f"unknown financial domain: {descriptor.domain}")
        eligible = production_eligible(surface, release_manifest)
        record = _record_for(descriptor, surface, is_production_eligible=eligible)
        records[record.record_id] = record.model_dump(mode="json")
        by_domain[record.domain] = by_domain.get(record.domain, 0) + 1
        by_state[record.state] = by_state.get(record.state, 0) + 1
        by_release_domain[record.release_domain] = (
            by_release_domain.get(record.release_domain, 0) + 1
        )

    return {
        "records": dict(sorted(records.items())),
        "domain_surfaces": {
            key: _surface_payload(surface)
            for key, surface in sorted(FINANCIAL_DOMAIN_SURFACES.items())
        },
        "summary": {
            "total": len(records),
            "domains": len(FINANCIAL_DOMAIN_SURFACES),
            "by_domain": dict(sorted(by_domain.items())),
            "by_state": dict(sorted(by_state.items())),
            "by_release_domain": dict(sorted(by_release_domain.items())),
            "production_eligible": sum(
                1 for record in records.values() if record["production_eligible"]
            ),
        },
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def validate_financial_capability_matrix(
    matrix: Mapping[str, Any],
    *,
    service_classification: Mapping[str, Any],
    route_registry: Mapping[str, Any],
    release_manifest: Mapping[str, Any],
    deployment_profiles: Mapping[str, Any],
    data_rights_fields: Iterable[str],
    root: Any = None,
) -> list[str]:
    """Cross-registry validation for the financial capability matrix.

    Returns human-readable errors; an empty list is the only passing result.
    """
    errors: list[str] = []
    records = _mapping(matrix.get("records"))
    service_keys = set(_mapping(service_classification.get("services")))
    known_prefixes = set(route_registry.get("known_prefixes") or ())
    release = _release_surface(release_manifest)
    enabled_prefixes = set(release.get("enabled_route_prefixes") or ())
    data_right_keys = set(data_rights_fields)
    allowed_profiles = set(_mapping(deployment_profiles.get("canonical_environments")))
    allowed_profiles.update(_mapping(deployment_profiles.get("profiles")))

    by_domain: dict[str, int] = {}
    for record_id, record in records.items():
        if not isinstance(record, Mapping):
            errors.append(f"{record_id}: record is not an object")
            continue
        domain = str(record.get("domain") or "")
        surface = FINANCIAL_DOMAIN_SURFACES.get(domain)
        if surface is None:
            errors.append(f"{record_id}: unknown financial domain {domain!r}")
            continue
        by_domain[domain] = by_domain.get(domain, 0) + 1

        if record_id != f"{domain}:{record.get('provider')}":
            errors.append(f"{record_id}: record_id does not match domain:provider")
        if record.get("release_domain") != surface.release_domain:
            errors.append(
                f"{record_id}: release_domain {record.get('release_domain')!r} "
                f"!= {surface.release_domain!r}"
            )
        if list(record.get("service_classification") or ()) != list(
            surface.service_classification
        ):
            errors.append(f"{record_id}: service_classification drift")
        if list(record.get("route_prefixes") or ()) != list(surface.route_prefixes):
            errors.append(f"{record_id}: route_prefixes drift")
        if list(record.get("gated_route_prefixes") or ()) != list(
            surface.gated_route_prefixes
        ):
            errors.append(f"{record_id}: gated_route_prefixes drift")
        if record.get("owner_path") != surface.owner_path:
            errors.append(f"{record_id}: owner_path drift")

        vocabulary = set(domain_event_vocabulary(domain))
        events = set(record.get("supported_event_types") or ())
        unknown_events = sorted(events - vocabulary)
        if unknown_events:
            errors.append(
                f"{record_id}: unsupported event type(s) for {domain}: "
                f"{', '.join(unknown_events)}"
            )

        supported = set(record.get("supported_operations") or ())
        expected_events = set(events_for_operations(domain, supported))
        unreachable_events = sorted(events - expected_events)
        if unreachable_events:
            errors.append(
                f"{record_id}: event type(s) not reachable from declared operations: "
                f"{', '.join(unreachable_events)}"
            )

        unknown_rights = sorted(
            set(record.get("required_data_rights") or ()) - data_right_keys
        )
        if unknown_rights:
            errors.append(
                f"{record_id}: unknown data right(s): {', '.join(unknown_rights)}"
            )

        profiles = set(record.get("deployment_profiles") or ())
        if not profiles:
            errors.append(f"{record_id}: no deployment profile declared")
        unknown_profiles = sorted(profiles - allowed_profiles)
        if unknown_profiles:
            errors.append(
                f"{record_id}: unknown deployment profile(s): "
                f"{', '.join(unknown_profiles)}"
            )

        unsupported = set(record.get("unsupported_operations") or ())
        overlap = sorted(supported & unsupported)
        if overlap:
            errors.append(
                f"{record_id}: operation declared both supported and unsupported: "
                f"{', '.join(overlap)}"
            )

        state = str(record.get("state") or "")
        if state == CredentialReadiness.SCAFFOLDED.value and events:
            errors.append(
                f"{record_id}: scaffolded record must not advertise event types"
            )
        if (
            surface.requires_event_types
            and state != CredentialReadiness.SCAFFOLDED.value
            and not events
        ):
            errors.append(
                f"{record_id}: implemented {domain} record declares no canonical event types"
            )

        expected_production = production_eligible(surface, release_manifest)
        if bool(record.get("production_eligible")) != expected_production:
            errors.append(
                f"{record_id}: production_eligible={record.get('production_eligible')} "
                f"but release manifest implies {expected_production}"
            )
        if "production" in profiles:
            if not expected_production:
                errors.append(
                    f"{record_id}: claims production but the release surface excludes it"
                )
            if int(record.get("state_rank") or 0) < readiness_rank(
                CredentialReadiness.PARTNER_LIVE
            ):
                errors.append(
                    f"{record_id}: production profile requires partner_live readiness; "
                    f"state is {state}"
                )
        elif expected_production:
            errors.append(
                f"{record_id}: release surface allows production but record does not "
                "declare it"
            )

    for domain, surface in sorted(FINANCIAL_DOMAIN_SURFACES.items()):
        expected_production = production_eligible(surface, release_manifest)
        if not by_domain.get(domain):
            errors.append(f"financial domain {domain!r} has no provider records")
        if root is not None:
            owner = root / surface.owner_path
            if not owner.is_dir():
                errors.append(f"{domain}: owner_path does not exist: {surface.owner_path}")
        for key in surface.service_classification:
            if key not in service_keys:
                errors.append(f"{domain}: service classification missing {key!r}")
        route_prefixes = set(surface.route_prefixes)
        declared = set(surface.route_registry_prefixes) | set(
            surface.gated_route_prefixes
        )
        if route_prefixes != declared:
            errors.append(f"{domain}: route prefix declarations are inconsistent")
        for prefix in surface.route_registry_prefixes:
            if prefix not in known_prefixes:
                errors.append(
                    f"{domain}: classified route prefix {prefix!r} missing from "
                    "route registry"
                )
        for prefix in surface.gated_route_prefixes:
            if prefix in known_prefixes:
                errors.append(
                    f"{domain}: gated route prefix {prefix!r} unexpectedly classified "
                    "in route registry"
                )
        if not expected_production:
            for prefix in surface.route_prefixes:
                if prefix in enabled_prefixes:
                    errors.append(
                        f"{domain}: route prefix {prefix!r} is enabled for production "
                        "but the domain is not production-eligible"
                    )

    return errors


__all__ = [
    "FINANCIAL_DOMAIN_SURFACES",
    "FinancialCapabilityRecord",
    "FinancialDomainSurface",
    "build_financial_capability_matrix",
    "domain_event_vocabulary",
    "events_for_operations",
    "production_eligible",
    "validate_financial_capability_matrix",
]
