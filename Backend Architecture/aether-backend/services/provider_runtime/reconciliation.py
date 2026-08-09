"""Provider reconciliation engine.

Runs ``plugin.reconciliation().snapshot`` and compares per
``provider_record_type`` counts against the raw store, producing a
:class:`ProviderReconciliationReport`. Reconciliation compares the provider's
snapshot of an account against the runtime's stored state; a provider that does
not implement the reconciliation capability is a hard
:class:`ReconciliationFailed` — never a fabricated "passed".

Verdict semantics follow the :class:`ReconciliationCheck` contract:
``expected`` is what the runtime stores (raw-store count), ``found`` is what the
provider snapshot reports:

* ``matched`` — counts agree;
* ``mismatched`` — both sides hold records for the type but disagree;
* ``missing`` — the runtime expected records, the provider snapshot has none;
* ``extra`` — the provider snapshot reports records the runtime does not have.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from services.provider_runtime.errors import (
    ProviderNotInstalled,
    ReconciliationFailed,
)
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.reconciliation import (
    ProviderReconciliationReport,
    ReconciliationCheck,
)
from shared.integration_contracts.results import AdapterStatus
from shared.logger.logger import get_logger

logger = get_logger("aether.provider_runtime.reconciliation")


class ReconciliationEngine:
    """Runs plugin.reconciliation().snapshot; compares against raw-store counts; emits a report."""

    def __init__(
        self,
        *,
        raw_store: Any = None,
        broker: Any = None,
        registry: Any = None,
    ) -> None:
        self.raw_store = raw_store
        self.broker = broker
        self.registry = registry

    # ── Seam defaults (resolved lazily so imports stay decoupled) ──────────

    def _registry(self) -> Any:
        if self.registry is None:
            from services.provider_runtime.registry import registry
            self.registry = registry
        return self.registry

    def _broker(self) -> Any:
        if self.broker is None:
            from services.provider_runtime.credential_broker import CredentialBroker
            self.broker = CredentialBroker()
        return self.broker

    def _raw_store(self) -> Any:
        if self.raw_store is None:
            from services.provider_runtime.raw_store import RawProviderRecordStore
            self.raw_store = RawProviderRecordStore()
        return self.raw_store

    # ── Run ────────────────────────────────────────────────────────────────

    async def run(self, connection: Any) -> ProviderReconciliationReport:
        """plugin.reconciliation() must be present (else ReconciliationFailed)."""
        provider_identity = connection.provider_identity
        plugin = self._registry().get(provider_identity)
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider {provider_identity} is not installed in the runtime registry"
            )
        reconciliation = plugin.reconciliation()
        if reconciliation is None:
            raise ReconciliationFailed(
                f"provider {provider_identity} does not implement reconciliation"
            )

        selected = getattr(connection, "selected_accounts", None) or []
        account_id = str(selected[0]) if selected else ""
        credential = await self._resolve_credential(connection)
        context = AcquisitionContext(
            tenant_id=connection.tenant_id,
            provider_identity=provider_identity,
            connection_id=connection.connection_id,
            account_id=account_id,
            config=dict(getattr(connection, "config", None) or {}),
            credential=credential,
        )
        result = await reconciliation.snapshot(context, since=None)
        if result.status != AdapterStatus.OK:
            detail = result.error_code or result.status.value
            raise ReconciliationFailed(
                f"reconciliation snapshot failed for {provider_identity}: {detail}"
            )
        records = list(result.data or [])
        snapshot_total = len(records)
        snapshot_by_type = Counter(
            record.provider_record_type for record in records
        )

        checks: list[ReconciliationCheck] = []
        store = self._raw_store()

        # Per provider_record_type comparison (provider snapshot view).
        for record_type in sorted(snapshot_by_type):
            found = snapshot_by_type[record_type]
            expected = await store.count(
                tenant_id=connection.tenant_id,
                provider_identity=provider_identity,
                provider_record_type=record_type,
            )
            checks.append(self._check(
                name=f"provider_record_type:{record_type}",
                expected=expected, found=found,
            ))

        # Aggregate account-level safety net — catches runtime records whose
        # provider_record_type never appears in the provider snapshot (missing)
        # and snapshot records the runtime never stored (extra).
        expected_total = await store.count(
            tenant_id=connection.tenant_id,
            provider_identity=provider_identity,
        )
        checks.append(self._check(
            name="raw_store_aggregate",
            expected=expected_total, found=snapshot_total,
            detail=(
                "runtime raw-store records vs provider snapshot records "
                f"(account={account_id or 'none'})"
            ),
        ))

        passed = all(check.status == "matched" for check in checks)
        report = ProviderReconciliationReport(
            provider_identity=provider_identity,
            account_id=account_id,
            run_at=datetime.now(timezone.utc).isoformat(),
            checks=checks,
            passed=passed,
        )
        if not passed:
            logger.warning(
                f"provider reconciliation drift provider={provider_identity} "
                f"account={account_id or 'none'}: "
                + "; ".join(
                    f"{c.name}={c.status}(expected={c.expected},found={c.found})"
                    for c in checks if c.status != "matched"
                )
            )
        return report

    # ── Internals ───────────────────────────────────────────────────────────

    async def _resolve_credential(self, connection: Any) -> Any:
        credential_ref = getattr(connection, "credential_ref", None)
        if not credential_ref:
            return None
        try:
            return await self._broker().reveal(connection.tenant_id, credential_ref)
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning(
                f"reconciliation credential resolution failed "
                f"tenant={connection.tenant_id}: {exc}"
            )
            return None

    @staticmethod
    def _check(
        *,
        name: str,
        expected: int,
        found: int,
        detail: str = "",
    ) -> ReconciliationCheck:
        if expected == found:
            status = "matched"
        elif expected == 0:
            status = "extra"      # provider has it, runtime does not
        elif found == 0:
            status = "missing"    # runtime expected it, provider does not
        else:
            status = "mismatched"
        return ReconciliationCheck(
            name=name, status=status, expected=expected, found=found, detail=detail,
        )


__all__ = ["ReconciliationEngine"]
