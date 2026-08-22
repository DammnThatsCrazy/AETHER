"""Capability adapter protocols: method surface, conformance mapping, results."""

from __future__ import annotations

import inspect

import pytest

from shared.integration_contracts.capabilities import (
    CAPABILITY_ADAPTER_METHODS,
    AccountAdapter,
    AuthAdapter,
    PullAdapter,
    ReconciliationAdapter,
    ReportAdapter,
    StreamAdapter,
    WebhookAdapter,
)
from shared.integration_contracts.acquisition import AcquisitionContext, ProviderAccount
from shared.integration_contracts.events import RawProviderRecord, ReadBatch
from shared.integration_contracts.plugin import CapabilitySet
from shared.integration_contracts.results import AdapterResult, AdapterStatus


# ── CAPABILITY_ADAPTER_METHODS ──────────────────────────────────────────────


def test_capability_adapter_methods_covers_all_capability_set_fields() -> None:
    expected = {
        "auth",
        "account",
        "pull",
        "webhook",
        "report",
        "stream",
        "reconciliation",
    }
    assert set(CAPABILITY_ADAPTER_METHODS) == expected
    # Every adapter attr name is also a CapabilitySet field.
    assert expected == set(CapabilitySet.model_fields)


def test_capability_adapter_methods_lists_expected_methods() -> None:
    assert CAPABILITY_ADAPTER_METHODS["auth"] == ("validate_credentials", "test")
    assert CAPABILITY_ADAPTER_METHODS["account"] == ("discover_accounts", "select_account")
    assert CAPABILITY_ADAPTER_METHODS["pull"] == ("fetch", "initial_backfill")
    assert CAPABILITY_ADAPTER_METHODS["webhook"] == ("verify", "parse")
    assert CAPABILITY_ADAPTER_METHODS["report"] == ("fetch_report",)
    assert CAPABILITY_ADAPTER_METHODS["stream"] == ("subscribe",)
    assert CAPABILITY_ADAPTER_METHODS["reconciliation"] == ("snapshot",)


# ── Protocol signatures must match the seam exactly ─────────────────────────


def _param_kinds(sig: inspect.Signature) -> tuple[str, ...]:
    return tuple(
        f"{name}:{p.kind.name}" for name, p in sig.parameters.items()
    )


def test_pull_adapter_signature_matches_seam() -> None:
    sig = inspect.signature(PullAdapter.fetch)
    # self positional; context positional; cursor/limit keyword-only.
    assert _param_kinds(sig) == (
        "self:POSITIONAL_OR_KEYWORD",
        "context:POSITIONAL_OR_KEYWORD",
        "cursor:KEYWORD_ONLY",
        "limit:KEYWORD_ONLY",
    )
    assert sig.parameters["limit"].default is None
    assert sig.parameters["cursor"].default is inspect.Parameter.empty


def test_webhook_adapter_signatures_match_seam() -> None:
    verify = inspect.signature(WebhookAdapter.verify)
    assert _param_kinds(verify) == (
        "self:POSITIONAL_OR_KEYWORD",
        "raw_body:POSITIONAL_OR_KEYWORD",
        "headers:POSITIONAL_OR_KEYWORD",
        "secret:POSITIONAL_OR_KEYWORD",
    )
    parse = inspect.signature(WebhookAdapter.parse)
    assert _param_kinds(parse) == (
        "self:POSITIONAL_OR_KEYWORD",
        "payload:POSITIONAL_OR_KEYWORD",
        "headers:KEYWORD_ONLY",
    )


def test_reconciliation_adapter_signature_matches_seam() -> None:
    sig = inspect.signature(ReconciliationAdapter.snapshot)
    assert _param_kinds(sig) == (
        "self:POSITIONAL_OR_KEYWORD",
        "context:POSITIONAL_OR_KEYWORD",
        "since:KEYWORD_ONLY",
    )
    assert sig.parameters["since"].default is inspect.Parameter.empty


def test_report_and_account_adapter_signatures_match_seam() -> None:
    report = inspect.signature(ReportAdapter.fetch_report)
    assert _param_kinds(report) == (
        "self:POSITIONAL_OR_KEYWORD",
        "context:POSITIONAL_OR_KEYWORD",
        "report:KEYWORD_ONLY",
    )
    select = inspect.signature(AccountAdapter.select_account)
    assert _param_kinds(select) == (
        "self:POSITIONAL_OR_KEYWORD",
        "context:POSITIONAL_OR_KEYWORD",
        "account_id:KEYWORD_ONLY",
    )


