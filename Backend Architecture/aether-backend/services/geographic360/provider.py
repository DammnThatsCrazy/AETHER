"""Geographic360 intelligence-projection provider (geographic360 G4.4).

Geographic360 is Aether's **contextual WHERE projection** — a governed,
read-only answer to "where is / was this subject (or where did this population /
source come from), with what precision, and under what jurisdiction?" over the
registry's ``subjectKinds: [entity, population, source]``. It projects
``summary`` / ``state`` / ``timeline`` / ``evidence`` / ``findings`` over
canonical location truth (``services.geo`` location facts + context-capsule
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
(:class:`~services.geo.location_facts.LocationFactRepository` — in-memory local
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

# Lightweight plane imports — always importable.
from services.geographic360.capsule_semantics import (
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
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry
from shared.geo.generated_taxonomy import (
    LOCATION_PRECISION_CLASSES,
)

# Reused canonical primitives (never redefined here).
from services.operational_intelligence.models import EvidenceRef

# Geographic360 subject kinds (registry subjectKinds).
GEOGRAPHIC_SUBJECT_KINDS = ("entity", "population", "source")

# Sections the registry declares for geographic360 (matches outputSections order).
OUTPUT_SECTIONS: tuple[str, ...] = (
    "summary",
    "state",
    "timeline",
    "evidence",
    "findings",
)

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
    :class:`~services.geo.location_facts.LocationFactRepository` and maps each
    stored fact onto the projection posture, oldest -> newest. A subject kind
    this plane does not own is reported as such (never a fabricated read), and
    an in-kind subject the store has no active fact for still reads as an
    honest ``missing`` — only a subject with recorded facts projects a posture.
    Backing-store imports stay inside the read so importing this module never
    requires a database. ``repository`` is an optional test seam (defaults to
    the canonical singleton, resolved lazily per read).

    Since G4.5 every stored row whose ``provider`` is the capsule authority
    (:data:`~services.geographic360.capsule_semantics.CAPSULE_LOCATION_PROVIDER`)
    passes through the ``context_capsule_semantics`` read guard
    (:func:`~services.geographic360.capsule_semantics.normalise_capsule_fact_row`)
    in :meth:`_normalise_stored_row` — a capsule-derived fact can never render
    finer than ``coarse_cell`` and never echoes a coordinate.
    """

    def __init__(self, repository: Optional[Any] = None) -> None:
        self._repository = repository

    async def _resolve_repo(self) -> Any:
        if self._repository is None:
            # Deferred import keeps module import free of store dependencies.
            from services.geo.location_facts import location_fact_repo

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
        render_cap: Optional[str] = RENDER_CAP_NONE,
    ) -> None:
        # Injected canonical reader (test seam); the default is the G4.5
        # store-backed reader over canonical location facts.
        self._reader = reader if reader is not None else GeographicLocationReader()
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

        view = await self._safe_view(tenant_id, subject.kind, subject.id)
        posture = view.posture
        rows = _render_history(posture, self._cap) if posture is not None else []

        sections = [
            self._summary_section(request, view, rows, surface_mode),
            self._state_section(request, view, rows),
            self._timeline_section(request, view, rows),
            self._evidence_section(view),
            self._findings_section(request, view, rows),
        ]
        claims = self._build_claims(request, view, rows)

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
                "jurisdiction": _jurisdiction_content(rows),
                "effective_temporal_mode": surface_mode,
                "freshness": {
                    "latest_observed_at": latest,
                },
            },
            warnings=warnings or None,
        )

    def _state_section(
        self,
        request: ProjectionRequest,
        view: GeographicView,
        rows: list[LocationRow],
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
                stale = _age_days(latest_iso, datetime.now(timezone.utc)) > STALE_AFTER_DAYS
                dims.append({
                    "id": "freshness",
                    "state": "stale" if stale else "available",  # type: ignore[arg-type]
                    "reason": (
                        f"most recent location observation is older than "
                        f"{STALE_AFTER_DAYS} days"
                        if stale
                        else None
                    ),
                })

        worst = _worst_state(dims)
        return ProjectionSection(
            id="state",
            state=worst,  # type: ignore[arg-type]
            title="Geographic state",
            content={"dimensions": dims},
            warnings=[d["reason"] for d in dims if d["reason"] is not None] or None,
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
            age = _age_days(latest_iso, datetime.now(timezone.utc))
            if age > STALE_AFTER_DAYS:
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
        )

    # ── Claims ─────────────────────────────────────────────────────────────

    def _build_claims(
        self,
        request: ProjectionRequest,
        view: GeographicView,
        rows: list[LocationRow],
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
                            f"{subject.kind} {subject.id} has a primary {primary.role} "
                            f"location at {label or 'coarse region'} "
                            f"({primary.precision_class} precision, "
                            f"{primary.precision_state})"
                        ),
                        "rendered precision never exceeds the evidence shown",
                    ],
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
                            f"{subject.id} falls under {primary.jurisdiction_name} "
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
            return await self._reader.view(
                tenant_id=tenant_id, subject_kind=subject_kind, subject_id=subject_id
            )
        except Exception:  # noqa: BLE001 - backing authority unavailable -> degrade
            return GeographicView(
                kind=subject_kind,
                id=subject_id,
                posture=None,
                missing_reason="the geographic read authority was unavailable",
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
        "provider": row.provider,
    }


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
    registry.register(Geographic360Provider(), source="services/geographic360")


__all__ = [
    "GEOGRAPHIC_SUBJECT_KINDS",
    "Geographic360Provider",
    "Geographic360Reader",
    "GeographicLocationReader",
    "GeographicPosture",
    "GeographicView",
    "LOCATION_HISTORY_CAP",
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
