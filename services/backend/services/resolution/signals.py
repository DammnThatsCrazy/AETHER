"""
Aether Backend — Identity Resolution Signal Detectors

Each signal evaluates one dimension of identity similarity and returns a
confidence score (0.0-1.0) indicating likelihood that two profiles belong
to the same person.

Design:
    - All signals implement the ``ResolutionSignal`` ABC.
    - ``evaluate`` receives two profile dicts and a context dict (graph data,
      session metadata, enrichment results).
    - Each signal returns a ``ResolutionSignalResult`` with a normalised 0-1
      confidence, match type (deterministic | probabilistic), and an
      explanation dict for auditing.
    - Weights are constructor-configurable so tenants can tune sensitivity.

Integration:
    Used by ``services.resolution.engine.IdentityResolutionEngine`` which runs
    all registered signals and feeds results into the ``ResolutionRulesEngine``.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("aether.resolution.signals")


# ========================================================================
# DATA MODELS
# ========================================================================

@dataclass
class ResolutionSignalResult:
    """Output from a single resolution signal evaluation."""

    name: str
    confidence: float       # 0.0 - 1.0
    match_type: str         # "deterministic" | "probabilistic"
    details: dict = field(default_factory=dict)
    is_match: bool = False


# ========================================================================
# BASE CLASS
# ========================================================================

class ResolutionSignal(ABC):
    """Base class for all identity resolution signals."""

    name: str
    match_type: str
    weight: float

    def _result(
        self,
        confidence: float,
        is_match: bool = False,
        **details: Any,
    ) -> ResolutionSignalResult:
        """Helper to build a consistent ``ResolutionSignalResult``."""
        return ResolutionSignalResult(
            name=self.name,
            confidence=max(0.0, min(confidence, 1.0)),
            match_type=self.match_type,
            details={"weight": self.weight, **details},
            is_match=is_match,
        )

    @abstractmethod
    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        """Evaluate the signal and return a scored result."""
        ...


# ========================================================================
# DETERMINISTIC SIGNALS (confidence=1.0 on match)
# ========================================================================

class UserIdSignal(ResolutionSignal):
    """Direct user_id comparison — exact string match."""

    name = "user_id"
    match_type = "deterministic"

    def __init__(self, weight: float = 1.0) -> None:
        self.weight = weight

    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        uid_a = profile_a.get("user_id", "").strip()
        uid_b = profile_b.get("user_id", "").strip()

        if uid_a and uid_b and uid_a == uid_b:
            return self._result(
                confidence=1.0,
                is_match=True,
                user_id=uid_a,
            )

        return self._result(confidence=0.0, is_match=False)


class EmailSignal(ResolutionSignal):
    """Email hash comparison with normalisation (lowercase, trim, Gmail dot removal)."""

    name = "email"
    match_type = "deterministic"

    def __init__(self, weight: float = 1.0) -> None:
        self.weight = weight

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Normalize email for comparison: lowercase, strip, remove Gmail dots."""
        email = email.lower().strip()
        if not email:
            return ""
        local, _, domain = email.partition("@")
        if not domain:
            return email
        # Remove dots from Gmail local parts (john.doe -> johndoe)
        if domain in ("gmail.com", "googlemail.com"):
            local = local.replace(".", "")
            # Remove everything after '+' (sub-addressing)
            local = local.split("+")[0]
        return f"{local}@{domain}"

    @staticmethod
    def _hash_value(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        email_a = profile_a.get("email", "") or profile_a.get("email_hash", "")
        email_b = profile_b.get("email", "") or profile_b.get("email_hash", "")

        if not email_a or not email_b:
            return self._result(confidence=0.0, is_match=False)

        # If raw emails are provided, normalize and hash
        if "@" in email_a:
            email_a = self._hash_value(self._normalize_email(email_a))
        if "@" in email_b:
            email_b = self._hash_value(self._normalize_email(email_b))

        if email_a == email_b:
            return self._result(
                confidence=1.0,
                is_match=True,
                match_field="email_hash",
            )

        return self._result(confidence=0.0, is_match=False)


class PhoneSignal(ResolutionSignal):
    """Phone hash comparison with E.164 normalisation."""

    name = "phone"
    match_type = "deterministic"

    _DIGITS_ONLY = re.compile(r"[^\d+]")

    def __init__(self, weight: float = 1.0) -> None:
        self.weight = weight

    @classmethod
    def _normalize_phone(cls, phone: str) -> str:
        """Normalise to E.164-like format: strip non-digits except leading +."""
        phone = phone.strip()
        if not phone:
            return ""
        has_plus = phone.startswith("+")
        digits = cls._DIGITS_ONLY.sub("", phone).lstrip("+")
        return f"+{digits}" if has_plus else digits

    @staticmethod
    def _hash_value(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        phone_a = profile_a.get("phone", "") or profile_a.get("phone_hash", "")
        phone_b = profile_b.get("phone", "") or profile_b.get("phone_hash", "")

        if not phone_a or not phone_b:
            return self._result(confidence=0.0, is_match=False)

        # If raw phones are provided, normalize and hash
        if any(c.isdigit() for c in phone_a) and len(phone_a) < 64:
            phone_a = self._hash_value(self._normalize_phone(phone_a))
        if any(c.isdigit() for c in phone_b) and len(phone_b) < 64:
            phone_b = self._hash_value(self._normalize_phone(phone_b))

        if phone_a == phone_b:
            return self._result(
                confidence=1.0,
                is_match=True,
                match_field="phone_hash",
            )

        return self._result(confidence=0.0, is_match=False)


class WalletAddressSignal(ResolutionSignal):
    """Wallet address comparison — lowercase match on the same VM (EVM, SVM, etc.)."""

    name = "wallet_address"
    match_type = "deterministic"

    def __init__(self, weight: float = 1.0) -> None:
        self.weight = weight

    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        wallets_a: list[dict] = profile_a.get("wallets", [])
        wallets_b: list[dict] = profile_b.get("wallets", [])

        if not wallets_a or not wallets_b:
            return self._result(confidence=0.0, is_match=False)

        for wa in wallets_a:
            addr_a = wa.get("address", "").lower()
            vm_a = wa.get("vm", "evm").lower()
            for wb in wallets_b:
                addr_b = wb.get("address", "").lower()
                vm_b = wb.get("vm", "evm").lower()
                if addr_a and addr_b and addr_a == addr_b and vm_a == vm_b:
                    return self._result(
                        confidence=1.0,
                        is_match=True,
                        matched_address=addr_a,
                        vm=vm_a,
                    )

        return self._result(confidence=0.0, is_match=False)


class OAuthSignal(ResolutionSignal):
    """OAuth provider + subject comparison — exact match on provider:subject pair."""

    name = "oauth"
    match_type = "deterministic"

    def __init__(self, weight: float = 1.0) -> None:
        self.weight = weight

    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        oauth_a = profile_a.get("oauth", {})
        oauth_b = profile_b.get("oauth", {})

        provider_a = oauth_a.get("provider", "").lower()
        subject_a = oauth_a.get("subject", "")
        provider_b = oauth_b.get("provider", "").lower()
        subject_b = oauth_b.get("subject", "")

        if not (provider_a and subject_a and provider_b and subject_b):
            return self._result(confidence=0.0, is_match=False)

        if provider_a == provider_b and subject_a == subject_b:
            return self._result(
                confidence=1.0,
                is_match=True,
                provider=provider_a,
            )

        return self._result(confidence=0.0, is_match=False)


# ========================================================================
# PROBABILISTIC SIGNALS (variable confidence)
# ========================================================================

class FingerprintSimilaritySignal(ResolutionSignal):
    """Component-level fingerprint scoring with per-component weights."""

    name = "fingerprint_similarity"
    match_type = "probabilistic"

    # Per-component contribution to the overall fingerprint similarity score.
    COMPONENT_WEIGHTS: dict[str, float] = {
        "canvas_hash": 0.30,
        "webgl_renderer": 0.15,
        "webgl_vendor": 0.10,
        "audio_hash": 0.15,
        "screen": 0.05,
        "timezone": 0.05,
        "language": 0.05,
        "platform": 0.05,
        "hardware": 0.05,
        "fonts": 0.05,
    }

    def __init__(self, weight: float = 0.35) -> None:
        self.weight = weight

    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        fp_a: dict = profile_a.get("fingerprint", {})
        fp_b: dict = profile_b.get("fingerprint", {})

        if not fp_a or not fp_b:
            return self._result(confidence=0.0, is_match=False)

        score = 0.0
        matched_components: list[str] = []

        for component, comp_weight in self.COMPONENT_WEIGHTS.items():
            val_a = fp_a.get(component)
            val_b = fp_b.get(component)
            if val_a is not None and val_b is not None and val_a == val_b:
                score += comp_weight
                matched_components.append(component)

        return self._result(
            confidence=score,
            is_match=score >= 0.5,
            matched_components=matched_components,
            component_score=round(score, 4),
        )


class NetworkGraphProximitySignal(ResolutionSignal):
    """Jaccard similarity on shared graph neighbours."""

    name = "network_graph_proximity"
    match_type = "probabilistic"

    def __init__(self, weight: float = 0.20) -> None:
        self.weight = weight

    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        neighbors_a: set[str] = set(context.get("neighbors_a", []))
        neighbors_b: set[str] = set(context.get("neighbors_b", []))

        if not neighbors_a and not neighbors_b:
            return self._result(confidence=0.0, is_match=False)

        intersection = neighbors_a & neighbors_b
        union = neighbors_a | neighbors_b

        jaccard = len(intersection) / len(union) if union else 0.0

        return self._result(
            confidence=jaccard,
            is_match=jaccard >= 0.3,
            shared_neighbors=len(intersection),
            total_union=len(union),
            jaccard=round(jaccard, 4),
        )


class IPClusterSignal(ResolutionSignal):
    """IP-based proximity: same IP, same /24 subnet, same ASN."""

    name = "ip_cluster"
    match_type = "probabilistic"

    def __init__(
        self,
        weight: float = 0.15,
        same_ip_confidence: float = 0.8,
        same_subnet_confidence: float = 0.4,
        same_asn_confidence: float = 0.15,
        vpn_discount: float = 0.5,
    ) -> None:
        self.weight = weight
        self.same_ip_confidence = same_ip_confidence
        self.same_subnet_confidence = same_subnet_confidence
        self.same_asn_confidence = same_asn_confidence
        self.vpn_discount = vpn_discount

    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        ip_a = profile_a.get("ip_hash", "")
        ip_b = profile_b.get("ip_hash", "")
        subnet_a = profile_a.get("ip_range", "")
        subnet_b = profile_b.get("ip_range", "")
        asn_a = profile_a.get("asn", 0)
        asn_b = profile_b.get("asn", 0)
        is_vpn_a = profile_a.get("is_vpn", False)
        is_vpn_b = profile_b.get("is_vpn", False)

        confidence = 0.0
        reason = "no_match"

        if ip_a and ip_b and ip_a == ip_b:
            confidence = self.same_ip_confidence
            reason = "same_ip"
        elif subnet_a and subnet_b and subnet_a == subnet_b:
            confidence = self.same_subnet_confidence
            reason = "same_subnet"
        elif asn_a and asn_b and asn_a == asn_b:
            confidence = self.same_asn_confidence
            reason = "same_asn"

        # Discount if either side is VPN / proxy
        if (is_vpn_a or is_vpn_b) and confidence > 0:
            confidence *= self.vpn_discount
            reason += "_vpn_discounted"

        return self._result(
            confidence=confidence,
            is_match=confidence >= 0.3,
            reason=reason,
            ip_match=ip_a == ip_b if (ip_a and ip_b) else False,
            subnet_match=subnet_a == subnet_b if (subnet_a and subnet_b) else False,
        )


class BehavioralSimilaritySignal(ResolutionSignal):
    """Cosine similarity on user behavioural feature vectors."""

    name = "behavioral_similarity"
    match_type = "probabilistic"

    def __init__(self, weight: float = 0.15) -> None:
        self.weight = weight

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two equal-length vectors."""
        if len(vec_a) != len(vec_b) or not vec_a:
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = math.sqrt(sum(a * a for a in vec_a))
        mag_b = math.sqrt(sum(b * b for b in vec_b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        vec_a: list[float] = context.get("behavior_vector_a", [])
        vec_b: list[float] = context.get("behavior_vector_b", [])

        if not vec_a or not vec_b:
            return self._result(confidence=0.0, is_match=False)

        similarity = self._cosine_similarity(vec_a, vec_b)
        # Clamp to [0, 1] — cosine can be negative for opposed vectors
        similarity = max(0.0, similarity)

        return self._result(
            confidence=similarity,
            is_match=similarity >= 0.7,
            cosine_similarity=round(similarity, 4),
            vector_dim=len(vec_a),
        )


class LocationProximitySignal(ResolutionSignal):
    """Geographic proximity scoring: city > region > country."""

    name = "location_proximity"
    match_type = "probabilistic"

    def __init__(
        self,
        weight: float = 0.15,
        same_city_confidence: float = 0.6,
        same_region_confidence: float = 0.3,
        same_country_confidence: float = 0.1,
    ) -> None:
        self.weight = weight
        self.same_city_confidence = same_city_confidence
        self.same_region_confidence = same_region_confidence
        self.same_country_confidence = same_country_confidence

    async def evaluate(
        self, profile_a: dict, profile_b: dict, context: dict,
    ) -> ResolutionSignalResult:
        city_a = profile_a.get("city", "").lower()
        city_b = profile_b.get("city", "").lower()
        region_a = profile_a.get("region", "").lower()
        region_b = profile_b.get("region", "").lower()
        country_a = profile_a.get("country_code", "").upper()
        country_b = profile_b.get("country_code", "").upper()

        confidence = 0.0
        granularity = "none"

        if city_a and city_b and city_a == city_b:
            confidence = self.same_city_confidence
            granularity = "city"
        elif region_a and region_b and region_a == region_b:
            confidence = self.same_region_confidence
            granularity = "region"
        elif country_a and country_b and country_a == country_b:
            confidence = self.same_country_confidence
            granularity = "country"

        return self._result(
            confidence=confidence,
            is_match=confidence >= 0.3,
            granularity=granularity,
            city_match=city_a == city_b if (city_a and city_b) else False,
            region_match=region_a == region_b if (region_a and region_b) else False,
            country_match=country_a == country_b if (country_a and country_b) else False,
        )


# ========================================================================
# SIGNAL REGISTRY
# ========================================================================

def default_signals() -> list[ResolutionSignal]:
    """Return the full default signal suite with standard weights."""
    return [
        # Deterministic
        UserIdSignal(),
        EmailSignal(),
        PhoneSignal(),
        WalletAddressSignal(),
        OAuthSignal(),
        # Probabilistic
        FingerprintSimilaritySignal(weight=0.35),
        NetworkGraphProximitySignal(weight=0.20),
        IPClusterSignal(weight=0.15),
        BehavioralSimilaritySignal(weight=0.15),
        LocationProximitySignal(weight=0.15),
    ]