# ── Protocol conformance via the mapping ────────────────────────────────────


class _StubPullAdapter:
    """Implements every PullAdapter protocol method."""

    async def fetch(
        self, context: AcquisitionContext, *, cursor: str | None, limit: int | None = None
    ) -> AdapterResult[ReadBatch]:
        return AdapterResult.ok(ReadBatch())

    async def initial_backfill(self, context: AcquisitionContext) -> AdapterResult[ReadBatch]:
        return AdapterResult.not_supported("initial_backfill")


def test_pull_adapter_conforms_via_capability_adapter_methods() -> None:
    # The conformance check the certification harness performs structurally.
    for method in CAPABILITY_ADAPTER_METHODS["pull"]:
        assert callable(getattr(_StubPullAdapter(), method))


@pytest.mark.asyncio
async def test_pull_adapter_returns_adapter_result() -> None:
    adapter = _StubPullAdapter()
    ctx = AcquisitionContext(tenant_id="t1", provider_identity="shopify.admin.orders_read")
    ok = await adapter.fetch(ctx, cursor=None)
    assert ok.status == AdapterStatus.OK
    assert ok.success is True
    # cursor and limit are forwarded keyword-only args.
    ok2 = await adapter.fetch(ctx, cursor="c1", limit=50)
    assert ok2.status == AdapterStatus.OK
    # An unsupported op is a result, never a raise.
    unsupported = await adapter.initial_backfill(ctx)
    assert unsupported.status == AdapterStatus.NOT_SUPPORTED
    assert unsupported.success is False
    assert unsupported.error_code == "not_supported:initial_backfill"
    assert unsupported.retryable is False


# ── Conformance of a full capability adapter set ────────────────────────────


class _StubAuthAdapter:
    async def validate_credentials(self, context: AcquisitionContext) -> AdapterResult[object]:
        return AdapterResult.ok()

    async def test(self, context: AcquisitionContext) -> AdapterResult[object]:
        return AdapterResult.ok()


class _StubAccountAdapter:
    async def discover_accounts(
        self, context: AcquisitionContext
    ) -> AdapterResult[list[ProviderAccount]]:
        return AdapterResult.ok([ProviderAccount(account_id="a1")])

    async def select_account(
        self, context: AcquisitionContext, *, account_id: str
    ) -> AdapterResult[object]:
        return AdapterResult.ok()


class _StubWebhookAdapter:
    def verify(self, raw_body: bytes, headers: dict[str, str], secret: str | None) -> bool:
        return True

    def parse(
        self, payload: dict[str, object], *, headers: dict[str, str]
    ) -> list[RawProviderRecord]:
        return []


class _StubReportAdapter:
    async def fetch_report(
        self, context: AcquisitionContext, *, report: str
    ) -> AdapterResult[list[RawProviderRecord]]:
        return AdapterResult.ok([])


class _StubStreamAdapter:
    async def subscribe(self, context: AcquisitionContext) -> AdapterResult[object]:
        return AdapterResult.not_supported("subscribe")


class _StubReconciliationAdapter:
    async def snapshot(
        self, context: AcquisitionContext, *, since: str | None
    ) -> AdapterResult[list[RawProviderRecord]]:
        return AdapterResult.ok([])


_AdapterClasses = {
    "auth": _StubAuthAdapter,
    "account": _StubAccountAdapter,
    "pull": _StubPullAdapter,
    "webhook": _StubWebhookAdapter,
    "report": _StubReportAdapter,
    "stream": _StubStreamAdapter,
    "reconciliation": _StubReconciliationAdapter,
}


@pytest.mark.parametrize("attr", sorted(CAPABILITY_ADAPTER_METHODS))
def test_adapter_conformance_for_every_capability(attr: str) -> None:
    adapter = _AdapterClasses[attr]()
    for method in CAPABILITY_ADAPTER_METHODS[attr]:
        assert callable(getattr(adapter, method)), f"{attr}.{method} missing"


def test_capabilities_modules_import_cleanly() -> None:
    # The adapter protocols reference the events/acquisition/results types they
    # return; a missing import would fail at import time (already imported above).
    assert PullAdapter is not None
    assert WebhookAdapter is not None
    assert ReconciliationAdapter is not None
