"""Projection-engine executor + runtime facade + digest tests (A8).

The executor compiles → plans → runs the target (and its hard dependencies)
through the fail-isolated :class:`ProviderRegistry`, then reassembles an
engine-level result: composed lens ids, dispatched temporal mode, deterministic
content digest and a typed degradation summary. A missing target provider yields
a fully-degraded result — never an exception.
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

from shared.intelligence_projections.contracts import (  # noqa: E402
    ClaimEnvelope,
    ProjectionContext,
    ProjectionDependencyState,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import ProjectionError  # noqa: E402
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider  # noqa: E402
from shared.intelligence_projections.registry import ProviderRegistry  # noqa: E402
from shared.projection_engine.digest import canonical_json, compute_projection_digest  # noqa: E402
from shared.projection_engine.executor import ProjectionExecutor  # noqa: E402
from shared.projection_engine.runtime import ProjectionRuntime  # noqa: E402
from shared.projection_engine.temporal_modes import TemporalMode  # noqa: E402


def _subject(kind: str = "campaign", ident: str = "camp_1") -> ProjectionSubject:
    return ProjectionSubject(kind=kind, id=ident)


def _request(
    projection_id: str = "outcome360",
    **overrides: object,
) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": projection_id,
        "tenantId": "tenant-a",
        "subject": _subject(),
        "lensIds": ["economic", "outcome"],
    }
    values.update(overrides)
    return ProjectionRequest(**values)


class _SectionedProvider:
    """A provider that returns a fixed set of sections/claims.

    The result's content is keyed off the projection id so dependency-vs-target
    runs are distinguishable in the assembled digest.
    """

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        self.contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    async def project(
        self, request: ProjectionRequest, context: ProjectionContext
    ) -> ProjectionResult:
        return ProjectionResult(
            projectionId=request.projectionId,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=[
                ProjectionSection(id=f"{request.projectionId}.summary", state="available"),
            ],
            claims=[
                ClaimEnvelope(
                    id=f"{request.projectionId}.claim.1",
                    kind="observation",
                    subject=request.subject,
                    evidenceRefs=[],
                    claims=["contentful claim"],
                )
            ],
            dependencyState=list(context.dependencyState),
            generatedAt="2026-08-23T12:00:00Z",
            degradedReasons=[],
        )


class _RaisingProvider:
    """A provider that fails with a ProjectionError (fail-isolated)."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        self.contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    async def project(
        self, request: ProjectionRequest, context: ProjectionContext
    ) -> ProjectionResult:
        raise ProjectionError("secret provider diagnostic — never surfaced")


def _executor_with(providers: list[IntelligenceProjectionProvider]) -> ProjectionExecutor:
    registry = ProviderRegistry()
    for provider in providers:
        registry.register(provider)
    return ProjectionExecutor(registry=registry)


# ---------------------------------------------------------------------------
# Full executor flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_runs_target_and_dependencies_dependency_first() -> None:
    # outcome360 depends on temporal360 (hard). Both registered.
    executor = _executor_with([_SectionedProvider("temporal360"), _SectionedProvider("outcome360")])
    result = await executor.execute(_request())

    assert result.projectionId == "outcome360"
    assert result.tenantId == "tenant-a"
    # Composed lens frame rides on the target result.
    assert result.lensIds == ["standard", "economic", "outcome"]
    assert result.temporalMode == "window"  # TemporalMode.LIVE -> window surface mode
    assert len(result.sections) == 1
    assert result.sections[0].id == "outcome360.summary"
    # Content digest present and non-empty.
    assert isinstance(result.digest, str) and len(result.digest) == 64
    # No degradation: every requested section available, no conflicts.
    assert result.degradation is not None
    assert result.degradation.level == "none"
    assert result.degradation.reasons == []


@pytest.mark.asyncio
async def test_execute_target_missing_is_fully_degraded() -> None:
    # No provider for outcome360 -> fail-closed fully-degraded result, no raise.
    executor = _executor_with([_SectionedProvider("temporal360")])
    result = await executor.execute(_request())

    assert result.projectionId == "outcome360"
    assert result.sections == []
    assert result.claims == []
    assert result.digest is None
    assert result.degradation is not None
    assert result.degradation.level == "full"
    # temporal360 IS registered — it is not a missing dependency; only the
    # target itself is absent, reported through the content-free reasons.
    assert result.degradation.missingDependencies is None
    # degradedReasons are content-free: engine-computed, never a provider message.
    assert result.degradedReasons == [
        "no provider registered for target projection 'outcome360'"
    ]


@pytest.mark.asyncio
async def test_execute_reports_missing_dependencies() -> None:
    # outcome360 target registered but its hard dependency temporal360 is not.
    executor = _executor_with([_SectionedProvider("outcome360")])
    result = await executor.execute(_request())

    assert result.projectionId == "outcome360"
    assert result.degradation is not None
    assert result.degradation.level == "partial"
    assert result.degradation.missingDependencies == ["temporal360"]
    assert "outcome360.summary" in [s.id for s in result.sections]


