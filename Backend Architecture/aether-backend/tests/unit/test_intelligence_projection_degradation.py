"""Fail-isolation tests for the intelligence projection registry (P0.5, group 8).

The plane is fail-isolated: a missing / incompatible / absent dependency is a
COMPUTED context state — ``build_context`` never raises for any of them — and a
raising provider yields a DEGRADED result instead of taking the plane down. A
second, healthy projection on the SAME registry instance still returns
``available``. Degraded ``degradedReasons`` are content-free (exception class
name only; generic fallback for non-ProjectionError exceptions) — the message
and diagnostic ``context`` are never surfaced.
"""

from __future__ import annotations

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

from shared.intelligence_projections import (  # noqa: E402
    DependencyUnavailable,
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
    ProviderRegistry,
)


def _request(projection_id: str, **overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": projection_id,
        "tenantId": "tenant-a",
        "subject": ProjectionSubject(kind="entity", id="ent_1"),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


def _result(
    projection_id: str,
    request: ProjectionRequest,
    context: object,
    *,
    sections: list[ProjectionSection] | None = None,
) -> ProjectionResult:
    return ProjectionResult(
        projectionId=projection_id,
        tenantId=request.tenantId,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=list(sections) if sections is not None else [],
        claims=[],
        dependencyState=context.dependencyState,  # type: ignore[attr-defined]
        generatedAt="2026-08-23T12:00:00Z",
        degradedReasons=[],
    )


class _ClusterProvider:
    """cluster360 provider that omits its population section when the dep is missing."""

    projection_id = "cluster360"
    contract_version = "1.0.0"

    async def project(self, request: ProjectionRequest, context: ProjectionContext) -> ProjectionResult:
        population = next(
            (d for d in context.dependencyState if d.projectionId == "population360"),
            None,
        )
        sections: list[ProjectionSection] = []
        if population is not None and population.state == "available":
            sections.append(
                ProjectionSection(id="population", state="available", title="Population")
            )
        return _result("cluster360", request, context, sections=sections)


class _HealthySourceProvider:
    """source360 provider — no hard deps, always available."""

    projection_id = "source360"
    contract_version = "1.0.0"

    async def project(self, request: ProjectionRequest, context: ProjectionContext) -> ProjectionResult:
        return _result(
            "source360",
            request,
            context,
            sections=[
                ProjectionSection(
                    id="state",
                    state="available",
                    content={"tenantId": request.tenantId},
                )
            ],
        )


class _RaisingProvider:
    """profile360 provider that raises a ProjectionError with a secret-ish message."""

    projection_id = "profile360"
    contract_version = "1.0.0"

    async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
        raise DependencyUnavailable(
            "the temporal ledger is down for tenant-a; password=topsecret",
            projection_id=self.projection_id,
            context={"tenantId": request.tenantId, "diagnostic": "secret detail"},
        )


class _BoomProvider:
    """profile360 provider that raises a NON-ProjectionError exception."""

    projection_id = "profile360"
    contract_version = "1.0.0"

    async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
        raise RuntimeError("something exploded; password=topsecret")


def _population_provider(version: str = "1.0.0"):
    class _PopulationProvider:
        projection_id = "population360"
        contract_version = version

        async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
            return _result("population360", request, context)

    return _PopulationProvider()


# ---------------------------------------------------------------------------
# Missing hard dependency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_hard_dep_is_computed_missing_state() -> None:
    registry = ProviderRegistry()
    registry.register(_ClusterProvider())  # population360 is NOT registered

    request = _request("cluster360")
    context = await registry.build_context("cluster360", request)

    population = next(d for d in context.dependencyState if d.projectionId == "population360")
    assert population.state == "missing"
    assert context.registryState == "in_flight"  # definition's implementationState
    assert context.warnings == []  # a MISSING dep is a computed state, not a warning

    # build_context NEVER raises for a missing dep, and project() runs.
    result = await registry.project("cluster360", request)
    # The dependent population section is absent (provider honours the missing dep).
    assert result.sections == []
    assert result.degradedReasons == []


# ---------------------------------------------------------------------------
# Incompatible hard dependency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_incompatible_hard_dep_is_degraded_with_warning() -> None:
    registry = ProviderRegistry()
    registry.register(_ClusterProvider())
    population = _population_provider(version="1.0.0")
    registry.register(population)
    # Simulate a provider whose contract drifted out of compatibility after
    # registration (the registry re-introspects the live object).
    population.contract_version = "2.0.0"

    request = _request("cluster360")
    context = await registry.build_context("cluster360", request)

    population_state = next(
        d for d in context.dependencyState if d.projectionId == "population360"
    )
    assert population_state.state == "degraded"
    assert any("population360" in warning for warning in context.warnings)

    result = await registry.project("cluster360", request)
    # The provider sees the degraded dep and omits the dependent section.
    assert result.sections == []
    # Warnings are diagnostic-only — never surfaced in the result.
    assert result.degradedReasons == []


# ---------------------------------------------------------------------------
# Provider raising a ProjectionError -> fail-isolated degraded result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_project_error_returns_degraded_result_not_raise() -> None:
    registry = ProviderRegistry()
    registry.register(_RaisingProvider())

    request = _request("profile360")
    result = await registry.project("profile360", request)

    # NOT a raise: a valid, fail-isolated result.
    assert isinstance(result, ProjectionResult)
    assert result.projectionId == "profile360"
    assert result.tenantId == request.tenantId
    assert result.contractVersion == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    assert result.sections == []
    assert result.claims == []
    # Content-free reason: exception class name only.
    assert result.degradedReasons == ["DependencyUnavailable"]
    # Fail-closed secret hygiene: the message and diagnostic context are never
    # surfaced in degradedReasons.
    assert "topsecret" not in str(result.degradedReasons)
    assert "temporal ledger" not in str(result.degradedReasons)


# ---------------------------------------------------------------------------
# Fail-isolation: one broken projection never takes down the plane
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_broken_projection_does_not_take_down_healthy_projection() -> None:
    registry = ProviderRegistry()
    registry.register(_RaisingProvider())  # broken: profile360
    registry.register(_HealthySourceProvider())  # healthy: source360

    request = _request("profile360")
    broken = await registry.project("profile360", request)
    healthy = await registry.project("source360", _request("source360"))

    assert broken.degradedReasons == ["DependencyUnavailable"]
    assert broken.sections == []
    # The SAME registry instance still serves the healthy projection.
    assert healthy.sections[0].state == "available"
    assert healthy.sections[0].content == {"tenantId": "tenant-a"}
    assert healthy.degradedReasons == []


# ---------------------------------------------------------------------------
# Non-ProjectionError exception -> generic degraded reason
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_projection_error_yields_generic_degraded_reason() -> None:
    registry = ProviderRegistry()
    registry.register(_BoomProvider())

    result = await registry.project("profile360", _request("profile360"))
    assert isinstance(result, ProjectionResult)
    assert result.sections == []
    assert result.claims == []
    assert result.degradedReasons == ["projection provider failure"]
    # Secret hygiene holds for arbitrary exceptions too.
    assert "topsecret" not in str(result.degradedReasons)
    assert "exploded" not in str(result.degradedReasons)


# ---------------------------------------------------------------------------
# Optional dependencies
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_optional_dep_absent_is_not_applicable() -> None:
    registry = ProviderRegistry()
    registry.register(_HealthySourceProvider())  # any provider; source360 has no deps

    # profile360 declares optionalProjectionDependencies = ("risk360",).
    request = _request("profile360")
    context = await registry.build_context("profile360", request)

    risk = next(d for d in context.dependencyState if d.projectionId == "risk360")
    assert risk.state == "not_applicable"
    assert context.warnings == []


@pytest.mark.asyncio
async def test_optional_dep_present_compatible_is_available() -> None:
    registry = ProviderRegistry()
    registry.register(_HealthySourceProvider())

    class _RiskProvider:
        projection_id = "risk360"
        contract_version = "1.0.0"

        async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
            return _result("risk360", request, context)

    registry.register(_RiskProvider())

    context = await registry.build_context("profile360", _request("profile360"))
    risk = next(d for d in context.dependencyState if d.projectionId == "risk360")
    assert risk.state == "available"


# ---------------------------------------------------------------------------
# build_context NEVER raises across all dependency shapes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_context_never_raises_for_any_dependency_shape() -> None:
    registry = ProviderRegistry()
    registry.register(_ClusterProvider())
    population = _population_provider()
    registry.register(population)

    # 1) missing hard dep (no population360 yet -> remove it first).
    registry.unregister("population360")
    await registry.build_context("cluster360", _request("cluster360"))

    # 2) incompatible hard dep.
    registry.register(population)
    population.contract_version = "9.0.0"
    await registry.build_context("cluster360", _request("cluster360"))

    # 3) optional dep absent + optional dep present (profile360/risk360).
    await registry.build_context("profile360", _request("profile360"))

    # 4) a projection with no declared deps at all (source360).
    await registry.build_context("source360", _request("source360"))

    # 5) every registry id builds a context without raising.
    for projection_id in ("agent360", "campaign360", "relationship360", "execution360"):
        ctx = await registry.build_context(projection_id, _request(projection_id))
        assert isinstance(ctx, ProjectionContext)
        assert ctx.dependencyState is not None
        assert ctx.warnings is not None
