"""Deterministic, explainable device risk.

This module deliberately does *not* fingerprint. It reads four signals that the
backend already produces as a by-product of enforcing the device model, records
which of them fired in the device's ``metadata``, and derives a risk state from
that record:

``counter_regression``
    A WebAuthn assertion reported a signature counter at or below the one the
    server already stored. For an authenticator that maintains a counter this
    is the textbook cloning indicator.
``proof_failure_burst``
    Repeated device-proof signature failures inside a short window. One failure
    is noise (a stale challenge, a closed tab); a burst is someone trying keys.
``approval_state_withdrawn``
    The device is suspended or revoked. Risk follows the approval decision so a
    withdrawn device cannot look healthy in the console.
``browser_family_changed``
    The coarse browser family (Chrome / Firefox / Safari / Edge) no longer
    matches the family recorded at registration. The proof key is bound to one
    browser profile, so a family change means the request is not coming from
    the enrolled profile.

Risk only ever escalates here. An evaluation never quietly lowers a device back
to ``ok``: clearing risk is an operator decision (approve / rename / re-enroll),
not something a well-timed request can achieve by looking normal once.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

from ..access.contracts import DeviceRiskState, TrustedDevice, now_iso
from .repository import TrustedDeviceRepository, parse_ts

logger = get_logger("aether.kyber.devices.risk")

#: Ordering used to decide whether a computed state is an escalation.
_RISK_ORDER: dict[str, int] = {"ok": 0, "suspect": 1, "blocked": 2}

#: Window and threshold for the proof-failure burst signal.
PROOF_FAILURE_WINDOW = timedelta(minutes=10)
PROOF_FAILURE_THRESHOLD = 5

#: Coarse browser families. Order matters — Edge and Chrome both say "Chrome",
#: and Chrome says "Safari", so the more specific token has to win.
_BROWSER_FAMILIES: tuple[tuple[str, str], ...] = (
    ("edg/", "edge"),
    ("opr/", "opera"),
    ("firefox/", "firefox"),
    ("chrome/", "chrome"),
    ("chromium/", "chrome"),
    ("safari/", "safari"),
)


def browser_family(user_agent: Optional[str]) -> Optional[str]:
    """Coarse browser family from a user-agent string.

    Family only — no version, no platform build, no entropy worth calling a
    fingerprint. It exists to answer one question: is this the browser the
    proof key was enrolled in?
    """
    if not user_agent:
        return None
    lowered = user_agent.lower()
    for token, family in _BROWSER_FAMILIES:
        if token in lowered:
            return family
    return None


class DeviceRiskService:
    """Computes and persists a device's risk state from recorded signals."""

    def __init__(self, devices: Optional[TrustedDeviceRepository] = None) -> None:
        self._devices = devices or TrustedDeviceRepository()

    # ── Evaluation ────────────────────────────────────────────────────────────

    async def evaluate(
        self,
        device: TrustedDevice,
        *,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> DeviceRiskState:
        """Recompute the device's risk state and persist the contributing signals."""
        signals = self._signals(device, user_agent=user_agent)
        computed: DeviceRiskState = "suspect" if signals else "ok"
        resolved = self._escalate(device.risk_state, computed)

        device.metadata["risk_signals"] = signals
        device.metadata["risk_evaluated_at"] = now_iso()
        if client_ip:
            # Coarse provenance for the investigator reading the record later.
            # Never used as an authorization input: IPs move, devices do not.
            device.metadata["risk_last_client_ip"] = client_ip
        if user_agent:
            device.metadata["risk_last_browser_family"] = browser_family(user_agent)
        device.risk_state = resolved
        await self._devices.save(device)

        if resolved != "ok":
            metrics.increment(
                "kyber_device_risk_total", labels={"state": resolved}
            )
        return resolved

    def _signals(
        self, device: TrustedDevice, *, user_agent: Optional[str]
    ) -> list[str]:
        signals: list[str] = []
        meta = device.metadata or {}

        if meta.get("counter_regression_at"):
            signals.append("counter_regression")

        if self._recent_proof_failures(device) >= PROOF_FAILURE_THRESHOLD:
            signals.append("proof_failure_burst")

        if device.approval_state in ("suspended", "revoked"):
            signals.append("approval_state_withdrawn")

        observed = browser_family(user_agent)
        if device.browser_family and observed and observed != device.browser_family:
            signals.append("browser_family_changed")

        return signals

    @staticmethod
    def _escalate(current: DeviceRiskState, computed: DeviceRiskState) -> DeviceRiskState:
        if _RISK_ORDER.get(computed, 0) > _RISK_ORDER.get(current, 0):
            return computed
        return current

    @staticmethod
    def _recent_proof_failures(device: TrustedDevice) -> int:
        cutoff = utc_now() - PROOF_FAILURE_WINDOW
        recorded = (device.metadata or {}).get("proof_failures") or []
        count = 0
        for stamp in recorded:
            parsed = parse_ts(stamp)
            if parsed is not None and parsed >= cutoff:
                count += 1
        return count

    # ── Signal recording ──────────────────────────────────────────────────────

    async def record_proof_failure(
        self, device_id: str, *, reason: str
    ) -> Optional[DeviceRiskState]:
        """Append a device-proof failure and escalate once the burst threshold trips."""
        device = await self._devices.get(device_id)
        if device is None:
            return None

        cutoff = utc_now() - PROOF_FAILURE_WINDOW
        history = [
            stamp
            for stamp in ((device.metadata or {}).get("proof_failures") or [])
            if (parse_ts(stamp) or cutoff) >= cutoff
        ]
        history.append(now_iso())
        # Bounded so a sustained attack cannot grow the row without limit.
        device.metadata["proof_failures"] = history[-(PROOF_FAILURE_THRESHOLD * 4):]
        device.metadata["last_proof_failure_reason"] = reason
        await self._devices.save(device)

        if len(history) >= PROOF_FAILURE_THRESHOLD:
            updated = await self.mark_suspect(device_id, "proof_failure_burst")
            return updated.risk_state if updated else "suspect"
        return device.risk_state

    async def clear_proof_failures(self, device_id: str) -> None:
        """Reset the burst counter after a successful proof.

        This clears the *counter*, never the risk state — a device that already
        escalated stays escalated until an operator acts on it.
        """
        device = await self._devices.get(device_id)
        if device is None or not (device.metadata or {}).get("proof_failures"):
            return
        device.metadata["proof_failures"] = []
        await self._devices.save(device)

    async def mark_suspect(self, device_id: str, reason: str) -> Optional[TrustedDevice]:
        """Escalate a device to ``suspect``. Idempotent."""
        return await self._mark(device_id, "suspect", reason)

    async def mark_blocked(self, device_id: str, reason: str) -> Optional[TrustedDevice]:
        """Escalate a device to ``blocked``. Idempotent.

        A blocked device fails :meth:`DeviceApprovalService.is_usable` even
        while its approval record still says ``approved``.
        """
        return await self._mark(device_id, "blocked", reason)

    async def _mark(
        self, device_id: str, state: DeviceRiskState, reason: str
    ) -> Optional[TrustedDevice]:
        device = await self._devices.get(device_id)
        if device is None:
            return None
        resolved = self._escalate(device.risk_state, state)
        reasons = list((device.metadata or {}).get("risk_reasons") or [])
        entry = {"state": state, "reason": reason, "at": now_iso()}
        reasons.append(entry)
        device.metadata["risk_reasons"] = reasons[-20:]
        if state == "suspect" and reason == "counter_regression":
            device.metadata["counter_regression_at"] = entry["at"]
        device.risk_state = resolved
        await self._devices.save(device)
        logger.warning(
            "kyber device risk escalated device_id=%s state=%s reason=%s",
            device_id,
            resolved,
            reason,
        )
        metrics.increment("kyber_device_risk_total", labels={"state": resolved})
        return device


device_risk_service = DeviceRiskService()

__all__ = [
    "PROOF_FAILURE_THRESHOLD",
    "PROOF_FAILURE_WINDOW",
    "DeviceRiskService",
    "browser_family",
    "device_risk_service",
]
