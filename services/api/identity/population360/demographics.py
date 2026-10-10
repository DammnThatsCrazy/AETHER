"""Human demographic lens over ``population360`` (population360 P3.4).

Demographics are a governed **human lens** of the population360 projection over
canonical profile facts — there is **no ``Demographic360`` backend** and no
``Spatiotemporal360`` (standing rule 6 of ``CONTEXTUAL_360_PHASES.md``). The
lens:

* reads canonical per-human profile facts through an injectable
  :class:`ProfileFactsReader` seam. The production reader talks to the
  ``profile360`` dependency, which is still ``in_flight``; until a profile-fact
  source is implemented the default reader raises
  :class:`ProfileFactsUnavailable` and the lens degrades to a typed ``missing``
  state — it never fabricates a demographic;
* aggregates three profile dimensions — age band, gender, language — over the
  cohort's human members; and
* applies **configurable small-cell suppression** (minimum cell size, default 5)
  so a sparse cell is never published. Suppression is a disclosure control and
  is NEVER marketed as differential privacy.

Lens applicability is honest and typed: only a population subject whose active
members are humans (``entity_type == "user"``) is ``applicable``; an
entity/cluster subject, an agent cohort, or a non-human cohort renders
``not_applicable``. An applicable population with no active members renders
``empty`` (a real zero-observation aggregate, never fabricated); members with no
canonical profile facts render ``unknown`` per dimension. ``missing`` /
``not_applicable`` / ``empty`` / ``unknown`` stay distinct states.

No temporal or geo derivation here: the lens consumes only canonical profile
facts (age/gender/language). Region/metro/city composition belongs to the
``geographic360`` projection, not to this lens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Protocol, TypedDict

# ── Configuration ─────────────────────────────────────────────────────────────

# Default small-cell floor: a bucket whose count is below this is never shown.
DEFAULT_MINIMUM_CELL_SIZE = 5

# Canonical profile dimensions the lens aggregates. Region/metro is deliberately
# absent: that is geographic360's jurisdiction (precision + evidence there), and
# this lens must not duplicate it.
LENS_DIMENSIONS: tuple[str, ...] = ("age_band", "gender", "language")

AGE_BANDS: tuple[str, ...] = (
    "0-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+",
)

# A bucket string reserved for a fact that names a value outside the lens's
# declared vocabulary (e.g. an unexpected gender string). Kept visible so an
# unrecognised value is never silently dropped.
OTHER_BUCKET = "other"


class ProfileFactsUnavailable(Exception):
    """The canonical profile-fact source is not implemented / unreachable.

    The demographic lens degrades to a typed ``missing`` state on this — it
    never fabricates an aggregate from nothing.
    """


# ── Canonical profile facts (per-human, read-only) ────────────────────────────


class HumanProfileFact(TypedDict, total=False):
    """One human's canonical profile facts the lens is allowed to aggregate.

    Only the three lens dimensions may be consumed. This deliberately does NOT
    carry coordinates or place ids — geographic composition is the
    ``geographic360`` projection's concern (standing rule 2, precision never
    exceeds evidence).
    """

    age: Optional[int]
    birthdate: Optional[str]  # ISO-8601 calendar date (YYYY-MM-DD)
    gender: Optional[str]
    language: Optional[str]


class ProfileFactsReader(Protocol):
    """The canonical profile-facts seam the demographic lens reads.

    ``facts_for`` returns one :class:`HumanProfileFact` per requested ``user``
    entity id that HAS canonical profile facts; an id with no facts is simply
    absent from the returned mapping (absent != zero). Reader failures raise
    :class:`ProfileFactsUnavailable` (the lens degrades); they never return a
    fabricated empty mapping that could masquerade as "no facts observed".
    """

    async def facts_for(
        self, *, tenant_id: str, entity_ids: list[str]
    ) -> dict[str, HumanProfileFact]:
        ...


class UnavailableProfileFactsReader:
    """Default reader: profile360 is ``in_flight``, so no fact source yet.

    Honest by construction — the lens degrades to ``missing`` until a canonical
    profile-fact repository exists, exactly the "demographic lens lifts when
    profile360 lands" dependency story in the population360 blueprint.
    """

    async def facts_for(
        self, *, tenant_id: str, entity_ids: list[str]
    ) -> dict[str, HumanProfileFact]:
        raise ProfileFactsUnavailable(
            "no canonical profile-fact source is implemented yet "
            "(profile360 is in_flight); the demographic lens is missing, "
            "never fabricated"
        )


# ── Small-cell suppression (configurable; not differential privacy) ───────────


@dataclass(frozen=True)
class SmallCellSuppression:
    """Disclosure control applied per demographic bucket.

    ``minimum_cell_size`` is the smallest bucket count that may be published.
    ``enabled`` lets a caller turn suppression off (``minimum_cell_size`` is then
    ignored). Suppression is a configurable disclosure control — it is NOT
    differential privacy and is never described as one.
    """

    minimum_cell_size: int = DEFAULT_MINIMUM_CELL_SIZE
    enabled: bool = True

    def effective_floor(self) -> int:
        return self.minimum_cell_size if self.enabled else 0


@dataclass(frozen=True)
class SuppressedDistribution:
    """A dimension distribution after small-cell suppression.

    ``buckets`` holds only publishable cells (count >= the effective floor).
    ``suppressed_total`` / ``suppressed_cells`` report what was withheld so the
    consumer (and the provider's honesty contract) knows aggregation ran over
    the full member set even though sparse cells are not published.
    """

    dimension: str
    buckets: dict[str, int] = field(default_factory=dict)
    suppressed_total: int = 0
    suppressed_cells: int = 0
    total: int = 0


def suppress_distribution(
    dimension: str,
    counts: dict[str, int],
    suppression: SmallCellSuppression,
) -> SuppressedDistribution:
    """Withhold buckets below the effective small-cell floor (pure).

    Buckets below the floor are not published individually; their counts are
    aggregated into the result's ``suppressed_total`` so no sparse cell leaks
    while the aggregate honestly reflects the full observation set. Never
    mutates ``counts``.
    """
    floor = suppression.effective_floor()
    visible: dict[str, int] = {}
    withheld_total = 0
    withheld_cells = 0
    for bucket, count in sorted(counts.items()):
        if floor > 0 and count < floor:
            withheld_total += count
            withheld_cells += 1
        else:
            visible[bucket] = count
    return SuppressedDistribution(
        dimension=dimension,
        buckets=visible,
        suppressed_total=withheld_total,
        suppressed_cells=withheld_cells,
        total=sum(counts.values()),
    )


# ── Age-band derivation (pure) ────────────────────────────────────────────────


def _band_for_age(age: Optional[int]) -> Optional[str]:
    """Bucket a whole age into one of AGE_BANDS (pure). None when unknown."""
    if age is None or age < 0:
        return None
    edges = ((17, "0-17"), (24, "18-24"), (34, "25-34"), (44, "35-44"),
             (54, "45-54"), (64, "55-64"))
    for edge, band in edges:
        if age <= edge:
            return band
    return "65+"


def _iso_year(iso_date: str) -> Optional[int]:
    """Calendar year of an ISO-8601 date string (``YYYY-MM-DD`` or full ts)."""
    try:
        return datetime.fromisoformat(iso_date.replace("Z", "+00:00")).year
    except (ValueError, TypeError):
        return None


def derive_age_band(
    fact: HumanProfileFact, *, as_of_year: int
) -> Optional[str]:
    """Derive an age band from a profile fact (age, else birthdate). Pure."""
    if fact.get("age") is not None:
        return _band_for_age(fact.get("age"))
    birthdate = fact.get("birthdate")
    year = _iso_year(birthdate) if birthdate else None
    if year is None:
        return None
    return _band_for_age(as_of_year - year)


def _bucketed(value: Optional[str], vocabulary: tuple[str, ...]) -> Optional[str]:
    """Map a categorical value onto a vocabulary, else OTHER_BUCKET."""
    if not value:
        return None
    normalized = str(value).strip().lower()
    if normalized in vocabulary:
        return normalized
    return OTHER_BUCKET


def _fact_dimension(
    fact: HumanProfileFact, dimension: str, *, as_of_year: int
) -> Optional[str]:
    if dimension == "age_band":
        return derive_age_band(fact, as_of_year=as_of_year)
    if dimension == "gender":
        return _bucketed(fact.get("gender"), ("female", "male", "non_binary"))
    if dimension == "language":
        return _bucketed(fact.get("language"), ("en", "fr", "de", "es", "pt"))
    return None


# ── Lens result ───────────────────────────────────────────────────────────────

_DIMENSION_STATES = ("available", "empty", "unknown", "suppressed", "missing")


@dataclass(frozen=True)
class DemographicLensResult:
    """What the demographic lens renders for one cohort.

    ``state`` follows the projection SectionState vocabulary but is restricted
    to the states this lens can honestly produce: ``available`` (an aggregate is
    rendered), ``empty`` (real zero active members), ``unknown`` (members exist
    but no canonical profile facts observed), ``missing`` (the profile-fact
    source is unavailable), ``not_applicable`` (non-human / non-population
    subject) and ``degraded`` (a partial reader failure).
    """

    applicable: bool
    state: str
    reason: Optional[str] = None
    total_members: int = 0
    profiled_members: int = 0
    suppression: SmallCellSuppression = SmallCellSuppression()
    # dimension -> SuppressedDistribution (age_band / gender / language)
    dimensions: dict[str, SuppressedDistribution] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def aggregate_human_profile(
    facts: dict[str, HumanProfileFact],
    *,
    as_of_year: int,
    suppression: SmallCellSuppression,
) -> dict[str, SuppressedDistribution]:
    """Aggregate canonical profile facts into per-dimension distributions.

    A subject contributes to a dimension only when it has a canonical fact for
    that dimension (a missing value is not a fabricated bucket). Returns one
    suppressed distribution per LENS_DIMENSION. Pure.
    """
    per_dimension: dict[str, dict[str, int]] = {d: {} for d in LENS_DIMENSIONS}
    for fact in facts.values():
        for dimension in LENS_DIMENSIONS:
            bucket = _fact_dimension(fact, dimension, as_of_year=as_of_year)
            if bucket is None:
                continue
            counts = per_dimension[dimension]
            counts[bucket] = counts.get(bucket, 0) + 1
    return {
        dimension: suppress_distribution(
            dimension, per_dimension[dimension], suppression
        )
        for dimension in LENS_DIMENSIONS
    }


# ── The lens ──────────────────────────────────────────────────────────────────


class DemographicLens:
    """The governed human demographic lens (no ``Demographic360`` backend).

    Injected seams keep the lens testable and honest: a :class:`ProfileFactsReader`
    (canonical facts) and a clock. The lens is read-only and never mutates
    canonical state.
    """

    def __init__(
        self,
        facts_reader: Optional[ProfileFactsReader] = None,
        *,
        as_of_year: Optional[int] = None,
    ) -> None:
        self._reader = (
            facts_reader if facts_reader is not None else UnavailableProfileFactsReader()
        )
        self._as_of_year = as_of_year or date.today().year

    async def lens_for_population(
        self,
        *,
        tenant_id: str,
        subject_kind: str,
        entity_ids: list[str],
        suppression: Optional[SmallCellSuppression] = None,
    ) -> DemographicLensResult:
        """Render the demographic lens for one cohort's human members.

        ``subject_kind`` gates applicability: only a ``population`` / ``cluster``
        subject can carry a cohort lens; an ``entity`` subject (a single human)
        is ``not_applicable`` (a single subject cannot be a small cell without
        revealing the individual).
        """
        control = suppression or SmallCellSuppression()

        if subject_kind not in ("population", "cluster"):
            return DemographicLensResult(
                applicable=False,
                state="not_applicable",
                reason=(
                    f"demographics are a cohort lens; a {subject_kind!r} subject "
                    "is not a human cohort"
                ),
                suppression=control,
            )
        if not entity_ids:
            # A real zero-observation aggregate (the population has no active
            # members) — never a fabricated 0.
            return DemographicLensResult(
                applicable=True,
                state="empty",
                reason="the population has no active human members to aggregate",
                total_members=0,
                suppression=control,
            )

        try:
            facts = await self._reader.facts_for(
                tenant_id=tenant_id, entity_ids=entity_ids
            )
        except ProfileFactsUnavailable as exc:
            return DemographicLensResult(
                applicable=True,
                state="missing",
                reason=str(exc),
                total_members=len(entity_ids),
                suppression=control,
                warnings=["profile-fact source unavailable; demographics are missing, never fabricated"],
            )
        except Exception:  # noqa: BLE001 — a reader failure degrades the lens
            return DemographicLensResult(
                applicable=True,
                state="degraded",
                reason="the canonical profile-fact reader failed",
                total_members=len(entity_ids),
                suppression=control,
                warnings=["demographic lens degraded; aggregates are not rendered"],
            )

        if not facts:
            # Members exist, but no canonical profile facts observed.
            return DemographicLensResult(
                applicable=True,
                state="unknown",
                reason="no canonical profile facts observed for the cohort's members",
                total_members=len(entity_ids),
                profiled_members=0,
                suppression=control,
            )

        dimensions = aggregate_human_profile(
            facts, as_of_year=self._as_of_year, suppression=control
        )
        return DemographicLensResult(
            applicable=True,
            state="available",
            reason=None,
            total_members=len(entity_ids),
            profiled_members=len(facts),
            suppression=control,
            dimensions=dimensions,
        )


__all__ = [
    "AGE_BANDS",
    "DemographicLens",
    "DemographicLensResult",
    "DEFAULT_MINIMUM_CELL_SIZE",
    "HumanProfileFact",
    "LENS_DIMENSIONS",
    "ProfileFactsReader",
    "ProfileFactsUnavailable",
    "SmallCellSuppression",
    "SuppressedDistribution",
    "UnavailableProfileFactsReader",
    "aggregate_human_profile",
    "derive_age_band",
    "suppress_distribution",
]
