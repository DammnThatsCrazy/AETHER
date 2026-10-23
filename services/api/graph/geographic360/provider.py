"""Geographic360 intelligence-projection provider (geographic360 G4.4).

Geographic360 is Aether's **contextual WHERE projection** — a governed,
read-only answer to "where is / was this subject (or where did this population /
source come from), with what precision, and under what jurisdiction?" over the
registry's ``subjectKinds: [entity, population, source]``. It projects
``summary`` / ``state`` / ``timeline`` / ``evidence`` / ``findings`` over
canonical location truth (``graph.geo`` location facts + context-capsule
geo observations) — never a competing geography store. This module ships the
provider surface (G4.4); the registry row stays ``in_flight`` (the ``implemented``
flip + boot wiring + the location write path land in G4.5).

Read-only, fail-isolated, tenant-scoped, evidence-grounded, and honest:

* It raises only :class:`ProjectionError` subclasses; the registry fail-isolates
  anything else, and backing-source failures degrade sections (typed
  ``degraded`` / ``missing``) instead of raising or fabricating.
* **Precision never exceeds evidence** (standing rule 2): a fact renders only
  the labels it actually carries — a fact without a coordinate never yields one,
  a ``coarse_cell``-only fact renders the cell string, never a guessed city, and
  a rendered answer's ``precision_class`` is recomputed from the labels that
  remain, so a coarsened render can never be mistaken for an exact one.
* **Privacy downgrades are explicit, never silent.** The provider supports the
  ``exact → city → metro`` downgrade ladder through an injectable render cap
  (``RENDER_CAP_CITY`` / ``RENDER_CAP_METRO``). Downgrading drops finer labels
  (coordinate / coarse cell / city / place) and marks the fact
  ``precision_reduced``; an authority-suppressed fact renders coarse-only and
  stays ``suppressed``. No differential-privacy claim is ever made.
* ``unknown`` subjects, an ``empty`` read, a ``missing`` authority and a
  ``suppressed`` / ``degraded`` surface stay distinct typed states — never
  coerced into ``0`` / ``false``. Jurisdiction stays a first-class separation
  from the observation that locates a subject.
* Every location claim names its grounding :class:`EvidenceRef` (the location
  fact row behind it). Read caps (timeline events, evidence list) are surfaced
  as warnings when hit so a bounded list never pretends to be complete.

Canonical reads happen only through the injected :class:`Geographic360Reader`
seam. Since G4.5 the default :class:`GeographicLocationReader` is store-backed:
it reads a subject's active facts from the canonical ``location_facts`` store
(:class:`~graph.geo.location_facts.LocationFactRepository` — in-memory local
/ asyncpg prod) and maps each onto the projection posture, so a subject with
recorded facts projects them and a subject with none reads as an honest
``missing`` (never a fabricated read). Injected readers exercise the full
projection semantics in tests. Imports of any backing store stay inside reader
implementations so importing this module never requires a database.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from urllib.parse import quote

# Lightweight plane imports — always importable.
from graph.geographic360.capsule_semantics import (
    CAPSULE_LOCATION_PROVIDER,
    normalise_capsule_fact_row,
)
from shared.temporal.instant import coerce_utc_lenient
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry
from shared.geo.generated_taxonomy import (
    LOCATION_PRECISION_CLASSES,
)
from shared.contracts_models.epistemic import EpistemicStatus

# Reused canonical primitives (never redefined here).
from graph.operational_intelligence.models import EvidenceRef

# Geographic360 subject kinds (registry subjectKinds).
GEOGRAPHIC_SUBJECT_KINDS = ("entity", "population", "source")

# Sections the registry declares for geographic360 (matches outputSections order).
OUTPUT_SECTIONS: tuple[str, ...] = (
    "summary",
    "state",
    "timeline",
    "evidence",
    "findings",
    "normalization",
)

# Product-contract slots from SSOT §11.14. Keep this provider output aligned
# with the 360 product catalog; registry changes remain centrally owned.
LOCATION_REQUIRED_SLOT_IDS: tuple[str, ...] = (
    "place_summary",
    "geo_hierarchy",
    "timezone",
    "activity_density",
    "journeys",
    "campaigns",
    "profiles",
    "value",
    "risk",
    "normalization",
    "evidence_trace",
)

_UNSUPPORTED_SLOT_REASONS = {
    "timezone": "canonical_timezone_authority_unavailable",
    "activity_density": "canonical_location_activity_aggregation_unavailable",
    "journeys": "exact_location_journey_join_unavailable",
    "campaigns": "exact_location_campaign_join_unavailable",
    "profiles": "exact_location_profile_join_unavailable",
    "value": "exact_location_value_join_unavailable",
    "risk": "exact_location_risk_join_unavailable",
    "normalization": "location_normalization_lineage_unavailable",
}

# The registry surface modes geographic360 supports — window/compare/relative
# only, no knowledge-time ``as_of`` reconstruction (that belongs to the
# temporal360 dependency).
SUPPORTED_TEMPORAL_MODES: frozenset[str] = frozenset({"window", "compare", "relative"})

# Precision-state vocabulary a location fact row may carry.
STATE_FULL = "full"
STATE_PRECISION_REDUCED = "precision_reduced"
STATE_SUPPRESSED = "suppressed"

# The exact → city → metro render-cap ladder. ``metro`` maps onto the canonical
# ``region`` precision class (a metro area is an admin/metro ``region_type``);
# the ladder is expressed over LOCATION_PRECISION_CLASSES granularity.
RENDER_CAP_NONE = None     # render at whatever the evidence supports (up to precise)
RENDER_CAP_CITY = "city"   # drop coordinate + coarse cell; keep place/city and coarser
RENDER_CAP_METRO = "metro"  # drop coordinate/cell/city/place; keep metro/region and coarser

# Read bounds (honesty caps, not silent truncation — each cap surfaces when hit).
LOCATION_HISTORY_CAP = 100  # timeline events listed
EVIDENCE_CAP = 100          # evidence refs listed in the evidence section
ACTIVITY_DENSITY_READ_LIMIT = 200

# A primary/current location whose newest observation is older than this is stale.
STALE_AFTER_DAYS = 180

# Section-state severity (lowest index wins the section's typed state).
_STATE_RANK = {
    "available": 0,
    "not_applicable": 1,
    "empty": 2,
    "unknown": 3,
    "degraded": 4,
    "missing": 5,
    "suppressed": 6,
    "stale": 7,
}

# Fine→coarse label class ranking over LOCATION_PRECISION_CLASSES.
_PRECISION_RANK = {name: index for index, name in enumerate(LOCATION_PRECISION_CLASSES)}

# Finest precision class each render cap permits (index into the ladder).
_ALLOWED_BY_CAP: dict[Optional[str], int] = {
    RENDER_CAP_NONE: _PRECISION_RANK["precise"],   # 4 — evidence only
    RENDER_CAP_CITY: _PRECISION_RANK["city"],      # 2 — drop cell/coordinate
    RENDER_CAP_METRO: _PRECISION_RANK["region"],   # 1 — drop city/place/cell/coordinate
}

# Which roles best answer "where is the subject now" when picking a primary.
_ROLE_PRIORITY = {
    "primary_residence": 10,
    "likely_residence": 9,
    "declared_address": 8,
    "shipping_address": 7,
    "billing_address": 7,
    "organization_registered": 6,
    "workplace": 5,
    "agent_execution_region": 5,
    "observed_presence": 4,
    "commercial_destination": 3,
    "venue_association": 3,
    "trip_destination": 2,
    "network_egress": 1,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_aware(value: Optional[str]) -> str:
    """Normalise an ISO string for chronological sorting (all are UTC ISO)."""
    return value or ""


def _parse_utc_iso(value: str) -> datetime:
    """Parse a UTC ISO string to an aware datetime via the temporal kernel.

    Location-fact instants are canonical UTC ISO. The kernel is the only
    sanctioned place allowed to attach an assumed UTC timezone to a naive
    value (``coerce_utc_lenient``), so the naive fallback never attaches one
    locally (temporal-integrity gate).
    """
    parsed = coerce_utc_lenient(value)
    if parsed is None:
        raise ValueError(f"unparseable UTC ISO instant: {value!r}")
    return parsed


def _age_days(value: str, now: datetime) -> float:
    return max(0.0, (now - _parse_utc_iso(value)).total_seconds() / 86400.0)


def _freshness_for_timestamp(
    value: Optional[str], *, valid_to: Optional[str] = None
) -> tuple[str, Optional[str]]:
    """Classify one source timestamp without hiding malformed/missing time."""
    if not value:
        return "unknown", "location_observation_timestamp_missing"
    try:
        now = datetime.now(timezone.utc)
        age = _age_days(value, now)
    except (TypeError, ValueError, OverflowError):
        return "degraded", "location_observation_timestamp_unparseable"
    if valid_to:
        try:
            if now > _parse_utc_iso(valid_to):
                return "stale", "location_fact_past_valid_to"
        except (TypeError, ValueError, OverflowError):
            return "degraded", "location_fact_validity_unparseable"
    if age > STALE_AFTER_DAYS:
        return "stale", "location_observation_stale"
    return "available", None


def _worst_state(dims: list[dict[str, Any]]) -> str:
    """Most severe typed state among dimensions (available is best)."""
    return min(
        (d["state"] for d in dims),
        key=lambda s: _STATE_RANK.get(s, 100),
    )


# ── Canonical posture model (normalised read output) ──────────────────────────


@dataclass(frozen=True)
class LocationRow:
    """One canonical location fact a geographic360 projection renders.

    ``precision_class`` is the fact's **stored** authority class; the provider
    recomputes the class actually rendered from the labels that survive the
    render cap, so a coarsened render can never claim a finer precision than the
    evidence it shows. ``precision_state`` is ``full`` | ``precision_reduced`` |
    ``suppressed``. Coordinates are carried only as a presence flag — a
    coordinate value is never echoed into a projection section.
    """

    location_id: str
    role: str
    precision_class: str
    region_type: Optional[str] = None
    country_code: Optional[str] = None
    region_name: Optional[str] = None
    region_code: Optional[str] = None
    city: Optional[str] = None
    place_name: Optional[str] = None
    jurisdiction_name: Optional[str] = None
    jurisdiction_kind: Optional[str] = None
    coarse_cell: Optional[str] = None
    coordinate_present: bool = False
    precision_state: str = STATE_FULL
    observed_at: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    provider: Optional[str] = None
    source_observation_id: Optional[str] = None
    # Version of the canonical LocationFact payload. This is not a
    # normalization-algorithm version; the distinction is surfaced by the
    # normalization slot rather than overclaimed as transformation lineage.
    schema_version: Optional[str] = None
    # Source-owned evidence identifiers from LocationFact, kept distinct from
    # the stable location-fact EvidenceRef synthesized for this projection.
    source_evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class GeographicPosture:
    """Canonical WHERE facts one entity/population/source subject projects over.

    ``facts`` is the authority-stored history (oldest → newest) at full
    evidence precision; the provider applies the render cap + suppression at
    projection time so truth is never rewritten for a coarser surface/tenant.
    """

    subject_type: str
    subject_id: str
    facts: tuple[LocationRow, ...]


@dataclass(frozen=True)
class GeographicView:
    """What the reader resolved for the requested subject (or why not)."""

    kind: str  # subject kind echoed
    id: str
    posture: Optional[GeographicPosture]
    # None posture + reason => the plane has no location observation of the subject.
    missing_reason: Optional[str]


@dataclass(frozen=True)
class GeographicActivityDensityRead:
    """Exact-tenant temporal activity metrics for one entity subject."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    scope_mismatch: bool = False
    reason: Optional[str] = None


