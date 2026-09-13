"""Noesis Relationship / Spine Intelligence adapter (Wave 3a) — read-only reads.

The adapter answers relationship_explain / influence_path / engagement_fidelity /
incentive_context_explain over an injectable read runtime, behind an injectable
consent provider (the Social360 surface requires historical-consent evaluation).
Under test: the standard envelope shape, tenant-scoped read invocation, and the
honest content-free degradation paths (consent_required / no_data /
provider_unavailable). Values returned by the read plane are surfaced verbatim —
a missing dimension is never coerced to zero and nothing is ever fabricated.

The tests bind a fake read runtime and consent provider so they never import
``services.relationship_intelligence`` (that package is built concurrently and
may not exist yet); the default lazy-import seams are exercised behind an
import blocker instead.
"""

from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")

from services.noesis.adapters.relationship_spine_adapter import (  # noqa: E402
    RelationshipSpineNoesisAdapter,
)

_FIDELITY_ROW = {
    "subject": "p_5",
    "interaction_frequency": 0.6,
    "interaction_depth": 0.4,
    "reciprocity": None,
    "persistence": None,
}


class _FakeReadRuntime:
    """Read runtime returning fixture envelopes for every read method."""

    def __init__(self, *, no_data: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str, str | None, int]] = []
        self._no_data = no_data or set()

    async def _answer(self, name: str, tenant_id: str, target: str | None, limit: int) -> dict | None:
        self.calls.append((name, tenant_id, target, limit))
        if name in self._no_data:
            return None
        return {
            "subject": target or "current",
            "summary": f"measured {name} digest for {target or 'current'}",
            "as_of": "2026-09-04T00:00:00Z",
            "rows": [{"read": name, "tenant_id": tenant_id, "subject": target or "current"}],
        }

    async def relationship_explain(self, *, tenant_id: str, target: str | None, limit: int) -> dict | None:
        return await self._answer("relationship_explain", tenant_id, target, limit)

    async def influence_path(self, *, tenant_id: str, target: str | None, limit: int) -> dict | None:
        return await self._answer("influence_path", tenant_id, target, limit)

    async def engagement_fidelity(self, *, tenant_id: str, target: str | None, limit: int) -> dict | None:
        return await self._answer("engagement_fidelity", tenant_id, target, limit)

    async def incentive_context_explain(self, *, tenant_id: str, target: str | None, limit: int) -> dict | None:
        return await self._answer("incentive_context_explain", tenant_id, target, limit)


async def _allow(*args, **kwargs) -> bool:
    return True


async def _deny(*args, **kwargs) -> bool:
    return False


async def _raise(*args, **kwargs) -> bool:
    raise RuntimeError("consent evaluation exploded")


def _consent_provider(decision: str = "allow"):
    return {"allow": _allow, "deny": _deny, "raise": _raise}[decision]


def _adapter(*, runtime=None, consent=None) -> RelationshipSpineNoesisAdapter:
    return RelationshipSpineNoesisAdapter(
        read_runtime=runtime,
        consent_provider=_consent_provider() if consent is None else consent,
    )


