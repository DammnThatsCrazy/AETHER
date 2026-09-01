from __future__ import annotations

import pytest

from repositories.repos import BaseRepository
from shared.rights_authority.reconciliation import build_reconciliation_report
from shared.rights_authority.repository import RightsLedgerRepository
from shared.rights_authority.service import RightsAuthority


@pytest.mark.asyncio
async def test_reconciliation_reports_legacy_rows_without_mutating():
    repo = BaseRepository("connector_raw")
    await repo.insert("legacy-rightsless-row", {
        "tenant_id": "reconciliation-tenant",
        "source": "legacy",
        "payload": {"value": "redacted"},
    })
    report = await build_reconciliation_report(
        tenant_id="reconciliation-tenant",
        authority=RightsAuthority(RightsLedgerRepository(), signing_key="report-key"),
    )

    item = report["resources"]["bronze:connector_raw"]
    assert item["rightsless"] == 1
    assert report["migration"]["mutation_performed"] is False
    assert report["migration"]["status"] == "evidence_required"
    assert await repo.find_by_id("legacy-rightsless-row") is not None