class GeographicActivityDensityReader(Protocol):
    """Optional exact-subject activity reader; it does not supply location truth."""

    async def activity_density(
        self, *, tenant_id: str, entity_id: str, limit: int
    ) -> GeographicActivityDensityRead:
        ...


class RepositoryGeographicActivityDensityReader:
    """Read bounded temporal activity bins from exact-tenant Gold metrics."""

    async def activity_density(
        self, *, tenant_id: str, entity_id: str, limit: int
    ) -> GeographicActivityDensityRead:
        if not tenant_id or not entity_id:
            return GeographicActivityDensityRead(
                (), False, False, reason="exact_tenant_entity_activity_scope_required"
            )
        try:
            from repositories.lake import gold_temporal_heatmap

            bounded_limit = min(max(int(limit), 1), ACTIVITY_DENSITY_READ_LIMIT)
            source_rows = await gold_temporal_heatmap.get_metrics(
                entity_id, tenant_id=tenant_id
            )
        except Exception:  # noqa: BLE001 - source internals stay private
            return GeographicActivityDensityRead(
                (), False, False, reason="temporal_activity_density_source_unavailable"
            )

        if not isinstance(source_rows, list):
            return GeographicActivityDensityRead(
                (), False, False, reason="temporal_activity_density_source_invalid"
            )
        complete = len(source_rows) < ACTIVITY_DENSITY_READ_LIMIT
        scoped: list[dict[str, Any]] = []
        scope_mismatch = False
        for row in source_rows:
            if not isinstance(row, dict):
                scope_mismatch = True
                continue
            row_tenant = row.get("tenant_id")
            if row_tenant in (None, ""):
                # GoldRepository can return legacy rows alongside a tenant's
                # records; these have no tenant authority and are excluded.
                continue
            if row_tenant != tenant_id or row.get("entity_id") != entity_id:
                scope_mismatch = True
                continue
            scoped.append(row)
        if len(scoped) > bounded_limit:
            scoped = scoped[:bounded_limit]
            complete = False
        if scope_mismatch:
            complete = False
        return GeographicActivityDensityRead(
            tuple(scoped),
            True,
            complete,
            scope_mismatch=scope_mismatch,
            reason=(
                "temporal_activity_density_scope_incomplete"
                if not complete
                else None
            ),
        )


def _row_from_stored_fact(stored: dict) -> LocationRow:
    """Map one stored ``LocationFact`` JSONB row onto the render shape.

    ``LocationFact`` nests a single ``region`` / ``place`` / ``jurisdiction`` /
    ``coordinate``; the render :class:`LocationRow` carries flat labels the
    provider composes. The mapping lifts labels without inventing any:

    * a ``city`` region type lifts its ``name`` to ``city`` (and keeps the
      parent admin code in ``geo_reference`` as the row's ``region_code``);
    * ``country`` / ``continent`` region granularity contributes no admin
      labels (so a country-only fact never renders "US, US");
    * any other region type contributes ``name`` / ``geo_reference`` as
      region labels;
    * the coordinate VALUE is never echoed — only its presence flag.
    """
    region = stored.get("region") or {}
    place = stored.get("place") or {}
    jurisdiction = stored.get("jurisdiction") or {}
    region_type = region.get("region_type")
    country = region.get("country_code") or place.get("country_code")
    city: Optional[str] = None
    region_name: Optional[str] = None
    region_code: Optional[str] = None
    if region_type == "city":
        city = region.get("name")
        region_code = region.get("geo_reference")
    elif region_type not in ("country", "continent"):
        region_name = region.get("name")
        region_code = region.get("geo_reference")
    elif not country:
        # A country granularity whose name IS the country code (a capsule
        # observation resolved to country only) carries it as the country.
        country = region.get("name")
    source_evidence_refs = stored.get("evidence_refs")
    return LocationRow(
        location_id=stored.get("location_id") or stored.get("id"),
        role=stored.get("role") or "observed_presence",
        precision_class=stored.get("precision_class") or "country",
        region_type=region_type,
        country_code=country,
        region_name=region_name,
        region_code=region_code,
        city=city,
        place_name=place.get("name"),
        jurisdiction_name=jurisdiction.get("name"),
        jurisdiction_kind=jurisdiction.get("kind"),
        coarse_cell=stored.get("coarse_cell") or place.get("coarse_cell"),
        coordinate_present=bool(stored.get("coordinate"))
        or bool((place or {}).get("coordinate")),
        precision_state=stored.get("precision_state") or STATE_FULL,
        observed_at=stored.get("observed_at"),
        valid_from=stored.get("valid_from"),
        valid_to=stored.get("valid_to"),
        provider=stored.get("provider"),
        source_observation_id=stored.get("source_observation_id"),
        schema_version=stored.get("schema_version"),
        source_evidence_refs=(
            tuple(
                reference
                for reference in source_evidence_refs
                if isinstance(reference, str) and reference.strip()
            )
            if isinstance(source_evidence_refs, (list, tuple))
            else ()
        ),
    )


# ── Canonical read seam (injected in tests; registry-backed in production) ────


