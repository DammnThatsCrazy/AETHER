"""Tests for the legacy-compatibility plugin (BaseConnector -> UPR seam).

Team C seam: ``services.provider_runtime.legacy``. A fake ``BaseConnector``
(subclass) drives the adapter tests without network I/O; real connectors cover
the identity/manifest and Klaviyo seam-ambiguity cases.
"""

from __future__ import annotations

import pytest

from services.integrations.connectors.base import (
    BaseConnector,
    ConnectionTestResult,
    ConnectorConfig,
    NormalizedEvent,
)
from services.integrations.connectors.registry import CONNECTORS
from services.security.integration_security import sign_payload
from shared.credentials.types import ApiKeyCredential
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.catalog import manifest_by_identity
from shared.integration_contracts.events import RawProviderRecord, ReadBatch
from shared.integration_contracts.manifest import validate_manifest
from shared.integration_contracts.results import AdapterStatus

from services.provider_runtime.errors import ManifestInvalid
from services.provider_runtime.legacy import (
    LegacyConnectorPlugin,
    install_legacy_plugins,
)
from services.provider_runtime.registry import ProviderRegistry

from pydantic import SecretStr


class FakeConnector(BaseConnector):
    """Deterministic fake connector (no network)."""

    connector_type = "defi_llama"  # valid ConnectorType literal, not in CONNECTORS
    label = "Defi Llama"
    category = "onchain"
    description = "Fake test connector"
    supports_webhook = True
    supports_pull = True
    requires_secret = True
    supports_historical_backfill = True
    ingest_event_types = ("defi_llama.item",)

    async def test_connection(
        self, config: ConnectorConfig, secret: str | None = None
    ) -> ConnectionTestResult:
        return ConnectionTestResult(
            connector_type=self.connector_type, ok=True, status="ok", detail="ok"
        )

    async def pull(
        self, config: ConnectorConfig, since: str | None = None, secret: str | None = None
    ) -> list[NormalizedEvent]:
        return [
            NormalizedEvent(
                event_type="defi_llama.item",
                source="defi_llama",
                external_id=f"id-{i}",
                occurred_at=f"2026-01-0{i}T00:00:00+00:00",
                properties={"i": i, "since": since},
            )
            for i in range(1, 3)
        ]

    def parse_webhook(self, payload: dict) -> list[NormalizedEvent]:
        return [
            NormalizedEvent(
                event_type="defi_llama.event",
                source="defi_llama",
                external_id=payload.get("id") or "wh-1",
                occurred_at="2026-02-01T00:00:00+00:00",
                properties={"payload": payload},
            )
        ]


class RecordingConnector(FakeConnector):
    """Fake connector that records every adapter-facing call."""

    def __init__(self) -> None:
        self.seen: list[tuple] = []

    async def test_connection(self, config, secret=None):
        self.seen.append(("test_connection", config.connector_type, secret))
        return await super().test_connection(config, secret)

    async def pull(self, config, since=None, secret=None):
        self.seen.append(("pull", since, secret))
        return await super().pull(config, since=since, secret=secret)


def _context(**overrides) -> AcquisitionContext:
    kwargs = dict(
        tenant_id="t1",
        provider_identity="defi_llama.ingestion.connector",
        connection_id="c1",
        config={},
    )
    kwargs.update(overrides)
    return AcquisitionContext(**kwargs)


# ── Identity / manifest ─────────────────────────────────────────────────────


def test_identity_and_manifest_match_catalog() -> None:
    plugin = LegacyConnectorPlugin(CONNECTORS["klaviyo"])
    assert plugin.identity().key == "klaviyo.ingestion.connector"
    assert plugin.manifest().identity_key == "klaviyo.ingestion.connector"
    # The legacy re-derivation is byte-identical to the catalog's projection.
    assert plugin.manifest().model_dump() == manifest_by_identity[
        "klaviyo.ingestion.connector"
    ].model_dump()


def test_manifest_passes_validate_manifest() -> None:
    plugin = LegacyConnectorPlugin(FakeConnector())
    assert validate_manifest(plugin.manifest()) is plugin.manifest()


def test_fake_connector_capabilities() -> None:
    plugin = LegacyConnectorPlugin(FakeConnector())
    assert plugin.auth() is not None
    assert plugin.pull() is not None
    assert plugin.webhook() is not None
    # No account/reconciliation claims on this connector.
    assert plugin.account() is None
    assert plugin.reconciliation() is None


# ── auth adapter ────────────────────────────────────────────────────────────


