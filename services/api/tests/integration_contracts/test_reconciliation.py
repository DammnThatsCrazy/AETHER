"""Reconciliation check + report contracts."""

from __future__ import annotations

import pytest

from shared.integration_contracts.reconciliation import (
    ProviderReconciliationReport,
    ReconciliationCheck,
)


def test_reconciliation_check_defaults() -> None:
    c = ReconciliationCheck(name="orders", status="matched", expected=10, found=10)
    assert c.detail == ""


def test_reconciliation_check_status_literals() -> None:
    for status in ("matched", "mismatched", "missing", "extra"):
        c = ReconciliationCheck(name="orders", status=status, expected=0, found=0)  # type: ignore[arg-type]
        assert c.status == status


def test_reconciliation_check_rejects_bad_status() -> None:
    with pytest.raises(Exception):
        ReconciliationCheck(name="orders", status="nope", expected=1, found=1)


def test_reconciliation_check_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        ReconciliationCheck(name="orders", status="matched", expected=1, found=1, unexpected_field=True)  # type: ignore[call-arg]


def test_reconciliation_report_requires_checks_and_passed() -> None:
    with pytest.raises(Exception):
        ProviderReconciliationReport(  # type: ignore[call-arg]
            provider_identity="shopify.admin.orders_read",
            account_id="a1",
            run_at="2026-01-01T00:00:00+00:00",
        )


def test_reconciliation_report_bundles_checks() -> None:
    checks = [
        ReconciliationCheck(name="orders", status="matched", expected=10, found=10),
        ReconciliationCheck(name="refunds", status="mismatched", expected=2, found=1, detail="amount diff"),
    ]
    r = ProviderReconciliationReport(
        provider_identity="shopify.admin.orders_read",
        account_id="a1",
        run_at="2026-01-01T00:00:00+00:00",
        checks=checks,
        passed=False,
    )
    assert r.passed is False
    assert len(r.checks) == 2
    assert r.schema_version == "1"


def test_reconciliation_report_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        ProviderReconciliationReport(  # type: ignore[call-arg]
            provider_identity="x",
            account_id="a1",
            run_at="2026-01-01T00:00:00+00:00",
            checks=[],
            passed=True,
            unexpected_field=True,
        )
