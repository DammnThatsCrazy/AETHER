"""Inbound data-provider / connector ingestion.

Aether enriches the intelligence graph from SDKs **or** direct platform
connectors. This package adds the non-SDK ingestion path: a provider-safe
connector framework (config, connection test, sync, webhook ingest) with 14
production-shaped adapters that are disabled by default and require provider credentials.
Real provider API calls are credential-gated TODOs.
"""
