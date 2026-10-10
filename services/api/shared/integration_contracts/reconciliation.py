"""Provider reconciliation reports.

Reconciliation compares the provider's snapshot of an account against the
runtime's stored state. Each :class:`ReconciliationCheck` is one named
comparison with a typed verdict:

* ``matched`` — expected and found counts agree;
* ``mismatched`` — both sides have the item but disagree on a field;
* ``missing`` — the runtime expected it, the provider does not have it;
* ``extra`` — the provider has it, the runtime does not.

:class:`ProviderReconciliationReport` bundles the checks for one account and
carries an overall ``passed`` verdict.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReconciliationCheck(BaseModel):
    """One named reconciliation comparison for an account."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["matched", "mismatched", "missing", "extra"]
    expected: int
    found: int
    detail: str = ""


class ProviderReconciliationReport(BaseModel):
    """The full reconciliation verdict for one provider account."""

    model_config = ConfigDict(extra="forbid")

    provider_identity: str
    account_id: str
    run_at: str  # ISO-8601 UTC
    checks: list[ReconciliationCheck]
    passed: bool
    schema_version: str = "1"


__all__ = [
    "ProviderReconciliationReport",
    "ReconciliationCheck",
]
