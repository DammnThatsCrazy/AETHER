"""Offline billing providers: manual invoicing and enterprise contracts.

Both extend the internal provider (no external processor). They differ only in
invoice export semantics: manual invoicing emits a downloadable artifact;
enterprise contracts are settled out-of-band against a signed contract.
"""
from __future__ import annotations

from typing import Any

from services.billing.providers.base import InvoiceExportMode
from services.billing.providers.internal import InternalOnlyProvider


class ManualInvoiceProvider(InternalOnlyProvider):
    def __init__(self) -> None:
        super().__init__(provider_type="manual_invoice")

    def invoice_export_mode(self) -> InvoiceExportMode:
        return "manual_artifact"

    async def export_invoice(self, *, tenant_id: str, invoice_preview: dict[str, Any]) -> dict[str, Any]:
        # Produce a manual invoice artifact (operator downloads + sends out-of-band).
        return {
            "provider": "manual_invoice",
            "tenant_id": tenant_id,
            "mode": "manual_artifact",
            "exported": True,
            "artifact": "manual_invoice_document",
            "line_items": invoice_preview.get("line_items", []),
        }


class EnterpriseContractProvider(InternalOnlyProvider):
    def __init__(self) -> None:
        super().__init__(provider_type="enterprise_contract")

    def invoice_export_mode(self) -> InvoiceExportMode:
        # Enterprise billing is settled against a signed contract, not a processor.
        return "approved_preview"

    async def export_invoice(self, *, tenant_id: str, invoice_preview: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": "enterprise_contract",
            "tenant_id": tenant_id,
            "mode": "approved_preview",
            "exported": True,
            "artifact": "enterprise_contract_settlement",
            "note": "Settled out-of-band against the signed enterprise contract.",
        }