class Geographic360Reader(Protocol):
    """The read authority a Geographic360 projection reconstructs from."""

    async def view(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> GeographicView:
        ...


class GeographicLocationReader:
    """Default reader — store-backed over canonical location facts (G4.5).

    Reads a subject's active facts through
    :class:`~graph.geo.location_facts.LocationFactRepository` and maps each
    stored fact onto the projection posture, oldest -> newest. A subject kind
    this plane does not own is reported as such (never a fabricated read), and
    an in-kind subject the store has no active fact for still reads as an
    honest ``missing`` — only a subject with recorded facts projects a posture.
    Backing-store imports stay inside the read so importing this module never
    requires a database. ``repository`` is an optional test seam (defaults to
    the canonical singleton, resolved lazily per read).

    Since G4.5 every stored row whose ``provider`` is the capsule authority
    (:data:`~graph.geographic360.capsule_semantics.CAPSULE_LOCATION_PROVIDER`)
    passes through the ``context_capsule_semantics`` read guard
    (:func:`~graph.geographic360.capsule_semantics.normalise_capsule_fact_row`)
    in :meth:`_normalise_stored_row` — a capsule-derived fact can never render
    finer than ``coarse_cell`` and never echoes a coordinate.
    """

    def __init__(self, repository: Optional[Any] = None) -> None:
        self._repository = repository

    async def _resolve_repo(self) -> Any:
        if self._repository is None:
            # Deferred import keeps module import free of store dependencies.
            from graph.geo.location_facts import location_fact_repo

            self._repository = location_fact_repo
        return self._repository

    async def view(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> GeographicView:
        if subject_kind not in GEOGRAPHIC_SUBJECT_KINDS:
            return GeographicView(
                kind=subject_kind,
                id=subject_id,
                posture=None,
                missing_reason=(
                    f"subject kind {subject_kind!r} is not a geographic360 subject"
                ),
            )
        repo = await self._resolve_repo()
        rows = await repo.active_facts_for_subject(tenant_id, subject_kind, subject_id)
        if not rows:
            return GeographicView(
                kind=subject_kind,
                id=subject_id,
                posture=None,
                missing_reason=(
                    "the geographic location authority has no recorded location "
                    "facts for this subject"
                ),
            )
        rows = [self._normalise_stored_row(row) for row in rows]
        facts = tuple(_row_from_stored_fact(row) for row in rows)
        posture = GeographicPosture(
            subject_type=subject_kind,
            subject_id=subject_id,
            facts=facts,
        )
        return GeographicView(
            kind=subject_kind,
            id=subject_id,
            posture=posture,
            missing_reason=None,
        )

    def _normalise_stored_row(self, stored: dict) -> dict:
        """Normalise one stored fact before it becomes posture evidence.

        Rows recorded by the capsule authority
        (``provider == context_capsule``) are routed through the
        ``context_capsule_semantics`` read guard, which strips any coordinate
        and clamps a ``precise``-over-claim down to what the labels carry (a
        capsule has no coordinate, so it can never ground ``precise``). Any
        other provenance passes through untouched — the reader is exactly honest
        about whatever the canonical store records. Subclasses may extend this
        seam for their own provenance invariants.
        """
        if stored.get("provider") == CAPSULE_LOCATION_PROVIDER:
            return normalise_capsule_fact_row(stored)
        return stored


# ── Precision rendering (evidence-honest, downgrade-explicit) ────────────────


def _carried_class_index(row: LocationRow) -> Optional[int]:
    """Finest precision class the labels a row carries actually support (pure)."""
    if row.coordinate_present:
        return _PRECISION_RANK["precise"]
    if row.coarse_cell:
        return _PRECISION_RANK["coarse_cell"]
    if row.place_name or row.city:
        return _PRECISION_RANK["city"]
    if row.region_name or row.region_code:
        return _PRECISION_RANK["region"]
    if row.country_code:
        return _PRECISION_RANK["country"]
    return None


def _clear_finer_than(row: LocationRow, allowed: int) -> LocationRow:
    """Drop labels whose precision class is finer than ``allowed`` (pure).

    A downgrade never fabricates: only labels that actually exist are cleared,
    so a coarse render is always a subset of the evidence.
    """
    changes: dict[str, Any] = {}
    if allowed < _PRECISION_RANK["precise"] and row.coordinate_present:
        changes["coordinate_present"] = False
    if allowed < _PRECISION_RANK["coarse_cell"] and row.coarse_cell:
        changes["coarse_cell"] = None
    if allowed < _PRECISION_RANK["city"] and (row.city or row.place_name):
        changes["city"] = None
        changes["place_name"] = None
    if allowed < _PRECISION_RANK["region"] and (row.region_name or row.region_code):
        changes["region_name"] = None
        changes["region_code"] = None
    if not changes:
        return row
    return replace(row, **changes)


def _render_row(row: LocationRow, cap: Optional[str]) -> LocationRow:
    """One fact, downgraded to the surface/tenant's render cap (never silent).

    * a ``suppressed`` fact is authority-blanked: it renders at most country
      granularity and stays ``suppressed`` — fine labels are never re-leaked;
    * a fact whose evidence is finer than the cap loses those finer labels and
      is marked ``precision_reduced`` with its ``precision_class`` recomputed
      from what remains;
    * a fact already at or coarser than the cap is unchanged.
    """
    if row.precision_state == STATE_SUPPRESSED:
        cleared = _clear_finer_than(row, _PRECISION_RANK["country"])
        remaining = _carried_class_index(cleared)
        if remaining is None:
            return cleared
        return replace(
            cleared,
            precision_class=LOCATION_PRECISION_CLASSES[remaining],
            precision_state=STATE_SUPPRESSED,
        )
    allowed = _ALLOWED_BY_CAP.get(cap, _ALLOWED_BY_CAP[RENDER_CAP_NONE])
    carried = _carried_class_index(row)
    if carried is None or carried <= allowed:
        return row
    cleared = _clear_finer_than(row, allowed)
    remaining = _carried_class_index(cleared)
    return replace(
        cleared,
        precision_class=(
            LOCATION_PRECISION_CLASSES[remaining]
            if remaining is not None
            else row.precision_class
        ),
        precision_state=STATE_PRECISION_REDUCED,
    )


def _render_history(posture: GeographicPosture, cap: Optional[str]) -> list[LocationRow]:
    """Rendered facts (newest first) after cap + suppression, honouring evidence.

    A fact whose render leaves nothing honest (e.g. only a cell under a metro
    cap) is dropped from rendered content — never shown as an empty row — but
    its evidence row still grounds the evidence section.
    """
    rows = [_render_row(row, cap) for row in posture.facts]
    rows = [row for row in rows if _carried_class_index(row) is not None]
    rows.sort(
        key=lambda r: _iso_aware(r.observed_at or r.valid_from or ""),
        reverse=True,
    )
    return rows


def _label(row: LocationRow) -> str:
    """Human WHERE label from the labels a row actually renders (pure).

    Never echoes a coordinate; a cell-only fact falls back to the H3 cell string.
    """
    parts: list[str] = []
    if row.place_name:
        parts.append(row.place_name)
    if row.city:
        parts.append(row.city)
    if row.region_name:
        parts.append(row.region_name)
    elif row.region_code:
        parts.append(row.region_code)
    if row.country_code:
        parts.append(row.country_code)
    if not parts and row.coarse_cell:
        parts.append(f"h3:{row.coarse_cell}")
    return ", ".join(parts)


def _primary_row(rows: list[LocationRow]) -> Optional[LocationRow]:
    """The subject's primary "where": highest-priority role, then most recent.

    Suppressed rows never win a primary; when only suppressed rows render, the
    most recent of them is returned so a coarse WHERE (country-level, already
    authority-blanked) still surfaces with its ``suppressed`` state intact.
    """
    if not rows:
        return None
    available = [r for r in rows if r.precision_state != STATE_SUPPRESSED]
    pool = available or rows
    return max(
        pool,
        key=lambda r: (
            _ROLE_PRIORITY.get(r.role, 0),
            _iso_aware(r.observed_at or r.valid_from or ""),
        ),
    )


def _row_evidence(row: LocationRow) -> EvidenceRef:
    """One canonical EvidenceRef grounding a location fact row."""
    return EvidenceRef(
        id=f"location:{row.location_id}",
        type="relationship",
        source="location_facts",
        observedAt=row.observed_at or None,
    )


def _posture_evidence(posture: GeographicPosture) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    seen: set[str] = set()
    for row in posture.facts:
        ref = _row_evidence(row)
        if ref.id in seen:
            continue
        seen.add(ref.id)
        refs.append(ref)
    return refs


# ── Provider ──────────────────────────────────────────────────────────────────


class Geographic360Provider:
    """Intelligence-projection provider for ``geographic360`` (read-only)."""

    projection_id = "geographic360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(
        self,
        reader: Optional[Geographic360Reader] = None,
        *,
        activity_reader: Optional[GeographicActivityDensityReader] = None,
        render_cap: Optional[str] = RENDER_CAP_NONE,
    ) -> None:
        use_default_reader = reader is None
        # Injected canonical reader (test seam); the default is the G4.5
        # store-backed reader over canonical location facts.
        self._reader = reader if reader is not None else GeographicLocationReader()
        # Only the default production path receives the independent Gold
        # activity reader. A test/custom location reader must inject its
        # activity authority explicitly, preventing hidden cross-source reads.
        self._activity_reader = activity_reader or (
            RepositoryGeographicActivityDensityReader()
            if use_default_reader
            else None
        )
        # Surface/tenant render cap — the exact→city→metro downgrade boundary.
        # Default: no extra cap (evidence-limited only). Never rewritten per
        # request; a coarser surface wires its own cap here.
        self._cap = (
            render_cap if render_cap in _ALLOWED_BY_CAP else RENDER_CAP_NONE
        )

    # ── IntelligenceProjectionProvider ─────────────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one read-only Geographic360 projection over canonical truth."""
        tenant_id = request.tenantId
        subject = request.subject
        surface_mode = (
            request.temporalMode
            if request.temporalMode in SUPPORTED_TEMPORAL_MODES
            else "window"
        )

        if context.tenantId != tenant_id or context.projectionId != self.projection_id:
            # ProjectionContext is part of the tenant authorization boundary.
            # Do not perform a read when it has a different scope.
            view = GeographicView(
                kind=subject.kind,
                id=subject.id,
                posture=None,
                missing_reason="the geographic request and projection context scope did not match",
            )
        else:
            view = await self._safe_view(tenant_id, subject.kind, subject.id)
        posture = view.posture
        rows = _render_history(posture, self._cap) if posture is not None else []
        activity_read = await self._safe_activity_density(
            tenant_id=tenant_id,
            subject_kind=subject.kind,
            subject_id=subject.id,
            posture=posture,
            scope_valid=context.tenantId == tenant_id
            and context.projectionId == self.projection_id,
        )
        activity_slot, activity_claim = _activity_density_projection(
            request, posture=posture, read=activity_read
        )
        normalization_slot, normalization_claim = _normalization_lineage_projection(
            view, subject=request.subject
        )

        sections = [
            self._summary_section(request, view, rows, surface_mode),
            self._state_section(
                request,
                view,
                rows,
                activity_slot,
                normalization_slot=normalization_slot,
            ),
            self._timeline_section(request, view, rows),
            self._evidence_section(view),
            self._findings_section(request, view, rows),
            ProjectionSection(
                id="normalization",
                state=(
                    "degraded"
                    if normalization_slot.get("state") == "degraded"
                    else "unknown"
                ),
                title="Location normalization lineage",
                content=(
                    normalization_slot
                    if normalization_slot.get("state") == "degraded"
                    else None
                ),
                warnings=(
                    [str(normalization_slot.get("reasonCode"))]
                    if normalization_slot.get("reasonCode")
                    else None
                ),
                canonicalAuthorityRefs=["locations"],
            ),
        ]
        claims = self._build_claims(
            request,
            view,
            rows,
            activity_claim=activity_claim,
            normalization_claim=normalization_claim,
        )

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            asOf=_utc_now_iso(),
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
            temporalMode=surface_mode,
            lensIds=request.lensIds,
        )

    # ── Section builders ───────────────────────────────────────────────────

    def _summary_section(
        self,
        request: ProjectionRequest,
        view: GeographicView,
        rows: list[LocationRow],
        surface_mode: str,
    ) -> ProjectionSection:
        """summary — the subject's geo posture under the surface mode."""
        subject = request.subject
        posture = view.posture
        warnings: list[str] = []
        if view.missing_reason:
            warnings.append(view.missing_reason)

        if posture is None:
            return ProjectionSection(
                id="summary",
                state="unknown",  # type: ignore[arg-type]
                title="Geographic posture",
                content={
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "subject_type": subject.kind,
                    "location_count": 0,
                    "primary": None,
                },
                warnings=warnings or None,
                canonicalAuthorityRefs=["locations", "context_capsules"],
            )

        suppressed_count = sum(
            1 for row in posture.facts if row.precision_state == STATE_SUPPRESSED
        )
        downgraded = [row for row in rows if row.precision_state == STATE_PRECISION_REDUCED]
        primary = _primary_row(rows)
        carried = (
            [_carried_class_index(r) for r in rows if r.precision_state != STATE_SUPPRESSED]
            or None
        )
        finest_class = (
            LOCATION_PRECISION_CLASSES[max(carried)] if carried else None
        )
        latest = max(
            (row.observed_at for row in posture.facts if row.observed_at),
            default=None,
        )
        if downgraded:
            warnings.append(
                f"{len(downgraded)} location fact(s) rendered at reduced precision "
                f"({self._cap} render cap; exact→city→metro downgrade)"
            )
        if suppressed_count:
            warnings.append(
                f"{suppressed_count} location fact(s) suppressed (fine labels withheld)"
            )

        if primary is None:
            state = "empty"
        elif primary.precision_state == STATE_SUPPRESSED:
            state = "suppressed"
        elif primary.precision_state == STATE_PRECISION_REDUCED:
            state = "degraded"
        else:
            state = "available"

        return ProjectionSection(
            id="summary",
            state=state,  # type: ignore[arg-type]
            title="Geographic posture",
            content={
                "subject": {"kind": subject.kind, "id": subject.id},
                "subject_type": posture.subject_type,
                "location_count": len(rows),
                "suppressed_count": suppressed_count,
                "precision_class": finest_class,
                "precision_cap": self._cap,
                "primary": _row_content(primary) if primary is not None else None,
                "primary_selection_basis": "canonical_role_priority_then_observation_time",
                "current_presence_asserted": False,
                "jurisdiction": _jurisdiction_content(rows),
                "effective_temporal_mode": surface_mode,
                "freshness": {
                    "latest_observed_at": latest,
                },
            },
            warnings=warnings or None,
            canonicalAuthorityRefs=["locations", "context_capsules"],
        )

    def _state_section(
        self,
        request: ProjectionRequest,
        view: GeographicView,
        rows: list[LocationRow],
        activity_density_slot: dict[str, Any],
        *,
        normalization_slot: Optional[dict[str, Any]] = None,
    ) -> ProjectionSection:
        """state — typed per-dimension state (unknown != empty != 0 != missing)."""
        posture = view.posture
        dims: list[dict[str, Any]] = []

        if posture is None:
            dims.append({
                "id": "subject",
                "state": "unknown",
                "reason": view.missing_reason or (
                    "the geographic plane has no location observation of this subject"
                ),
            })
        else:
            facts = posture.facts
            if facts:
                dims.append({
                    "id": "location_observation",
                    "state": "available",
                    "reason": None,
                })
            else:
                dims.append({
                    "id": "location_observation",
                    "state": "empty",
                    "reason": "no location fact is recorded for this subject",
                })

            # Precision — never exceeds evidence; downgrades are surfaced.
            full = [r for r in rows if r.precision_state == STATE_FULL]
            reduced = [r for r in rows if r.precision_state == STATE_PRECISION_REDUCED]
            if full:
                dims.append({
                    "id": "precision",
                    "state": "available",
                    "reason": None,
                })
            elif reduced:
                dims.append({
                    "id": "precision",
                    "state": "degraded",
                    "reason": (
                        "all rendered location facts carry reduced precision "
                        "(exact→city→metro downgrade)"
                    ),
                })
            elif rows:
                dims.append({
                    "id": "precision",
                    "state": "suppressed",
                    "reason": "all rendered location facts are suppressed",
                })
            else:
                dims.append({
                    "id": "precision",
                    "state": "missing",
                    "reason": "no renderable location precision",
                })

            suppressed_count = sum(
                1 for row in facts if row.precision_state == STATE_SUPPRESSED
            )
            if suppressed_count:
                dims.append({
                    "id": "suppression",
                    "state": "suppressed",
                    "reason": (
                        f"{suppressed_count} location fact(s) suppressed for this "
                        "surface/tenant; fine labels withheld"
                    ),
                })

            # Primary — a subject with recorded facts always has a coarse WHERE.
            if _primary_row(rows) is not None:
                dims.append({
                    "id": "primary_location",
                    "state": "available",
                    "reason": None,
                })
            else:
                dims.append({
                    "id": "primary_location",
                    "state": "empty" if facts else "missing",
                    "reason": None,
                })

            jurisdictions = {
                (row.jurisdiction_name, row.jurisdiction_kind)
                for row in facts
                if row.jurisdiction_name
            }
            if jurisdictions:
                dims.append({
                    "id": "jurisdiction",
                    "state": "available",
                    "reason": None,
                })
            elif facts:
                dims.append({
                    "id": "jurisdiction",
                    "state": "missing",
                    "reason": "no governing jurisdiction is recorded for any fact",
                })

            # Freshness — stale is a typed state, never silent.
            latest_iso = max(
                (row.observed_at for row in facts if row.observed_at), default=None
            )
            if latest_iso is None:
                dims.append({
                    "id": "freshness",
                    "state": "missing",
                    "reason": "no location fact carries an observed timestamp",
                })
            else:
                freshness_state, freshness_reason = _freshness_for_timestamp(latest_iso)
                dims.append({
                    "id": "freshness",
                    "state": freshness_state,
                    "reason": (
                        f"most recent location observation is older than "
                        f"{STALE_AFTER_DAYS} days"
                        if freshness_state == "stale"
                        else freshness_reason
                    ),
                })

        worst = _worst_state(dims)
        required_slots = _required_location_slots(
            view,
            rows,
            activity_density_slot=activity_density_slot,
            normalization_slot=normalization_slot,
        )
        authorities = ["locations", "context_capsules"]
        if activity_density_slot.get("evidenceRefs"):
            authorities.append("gold_temporal_heatmap")
        return ProjectionSection(
            id="state",
            state=worst,  # type: ignore[arg-type]
            title="Geographic state",
            content={"dimensions": dims, "requiredSlots": required_slots},
            warnings=[d["reason"] for d in dims if d["reason"] is not None] or None,
            canonicalAuthorityRefs=authorities,
        )

    def _timeline_section(
        self,
        request: ProjectionRequest,
        view: GeographicView,
        rows: list[LocationRow],
    ) -> ProjectionSection:
        """timeline — ordered location history, each fact evidence-grounded."""
        warnings: list[str] = []
        if view.missing_reason:
            warnings.append(view.missing_reason)

        events: list[dict[str, Any]] = []
        for row in rows:
            at = row.observed_at or row.valid_from or ""
            if not at:
                continue
            events.append({
                "at": at,
                "kind": "location_fact",
                "location_id": row.location_id,
                "role": row.role,
                "precision_class": row.precision_class,
                "precision_state": row.precision_state,
                "region_type": row.region_type,
                "country_code": row.country_code,
                "region_name": row.region_name,
                "region_code": row.region_code,
                "city": row.city,
                "place_name": row.place_name,
                "jurisdiction_name": row.jurisdiction_name,
                "jurisdiction_kind": row.jurisdiction_kind,
                "coarse_cell": row.coarse_cell,
                "coordinate_present": row.coordinate_present,
                "valid_from": row.valid_from,
                "valid_to": row.valid_to,
                "provider": row.provider,
                "source_observation_id": row.source_observation_id,
                "source_evidence_refs": list(row.source_evidence_refs),
            })
        events.sort(key=lambda e: _iso_aware(e["at"]), reverse=True)
        if len(events) > LOCATION_HISTORY_CAP:
            warnings.append(f"location history capped at {LOCATION_HISTORY_CAP}")
            events = events[:LOCATION_HISTORY_CAP]

        if not rows and view.posture is not None and view.posture.facts:
            # Facts exist but none rendered a timed, honest location.
            state = "empty" if events else "suppressed"
        elif not rows and view.posture is not None:
            state = "empty"
        elif events:
            state = "available"
        elif rows:
            state = "empty"
        else:
            state = "missing"

        return ProjectionSection(
            id="timeline",
            state=state,  # type: ignore[arg-type]
            title="Location history",
            content={
                "count": len(events),
                "events": events,
            },
            warnings=warnings or None,
            canonicalAuthorityRefs=["locations", "context_capsules"],
        )

    def _evidence_section(
        self,
        view: GeographicView,
    ) -> ProjectionSection:
        """evidence — the reused EvidenceRefs grounding location claims."""
        posture = view.posture
        refs = _posture_evidence(posture) if posture is not None else []
        truncated = len(refs) > EVIDENCE_CAP
        if truncated:
            refs = refs[:EVIDENCE_CAP]
        return ProjectionSection(
            id="evidence",
            state="available" if refs else "empty",  # type: ignore[arg-type]
            title="Evidence",
            content={
                "count": len(refs),
                "evidence": [ref.model_dump(mode="json") for ref in refs],
            },
            warnings=[f"evidence list capped at {EVIDENCE_CAP}"] if truncated else None,
            canonicalAuthorityRefs=["locations", "context_capsules"],
        )

    def _findings_section(
        self,
        request: ProjectionRequest,
        view: GeographicView,
        rows: list[LocationRow],
    ) -> ProjectionSection:
        """findings — downgrades, suppression, conflicts, staleness."""
        findings: list[dict[str, Any]] = []
        posture = view.posture

        if view.missing_reason:
            findings.append({
                "code": "geographic360.subject_unknown",
                "level": "info",
                "message": view.missing_reason,
            })

        if posture is None:
            return ProjectionSection(
                id="findings",
                state="available",  # type: ignore[arg-type]
                title="Geographic findings",
                content={
                    "findings": findings,
                    "evidence_count": 0,
                },
                canonicalAuthorityRefs=["locations", "context_capsules"],
            )

        suppressed = [row for row in posture.facts if row.precision_state == STATE_SUPPRESSED]
        if suppressed:
            findings.append({
                "code": "geographic360.suppressed",
                "level": "warning",
                "message": (
                    f"{len(suppressed)} location fact(s) suppressed; fine labels "
                    "withheld for this surface/tenant"
                ),
            })

        reduced = [row for row in rows if row.precision_state == STATE_PRECISION_REDUCED]
        if reduced:
            findings.append({
                "code": "geographic360.precision_reduced",
                "level": "warning",
                "message": (
                    f"{len(reduced)} location fact(s) rendered at reduced precision "
                    f"({self._cap} render cap) — never finer than the evidence shown"
                ),
            })

        jurisdictions = sorted(
            {
                row.jurisdiction_name
                for row in posture.facts
                if row.jurisdiction_name
            }
        )
        if len(jurisdictions) > 1:
            findings.append({
                "code": "geographic360.jurisdiction_conflict",
                "level": "warning",
                "message": (
                    f"recorded facts fall under conflicting jurisdictions: "
                    f"{', '.join(jurisdictions)}"
                ),
            })

        # Contradictory country evidence among the two most recent rendered facts.
        timed = [row for row in rows if row.observed_at]
        countries = [row.country_code for row in timed if row.country_code]
        if len(countries) >= 2 and len(set(countries)) > 1:
            findings.append({
                "code": "geographic360.conflicting_country",
                "level": "warning",
                "message": "recent location facts disagree on the subject's country",
            })

        latest_iso = max(
            (row.observed_at for row in posture.facts if row.observed_at), default=None
        )
        if latest_iso is not None:
            freshness_state, _ = _freshness_for_timestamp(latest_iso)
            if freshness_state == "stale":
                age = _age_days(latest_iso, datetime.now(timezone.utc))
                findings.append({
                    "code": "geographic360.stale_location",
                    "level": "warning",
                    "message": (
                        f"most recent location observation is "
                        f"{int(round(age))} days old"
                    ),
                })

        return ProjectionSection(
            id="findings",
            state="available",  # type: ignore[arg-type]
            title="Geographic findings",
            content={
                "findings": findings,
                "evidence_count": len(_posture_evidence(posture)),
            },
            canonicalAuthorityRefs=["locations", "context_capsules"],
        )

    # ── Claims ─────────────────────────────────────────────────────────────

    def _build_claims(
        self,
        request: ProjectionRequest,
        view: GeographicView,
        rows: list[LocationRow],
        *,
        activity_claim: Optional[ClaimEnvelope] = None,
        normalization_claim: Optional[ClaimEnvelope] = None,
    ) -> list[ClaimEnvelope]:
        """Evidence-grounded claims (requiresEvidence: every claim is grounded)."""
        claims: list[ClaimEnvelope] = []
        subject = request.subject
        posture = view.posture

        if posture is None:
            claims.append(
                ClaimEnvelope(
                    id="summary.unknown",
                    kind="geographic_location",
                    subject=subject,
                    evidenceRefs=[],
                    claims=[
                        "the geographic plane has no location observation of this subject",
                    ],
                )
            )
            return claims

        evidence = {ref.id: ref for ref in _posture_evidence(posture)}
        primary = _primary_row(rows)

        timed_rows = [row for row in rows if row.observed_at or row.valid_from]
        timed_evidence = [
            evidence[f"location:{row.location_id}"]
            for row in timed_rows
            if f"location:{row.location_id}" in evidence
        ]
        if timed_evidence:
            claims.append(
                ClaimEnvelope(
                    id=f"profile_location_temporal.{subject.kind}.{subject.id}",
                    kind="profile_location_temporal_evidence",
                    subject=subject,
                    evidenceRefs=timed_evidence,
                    claims=[
                        (
                            f"Canonical location facts record {len(timed_evidence)} "
                            "time-scoped observation(s) for this exact subject; recorded "
                            "timestamps and validity bounds do not establish a continuous "
                            "physical trajectory."
                        )
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["location_temporal"],
                )
            )

        if primary is not None:
            ref = evidence.get(f"location:{primary.location_id}")
            label = _label(primary)
            claims.append(
                ClaimEnvelope(
                    id="summary.primary_location",
                    kind="geographic_location",
                    subject=subject,
                    evidenceRefs=[ref] if ref is not None else [],
                    claims=[
                        (
                            f"canonical location fact {primary.location_id} records "
                            f"a {primary.role} at {label or 'coarse region'} "
                            f"({primary.precision_class} precision, "
                            f"{primary.precision_state}); this does not assert "
                            "current physical presence"
                        ),
                        "rendered precision never exceeds the evidence shown",
                    ],
                    domainSlotIds=["place_summary"],
                )
            )
            if primary.jurisdiction_name:
                claims.append(
                    ClaimEnvelope(
                        id="summary.jurisdiction",
                        kind="geographic_jurisdiction",
                        subject=subject,
                        evidenceRefs=[ref] if ref is not None else [],
                        claims=[
                            f"canonical location fact {primary.location_id} reports "
                            f"jurisdiction {primary.jurisdiction_name} "
                            f"({primary.jurisdiction_kind or 'jurisdiction'})",
                        ],
                    )
                )
        else:
            claims.append(
                ClaimEnvelope(
                    id="summary.suppressed",
                    kind="geographic_location",
                    subject=subject,
                    evidenceRefs=[],
                    claims=[
                        "no location fact is renderable for this subject on this "
                        "surface (facts suppressed or empty)",
                    ],
                )
            )
        hierarchy_rows = [
            row
            for row in rows
            if any(
                (
                    row.region_type,
                    row.country_code,
                    row.region_name,
                    row.region_code,
                    row.city,
                    row.place_name,
                )
            )
        ]
        for row in hierarchy_rows:
            ref = evidence.get(f"location:{row.location_id}")
            if ref is None:
                continue
            label = _label(row)
            claims.append(
                ClaimEnvelope(
                    id=f"geography.hierarchy.{row.location_id}",
                    kind="geographic_hierarchy",
                    subject=subject,
                    evidenceRefs=[ref],
                    claims=[
                        f"canonical location fact {row.location_id} records geographic "
                        f"labels {label or 'at the recorded precision'}"
                    ],
                    domainSlotIds=["geo_hierarchy"],
                )
            )
        evidence_refs = list(evidence.values())
        if evidence_refs:
            claims.append(
                ClaimEnvelope(
                    id="evidence.location_fact_trace",
                    kind="geographic_evidence_trace",
                    subject=subject,
                    evidenceRefs=evidence_refs,
                    claims=[
                        f"the tenant-scoped geographic read returned {len(evidence_refs)} "
                        "canonical location-fact evidence reference(s)"
                    ],
                    domainSlotIds=["evidence_trace"],
                )
            )
        if activity_claim is not None:
            claims.append(activity_claim)
        if normalization_claim is not None:
            claims.append(normalization_claim)
        return claims

    # ── Canonical read helper (defensive) ─────────────────────────────────

    async def _safe_view(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
    ) -> GeographicView:
        """A reader failure degrades the subject view, never raises."""
        try:
            view = await self._reader.view(
                tenant_id=tenant_id, subject_kind=subject_kind, subject_id=subject_id
            )
            if not isinstance(view, GeographicView):
                raise TypeError("geographic reader returned an invalid view")
            if view.kind != subject_kind or view.id != subject_id:
                raise ValueError("geographic reader returned a different subject")
            if view.posture is not None and (
                view.posture.subject_type != subject_kind
                or view.posture.subject_id != subject_id
            ):
                raise ValueError("geographic reader posture is scoped to a different subject")
            return view
        except Exception:  # noqa: BLE001 - backing authority unavailable -> degrade
            return GeographicView(
                kind=subject_kind,
                id=subject_id,
                posture=None,
                missing_reason="the geographic read authority was unavailable",
            )

    async def _safe_activity_density(
        self,
        *,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        posture: Optional[GeographicPosture],
        scope_valid: bool,
    ) -> Optional[GeographicActivityDensityRead]:
        """Read activity only for an exact entity with a canonical location fact."""
        if (
            not scope_valid
            or subject_kind != "entity"
            or posture is None
            or posture.subject_type != subject_kind
            or posture.subject_id != subject_id
            or not posture.facts
            or self._activity_reader is None
        ):
            return None
        try:
            read = await self._activity_reader.activity_density(
                tenant_id=tenant_id,
                entity_id=subject_id,
                limit=ACTIVITY_DENSITY_READ_LIMIT,
            )
            if not isinstance(read, GeographicActivityDensityRead):
                raise TypeError("activity density reader returned an invalid contract")
            return read
        except Exception:  # noqa: BLE001 - typed unknown instead of source detail
            return GeographicActivityDensityRead(
                (), False, False,
                reason="temporal_activity_density_source_unavailable",
            )


# ── Content render helpers (shared by summary) ───────────────────────────────


def _row_content(row: LocationRow) -> dict[str, Any]:
    """The renderable location content of one row (never a coordinate value)."""
    return {
        "location_id": row.location_id,
        "role": row.role,
        "label": _label(row),
        "precision_class": row.precision_class,
        "precision_state": row.precision_state,
        "country_code": row.country_code,
        "region_name": row.region_name,
        "region_code": row.region_code,
        "city": row.city,
        "place_name": row.place_name,
        "jurisdiction_name": row.jurisdiction_name,
        "jurisdiction_kind": row.jurisdiction_kind,
        "coarse_cell": row.coarse_cell,
        "coordinate_present": row.coordinate_present,
        "observed_at": row.observed_at,
        "valid_from": row.valid_from,
        "valid_to": row.valid_to,
        "provider": row.provider,
        "source_observation_id": row.source_observation_id,
        "source_evidence_refs": list(row.source_evidence_refs),
    }


def _activity_density_projection(
    request: ProjectionRequest,
    *,
    posture: Optional[GeographicPosture],
    read: Optional[GeographicActivityDensityRead],
) -> tuple[dict[str, Any], Optional[ClaimEnvelope]]:
    """Render exact-entity temporal bins as partial activity, never spatial density."""
    policy = {
        "state": "not_evaluated_by_projection_provider",
        "reasonCode": "policy_disposition_is_owned_by_frame_runtime",
    }
    slot: dict[str, Any] = {
        "state": "unknown",
        "reasonCode": "canonical_location_activity_aggregation_unavailable",
        "content": None,
        "evidenceRefs": [],
        "freshness": {"state": "unknown", "reasonCode": "no_exact_source_join"},
        "policy": policy,
    }
    subject = request.subject
    if (
        subject.kind != "entity"
        or posture is None
        or posture.subject_type != "entity"
        or posture.subject_id != subject.id
        or not posture.facts
        or read is None
    ):
        return slot, None
    if not read.available:
        slot["reasonCode"] = _safe_activity_reason(read.reason)
        slot["freshness"] = {
            "state": "unknown",
            "reasonCode": "temporal_activity_density_source_unavailable",
        }
        return slot, None

    tenant_id = request.tenantId
    points: list[dict[str, Any]] = []
    evidence_refs: list[EvidenceRef] = []
    invalid_or_unscoped = read.scope_mismatch
    timestamps: list[str] = []
    for row in read.rows:
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("entity_id") != subject.id
        ):
            invalid_or_unscoped = True
            continue
        row_id = _safe_activity_identifier(row.get("id"))
        value = row.get("value") if isinstance(row.get("value"), dict) else {}
        dimensions = row.get("dimensions") if isinstance(row.get("dimensions"), dict) else {}
        day = value.get("day_of_week", dimensions.get("day_of_week"))
        hour = value.get("hour_utc", dimensions.get("hour_utc"))
        count = value.get("activity_count", dimensions.get("activity_count"))
        day_value = _activity_weekday(day)
        if (
            row_id is None
            or day_value is None
            or isinstance(hour, bool)
            or not isinstance(hour, int)
            or not 0 <= hour <= 23
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            invalid_or_unscoped = True
            continue
        observed_at = _safe_activity_timestamp(
            row.get("materialized_at") or row.get("computed_at")
        )
        if observed_at is not None:
            timestamps.append(observed_at)
        points.append(
            {
                "dayOfWeek": day_value,
                "hourUtc": hour,
                "activityCount": count,
                "materializedAt": observed_at,
            }
        )
        evidence_refs.append(
            EvidenceRef(
                id=row_id,
                type="model_output",
                source="gold_temporal_heatmap",
                observedAt=observed_at,
                uri=f"store://gold_temporal_heatmap/{quote(row_id, safe='')}",
            )
        )

    if not points:
        slot["reasonCode"] = (
            "temporal_activity_density_rows_unusable"
            if invalid_or_unscoped
            else "temporal_activity_density_not_materialized"
        )
        return slot, None

    latest = max(timestamps, default=None)
    freshness_state, freshness_reason = _freshness_for_timestamp(latest)
    if freshness_state == "stale":
        slot_state = "stale"
        reason_code = freshness_reason or "temporal_activity_density_stale"
    else:
        slot_state = "degraded"
        reason_code = (
            "temporal_activity_density_read_incomplete"
            if invalid_or_unscoped or not read.complete
            else "temporal_activity_density_not_linked_to_place"
        )
    slot = {
        "state": slot_state,
        "reasonCode": reason_code,
        "content": {
            "densityKind": "temporal_activity_by_utc_hour",
            "scope": "exact_tenant_entity_with_recorded_location_facts",
            "locationCorrelationState": "unknown",
            "spatialDensityAsserted": False,
            "points": points,
            "returnedPointCount": len(points),
            "pointCountComplete": read.complete and not invalid_or_unscoped,
            "source": "gold_temporal_heatmap",
        },
        "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence_refs],
        "freshness": {
            "state": freshness_state,
            "reasonCode": freshness_reason,
            "latestMaterializedAt": latest,
        },
        "policy": policy,
    }
    claim = ClaimEnvelope(
        id="activity.temporal_density",
        kind="entity_temporal_activity_density",
        subject=subject,
        evidenceRefs=evidence_refs,
        claims=[
            "Tenant-scoped Gold temporal heatmap records provide activity counts by UTC weekday and hour for this entity; no count is assigned to a geographic place and no timezone is inferred."
        ],
        claimState=EpistemicStatus.OBSERVED,
        domainSlotIds=["activity_density"],
    )
    return slot, claim


def _safe_activity_identifier(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in text):
        return None
    return text


def _activity_weekday(value: Any) -> Optional[str]:
    weekdays = {
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
    }
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in weekdays else None


def _safe_activity_timestamp(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    parsed = coerce_utc_lenient(value)
    return parsed.isoformat() if parsed is not None else None


def _safe_activity_reason(value: Any) -> str:
    safe = _safe_activity_identifier(value)
    if safe is None or not safe.replace("_", "").replace(".", "").isalnum():
        return "temporal_activity_density_source_unavailable"
    return safe


def _required_location_slots(
    view: GeographicView,
    rows: list[LocationRow],
    *,
    activity_density_slot: Optional[dict[str, Any]] = None,
    normalization_slot: Optional[dict[str, Any]] = None,
) -> dict[str, dict[str, Any]]:
    """Expose every SSOT-required slot with source-backed state and gaps."""
    posture = view.posture
    policy_boundary = {
        "state": "not_evaluated_by_projection_provider",
        "reasonCode": "policy_disposition_is_owned_by_frame_runtime",
    }
    slots: dict[str, dict[str, Any]] = {
        slot_id: {
            "state": "unknown",
            "reasonCode": reason,
            "content": None,
            "evidenceRefs": [],
            "freshness": {"state": "unknown", "reasonCode": "no_exact_source_join"},
            "policy": policy_boundary,
        }
        for slot_id, reason in _UNSUPPORTED_SLOT_REASONS.items()
    }

    if posture is None:
        missing_reason = view.missing_reason or "geographic_location_read_unavailable"
        for slot_id in ("place_summary", "geo_hierarchy", "evidence_trace"):
            slots[slot_id] = {
                "state": "unknown",
                "reasonCode": "canonical_location_read_unresolved",
                "reason": missing_reason,
                "content": None,
                "evidenceRefs": [],
                "freshness": {"state": "unknown", "reasonCode": "source_timestamp_unavailable"},
                "policy": policy_boundary,
            }
        return {slot_id: slots[slot_id] for slot_id in LOCATION_REQUIRED_SLOT_IDS}

    facts = posture.facts
    all_refs = _posture_evidence(posture)
    refs_by_location = {
        row.location_id: _row_evidence(row)
        for row in facts
    }
    if not facts:
        for slot_id in ("place_summary", "geo_hierarchy", "evidence_trace"):
            slots[slot_id] = {
                "state": "empty",
                "reasonCode": "canonical_location_read_empty",
                "content": None,
                "evidenceRefs": [],
                "freshness": {"state": "unknown", "reasonCode": "no_location_facts"},
                "policy": policy_boundary,
            }
        return {slot_id: slots[slot_id] for slot_id in LOCATION_REQUIRED_SLOT_IDS}

    if activity_density_slot is not None:
        slots["activity_density"] = activity_density_slot
    if normalization_slot is not None:
        slots["normalization"] = normalization_slot

    primary = _primary_row(rows)
    if primary is None:
        slots["place_summary"] = {
            "state": "suppressed",
            "reasonCode": "location_fact_has_no_renderable_geography",
            "content": None,
            "evidenceRefs": [ref.model_dump(mode="json") for ref in all_refs],
            "freshness": {"state": "unknown", "reasonCode": "no_renderable_location_timestamp"},
            "policy": policy_boundary,
        }
    else:
        freshness_state, freshness_reason = _freshness_for_timestamp(
            primary.observed_at or primary.valid_from,
            valid_to=primary.valid_to,
        )
        if primary.precision_state == STATE_SUPPRESSED:
            slot_state = "suppressed"
            reason_code = "location_precision_suppressed"
        elif freshness_state == "stale":
            slot_state = "stale"
            reason_code = freshness_reason or "location_observation_stale"
        elif (
            primary.precision_state == STATE_PRECISION_REDUCED
            or freshness_state == "degraded"
            or freshness_state == "unknown"
        ):
            slot_state = "degraded"
            reason_code = (
                freshness_reason
                or "location_precision_reduced"
                if primary.precision_state == STATE_PRECISION_REDUCED
                else freshness_reason or "location_freshness_unresolved"
            )
        else:
            slot_state = "available"
            reason_code = None
        primary_ref = refs_by_location.get(primary.location_id)
        slots["place_summary"] = {
            "state": slot_state,
            "reasonCode": reason_code,
            "content": {
                **_row_content(primary),
                "selectionBasis": "canonical_role_priority_then_observation_time",
                "currentPresenceAsserted": False,
            },
            "evidenceRefs": (
                [primary_ref.model_dump(mode="json")] if primary_ref is not None else []
            ),
            "freshness": {
                "state": freshness_state,
                "reasonCode": freshness_reason,
                "observedAt": primary.observed_at,
                "validFrom": primary.valid_from,
                "validTo": primary.valid_to,
            },
            "policy": policy_boundary,
        }

    hierarchy_rows = [
        row for row in rows
        if any((row.region_type, row.country_code, row.region_name, row.region_code,
                row.city, row.place_name))
    ]
    if not hierarchy_rows:
        slots["geo_hierarchy"] = {
            "state": "unknown",
            "reasonCode": "canonical_geographic_hierarchy_unresolved",
            "content": None,
            "evidenceRefs": [ref.model_dump(mode="json") for ref in all_refs],
            "freshness": {"state": "unknown", "reasonCode": "no_resolved_hierarchy_timestamp"},
            "policy": policy_boundary,
        }
    else:
        hierarchy_evidence = [
            refs_by_location[row.location_id]
            for row in hierarchy_rows
            if row.location_id in refs_by_location
        ]
        reduced = any(row.precision_state != STATE_FULL for row in hierarchy_rows)
        hierarchy_freshness_states = [
            _freshness_for_timestamp(
                row.observed_at or row.valid_from,
                valid_to=row.valid_to,
            )[0]
            for row in hierarchy_rows
        ]
        if all(state == "stale" for state in hierarchy_freshness_states):
            hierarchy_freshness_state = "stale"
            hierarchy_freshness_reason = "location_hierarchy_observations_stale"
        elif any(state != "available" for state in hierarchy_freshness_states):
            hierarchy_freshness_state = "degraded"
            hierarchy_freshness_reason = "location_hierarchy_freshness_incomplete"
        else:
            hierarchy_freshness_state = "available"
            hierarchy_freshness_reason = None
        if hierarchy_freshness_state == "stale":
            hierarchy_slot_state = "stale"
        elif reduced or hierarchy_freshness_state == "degraded":
            hierarchy_slot_state = "degraded"
        else:
            hierarchy_slot_state = "available"
        slots["geo_hierarchy"] = {
            "state": hierarchy_slot_state,
            "reasonCode": (
                "location_hierarchy_precision_reduced"
                if reduced
                else hierarchy_freshness_reason
            ),
            "content": [
                {
                    "locationId": row.location_id,
                    "regionType": row.region_type,
                    "countryCode": row.country_code,
                    "regionName": row.region_name,
                    "regionCode": row.region_code,
                    "city": row.city,
                    "placeName": row.place_name,
                    "precisionClass": row.precision_class,
                    "precisionState": row.precision_state,
                    "observedAt": row.observed_at,
                    "validFrom": row.valid_from,
                    "validTo": row.valid_to,
                    "sourceObservationId": row.source_observation_id,
                    "sourceEvidenceRefs": list(row.source_evidence_refs),
                }
                for row in hierarchy_rows
            ],
            "evidenceRefs": [ref.model_dump(mode="json") for ref in hierarchy_evidence],
            "freshness": {
                "state": hierarchy_freshness_state,
                "reasonCode": hierarchy_freshness_reason,
                "latestObservedAt": max(
                    (row.observed_at for row in hierarchy_rows if row.observed_at),
                    default=None,
                ),
            },
            "policy": policy_boundary,
        }

    latest_evidence_time = max(
        (row.observed_at for row in facts if row.observed_at), default=None
    )
    evidence_freshness_state, evidence_freshness_reason = _freshness_for_timestamp(
        latest_evidence_time
    )
    slots["evidence_trace"] = {
        "state": "available" if all_refs else "unknown",
        "reasonCode": None if all_refs else "canonical_location_evidence_unavailable",
        "content": {
            "count": len(all_refs),
            "evidenceRefs": [ref.model_dump(mode="json") for ref in all_refs],
            "sourceEvidenceRefs": [
                {
                    "locationId": row.location_id,
                    "sourceObservationId": row.source_observation_id,
                    "evidenceRefs": list(row.source_evidence_refs),
                    "sourceProvider": row.provider,
                }
                for row in facts
            ],
        },
        "evidenceRefs": [ref.model_dump(mode="json") for ref in all_refs],
        "freshness": {
            "state": evidence_freshness_state if all_refs else "unknown",
            "reasonCode": (
                evidence_freshness_reason if all_refs else "canonical_location_evidence_unavailable"
            ),
            "latestObservedAt": latest_evidence_time,
        },
        "policy": policy_boundary,
    }
    return {slot_id: slots[slot_id] for slot_id in LOCATION_REQUIRED_SLOT_IDS}


def _normalization_lineage_projection(
    view: GeographicView,
    *,
    subject: ProjectionSubject,
) -> tuple[dict[str, Any], Optional[ClaimEnvelope]]:
    """Expose only exact source lineage persisted on canonical LocationFacts.

    The current location authority can link a fact to an upstream observation
    and source evidence, but it does not persist the normalization/validation
    versions or the time of that transformation. A source-linked read is
    therefore useful but deliberately degraded; it never treats the
    LocationFact schema version as a normalization algorithm version.
    """
    policy = {
        "state": "not_evaluated_by_projection_provider",
        "reasonCode": "policy_disposition_is_owned_by_frame_runtime",
    }
    unknown = {
        "state": "unknown",
        "reasonCode": "location_normalization_lineage_unavailable",
        "content": None,
        "evidenceRefs": [],
        "freshness": {
            "state": "unknown",
            "reasonCode": "location_normalization_timestamp_unavailable",
        },
        "policy": policy,
    }
    posture = view.posture
    if posture is None or not posture.facts:
        return unknown, None

    linked_rows: list[tuple[LocationRow, dict[str, Any]]] = []
    for row in posture.facts:
        source_observation_id = _safe_activity_identifier(row.source_observation_id)
        source_provider = _safe_activity_identifier(row.provider)
        source_evidence_refs_all = [
            safe_ref
            for value in row.source_evidence_refs
            if (safe_ref := _safe_activity_identifier(value)) is not None
        ]
        if not source_observation_id and not source_evidence_refs_all:
            continue
        linked_rows.append(
            (
                row,
                {
                    "locationFactId": _safe_activity_identifier(row.location_id),
                    "sourceLinkState": "linked",
                    "sourceObservationId": source_observation_id,
                    "sourceProvider": source_provider,
                    "sourceEvidenceRefs": source_evidence_refs_all[:EVIDENCE_CAP],
                    "sourceEvidenceRefsTruncated": len(source_evidence_refs_all)
                    > EVIDENCE_CAP,
                    "locationFactSchemaVersion": _safe_activity_identifier(
                        row.schema_version
                    ),
                    "sourceObservedAt": row.observed_at,
                },
            )
        )

    if not linked_rows:
        return unknown, None

    # Location facts are ordered oldest -> newest by the canonical reader.
    # Keep the newest source-linked entries within the evidence cap and make
    # any truncation visible in the slot content.
    linked_rows.sort(key=lambda item: _iso_aware(item[0].observed_at or item[0].valid_from))
    listed_rows = linked_rows[-EVIDENCE_CAP:]
    entries = [entry for _, entry in listed_rows]
    evidence_refs = [_row_evidence(row) for row, _ in listed_rows]
    omitted_linked_count = len(linked_rows) - len(listed_rows)
    slot = {
        "state": "degraded",
        "reasonCode": "location_normalization_algorithm_lineage_unavailable",
        "content": {
            "lineageCompleteness": "partial",
            "lineageBasis": "source_links_recorded_on_canonical_location_facts",
            "entries": entries,
            "sourceLinkedFactCount": len(linked_rows),
            "listedSourceLinkedFactCount": len(listed_rows),
            "omittedSourceLinkedFactCount": omitted_linked_count,
            "sourceLinkedFactListTruncated": omitted_linked_count > 0,
            "unavailableLineageFields": [
                "normalizationVersion",
                "validationVersion",
                "rawRecordRef",
                "normalizationTimestamp",
            ],
        },
        "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence_refs],
        "freshness": {
            "state": "unknown",
            "reasonCode": "location_normalization_timestamp_unavailable",
        },
        "policy": policy,
    }
    claim = None
    if evidence_refs:
        claim = ClaimEnvelope(
            id="normalization.location_fact_lineage",
            kind="geographic_normalization_lineage",
            subject=subject,
            evidenceRefs=evidence_refs,
            claims=[
                "the canonical location facts expose explicit source observation or evidence links, but do not expose transformation-version or normalization-time lineage; normalization coverage is partial"
            ],
            domainSlotIds=["normalization"],
        )
    return slot, claim


def _jurisdiction_content(rows: list[LocationRow]) -> Optional[dict[str, Any]]:
    """The governing jurisdiction most recently observed (separate from location)."""
    seen = [
        row for row in rows if row.jurisdiction_name and row.observed_at is not None
    ]
    if not seen:
        fallback = next(
            (row for row in rows if row.jurisdiction_name), None
        )
        if fallback is None:
            return None
        return {
            "name": fallback.jurisdiction_name,
            "kind": fallback.jurisdiction_kind,
        }
    latest = max(seen, key=lambda row: row.observed_at or "")
    return {
        "name": latest.jurisdiction_name,
        "kind": latest.jurisdiction_kind,
    }


def register_provider(registry: ProviderRegistry) -> None:
    """Register :class:`Geographic360Provider` on a provider registry.

    Deliberately NOT called at import time: the global ``projection_registry``
    is only mutated by the runtime wiring layer, never by provider modules.
    """
    registry.register(Geographic360Provider(), source="services/api/graph/geographic360")


__all__ = [
    "GEOGRAPHIC_SUBJECT_KINDS",
    "Geographic360Provider",
    "Geographic360Reader",
    "GeographicLocationReader",
    "GeographicPosture",
    "GeographicView",
    "LOCATION_HISTORY_CAP",
    "LOCATION_REQUIRED_SLOT_IDS",
    "LocationRow",
    "OUTPUT_SECTIONS",
    "RENDER_CAP_CITY",
    "RENDER_CAP_METRO",
    "RENDER_CAP_NONE",
    "SUPPORTED_TEMPORAL_MODES",
    "STATE_FULL",
    "STATE_PRECISION_REDUCED",
    "STATE_SUPPRESSED",
    "register_provider",
]
