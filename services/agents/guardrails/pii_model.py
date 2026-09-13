"""
Aether Agent Layer — Production PII Detection Model
Multi-layer PII detection combining regex patterns, checksums, and
optional NER (spaCy / Presidio).

Architecture:
  Layer 1: Fast regex patterns (emails, phones, SSNs, credit cards, IPs,
           crypto addresses, API keys, JWTs)
  Layer 2: Checksum validation (Luhn for credit cards, SSN ranges)
  Layer 3: NER model for unstructured PII (person names, addresses,
           dates of birth) — requires spaCy; gracefully degrades if absent.

Usage:
    detector = PIIDetectorModel()
    findings = detector.scan("Call me at 555-123-4567 or email john@acme.com")
    redacted = detector.redact("My SSN is 123-45-6789")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("aether.guardrails.pii")


# ---------------------------------------------------------------------------
# PII Categories
# ---------------------------------------------------------------------------

class PIICategory(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    CRYPTO_WALLET = "crypto_wallet"
    API_KEY = "api_key"
    JWT = "jwt"
    PERSON_NAME = "person_name"
    PHYSICAL_ADDRESS = "physical_address"
    DATE_OF_BIRTH = "date_of_birth"
    PASSPORT = "passport"


@dataclass
class PIIFinding:
    category: PIICategory
    value: str
    start: int
    end: int
    confidence: float = 1.0
    layer: str = "regex"  # "regex" | "checksum" | "ner"


# ---------------------------------------------------------------------------
# Layer 1: Regex Patterns
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[PIICategory, re.Pattern, float]] = [
    # Email
    (PIICategory.EMAIL,
     re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
     0.95),
    # US Phone (various formats)
    (PIICategory.PHONE,
     re.compile(
         r"(?:\+1[\s.-]?)?"
         r"(?:\(?\d{3}\)?[\s.-]?)"
         r"\d{3}[\s.-]?\d{4}"
     ),
     0.85),
    # SSN
    (PIICategory.SSN,
     re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
     0.95),
    # Credit card (13-19 digits, with optional separators)
    (PIICategory.CREDIT_CARD,
     re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
     0.70),  # low initial confidence; raised by Luhn check
    # IPv4
    (PIICategory.IP_ADDRESS,
     re.compile(
         r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
         r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
     ),
     0.80),
    # Ethereum address
    (PIICategory.CRYPTO_WALLET,
     re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
     0.90),
    # Bitcoin address (legacy + segwit)
    (PIICategory.CRYPTO_WALLET,
     re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b"),
     0.75),
    # API key patterns (generic "sk_", "ak_", "key-" prefixes)
    (PIICategory.API_KEY,
     re.compile(r"\b(?:sk|ak|pk|key)[-_][a-zA-Z0-9_\-]{20,}\b"),
     0.85),
    # JWT
    (PIICategory.JWT,
     re.compile(r"\beyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b"),
     0.95),
    # Date of birth patterns (MM/DD/YYYY, YYYY-MM-DD)
    (PIICategory.DATE_OF_BIRTH,
     re.compile(
         r"\b(?:0[1-9]|1[0-2])[/\-](?:0[1-9]|[12]\d|3[01])[/\-]"
         r"(?:19|20)\d{2}\b"
     ),
     0.60),
    # US passport
    (PIICategory.PASSPORT,
     re.compile(r"\b[A-Z]\d{8}\b"),
     0.50),
]


def _regex_scan(text: str) -> list[PIIFinding]:
    """Layer 1: Fast regex pattern matching."""
    findings: list[PIIFinding] = []
    for category, pattern, confidence in _PATTERNS:
        for match in pattern.finditer(text):
            findings.append(PIIFinding(
                category=category,
                value=match.group(),
                start=match.start(),
                end=match.end(),
                confidence=confidence,
                layer="regex",
            ))
    return findings


# ---------------------------------------------------------------------------
# Layer 2: Checksum Validation
# ---------------------------------------------------------------------------

def _luhn_check(number_str: str) -> bool:
    """Luhn algorithm for credit card validation."""
    digits = [int(d) for d in number_str if d.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _validate_ssn(ssn: str) -> bool:
    """Basic SSN range validation (reject known-invalid ranges)."""
    parts = ssn.split("-")
    if len(parts) != 3:
        return False
    area = int(parts[0])
    # Area 000, 666, and 900-999 are invalid
    if area == 0 or area == 666 or 900 <= area <= 999:
        return False
    group = int(parts[1])
    serial = int(parts[2])
    return group > 0 and serial > 0


def _checksum_refine(findings: list[PIIFinding]) -> list[PIIFinding]:
    """Layer 2: Promote or demote findings based on checksum validation."""
    refined: list[PIIFinding] = []
    for f in findings:
        if f.category == PIICategory.CREDIT_CARD:
            if _luhn_check(f.value):
                f.confidence = 0.95
                f.layer = "checksum"
            else:
                f.confidence = 0.20  # likely not a real CC
        elif f.category == PIICategory.SSN:
            if _validate_ssn(f.value):
                f.confidence = 0.97
                f.layer = "checksum"
            else:
                f.confidence = 0.30
        refined.append(f)
    return refined


# ---------------------------------------------------------------------------
# Layer 3: NER-based Detection (optional spaCy / Presidio)
# ---------------------------------------------------------------------------

_NER_MODEL = None
_NER_AVAILABLE = False

try:
    import spacy
    try:
        _NER_MODEL = spacy.load("en_core_web_sm")
        _NER_AVAILABLE = True
        logger.info("spaCy NER model loaded for PII detection")
    except OSError:
        logger.info(
            "spaCy model 'en_core_web_sm' not installed — "
            "NER layer disabled. Run: python -m spacy download en_core_web_sm"
        )
except ImportError:
    logger.info("spaCy not installed — NER layer disabled")


# Mapping from spaCy entity labels to PII categories
_SPACY_LABEL_MAP: dict[str, PIICategory] = {
    "PERSON": PIICategory.PERSON_NAME,
    "GPE": PIICategory.PHYSICAL_ADDRESS,   # geopolitical entity
    "LOC": PIICategory.PHYSICAL_ADDRESS,
    "FAC": PIICategory.PHYSICAL_ADDRESS,   # facility / building
}


def _ner_scan(text: str) -> list[PIIFinding]:
    """Layer 3: NER-based entity extraction for unstructured PII."""
    if not _NER_AVAILABLE or _NER_MODEL is None:
        return []

    findings: list[PIIFinding] = []
    doc = _NER_MODEL(text)
    for ent in doc.ents:
        category = _SPACY_LABEL_MAP.get(ent.label_)
        if category is not None:
            findings.append(PIIFinding(
                category=category,
                value=ent.text,
                start=ent.start_char,
                end=ent.end_char,
                confidence=0.70,
                layer="ner",
            ))
    return findings


# ---------------------------------------------------------------------------
# Composite PII Detector Model
# ---------------------------------------------------------------------------

class PIIDetectorModel:
    """
    Production PII detector that chains three layers:
      1. Regex patterns (fast, high-recall)
      2. Checksum validation (precision boost)
      3. NER model (unstructured PII; optional)

    Drop-in replacement for the original regex-only PIIDetector.
    """

    def __init__(self, min_confidence: float = 0.50):
        self.min_confidence = min_confidence

    @property
    def ner_available(self) -> bool:
        return _NER_AVAILABLE

    def scan(self, text: str) -> list[PIIFinding]:
        """
        Full three-layer scan. Returns de-duplicated findings above
        the min_confidence threshold, sorted by position.
        """
        if not text:
            return []

        # Layer 1: regex
        findings = _regex_scan(text)

        # Layer 2: checksum refinement
        findings = _checksum_refine(findings)

        # Layer 3: NER (additive)
        findings.extend(_ner_scan(text))

        # De-duplicate overlapping spans (keep highest confidence)
        findings = _deduplicate(findings)

        # Filter by confidence
        findings = [f for f in findings if f.confidence >= self.min_confidence]

        # Sort by position
        findings.sort(key=lambda f: f.start)

        if findings:
            logger.info(
                f"PII scan: {len(findings)} finding(s) "
                f"({', '.join(f.category.value for f in findings)})"
            )

        return findings

    def contains_pii(self, text: str) -> bool:
        """Quick boolean check — stops at first finding above threshold."""
        if not text:
            return False
        # Fast path: check regex patterns only for speed
        for category, pattern, confidence in _PATTERNS:
            if confidence >= self.min_confidence and pattern.search(text):
                return True
        # Slow path: NER
        return len(_ner_scan(text)) > 0

    def redact(
        self,
        text: str,
        replacement: str = "[REDACTED]",
        categories: Optional[set[PIICategory]] = None,
    ) -> str:
        """
        Return text with PII replaced by [REDACTED].
        Optionally filter to specific categories.
        """
        findings = self.scan(text)
        if categories:
            findings = [f for f in findings if f.category in categories]

        # Replace from end to preserve offsets
        result = text
        for f in reversed(findings):
            tag = f"[{f.category.value.upper()}_REDACTED]"
            result = result[:f.start] + (replacement or tag) + result[f.end:]
        return result

    def scan_dict(
        self,
        data: dict[str, Any],
        prefix: str = "",
    ) -> list[tuple[str, PIIFinding]]:
        """
        Recursively scan all string values in a dict.
        Returns list of (dotted_key, PIIFinding) pairs.
        """
        results: list[tuple[str, PIIFinding]] = []
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, str):
                for finding in self.scan(value):
                    results.append((full_key, finding))
            elif isinstance(value, dict):
                results.extend(self.scan_dict(value, prefix=full_key))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, str):
                        for finding in self.scan(item):
                            results.append((f"{full_key}[{i}]", finding))
                    elif isinstance(item, dict):
                        results.extend(
                            self.scan_dict(item, prefix=f"{full_key}[{i}]")
                        )
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deduplicate(findings: list[PIIFinding]) -> list[PIIFinding]:
    """Remove overlapping findings, keeping the one with highest confidence."""
    if not findings:
        return findings

    findings.sort(key=lambda f: (f.start, -f.confidence))
    deduped: list[PIIFinding] = [findings[0]]

    for f in findings[1:]:
        prev = deduped[-1]
        # If this finding overlaps with the previous one, keep the better one
        if f.start < prev.end:
            if f.confidence > prev.confidence:
                deduped[-1] = f
        else:
            deduped.append(f)

    return deduped
