"""
Aether Backend — Fraud Signal Detectors

Each signal evaluates one dimension of fraud risk and returns a 0-100 score
with a weight factor.  Signals are composable and independently testable.

Design:
    - All signals implement the ``FraudSignal`` ABC.
    - ``evaluate`` receives the raw event dict and a context dict (session data,
      IP metadata, wallet info, device fingerprint, etc.).
    - Each signal returns a ``SignalResult`` with a normalised 0-100 score,
      its configured weight, and an explanation dict for auditing.
    - Thresholds are constructor-configurable so tenants can tune sensitivity.

Integration:
    Used by ``services.fraud.engine.FraudEngine`` which runs all registered
    signals concurrently and computes a weighted composite score.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("aether.fraud.signals")


# ========================================================================
# DATA MODELS
# ========================================================================

@dataclass
class SignalResult:
    """Output from a single fraud signal evaluation."""

    name: str
    score: float           # 0-100 normalised risk score
    weight: float          # 0.0-1.0 contribution to composite
    details: dict = field(default_factory=dict)
    triggered: bool = False


# ========================================================================
# BASE CLASS
# ========================================================================

class FraudSignal(ABC):
    """Base class for all fraud signals."""

    name: str
    weight: float

    def _result(
        self,
        score: float,
        triggered: bool = False,
        **details: Any,
    ) -> SignalResult:
        """Helper to build a consistent ``SignalResult``."""
        return SignalResult(
            name=self.name,
            score=max(0.0, min(score, 100.0)),
            weight=self.weight,
            triggered=triggered,
            details=details,
        )

    @abstractmethod
    async def evaluate(self, event: dict, context: dict) -> SignalResult:
        """Evaluate the signal and return a scored result."""
        ...


# ========================================================================
# CONCRETE SIGNALS
# ========================================================================

class BotDetectionSignal(FraudSignal):
    """Uses EdgeML bot score, mouse entropy, and timing patterns."""

    name = "bot_detection"

    def __init__(
        self,
        weight: float = 0.20,
        bot_score_threshold: float = 0.8,
        min_mouse_entropy: float = 1.5,
    ) -> None:
        self.weight = weight
        self.bot_score_threshold = bot_score_threshold
        self.min_mouse_entropy = min_mouse_entropy

    async def evaluate(self, event: dict, context: dict) -> SignalResult:
        bot_score = context.get("bot_score", 0.0)
        mouse_entropy = context.get("mouse_entropy", 5.0)
        timing_std = context.get("interaction_timing_std_ms", 200.0)

        score = 0.0
        if bot_score >= self.bot_score_threshold:
            score += 50.0 * (bot_score / 1.0)
        if mouse_entropy < self.min_mouse_entropy:
            score += 25.0
        # Suspiciously consistent timing (< 20ms std) suggests automation
        if timing_std < 20.0:
            score += 25.0

        return self._result(
            score=score,
            triggered=score >= 50.0,
            bot_score=bot_score,
            mouse_entropy=mouse_entropy,
            timing_std=timing_std,
        )


class SybilDetectionSignal(FraudSignal):
    """Wallet clustering, shared-IP patterns, and creation-timing correlation."""

    name = "sybil_detection"

    def __init__(
        self,
        weight: float = 0.20,
        max_wallets_per_ip: int = 3,
        creation_window_seconds: int = 300,
    ) -> None:
        self.weight = weight
        self.max_wallets_per_ip = max_wallets_per_ip
        self.creation_window_seconds = creation_window_seconds

    async def evaluate(self, event: dict, context: dict) -> SignalResult:
        wallets_on_ip = context.get("wallets_on_ip", 1)
        cluster_size = context.get("wallet_cluster_size", 1)
        creation_delta_s = context.get("creation_timing_delta_s")

        score = 0.0
        if wallets_on_ip > self.max_wallets_per_ip:
            score += min(40.0, 10.0 * (wallets_on_ip - self.max_wallets_per_ip))
        if cluster_size > 1:
            score += min(30.0, 10.0 * cluster_size)
        if creation_delta_s is not None and creation_delta_s < self.creation_window_seconds:
            score += 30.0

        return self._result(
            score=score,
            triggered=score >= 40.0,
            wallets_on_ip=wallets_on_ip,
            cluster_size=cluster_size,
            creation_delta_s=creation_delta_s,
        )


class VelocitySignal(FraudSignal):
    """Event frequency anomalies, per-user / per-IP / per-wallet burst detection."""

    name = "velocity"

    def __init__(
        self,
        weight: float = 0.15,
        max_events_per_minute_user: int = 30,
        max_events_per_minute_ip: int = 100,
        burst_window_seconds: int = 5,
        burst_threshold: int = 10,
    ) -> None:
        self.weight = weight
        self.max_epm_user = max_events_per_minute_user
        self.max_epm_ip = max_events_per_minute_ip
        self.burst_window = burst_window_seconds
        self.burst_threshold = burst_threshold

    async def evaluate(self, event: dict, context: dict) -> SignalResult:
        epm_user = context.get("events_per_minute_user", 0)
        epm_ip = context.get("events_per_minute_ip", 0)
        burst_count = context.get("burst_count", 0)

        score = 0.0
        if epm_user > self.max_epm_user:
            score += min(40.0, 2.0 * (epm_user - self.max_epm_user))
        if epm_ip > self.max_epm_ip:
            score += min(30.0, 1.0 * (epm_ip - self.max_epm_ip))
        if burst_count > self.burst_threshold:
            score += 30.0

        return self._result(
            score=score,
            triggered=score >= 40.0,
            epm_user=epm_user,
            epm_ip=epm_ip,
            burst_count=burst_count,
        )


class WalletAgeSignal(FraudSignal):
    """New-wallet penalty and known mixer / tumbler address detection."""

    name = "wallet_age"

    def __init__(
        self,
        weight: float = 0.10,
        new_wallet_hours: int = 24,
        known_mixers: Optional[set[str]] = None,
    ) -> None:
        self.weight = weight
        self.new_wallet_hours = new_wallet_hours
        self.known_mixers: set[str] = known_mixers or set()

    async def evaluate(self, event: dict, context: dict) -> SignalResult:
        # The reward policy engine passes identity.wallet_address verbatim,
        # which is None for user-only identities.
        wallet = (context.get("wallet_address") or "").lower()
        wallet_age_hours = context.get("wallet_age_hours")
        interacted_with: list[str] = context.get("interacted_addresses", [])

        score = 0.0
        is_new = False
        mixer_hit = False

        if wallet_age_hours is not None and wallet_age_hours < self.new_wallet_hours:
            age_ratio = max(0.0, 1.0 - wallet_age_hours / self.new_wallet_hours)
            score += 50.0 * age_ratio
            is_new = True

        for addr in interacted_with:
            if addr.lower() in self.known_mixers:
                score += 50.0
                mixer_hit = True
                break

        return self._result(
            score=score,
            triggered=score >= 40.0,
            wallet_age_hours=wallet_age_hours,
            is_new_wallet=is_new,
            mixer_detected=mixer_hit,
        )


class GeographicSignal(FraudSignal):
    """VPN / proxy detection, impossible travel, and sanctioned-region checks."""

    name = "geographic"

    SANCTIONED_REGIONS: set[str] = {"KP", "IR", "SY", "CU", "RU"}

    def __init__(
        self,
        weight: float = 0.10,
        impossible_travel_kmh: float = 900.0,
        sanctioned_regions: Optional[set[str]] = None,
    ) -> None:
        self.weight = weight
        self.impossible_travel_kmh = impossible_travel_kmh
        if sanctioned_regions is not None:
            self.SANCTIONED_REGIONS = sanctioned_regions

    async def evaluate(self, event: dict, context: dict) -> SignalResult:
        vpn_detected = context.get("vpn_detected", False)
        proxy_detected = context.get("proxy_detected", False)
        country_code = context.get("country_code", "").upper()
        travel_speed_kmh = context.get("travel_speed_kmh")

        score = 0.0
        flags: dict[str, Any] = {}

        if vpn_detected:
            score += 25.0
            flags["vpn"] = True
        if proxy_detected:
            score += 20.0
            flags["proxy"] = True
        if country_code in self.SANCTIONED_REGIONS:
            score += 50.0
            flags["sanctioned_region"] = country_code
        if travel_speed_kmh is not None and travel_speed_kmh > self.impossible_travel_kmh:
            score += 30.0
            flags["impossible_travel_kmh"] = travel_speed_kmh

        return self._result(score=score, triggered=score >= 30.0, **flags)


class BehavioralSignal(FraudSignal):
    """Session-duration anomalies, zero-interaction patterns, inhuman timing."""

    name = "behavioral"

    def __init__(
        self,
        weight: float = 0.10,
        min_session_seconds: int = 2,
        max_action_speed_ms: int = 50,
    ) -> None:
        self.weight = weight
        self.min_session_seconds = min_session_seconds
        self.max_action_speed_ms = max_action_speed_ms

    async def evaluate(self, event: dict, context: dict) -> SignalResult:
        session_duration_s = context.get("session_duration_seconds", 60)
        interaction_count = context.get("interaction_count", 1)
        avg_action_ms = context.get("avg_action_interval_ms", 500)

        score = 0.0
        if session_duration_s < self.min_session_seconds:
            score += 40.0
        if interaction_count == 0:
            score += 30.0
        if avg_action_ms < self.max_action_speed_ms:
            score += 30.0

        return self._result(
            score=score,
            triggered=score >= 40.0,
            session_duration_s=session_duration_s,
            interaction_count=interaction_count,
            avg_action_ms=avg_action_ms,
        )


class DeviceFingerprintSignal(FraudSignal):
    """Fingerprint-spoofing detection and device-farm pattern recognition."""

    name = "device_fingerprint"

    def __init__(
        self,
        weight: float = 0.10,
        max_sessions_per_fingerprint: int = 50,
        max_fingerprints_per_ip: int = 10,
    ) -> None:
        self.weight = weight
        self.max_sessions_per_fp = max_sessions_per_fingerprint
        self.max_fps_per_ip = max_fingerprints_per_ip

    async def evaluate(self, event: dict, context: dict) -> SignalResult:
        spoofing_indicators = context.get("fingerprint_spoofing_score", 0.0)
        sessions_per_fp = context.get("sessions_per_fingerprint", 1)
        fps_per_ip = context.get("fingerprints_per_ip", 1)

        score = 0.0
        score += min(40.0, spoofing_indicators * 40.0)
        if sessions_per_fp > self.max_sessions_per_fp:
            score += 30.0
        if fps_per_ip > self.max_fps_per_ip:
            score += 30.0

        return self._result(
            score=score,
            triggered=score >= 40.0,
            spoofing_score=spoofing_indicators,
            sessions_per_fingerprint=sessions_per_fp,
            fingerprints_per_ip=fps_per_ip,
        )


class TransactionPatternSignal(FraudSignal):
    """Wash-trading, circular-transfer, and dust-attack detection."""

    name = "transaction_pattern"

    def __init__(
        self,
        weight: float = 0.05,
        dust_threshold_wei: int = 1_000,
        circular_depth: int = 3,
    ) -> None:
        self.weight = weight
        self.dust_threshold_wei = dust_threshold_wei
        self.circular_depth = circular_depth

    async def evaluate(self, event: dict, context: dict) -> SignalResult:
        wash_trade_score = context.get("wash_trade_score", 0.0)
        circular_transfers = context.get("circular_transfer_count", 0)
        dust_tx_count = context.get("dust_transaction_count", 0)
        tx_amount_wei = context.get("transaction_amount_wei", 0)

        score = 0.0
        score += min(40.0, wash_trade_score * 40.0)
        if circular_transfers >= self.circular_depth:
            score += 30.0
        if dust_tx_count > 5 or (tx_amount_wei > 0 and tx_amount_wei < self.dust_threshold_wei):
            score += 30.0

        return self._result(
            score=score,
            triggered=score >= 30.0,
            wash_trade_score=wash_trade_score,
            circular_transfers=circular_transfers,
            dust_tx_count=dust_tx_count,
        )