def _block_relationship_intelligence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the default lazy-import seams to fail deterministically.

    The ``services.relationship_intelligence`` package is built concurrently and
    may or may not exist on disk when these tests run — block its import so the
    default-seam degradation path is asserted regardless of that package's state.
    """
    real_import = builtins.__import__

    def _blocked(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "services.relationship_intelligence" or name.startswith(
            "services.relationship_intelligence."
        ):
            raise ModuleNotFoundError(f"No module named {name!r} (blocked in test)")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _blocked)


# ---------------------------------------------------------------------------
# Envelope shape + tenant-scoped reads on data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_each_read_returns_standard_envelope() -> None:
    runtime = _FakeReadRuntime()
    adapter = _adapter(runtime=runtime, consent=_consent_provider("allow"))

    results = {
        "relationship_explain": await adapter.relationship_explain("tenant-a", "ent_1", 5),
        "influence_path": await adapter.influence_path("tenant-a", "ent_1", 5),
        "engagement_fidelity": await adapter.engagement_fidelity("tenant-a", "ent_1", 5),
        "incentive_context_explain": await adapter.incentive_context_explain("tenant-a", "ent_1", 5),
    }

    for intent, result in results.items():
        assert set(result) == {"answer", "results", "sources", "sufficient", "degraded", "reason"}
        assert result["sufficient"] is True
        assert result["degraded"] is False
        assert result["reason"] is None
        assert isinstance(result["answer"], str) and result["answer"]
        assert result["results"] == [
            {"read": intent, "tenant_id": "tenant-a", "subject": "ent_1"}
        ]

    # Every read was tenant-scoped and passed target + limit through.
    assert runtime.calls == [
        ("relationship_explain", "tenant-a", "ent_1", 5),
        ("influence_path", "tenant-a", "ent_1", 5),
        ("engagement_fidelity", "tenant-a", "ent_1", 5),
        ("incentive_context_explain", "tenant-a", "ent_1", 5),
    ]


@pytest.mark.asyncio
async def test_envelope_sources_name_the_canonical_substrates() -> None:
    runtime = _FakeReadRuntime()
    adapter = _adapter(runtime=runtime, consent=_consent_provider("allow"))

    assert (await adapter.relationship_explain("t", "x"))["sources"] == [
        "relationship_spine", "relationship_fidelity", "incentive_context",
    ]
    assert (await adapter.influence_path("t", "x"))["sources"] == [
        "relationship_spine", "influence_propagation", "computation_substrate",
    ]
    assert (await adapter.engagement_fidelity("t", "x"))["sources"] == [
        "relationship_fidelity", "relationship_spine",
    ]
    assert (await adapter.incentive_context_explain("t", "x"))["sources"] == [
        "incentive_context", "relationship_spine",
    ]


@pytest.mark.asyncio
async def test_measured_facts_are_surfaced_verbatim_missing_dims_never_zero() -> None:
    class _FidelityRuntime:
        async def engagement_fidelity(self, *, tenant_id: str, target: str | None, limit: int) -> dict:
            return {
                "subject": target,
                "summary": (
                    "Latest persisted fidelity vector for p_5 reports "
                    "interaction_frequency 0.6 and interaction_depth 0.4; "
                    "reciprocity and persistence are not yet measured."
                ),
                "as_of": "2026-09-04T00:00:00Z",
                "rows": [_FIDELITY_ROW],
            }

    adapter = _adapter(runtime=_FidelityRuntime(), consent=_consent_provider("allow"))
    result = await adapter.engagement_fidelity("tenant-a", "p_5")

    assert result["sufficient"] is True
    assert result["answer"] == (
        "Latest persisted fidelity vector for p_5 reports "
        "interaction_frequency 0.6 and interaction_depth 0.4; "
        "reciprocity and persistence are not yet measured."
    )
    # The measured row is surfaced verbatim — a missing dimension stays None
    # and is never coerced to 0.0.
    assert result["results"] == [_FIDELITY_ROW]
    assert result["results"][0]["reciprocity"] is None
    assert result["results"][0]["persistence"] is None
    assert result["results"][0]["interaction_frequency"] == 0.6


# ---------------------------------------------------------------------------
# Honest degradation paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_persisted_evidence_degrades_no_data() -> None:
    runtime = _FakeReadRuntime(no_data={"influence_path"})
    adapter = _adapter(runtime=runtime, consent=_consent_provider("allow"))

    result = await adapter.influence_path("tenant-a", "ent_9")

    assert result["sufficient"] is False
    assert result["degraded"] is True
    assert result["reason"] == "no_data"
    assert result["results"] == []
    # Content-free: no fabricated numbers or target-specific diagnostics.
    assert "measured" not in result["answer"]


@pytest.mark.asyncio
async def test_consent_denied_degrades_consent_required() -> None:
    runtime = _FakeReadRuntime()
    adapter = _adapter(runtime=runtime, consent=_consent_provider("deny"))

    result = await adapter.relationship_explain("tenant-a", "ent_1")

    assert result["sufficient"] is False
    assert result["degraded"] is True
    assert result["reason"] == "consent_required"
    assert result["results"] == []
    # The read runtime was never consulted when consent is not established.
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_consent_check_failure_is_fail_closed_consent_required() -> None:
    adapter = _adapter(runtime=_FakeReadRuntime(), consent=_consent_provider("raise"))

    result = await adapter.engagement_fidelity("tenant-a", "p_5")

    assert result["reason"] == "consent_required"
    assert result["sufficient"] is False
    assert result["degraded"] is True


@pytest.mark.asyncio
async def test_read_runtime_missing_method_degrades_provider_unavailable() -> None:
    class _BrokenRuntime:  # exposes no read methods
        pass

    adapter = _adapter(runtime=_BrokenRuntime(), consent=_consent_provider("allow"))

    result = await adapter.influence_path("tenant-a", "ent_1")

    assert result["reason"] == "provider_unavailable"
    assert result["sufficient"] is False
    assert result["results"] == []


@pytest.mark.asyncio
async def test_read_exception_degrades_provider_unavailable_content_free() -> None:
    class _ExplodingRuntime:
        async def influence_path(self, *, tenant_id: str, target: str | None, limit: int) -> dict:
            raise RuntimeError("influence substrate on fire")

    adapter = _adapter(runtime=_ExplodingRuntime(), consent=_consent_provider("allow"))

    result = await adapter.influence_path("tenant-a", "ent_1")

    assert result["reason"] == "provider_unavailable"
    assert result["sufficient"] is False
    assert "fire" not in result["answer"]


# ---------------------------------------------------------------------------
# Default lazy-import seams (relationship-intelligence package may be absent)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_consent_seam_is_fail_closed_when_module_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_relationship_intelligence(monkeypatch)
    # No injectables: the consent default (lazy import) cannot resolve → deny.
    adapter = RelationshipSpineNoesisAdapter()

    result = await adapter.relationship_explain("tenant-a", "ent_1")

    assert result["reason"] == "consent_required"
    assert result["sufficient"] is False


@pytest.mark.asyncio
async def test_default_read_runtime_degrades_when_module_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_relationship_intelligence(monkeypatch)
    # Consent granted (injected); the read-runtime default (lazy import)
    # cannot resolve → honest provider_unavailable degradation.
    adapter = RelationshipSpineNoesisAdapter(consent_provider=_consent_provider("allow"))

    result = await adapter.engagement_fidelity("tenant-a", "p_5")

    assert result["reason"] == "provider_unavailable"
    assert result["sufficient"] is False