async def test_auth_delegates_test_connection() -> None:
    connector = RecordingConnector()
    plugin = LegacyConnectorPlugin(connector)
    result = await plugin.auth().validate_credentials(_context())
    assert result.success is True
    assert result.status is AdapterStatus.OK
    assert connector.seen[0][0] == "test_connection"
    assert connector.seen[0][1] == "defi_llama"
    assert connector.seen[0][2] is None  # no credential -> no secret


async def test_auth_resolves_structured_secret() -> None:
    connector = RecordingConnector()
    plugin = LegacyConnectorPlugin(connector)
    context = _context(credential=ApiKeyCredential(api_key=SecretStr("sk-123")))
    result = await plugin.auth().test(context)
    assert result.success is True
    assert connector.seen[0][2] == "sk-123"  # auditable reveal reached the connector


# ── pull adapter ────────────────────────────────────────────────────────────


async def test_fetch_mirrors_base_connector_pull_signature() -> None:
    """The exact BaseConnector.pull(config, since=..., secret=...) delegation."""
    connector = RecordingConnector()
    plugin = LegacyConnectorPlugin(connector)
    adapter = plugin.pull()
    cursor = "2026-01-01T00:00:00+00:00"
    result = await adapter.fetch(_context(), cursor=cursor)
    assert result.success is True
    assert connector.seen[0] == ("pull", cursor, None)  # since=cursor, secret resolved
    batch: ReadBatch = result.data
    assert batch.has_more is False
    assert batch.next_cursor == "2026-01-02T00:00:00+00:00"  # last event occurred_at
    assert len(batch.records) == 2


async def test_fetch_honors_limit_as_page_bound() -> None:
    """``limit`` is a page bound (client-side slice) with an honest ``has_more``.

    The legacy pull is a single snapshot with no page API, so ``limit`` cannot
    be forwarded to the connector; it is honored on the returned page and
    ``has_more`` truthfully reports that records exist beyond the slice.
    """
    connector = RecordingConnector()
    plugin = LegacyConnectorPlugin(connector)
    adapter = plugin.pull()
    cursor = "2026-01-01T00:00:00+00:00"
    result = await adapter.fetch(_context(), cursor=cursor, limit=1)
    assert result.success is True
    assert connector.seen[0] == ("pull", cursor, None)  # full pull still ran once
    batch: ReadBatch = result.data
    assert len(batch.records) == 1
    assert batch.records[0].provider_record_id == "id-1"
    assert batch.has_more is True  # honest: 2 records existed, page bounded to 1
    assert batch.next_cursor == "2026-01-01T00:00:00+00:00"  # last returned event
    assert batch.records[0].cursor == cursor


async def test_fetch_wraps_normalized_event_into_raw_record() -> None:
    plugin = LegacyConnectorPlugin(FakeConnector())
    adapter = plugin.pull()
    result = await adapter.fetch(_context(), cursor=None)
    record: RawProviderRecord = result.data.records[0]
    assert record.provider_identity == "defi_llama.ingestion.connector"
    assert record.provider_record_id == "id-1"
    assert record.provider_occurred_at == "2026-01-01T00:00:00+00:00"
    assert record.tenant_id == "t1"
    assert record.connection_id == "c1"
    assert record.acquisition_mode == "poll"
    assert record.provider_record_type == "defi_llama.item"
    # The legacy event_type survives verbatim in metadata for the normalizer.
    assert record.metadata["legacy_event_type"] == "defi_llama.item"
    assert record.payload == {"i": 1, "since": None}
    assert record.checksum  # tamper-evident checksum computed at wrap time


async def test_initial_backfill_uses_since_none() -> None:
    connector = RecordingConnector()
    plugin = LegacyConnectorPlugin(connector)
    adapter = plugin.pull()
    result = await adapter.initial_backfill(_context())
    assert result.success is True
    assert connector.seen[0] == ("pull", None, None)
    assert result.data.records[0].cursor is None


# ── webhook adapter ─────────────────────────────────────────────────────────


def test_webhook_verify_accepts_valid_hmac() -> None:
    plugin = LegacyConnectorPlugin(FakeConnector())
    adapter = plugin.webhook()
    body = b'{"a": 1}'
    headers = sign_payload("whsec_test", body)  # fresh timestamp within tolerance
    assert adapter.verify(body, headers, "whsec_test") is True
    assert adapter.verify(body, headers, "whsec_wrong") is False


