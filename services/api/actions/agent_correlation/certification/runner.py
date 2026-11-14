"""Replay certification fixtures and compute each mapper kind's certification status."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

from actions.agent_correlation.certification.fixtures import Fixture, digest, load_fixtures
from actions.agent_correlation.engine import CorrelationEngine
from actions.agent_correlation.keys import CorrelationKeyring
from actions.agent_correlation.mappers import PROVIDERS, AccountBinding, MapperContext, map_record
from actions.agent_correlation.repository import (
    CorrelationKeyIndexRepository,
    CorrelationObservationRepository,
    CorrelationVerdictRepository,
)
from shared.integration_contracts.correlation import CorrelationObservation
from shared.integration_contracts.correlation_token import token_verifier

REPORT_PATH = Path(__file__).resolve().parents[5] / "config" / "agent_correlation_certification.json"
REPORT_SCHEMA_VERSION = "1"

# Kinds that no provider read API can return; they arrive from a tenant export.
NOT_RECORDABLE = {
    ("cloudflare", "http_request"): "tenant Logpush or Worker export; Cloudflare has no read API for request rows",
}
FIRST_PARTY_PROVIDERS = {"aether_mcp"}


class _NullProjector:
    async def project(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"graph_projection_status": "not_applicable", "graph_mutations_persisted": 0}


def _isolated(repo: Any) -> Any:
    """A repository with its own empty in-memory store and no database pool."""
    repo._store = {}  # noqa: SLF001 - certification never touches shared stores

    async def _no_pool() -> None:
        return None

    repo._ensure_pool = _no_pool  # noqa: SLF001
    return repo


def isolated_engine(keyring: Optional[CorrelationKeyring], *, now: Optional[datetime] = None) -> CorrelationEngine:
    return CorrelationEngine(
        token_verifier=token_verifier(keyring.keys, now=now) if keyring else None,
        time_window=timedelta(minutes=5),
        observations=_isolated(CorrelationObservationRepository()),
        keys=_isolated(CorrelationKeyIndexRepository()),
        verdicts=_isolated(CorrelationVerdictRepository()),
        projector=_NullProjector(),  # type: ignore[arg-type]
    )


def context_for(tenant_id: str, bindings: dict[str, dict[str, str]]) -> MapperContext:
    return MapperContext(
        tenant_id=tenant_id,
        account_bindings={
            family: AccountBinding(b["source_account_key"], b.get("source_account_realm", "test"))
            for family, b in bindings.items()
        },
    )


def observation_digest(observations: Iterable[CorrelationObservation]) -> str:
    return digest([o.model_dump(mode="json") for o in observations])


def expected_from(observations: list[CorrelationObservation]) -> dict[str, Any]:
    return {
        "observation_count": len(observations),
        "roles": sorted({o.source_role for o in observations}),
        "object_types": sorted({r.object_type for o in observations for r in o.object_refs}),
        "tokens": sum(len(o.correlation_tokens) for o in observations),
        "observation_digest": observation_digest(observations),
    }


async def live_links(
    keyring: Optional[CorrelationKeyring],
    tenant_id: str,
    companions: list[CorrelationObservation],
    observations: list[CorrelationObservation],
    *,
    now: Optional[datetime] = None,
    provider: str,
    kind: str,
) -> list[dict[str, str]]:
    """Link decisions the observations make against the certification task."""
    engine = isolated_engine(keyring, now=now)
    for companion in companions:
        await engine.ingest(companion, provider="aether_mcp", kind="task_registered")
    links: list[dict[str, str]] = []
    for obs in observations:
        result = await engine.ingest(obs, provider=provider, kind=kind)
        for d in result.decisions:
            links.append({
                "observation_id": obs.observation_id,
                "other_observation_id": d.other_observation_id,
                "status": d.verdict.status,
                "key_kind": d.verdict.key_kind or "",
                "evidence_class": d.verdict.evidence_class,
            })
    return sorted(links, key=lambda l: (l["observation_id"], l["other_observation_id"], l["key_kind"]))


def certification_keyring(block: Optional[dict[str, Any]]) -> Optional[CorrelationKeyring]:
    if not block:
        return None
    secret = base64.urlsafe_b64decode(block["key_b64"] + "=" * (-len(block["key_b64"]) % 4))
    return CorrelationKeyring(signing_key_id=block["key_id"], keys={block["key_id"]: secret})


@dataclass
class ReplayResult:
    fixture: Fixture
    passed: bool
    failures: list[str] = field(default_factory=list)


async def replay(fixture: Fixture) -> ReplayResult:
    failures: list[str] = []
    tenant_id = (fixture.certification or {}).get("tenant_id", "aether_certification")
    try:
        observations = map_record(fixture.provider, fixture.kind, context_for(tenant_id, fixture.account_bindings), fixture.record)
    except Exception as exc:  # noqa: BLE001 - any mapper failure is a certification failure
        return ReplayResult(fixture, False, [f"mapper rejected the recorded payload: {exc}"])
    if digest(fixture.record) != fixture.record_sha256:
        failures.append("record does not match its recorded digest")
    got = expected_from(observations)
    exp = fixture.expected
    for key in ("observation_count", "roles", "object_types", "tokens", "observation_digest"):
        if got[key] != getattr(exp, key):
            failures.append(f"{key}: expected {getattr(exp, key)!r}, got {got[key]!r}")
    if exp.links:
        block = fixture.certification or {}
        companions = [CorrelationObservation.model_validate(c) for c in block.get("companions", [])]
        now = datetime.fromisoformat(fixture.recorded_at)
        links = await live_links(
            certification_keyring(block), tenant_id, companions, observations,
            now=now, provider=fixture.provider, kind=fixture.kind,
        )
        for want in exp.links:
            if want not in links:
                failures.append(f"link not reproduced: {want}")
    return ReplayResult(fixture, not failures, failures)


async def replay_all(fixtures: Optional[list[Fixture]] = None) -> list[ReplayResult]:
    return [await replay(f) for f in (fixtures if fixtures is not None else load_fixtures())]


def build_report(results: list[ReplayResult]) -> dict[str, Any]:
    by_kind: dict[tuple[str, str], list[ReplayResult]] = {}
    for r in results:
        by_kind.setdefault((r.fixture.provider, r.fixture.kind), []).append(r)
    rows = []
    for provider, kinds in sorted(PROVIDERS.items()):
        for kind in sorted(kinds):
            recorded = by_kind.get((provider, kind), [])
            row: dict[str, Any] = {"provider": provider, "kind": kind, "fixtures": len(recorded)}
            if provider in FIRST_PARTY_PROVIDERS:
                row["status"] = "first_party"
                row["basis"] = "Aether's own MCP surface; covered by the MCP and end-to-end tests"
            elif recorded and all(r.passed for r in recorded):
                row["status"] = "sandbox_certified"
                row["last_recorded_at"] = max(r.fixture.recorded_at for r in recorded)
                row["provider_api"] = sorted({json.dumps(r.fixture.provider_api, sort_keys=True) for r in recorded})
            elif recorded:
                row["status"] = "failed"
                row["failures"] = sorted({f for r in recorded for f in r.failures})
            elif (provider, kind) in NOT_RECORDABLE:
                row["status"] = "not_recordable"
                row["basis"] = NOT_RECORDABLE[(provider, kind)]
            else:
                row["status"] = "uncertified"
            rows.append(row)
    return {"schema_version": REPORT_SCHEMA_VERSION, "kinds": rows}


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def load_report(path: Path = REPORT_PATH) -> Optional[dict[str, Any]]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None
