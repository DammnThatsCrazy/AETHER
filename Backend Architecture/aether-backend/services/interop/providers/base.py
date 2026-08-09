"""Protocol-neutral interoperability provider adapter contract.

An adapter observes one protocol deployment family. It never relays,
routes, retries, or recovers messages; its output is canonical observation
dicts consumed by the correlation engine. Implementation status must be
honest — no adapter may claim PROVIDER_LIVE without live provider
validation evidence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from services.integrations.connectors.base import ImplementationStatus
from services.interop.foundation import utc_now_iso


class InteropProviderAdapter(ABC):
    provider_id: str = ""
    provider_kind: str = "unknown"
    display_name: str = ""
    protocol_products: tuple[str, ...] = ("messaging",)
    supported_versions: tuple[str, ...] = ()
    implementation_status: ImplementationStatus = ImplementationStatus.SCAFFOLDED
    capabilities: tuple[str, ...] = ()
    known_limitations: str = ""

    def descriptor(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "display_name": self.display_name,
            "protocol_products": list(self.protocol_products),
            "supported_versions": list(self.supported_versions),
            "implementation_status": self.implementation_status.value
            if hasattr(self.implementation_status, "value") else str(self.implementation_status),
            "capabilities": list(self.capabilities),
            "known_limitations": self.known_limitations,
            "execution_by_aether": False,
        }

    @abstractmethod
    async def scan(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Scan for new observations from the last checkpoint.

        Returns (observations, new_checkpoint). Observations are canonical
        phase dicts: {correlation_key, phase, endpoint_ref, observed_at, ...}.
        Checkpoints advance monotonically; re-scanning the same checkpoint
        must be idempotent. Concrete adapters implement :meth:`_scan_cycle`;
        :class:`OperationalFieldsMixin` supervises this entry point with
        runtime telemetry (last_success/last_failure, decode failures, reorg
        counts) persisted inside the checkpoint's ``runtime`` block.
        """


class OperationalFieldsMixin:
    """Canonical operational telemetry for interop adapters.

    Exposes the operational-state shape operators read for one adapter:
    ``configured``, ``credential_status``, ``reachable``, ``latest_cursor``,
    ``latest_observation_at``, ``lag``, ``decode_failures``, ``reorg_count``,
    ``reconciliation_conflicts``, ``dead_letter_count``, ``last_success`` and
    ``last_failure``. The durable values live in the scan checkpoint under
    ``runtime`` (and per-network cursors under ``networks``), so restarting a
    supervised worker resumes with the counters intact.

    The mixin supervises :meth:`scan` as a durable, resumable loop over the
    adapter's :meth:`_scan_cycle`: it initialises the checkpoint, counts decode
    failures through :meth:`_decode_safely`, advances ``runtime`` telemetry on
    success/failure, and counts reorg observations. ``reconciliation_conflicts``
    is populated by the reconciliation engine (1E); ``dead_letter_count`` is
    advanced by the scan worker when a poison observation is quarantined.
    """

    _scan_decode_failures: int = 0

    async def scan(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Supervised scan: run ``_scan_cycle`` and record runtime telemetry.

        A ``NotImplementedError`` (unwired client / credential-gated path) is
        re-raised WITHOUT recording a failure — a guard raise is not a scan
        attempt. Any other exception records ``reachable=False`` and
        ``last_failure`` then re-raises so the supervised worker can report the
        cycle as failed.
        """
        checkpoint = dict(checkpoint or {})
        runtime = checkpoint.setdefault("runtime", {})
        self._scan_decode_failures = 0
        try:
            observations, new_checkpoint = await self._scan_cycle(checkpoint)
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001 — telemetry then re-raise
            runtime["reachable"] = False
            runtime["last_failure"] = utc_now_iso()
            runtime["failure_count"] = runtime.get("failure_count", 0) + 1
            raise
        new_checkpoint = new_checkpoint or checkpoint
        runtime = new_checkpoint.setdefault("runtime", {})
        runtime["reachable"] = True
        runtime["last_success"] = utc_now_iso()
        if self._scan_decode_failures:
            runtime["decode_failures"] = (
                runtime.get("decode_failures", 0) + self._scan_decode_failures
            )
        reorgs = sum(1 for o in observations if o.get("phase") == "reorged")
        if reorgs:
            runtime["reorg_count"] = runtime.get("reorg_count", 0) + reorgs
        stamped = [o["observed_at"] for o in observations if o.get("observed_at")]
        if stamped:
            runtime["latest_observation_at"] = max(stamped)
        return observations, new_checkpoint

    def _decode_safely(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        """decode_log with malformed-log tolerance: an exception increments the
        per-scan ``decode_failures`` counter instead of aborting the scan."""
        try:
            return self.decode_log(raw_log)
        except Exception:  # noqa: BLE001 — malformed provider log, count and skip
            self._scan_decode_failures += 1
            return None

    def operational_state(self, checkpoint: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Canonical operational-field view for one adapter.

        Read-only and side-effect free: computes the shape purely from the
        persisted checkpoint plus the adapter's own wiring state. ``lag`` is
        only reportable once a scan recorded both a head and a cursor per
        network (``head_number`` / ``last_scanned_block``).
        """
        checkpoint = checkpoint or {}
        networks = checkpoint.get("networks", {}) or {}
        runtime = checkpoint.get("runtime", {}) or {}
        cursors: list[int] = []
        heads: list[int] = []
        for state in networks.values():
            cursor = state.get("last_scanned_block")
            if cursor is None:
                cursor = state.get("last_scanned_height")
            if cursor is not None:
                cursors.append(int(cursor))
            head = state.get("head_number")
            if head is not None:
                heads.append(int(head))
        latest_cursor = max(cursors) if cursors else 0
        lags = [h - c for h, c in zip(heads, cursors) if h > 0 and c > 0]
        configured = getattr(self, "rpc", None) is not None
        return {
            "provider_id": getattr(self, "provider_id", ""),
            "configured": configured,
            "credential_status": "configured" if configured else "credential_waiting",
            "reachable": runtime.get("reachable"),
            "latest_cursor": latest_cursor,
            "latest_observation_at": runtime.get("latest_observation_at"),
            "lag": max(lags) if lags else None,
            "decode_failures": int(runtime.get("decode_failures") or 0),
            "reorg_count": int(runtime.get("reorg_count") or 0),
            "reconciliation_conflicts": int(runtime.get("reconciliation_conflicts") or 0),
            "dead_letter_count": int(runtime.get("dead_letter_count") or 0),
            "last_success": runtime.get("last_success"),
            "last_failure": runtime.get("last_failure"),
        }

    @abstractmethod
    def decode_log(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Decode one raw provider log into a canonical observation dict, or
        None when the log is not a protocol event this adapter understands."""

    def derive_path(self, observation: dict[str, Any]) -> str:
        source = observation.get("source_network_id", "unknown")
        destination = observation.get("destination_network_id", "unknown")
        return f"{self.provider_id}:{source}->{destination}"

    def snapshot_security_policy(self, path_id: str) -> dict[str, Any]:
        raise NotImplementedError(
            f"{self.provider_id}: security policy snapshots require provider "
            "credentials/RPC access (credential-gated)"
        )