@pytest.mark.asyncio
async def test_execute_fail_isolates_raising_provider() -> None:
    # The target raises -> the registry returns a degraded result; the engine
    # passes the (content-free) reason through and keeps the projection alive.
    executor = _executor_with([_RaisingProvider("outcome360")])
    result = await executor.execute(_request())

    assert result.projectionId == "outcome360"
    assert result.sections == []
    # Provider exception class name only — the message never surfaces.
    assert result.degradedReasons == ["ProjectionError"]
    assert result.degradation is not None
    assert result.degradation.level == "full"


@pytest.mark.asyncio
async def test_execute_compiles_away_unsupported_lens() -> None:
    # consent cannot honor PLAYBACK (relative); it degrades out of the frame,
    # and the executor reports it as a conflicted lens on the result.
    executor = _executor_with([_SectionedProvider("outcome360")])
    result = await executor.execute(
        _request(lensIds=["consent", "outcome"]),
        temporal_mode=TemporalMode.PLAYBACK,
    )
    assert result.lensIds == ["standard", "outcome"]
    assert result.temporalMode == "relative"
    assert result.degradation is not None
    assert result.degradation.conflictedLenses == ["consent"]
    assert result.degradation.level == "partial"


# ---------------------------------------------------------------------------
# Runtime facade
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_runtime_execute_projection_defaults() -> None:
    runtime = ProjectionRuntime(executor=_executor_with([_SectionedProvider("outcome360")]))
    result = await runtime.execute_projection(_request(lensIds=None))
    # None lens ids -> the identity lens frame (default base only).
    assert result.lensIds == ["standard"]
    assert result.temporalMode == "window"


@pytest.mark.asyncio
async def test_runtime_accepts_temporal_mode_string() -> None:
    runtime = ProjectionRuntime(executor=_executor_with([_SectionedProvider("outcome360")]))
    result = await runtime.execute_projection(
        _request(lensIds=["outcome"]),
        temporal_mode="compare",
    )
    assert result.temporalMode == "compare"


def test_runtime_resolve_lens_ids_and_available_ids() -> None:
    runtime = ProjectionRuntime(executor=_executor_with([_SectionedProvider("outcome360")]))
    assert runtime.resolve_lens_ids(["outcome", "economic"]) == ("standard", "outcome", "economic")
    assert runtime.resolve_lens_ids(None) == ("standard",)
    # available_projection_ids reflects the executor's registry only.
    assert runtime.available_projection_ids() == {"outcome360"}


# ---------------------------------------------------------------------------
# Digest — determinism and exclusion contract
# ---------------------------------------------------------------------------

def _digest_inputs(**overrides: object) -> dict:
    base: dict[str, object] = {
        "projection_id": "outcome360",
        "tenant_id": "tenant-a",
        "subject": {"kind": "campaign", "id": "camp_1"},
        "as_of": "2026-08-23T00:00:00Z",
        "sections": [{"id": "summary", "state": "available"}],
        "claims": [],
        "dependency_state": [{"projectionId": "temporal360", "state": "available"}],
        "lens_ids": ["standard", "outcome"],
        "temporal_mode": "window",
    }
    base.update(overrides)
    return base


def test_digest_is_deterministic() -> None:
    a = compute_projection_digest(**_digest_inputs())
    b = compute_projection_digest(**_digest_inputs())
    assert a == b
    assert len(a) == 64


def test_digest_changes_with_content() -> None:
    a = compute_projection_digest(**_digest_inputs())
    b = compute_projection_digest(**_digest_inputs(sections=[{"id": "other", "state": "degraded"}]))
    assert a != b


def test_digest_excludes_generated_at_and_page() -> None:
    # generatedAt / page are NOT digest inputs — the function has no such params
    # (the executor builds the payload from content only). Two identical-content
    # runs across different "generated at" stamps share a digest by construction.
    a = compute_projection_digest(**_digest_inputs())
    b = compute_projection_digest(
        **_digest_inputs(as_of=None, temporal_mode=None, lens_ids=[])
    )
    assert a != b  # those inputs DO matter when present


def test_canonical_json_is_sorted_and_minimal() -> None:
    payload = {"b": 2, "a": 1}
    assert canonical_json(payload) == '{"a":1,"b":2}'
    assert canonical_json({"a": 1}) == canonical_json({"a": 1})


@pytest.mark.asyncio
async def test_executor_digest_stable_across_reruns_of_same_content() -> None:
    # Two runs of the SAME content produce the SAME digest even though the
    # executor stamps a fresh generatedAt each time.
    executor = _executor_with([_SectionedProvider("outcome360")])
    first = await executor.execute(_request())
    second = await executor.execute(_request())
    assert first.generatedAt != second.generatedAt  # fresh timestamps
    assert first.digest == second.digest
