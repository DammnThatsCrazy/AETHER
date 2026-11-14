"""The discovery frame every detector reads, plus shared statistics helpers."""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from ..extraction import ExtractedEvent, ExtractionResult

SESSION_GAP = timedelta(minutes=30)


@dataclass(frozen=True)
class DetectorConfig:
    min_support: int = 3              # distinct entities behind a pattern
    min_cluster: int = 3              # entities in a cluster / cohort
    max_patterns_per_detector: int = 25
    max_entity_share: float = 0.5     # a "pattern" covering more of the population is the norm
    sequence_min_n: int = 3
    sequence_max_n: int = 5
    sequence_min_lift: float = 2.0
    cohort_similarity: float = 0.95
    cohort_min_events: int = 5
    burst_window_seconds: int = 300
    burst_min_events: int = 10
    burst_max_p: float = 1e-4
    lockstep_window_seconds: int = 60
    lockstep_min_entities: int = 5
    outlier_min_population: int = 20
    outlier_z: float = 6.0
    motif_min_instances: int = 3
    motif_min_lift: float = 3.0
    drift_min_events: int = 20


@dataclass
class DiscoveryFrame:
    tenant_id: str
    extraction: ExtractionResult
    baseline: dict[str, Any]
    config: DetectorConfig = field(default_factory=DetectorConfig)
    external_edges: list[dict[str, Any]] = field(default_factory=list)
    known_motif_signatures: frozenset = frozenset()

    def __post_init__(self) -> None:
        self.events: list[ExtractedEvent] = [e for e in self.extraction.events if e.entity]
        timed = [e for e in self.events if e.ts]
        by_entity: dict[str, list[ExtractedEvent]] = defaultdict(list)
        for e in timed:
            by_entity[e.entity].append(e)
        for evs in by_entity.values():
            evs.sort(key=lambda e: (e.ts, e.event_id))
        self.by_entity = dict(by_entity)
        self.entity_count = len({e.entity for e in self.events})
        stamps = [e.ts for e in timed]
        self.window_start: Optional[datetime] = min(stamps) if stamps else None
        self.window_end: Optional[datetime] = max(stamps) if stamps else None
        span = (self.window_end - self.window_start).total_seconds() if stamps else 0.0
        self.window_hours = max(span / 3600.0, 1.0)

    def sessions(self) -> dict[str, list[list[ExtractedEvent]]]:
        """Per-entity activity split wherever the gap exceeds ``SESSION_GAP``."""
        if hasattr(self, "_sessions"):
            return self._sessions
        out: dict[str, list[list[ExtractedEvent]]] = {}
        for entity, evs in self.by_entity.items():
            sessions: list[list[ExtractedEvent]] = [[evs[0]]]
            for prev, cur in zip(evs, evs[1:]):
                if cur.ts - prev.ts > SESSION_GAP:
                    sessions.append([cur])
                else:
                    sessions[-1].append(cur)
            out[entity] = sessions
        self._sessions = out
        return out

    def token_rates(self) -> dict[str, float]:
        counts = Counter(e.token for e in self.events)
        return {t: c / self.window_hours for t, c in counts.items()}

    def entities_share_ok(self, n: int) -> bool:
        if self.entity_count <= 0:
            return False
        return n <= max(self.config.min_support, self.config.max_entity_share * self.entity_count)


def bounds(events: Iterable[ExtractedEvent]) -> tuple[Optional[datetime], Optional[datetime]]:
    stamps = [e.ts for e in events if e.ts]
    return (min(stamps), max(stamps)) if stamps else (None, None)


def robust_stats(values: list[float]) -> tuple[float, float]:
    """Median and MAD-based sigma (MAD * 1.4826), never zero."""
    if not values:
        return 0.0, 1.0
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values])
    sigma = mad * 1.4826
    if sigma <= 1e-9:
        mean_dev = sum(abs(v - med) for v in values) / len(values)
        sigma = mean_dev * 1.2533 if mean_dev > 1e-9 else 1.0
    return med, sigma


def poisson_sf(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam), computed in log space."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    log_term = -lam  # log P(X=0)
    cdf = math.exp(log_term)
    for i in range(1, k):
        log_term += math.log(lam) - math.log(i)
        cdf += math.exp(log_term)
    return max(0.0, 1.0 - cdf)


def risk_categories_for(tokens: Iterable[str] = (), attr_types: Iterable[str] = (),
                        entity_kinds: Iterable[str] = (), relations: Iterable[str] = ()) -> list[str]:
    """Map what a pattern is made of onto registered Risk360 dimension keys."""
    cats: set[str] = set()
    low = [t.lower() for t in tokens]
    joined = " ".join(low)
    if any(w in joined for w in ("pay", "charge", "card", "checkout", "refund", "invoice")):
        cats.add("payment")
    if any(w in joined for w in ("transfer", "swap", "withdraw", "deposit", "transaction", "tx_", "settle", "trade")):
        cats.add("transaction")
    if any(w in joined for w in ("login", "auth", "password", "otp", "mfa", "signin", "sign_in")):
        cats.add("authentication")
    if any(w in joined for w in ("signup", "register", "kyc", "verify", "identity")):
        cats.add("identity")
    if any(w in joined for w in ("message", "chat", "email_sent", "dm", "comment", "post")):
        cats.add("communication")
    if any(w in joined for w in ("tool", "agent", "spawn", "delegat", "mcp", "invoke")):
        cats.add("agentic")
    if any(w in joined for w in ("reward", "claim", "referral", "airdrop", "promo", "coupon")):
        cats.add("campaign")
    if any("!fail" in t for t in low):
        cats.add("behavioral")
    types = set(attr_types)
    if types & {"device", "ip", "host", "user_agent"}:
        cats.add("infrastructure")
    if types & {"payment_instrument"}:
        cats.add("payment")
    if types & {"wallet"}:
        cats.add("economic")
    if types & {"email", "phone", "account_ref", "identifier"} or any(t.startswith("field:") for t in types):
        cats.add("identity")
    if "agent" in set(entity_kinds):
        cats.add("agentic")
    rels = set(relations)
    if rels & {"DELEGATED_BY", "SPAWNED_BY"}:
        cats.add("agentic")
    if rels & {"TRANSACTS_WITH"}:
        cats.add("counterparty")
    if rels & {"INVITED_BY", "TARGETS"}:
        cats.add("relationship")
    return sorted(cats) or ["behavioral"]


def event_refs(events: Iterable[ExtractedEvent], limit: int = 25) -> list[str]:
    out: list[str] = []
    for e in events:
        if e.event_id not in out:
            out.append(e.event_id)
        if len(out) >= limit:
            break
    return out


def entity_kinds(entities: Iterable[str]) -> list[str]:
    return sorted({e.split(":", 1)[0] for e in entities})


_IRREGULAR = {"entity": "entities", "identity": "identities", "family": "families"}


def plural(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    return f"{n} {_IRREGULAR.get(word, word + 's')}"
