"""Cross-360 composition tests (A8 projection engine, slice S6).

:mod:`shared.projection_engine.composition` composes two or three 360 member
projections over the SAME tenant-scoped subject into one deterministic
:class:`CompositionResult` (ADR-010: a 360 is an intelligence projection over
canonical truth — never a competing system of record). These tests cover:

* each pair and the operational-value triangle composes when every member
  provider is a stub returning typed sections;
* a missing / raising member degrades the composition with a content-free
  ``CAPABILITY_MISSING`` reason — never an exception;
* an inapplicable member lens is a TYPED conflict (the member drops, the
  survivors compose), never a crash;
* tenant isolation — every member request carries the composition tenant and a
  tenant's composition never leaks another tenant's data;
* section-id sets are exactly the deterministic UNION of member section
  vocabularies (economic360 / outcome360 share the five measurement slots;
  infrastructure360 renders ``deployments`` in place of ``outcomes``);
* order-stable, deterministic output (identical input -> identical section
  order and content digest).

Members run through a :class:`ProjectionExecutor` over a FRESH
:class:`ProviderRegistry` of stub providers (mirroring
``test_projection_engine_executor.py``), so the global registry is never
touched and no real provider is required.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.intelligence_projections.contracts import (  # noqa: E402
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry  # noqa: E402
from shared.projection_engine.composition import (  # noqa: E402
    CompositionConflict,
    CompositionContext,
    CompositionResult,
    compose_economic_infrastructure,
    compose_economic_outcome,
    compose_operational_value_triangle,
    compose_outcome_infrastructure,
)
from shared.projection_engine.conflict import ConflictClass  # noqa: E402
from shared.projection_engine.executor import ProjectionExecutor  # noqa: E402

# The three member projections and the section vocabulary their providers
# render (mirrors the real providers: economic360/outcome360 share the five
# measurement slots; infrastructure360 renders deployments in place of
# outcomes).
_MEMBERS = ("economic360", "infrastructure360", "outcome360")

_SECTION_IDS: dict[str, tuple[str, ...]] = {
    "economic360": ("summary", "state", "evidence", "outcomes", "findings"),
    "outcome360": ("summary", "state", "evidence", "outcomes", "findings"),
    "infrastructure360": ("summary", "state", "deployments", "evidence", "findings"),
}


# ── Test doubles ──────────────────────────────────────────────────────────────


class _StubProvider:
    """A fixed-section stub projection provider.

    ``projection_id`` / ``contract_version`` satisfy the P0 provider protocol;
    ``project`` returns a typed, tenant-scoped result whose section ids come
    from ``_SECTION_IDS`` and whose content is tagged with the projection id and
    tenant (for tenant-isolation assertions). A provider can be configured to
    raise (fail-isolation path) or to echo every request it sees.
    """

    def __init__(
        self,
        projection_id: str,
        *,
        raises: Exception | None = None,
    ) -> None:
        self.projection_id = projection_id
        self.contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
        self._raises = raises
        self.calls: list[ProjectionRequest] = []

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        self.calls.append(request)
        if self._raises is not None:
            raise self._raises
        return ProjectionResult(
            projectionId=request.projectionId,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=[
                ProjectionSection(
                    id=section_id,
                    state="available",
                    content={"marker": f"{request.tenantId}/{self.projection_id}/{section_id}"},
                )
                for section_id in _SECTION_IDS[self.projection_id]
            ],
            claims=[
                ClaimEnvelope(
                    id=f"{request.tenantId}.{self.projection_id}.claim.1",
                    kind="observation",
                    subject=request.subject,
                    evidenceRefs=[],
                    claims=[f"{request.tenantId} {self.projection_id}"],
                )
            ],
            dependencyState=list(context.dependencyState),
            generatedAt="2026-09-02T00:00:00Z",
            degradedReasons=[],
        )


def _subject(kind: str = "entity", ident: str = "ent_1") -> ProjectionSubject:
    return ProjectionSubject(kind=kind, id=ident)


def _dump_json(result: object) -> str:
    """Serialize a CompositionResult (plain dataclass over Pydantic models).

    CompositionResult is NOT a Pydantic model, so it has no ``model_dump_json``;
    this helper recurses over the dataclass and converts any Pydantic member
    results via ``model_dump`` so tests can probe the WHOLE composite for
    content-free hygiene / cross-tenant leakage.
    """

    def primitives(value: object) -> object:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")  # type: ignore[attr-defined]
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: primitives(getattr(value, field.name))
                for field in dataclasses.fields(value)
            }
        if isinstance(value, dict):
            return {str(key): primitives(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [primitives(item) for item in value]
        if isinstance(value, enum.Enum):
            return value.value
        return value

    return json.dumps(primitives(result), sort_keys=True)


def _executor_with(*providers: object) -> ProjectionExecutor:
    """A fresh executor over a FRESH registry of stub providers."""
    registry = ProviderRegistry()
    for provider in providers:
        registry.register(provider)
    return ProjectionExecutor(registry=registry)


def _section_ids(result: CompositionResult) -> list[str]:
    return [s.id for s in result.sections]


# ---------------------------------------------------------------------------
# Each pair / the triangle composes when all member providers are present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compose_economic_outcome_unions_sections() -> None:
    executor = _executor_with(_StubProvider("economic360"), _StubProvider("outcome360"))
    context = CompositionContext(tenant_id="tenant-a", subject=_subject())

    result = await compose_economic_outcome(context, executor=executor)

    assert isinstance(result, CompositionResult)
    assert result.members == ("economic360", "outcome360")
    assert result.tenant_id == "tenant-a"
    assert result.subject == _subject()
    # The composed lens frame is base + member overlays, registry-ordered.
    assert result.composed_lens_ids == ("standard", "economic", "outcome")
    # Union of the shared five measurement slots — no duplicates.
    assert _section_ids(result) == ["summary", "state", "evidence", "outcomes", "findings"]
    assert result.degradation is not None
    assert result.degradation.level == "none"
    assert result.degraded_members == ()
    assert result.conflicts == ()
    # Every member's full result survives under member_results.
    assert set(result.member_results) == {"economic360", "outcome360"}


@pytest.mark.asyncio
async def test_compose_economic_infrastructure_composes() -> None:
    executor = _executor_with(
        _StubProvider("economic360"), _StubProvider("infrastructure360")
    )
    context = CompositionContext(tenant_id="tenant-a", subject=_subject())

    result = await compose_economic_infrastructure(context, executor=executor)

    assert result.members == ("economic360", "infrastructure360")
    assert result.composed_lens_ids == ("standard", "economic", "infrastructure")
    assert set(_section_ids(result)) == {
        "summary",
        "state",
        "evidence",
        "outcomes",
        "findings",
        "deployments",
    }
    assert result.degradation is not None
    assert result.degradation.level == "none"
    assert result.degraded_members == ()


@pytest.mark.asyncio
async def test_compose_outcome_infrastructure_keeps_deployments_vocab() -> None:
    executor = _executor_with(
        _StubProvider("outcome360"), _StubProvider("infrastructure360")
    )
    context = CompositionContext(tenant_id="tenant-a", subject=_subject())

    result = await compose_outcome_infrastructure(context, executor=executor)

    assert result.members == ("infrastructure360", "outcome360")
    assert result.composed_lens_ids == ("standard", "infrastructure", "outcome")
    # infrastructure360 renders deployments — never outcomes — and outcome360
    # renders outcomes — never deployments. The composition keeps BOTH.
    infra = result.member_results["infrastructure360"]
    outcome = result.member_results["outcome360"]
    assert "deployments" in [s.id for s in infra.sections]
    assert "outcomes" not in [s.id for s in infra.sections]
    assert "outcomes" in [s.id for s in outcome.sections]
    assert "deployments" not in [s.id for s in outcome.sections]
    # Top-level flattened union preserves every distinct member section id.
    assert set(_section_ids(result)) == {
        "summary",
        "state",
        "evidence",
        "findings",
        "outcomes",
        "deployments",
    }
    assert len(_section_ids(result)) == len(set(_section_ids(result)))


@pytest.mark.asyncio
async def test_compose_operational_value_triangle_runs_all_three() -> None:
    executor = _executor_with(
        _StubProvider("economic360"),
        _StubProvider("infrastructure360"),
        _StubProvider("outcome360"),
    )
    context = CompositionContext(tenant_id="tenant-a", subject=_subject())

    result = await compose_operational_value_triangle(context, executor=executor)

    assert result.members == ("economic360", "infrastructure360", "outcome360")
    assert result.composed_lens_ids == (
        "standard",
        "economic",
        "infrastructure",
        "outcome",
    )
    assert set(result.member_results) == {
        "economic360",
        "infrastructure360",
        "outcome360",
    }
    # summary/state/evidence/findings (shared) + outcomes + deployments.
    assert set(_section_ids(result)) == {
        "summary",
        "state",
        "evidence",
        "findings",
        "outcomes",
        "deployments",
    }
    assert result.degradation is not None
    assert result.degradation.level == "none"
    assert result.degraded_members == ()


# ---------------------------------------------------------------------------
# A missing member degrades the composition (content-free, never raises)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_member_degrades_capability_missing_no_raise() -> None:
    # Only economic360 is registered — outcome360 has no provider at all.
    executor = _executor_with(_StubProvider("economic360"))
    context = CompositionContext(tenant_id="tenant-a", subject=_subject())

    result = await compose_economic_outcome(context, executor=executor)

    assert result.degraded_members == ("outcome360",)
    assert result.degradation is not None
    assert result.degradation.level == "partial"
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert isinstance(conflict, CompositionConflict)
    assert conflict.member == "outcome360"
    assert conflict.conflict_class == ConflictClass.CAPABILITY_MISSING
    assert conflict.reason == "no provider registered for member projection 'outcome360'"
    # The surviving member still composes — nothing is dropped silently.
    assert "economic360" not in result.degraded_members
    assert _section_ids(result) == ["summary", "state", "evidence", "outcomes", "findings"]
    # The degraded member's own result is an EMPTY, fully-degraded projection
    # (an "available: false"-style state) — not an exception.
    degraded = result.member_results["outcome360"]
    assert degraded.sections == []
    assert degraded.degradation is not None
    assert degraded.degradation.level == "full"


@pytest.mark.asyncio
async def test_raising_member_degrades_with_content_free_reason() -> None:
    # outcome360 raises a provider error carrying a secret diagnostic; the
    # executor fail-isolates it and the composition degrades the member with a
    # content-free reason — the diagnostic NEVER surfaces anywhere.
    executor = _executor_with(
        _StubProvider("economic360"),
        _StubProvider("outcome360", raises=RuntimeError("secret provider diagnostic")),
    )
    context = CompositionContext(tenant_id="tenant-a", subject=_subject())

    result = await compose_economic_outcome(context, executor=executor)

    assert result.degraded_members == ("outcome360",)
    assert result.degradation is not None
    assert result.degradation.level == "partial"
    assert len(result.conflicts) == 1
    assert result.conflicts[0].conflict_class == ConflictClass.CAPABILITY_MISSING
    assert "secret provider diagnostic" not in _dump_json(result)
    assert "RuntimeError" not in _dump_json(result)
    assert "secret provider diagnostic" not in str(result.conflicts[0].reason)
    # economic360's sections survived the failing sibling.
    assert set(_section_ids(result)) == {
        "summary",
        "state",
        "evidence",
        "outcomes",
        "findings",
    }


# ---------------------------------------------------------------------------
# An inapplicable member lens is a typed conflict — never a crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inapplicable_member_lens_is_typed_conflict_not_crash() -> None:
    # The outcome overlay cannot apply to a ``source`` subject kind (its
    # applicableSubjectKinds exclude it), so the outcome360 member must drop as
    # a typed CAPABILITY_MISSING conflict while economic360 still composes.
    executor = _executor_with(_StubProvider("economic360"), _StubProvider("outcome360"))
    context = CompositionContext(tenant_id="tenant-a", subject=_subject(kind="source", ident="src_1"))

    result = await compose_economic_outcome(context, executor=executor)

    # No crash; the composition survives with a typed conflict.
    assert result.composed_lens_ids == ("standard", "economic")
    assert result.degraded_members == ("outcome360",)
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.member == "outcome360"
    assert conflict.conflict_class == ConflictClass.CAPABILITY_MISSING
    assert "cannot apply to subject kind" in conflict.reason
    assert result.degradation is not None
    assert result.degradation.level == "partial"
    # economic360 (whose lens DOES apply to source) still renders in full.
    assert "economic360" not in result.degraded_members
    assert _section_ids(result) == ["summary", "state", "evidence", "outcomes", "findings"]


# ---------------------------------------------------------------------------
# Tenant isolation — each member request carries the subject tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_requests_carry_tenant_and_no_cross_tenant_leak() -> None:
    economic = _StubProvider("economic360")
    outcome = _StubProvider("outcome360")
    executor = _executor_with(economic, outcome)
    context_a = CompositionContext(tenant_id="tenant-a", subject=_subject())
    context_b = CompositionContext(tenant_id="tenant-b", subject=_subject())

    result_a = await compose_economic_outcome(context_a, executor=executor)
    # Reset the record so run B is measured in isolation.
    economic.calls.clear()
    outcome.calls.clear()
    result_b = await compose_economic_outcome(context_b, executor=executor)

    # Every member request the executor issued for tenant A carried tenant-a.
    assert economic.calls and outcome.calls
    for call in economic.calls + outcome.calls:
        assert call.tenantId == "tenant-b", call.tenantId
    # The composed results are tenant-scoped end to end.
    assert result_a.tenant_id == "tenant-a"
    assert result_b.tenant_id == "tenant-b"
    assert all(r.tenantId == "tenant-a" for r in result_a.member_results.values())
    assert all(r.tenantId == "tenant-b" for r in result_b.member_results.values())
    # No tenant-b marker leaks into tenant A's composition, and vice versa.
    assert "tenant-b" not in _dump_json(result_a)
    assert "tenant-a" not in _dump_json(result_b)
    # Content is keyed to the requesting tenant.
    markers = {
        marker
        for section in result_a.sections
        if section.content
        for marker in [section.content["marker"]]
    }
    assert markers and all(marker.startswith("tenant-a/") for marker in markers)


# ---------------------------------------------------------------------------
# Determinism / order stability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composition_is_deterministic_across_identical_runs() -> None:
    executor = _executor_with(
        _StubProvider("economic360"),
        _StubProvider("infrastructure360"),
        _StubProvider("outcome360"),
    )
    context = CompositionContext(tenant_id="tenant-a", subject=_subject())

    first = await compose_operational_value_triangle(context, executor=executor)
    second = await compose_operational_value_triangle(context, executor=executor)

    # Identical member sets + identical content -> identical section ORDER and
    # an identical content digest (generatedAt / page are excluded by design).
    assert _section_ids(first) == _section_ids(second)
    assert first.composed_lens_ids == second.composed_lens_ids
    assert first.members == second.members
    assert first.digest == second.digest
    assert first.digest is not None and len(first.digest) == 64
    # The section vocabulary is exactly the union with no duplicates.
    assert _section_ids(first) == [
        "summary",
        "state",
        "evidence",
        "outcomes",
        "findings",
        "deployments",
    ]
