"""Explicit tenant-storage coverage for account erasure.

This registry is the compliance boundary. A tenant-scoped repository must be
registered here before it can be considered by the account-lifecycle worker.
Domains without a real provider are represented as ``unavailable`` or
``deferred``; they are never reported as erased.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class StorageDomain:
    name: str
    repository: str
    mode: str  # erase | revoke | retain_stub | unavailable | deferred
    reason: str = ""


STORAGE_DOMAIN_REGISTRY: tuple[StorageDomain, ...] = (
    StorageDomain("tenant_core", "tenants,users", "erase"),
    StorageDomain("api_keys", "api_keys", "revoke"),
    StorageDomain("sessions", "auth_sessions", "revoke"),
    StorageDomain("service_credentials", "service_accounts,service_credentials", "revoke"),
    StorageDomain("public_ingest_identifiers", "public_ingest_identifiers", "revoke"),
    StorageDomain(
        "notification_webhooks",
        "webhooks",
        "erase",
        "tenant webhook configurations and delivery destinations are erased",
    ),
    StorageDomain(
        "provider_credentials",
        "providers",
        "erase",
        "encrypted tenant provider credentials are erased with the tenant",
    ),
    StorageDomain(
        "webhook_delivery_claims",
        "customer_webhook_delivery_claims",
        "erase",
        "idempotent delivery claims are erased with tenant webhook history",
    ),
    StorageDomain(
        "webhook_delivery_attempts",
        "delivery_attempts",
        "erase",
        "tenant webhook delivery history is erased with the tenant",
    ),
    StorageDomain(
        "billing",
        "tenant_billing_accounts",
        "retain_stub",
        "billing evidence is legally retained in detached form",
    ),
    StorageDomain(
        "audit",
        "security_audit_events",
        "retain_stub",
        "audit evidence is legally retained in detached form",
    ),
    StorageDomain(
        "graph",
        "tenant_graph",
        "unavailable",
        "no tenant-scoped graph erasure provider is exposed by this deployment",
    ),
    StorageDomain(
        "object_store",
        "tenant_object_store",
        "deferred",
        "no tenant-scoped object-store erasure provider is exposed by this deployment",
    ),
    StorageDomain(
        "search_index",
        "tenant_search_index",
        "unavailable",
        "no tenant-scoped search erasure provider is exposed by this deployment",
    ),
)

# The repository registry is deliberately separate from the domain registry so
# a new tenant-scoped repository cannot be added without a manifest decision.
TENANT_SCOPED_REPOSITORY_REGISTRY: dict[str, str] = {
    "tenants": "tenant_core",
    "users": "tenant_core",
    "api_keys": "api_keys",
    "auth_sessions": "sessions",
    "service_accounts": "service_credentials",
    "service_credentials": "service_credentials",
    "public_ingest_identifiers": "public_ingest_identifiers",
    "webhooks": "notification_webhooks",
    "providers": "provider_credentials",
    "customer_webhook_delivery_claims": "webhook_delivery_claims",
    "delivery_attempts": "webhook_delivery_attempts",
    "tenant_billing_accounts": "billing",
    "security_audit_events": "audit",
    "tenant_graph": "graph",
    "tenant_object_store": "object_store",
    "tenant_search_index": "search_index",
}


def storage_domains_by_name(
    domains: Iterable[StorageDomain] = STORAGE_DOMAIN_REGISTRY,
) -> dict[str, StorageDomain]:
    result: dict[str, StorageDomain] = {}
    for domain in domains:
        if domain.name in result:
            raise AssertionError(f"duplicate account-erasure storage domain: {domain.name}")
        result[domain.name] = domain
    return result


def validate_storage_domain_coverage(
    repositories: Mapping[str, str] = TENANT_SCOPED_REPOSITORY_REGISTRY,
    domains: Iterable[StorageDomain] = STORAGE_DOMAIN_REGISTRY,
) -> None:
    """Fail closed when a tenant repository lacks an erasure-domain decision."""

    domain_names = set(storage_domains_by_name(domains))
    missing = {
        repository: domain
        for repository, domain in repositories.items()
        if domain not in domain_names
    }
    if missing:
        raise AssertionError(
            "tenant-scoped repositories missing account-erasure coverage: "
            f"{missing}"
        )


def manifest_template(
    domains: Iterable[StorageDomain] = STORAGE_DOMAIN_REGISTRY,
) -> dict[str, dict]:
    """Create a complete, deterministic machine-readable erasure manifest."""

    validate_storage_domain_coverage(domains=domains)
    manifest: dict[str, dict] = {}
    for domain in domains:
        initial = "pending" if domain.mode in {"erase", "revoke", "retain_stub"} else domain.mode
        manifest[domain.name] = {
            "domain": domain.name,
            "repository": domain.repository,
            "mode": domain.mode,
            "status": initial,
            "action": "not_attempted",
            "reason": domain.reason or None,
            "records_affected": 0,
            "completed_at": None,
            "error": None,
        }
    return manifest