def test_webhook_parse_wraps_events() -> None:
    plugin = LegacyConnectorPlugin(FakeConnector())
    adapter = plugin.webhook()
    records = adapter.parse({"id": "wh-9"}, headers={})
    assert len(records) == 1
    record = records[0]
    assert record.provider_record_id == "wh-9"
    assert record.acquisition_mode == "webhook"
    assert record.tenant_id == ""  # scoping is bound by the ingestion service
    assert record.metadata["legacy_event_type"] == "defi_llama.event"


# ── normalizer ──────────────────────────────────────────────────────────────


async def test_normalizer_preserves_legacy_event_type() -> None:
    plugin = LegacyConnectorPlugin(FakeConnector())
    adapter = plugin.pull()
    raw = (await adapter.fetch(_context(), cursor=None)).data.records[0]
    result = plugin.normalizer().normalize(raw)
    assert len(result.events) == 1
    event = result.events[0]
    # Legacy provider-namespaced event_type preserved (renaming is out of scope).
    assert event.event_type == "defi_llama.item"
    assert event.event_family == "defi_llama"
    assert event.provider == "defi_llama"
    assert event.tenant_id == "t1"
    assert event.data == {"i": 1, "since": None}
    assert event.context["acquisition_mode"] == "poll"
    assert event.context["provider_record_type"] == "defi_llama.item"
    assert event.context["provider_record_id"] == "id-1"
    assert event.source_record_id == raw.record_id


async def test_normalizer_is_deterministic() -> None:
    plugin = LegacyConnectorPlugin(FakeConnector())
    raw = (await plugin.pull().fetch(_context(), cursor=None)).data.records[0]
    first = plugin.normalizer().normalize(raw)
    second = plugin.normalizer().normalize(raw)
    assert first.model_dump() == second.model_dump()


# ── Klaviyo seam ambiguity ──────────────────────────────────────────────────


async def test_klaviyo_account_adapter_is_honest_not_supported() -> None:
    plugin = LegacyConnectorPlugin(CONNECTORS["klaviyo"])
    assert plugin.manifest().accounts.discovery_supported is True
    adapter = plugin.account()
    assert adapter is not None
    discover = await adapter.discover_accounts(_context())
    assert discover.status is AdapterStatus.NOT_SUPPORTED
    select = await adapter.select_account(_context(), account_id="a1")
    assert select.status is AdapterStatus.NOT_SUPPORTED


async def test_klaviyo_reconciliation_adapter_is_honest_not_supported() -> None:
    plugin = LegacyConnectorPlugin(CONNECTORS["klaviyo"])
    assert plugin.manifest().sync.reconciliation is True
    adapter = plugin.reconciliation()
    assert adapter is not None
    snapshot = await adapter.snapshot(_context(), since=None)
    assert snapshot.status is AdapterStatus.NOT_SUPPORTED


def test_non_klaviyo_connectors_have_no_account_or_reconciliation() -> None:
    plugin = LegacyConnectorPlugin(CONNECTORS["slack"])
    assert plugin.account() is None
    assert plugin.reconciliation() is None


# ── install_legacy_plugins ──────────────────────────────────────────────────


def test_install_legacy_plugins_registers_every_connector() -> None:
    registry = ProviderRegistry(auto_install_legacy=False)
    count = install_legacy_plugins(registry)
    assert count == len(CONNECTORS)
    for connector_type in CONNECTORS:
        assert f"{connector_type}.ingestion.connector" in registry
    assert registry.sources()["klaviyo.ingestion.connector"] == "legacy"


def test_install_legacy_plugins_byte_identical_to_catalog() -> None:
    registry = ProviderRegistry(auto_install_legacy=False)
    install_legacy_plugins(registry)
    for key, plugin in registry.manifests().items():
        assert plugin.model_dump() == manifest_by_identity[key].model_dump()


def test_broken_connector_fails_loudly_named(monkeypatch) -> None:
    """A connector whose plugin cannot be built fails loudly, connector named.

    The catalog projection is valid by construction (build_connector_manifests
    validates at import), so the reachable failure path is a connector whose
    plugin construction raises — here a descriptor that explodes.
    """
    from services.integrations.connectors import registry as _registry_module

    registry = ProviderRegistry(auto_install_legacy=False)

    class BadConnector(FakeConnector):
        def descriptor(self):
            raise RuntimeError("descriptor exploded")

    monkeypatch.setitem(_registry_module.CONNECTORS, "defi_llama", BadConnector())
    with pytest.raises(ManifestInvalid) as excinfo:
        install_legacy_plugins(registry)
    assert "defi_llama" in str(excinfo.value)
