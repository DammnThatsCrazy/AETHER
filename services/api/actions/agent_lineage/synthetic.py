"""Deterministic synthetic lineage populations with ground truth.

Used by the test suite and ``scripts/agent_lineage_scale_proof.py``; nothing in
the runtime imports this. A fixture is a mix of the populations the work order
requires, generated from a seed so a tier always produces the same evidence:

  * legitimate swarm: a verified human, an orchestrator, project agents, workers
    and short-lived test agents with high spawn velocity and mass tool use;
  * malicious swarm: a verified link at the top, then a burst of orchestrators,
    workers, wallet scanners and ephemeral transaction agents, with authority
    violations, revoked branches and verified fraudulent effects;
  * uncertain cluster: agents sharing infrastructure and timing with no principal;
  * edge cases: missing parents, cycles, replayed events, late observations,
    conflicting claims, impostors naming a verified parent, a chain deeper than
    the processed depth, and another tenant reusing the same ids.

``Truth`` records what a correct resolver must conclude for each agent, so the
proof can measure attribution quality rather than only speed.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .evidence import AuthorityRecord, PrincipalBinding

TENANT = "tenant-proof"
OTHER_TENANT = "tenant-other"
LEGIT_HUMAN = "human:h2"
MALICIOUS_HUMAN = "human:h1"
_BASE = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)


@dataclass
class Truth:
    """What a correct resolver concludes for one agent."""

    principal: Optional[str]
    #: ``verified`` / ``inferred`` / ``suspected_cluster`` / ``unresolved``
    attribution: str
    parent: Optional[str]
    root: Optional[str] = None
    cyclic: bool = False
    authority_status: Optional[str] = None


@dataclass
class Fixture:
    tier: int
    facts: list[dict[str, Any]] = field(default_factory=list)
    authorities: list[AuthorityRecord] = field(default_factory=list)
    bindings: list[PrincipalBinding] = field(default_factory=list)
    truth: dict[str, Truth] = field(default_factory=dict)
    foreign_facts: list[dict[str, Any]] = field(default_factory=list)
    replayed_events: int = 0
    populations: dict[str, int] = field(default_factory=dict)


def _at(seconds: float) -> str:
    return (_BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


class _Builder:
    def __init__(self, fixture: Fixture, rng: random.Random) -> None:
        self.fixture = fixture
        self.rng = rng
        self.sequence = 0

    def fact(self, agent: Optional[str], event: str, at: float, **extra: Any) -> dict[str, Any]:
        self.sequence += 1
        row = {
            "tenant_id": TENANT,
            "source_event_id": f"ev-{self.sequence}",
            "source_event_type": event,
            "agent_id": agent,
            "occurred_at": _at(at),
            **extra,
        }
        self.fixture.facts.append(row)
        return row

    def spawn(self, parent: str, child: str, at: float, *, state: Optional[str], deployment: str) -> None:
        self.fact(
            parent, "agent_subagent_spawned", at, parent_agent_ref=parent, child_agent_ref=child,
            execution_verification_state=state, deployment_id=deployment,
        )

    def work(
        self, agent: str, at: float, *, deployment: str, definition: str, state: Optional[str],
        tools: tuple[str, ...], instance: Optional[str] = None, **extra: Any,
    ) -> None:
        run = f"run-{agent}"
        instance = instance or f"inst-{agent}"
        for offset, tool in enumerate(tools):
            self.fact(
                agent, "agent_tool_invocation_observed", at + offset, tool_name=tool, server_name="mcp-core",
                provider="provider-a", source_run_id=run, agent_definition_id=definition,
                agent_instance_id=instance, deployment_id=deployment, execution_verification_state=state,
                root_run_id=f"root-{definition}", protocol="mcp", **extra,
            )


def _layered(count: int, widths: tuple[float, ...]) -> list[int]:
    """Split ``count`` across layers by share; the last layer takes the remainder."""
    sizes = []
    left = count
    for width in widths:
        size = max(1, int(count * width)) if left > 1 else 0
        size = min(size, left - 1) if left > 1 else 0
        sizes.append(size)
        left -= size
    sizes.append(left)
    return sizes


def _legit_swarm(b: _Builder, count: int) -> None:
    """Verified human -> orchestrator -> projects -> coders -> test workers."""
    fixture = b.fixture
    orchestrator = "legit-orch"
    fixture.authorities.append(AuthorityRecord(
        tenant_id=TENANT, authority_ref="grant-h2-orch", grantor_entity_id=LEGIT_HUMAN,
        grantee_entity_id=orchestrator, grantor_kind="principal", delegation_allowed=True,
        evidence_refs=("delegation:grant-h2-orch",),
    ))
    fixture.truth[orchestrator] = Truth(LEGIT_HUMAN, "verified", None, orchestrator, authority_status="verified")
    b.work(orchestrator, 0, deployment="dep-legit-core", definition="def-coding-orchestrator",
           state="deployment_verified", tools=("plan", "dispatch"), operator_entity_id="org:acme",
           risk_level="low")
    remaining = count - 1
    if remaining <= 0:
        return
    layers = _layered(remaining, (0.01, 0.19))
    parents = [orchestrator]
    index = 0
    for level, size in enumerate(layers):
        current = []
        for _ in range(size):
            index += 1
            agent = f"legit-{index}"
            parent = parents[index % len(parents)]
            # High spawn velocity is deliberate: scale must not read as fraud.
            at = 60 + index * 0.05
            b.spawn(parent, agent, at, state="deployment_verified", deployment="dep-legit-core")
            b.work(
                agent, at + 1, deployment=f"dep-legit-{level}", definition=f"def-legit-worker-{level}",
                state="deployment_verified", tools=("read_file", "run_tests"), operator_entity_id="org:acme",
                risk_level="low", outcome_ref=f"outcome-{index % 50}",
            )
            fixture.truth[agent] = Truth(LEGIT_HUMAN, "verified", parent, orchestrator, authority_status="verified")
            current.append(agent)
        parents = current or parents


def _malicious_swarm(b: _Builder, count: int) -> None:
    """Verified top link, burst fan-out, wallets, violations, verified fraud effects."""
    fixture = b.fixture
    orchestrator = "mal-orch"
    fixture.authorities.append(AuthorityRecord(
        tenant_id=TENANT, authority_ref="grant-h1-orch", grantor_entity_id=MALICIOUS_HUMAN,
        grantee_entity_id=orchestrator, grantor_kind="principal", delegation_allowed=True,
        # Delegation below level three is outside what the human granted.
        maximum_delegation_depth=2, evidence_refs=("delegation:grant-h1-orch",),
    ))
    fixture.truth[orchestrator] = Truth(MALICIOUS_HUMAN, "verified", None, orchestrator, authority_status="verified")
    b.work(orchestrator, 3600, deployment="dep-mal-core", definition="def-mal-orch",
           state="deployment_verified", tools=("plan",), risk_level="high")
    remaining = count - 1
    if remaining <= 0:
        return
    layers = _layered(remaining, (0.002, 0.018, 0.18))
    parents = [orchestrator]
    index = 0
    revoked_root: Optional[str] = None
    revoked: set[str] = set()
    for level, size in enumerate(layers):
        current = []
        for _ in range(size):
            index += 1
            agent = f"mal-{index}"
            parent = parents[index % len(parents)]
            at = 3660 + index * 0.002
            # The ephemeral layer's spawns are only source reported: strong at the
            # top of the swarm and inferred at the bottom, shown separately.
            ephemeral = level == len(layers) - 1
            b.spawn(parent, agent, at, state=None if ephemeral else "deployment_verified",
                    deployment="dep-mal-core")
            depth = level + 2
            if level == 1 and revoked_root is None:
                revoked_root = agent
                fixture.authorities.append(AuthorityRecord(
                    tenant_id=TENANT, authority_ref="grant-revoked-branch", grantor_entity_id=parent,
                    grantee_entity_id=agent, grantor_kind="agent", delegation_allowed=True,
                    revoked_at=3600 + _BASE.timestamp(), evidence_refs=("delegation:grant-revoked-branch",),
                ))
            in_revoked = agent == revoked_root or parent in revoked
            if in_revoked:
                revoked.add(agent)
            extra: dict[str, Any] = {"risk_level": "high" if index % 11 == 0 else "low"}
            if index % 7 == 0:
                extra["policy_decision"] = "denied"
            if index % 3 == 0:
                extra.update(object_type="wallet", object_id=f"wallet-{index % 400}")
            if index % 5 == 0:
                extra["payment_intent_ref"] = f"pi-{index}"
            b.work(agent, at + 1, deployment=f"dep-mal-{level}", definition=f"def-mal-worker-{level}",
                   state="deployment_verified", tools=("wallet_scan", "tx_attempt"), **extra)
            if index % 13 == 0:
                b.fact(agent, "agent_outcome_recorded", at + 5, external_effect_ref=f"effect-fraud-{index}",
                       execution_verification_state="attested", deployment_id=f"dep-mal-{level}")
            status = "revoked" if in_revoked else ("out_of_scope" if depth > 3 else "verified")
            fixture.truth[agent] = Truth(MALICIOUS_HUMAN, "inferred" if ephemeral else "verified", parent,
                                         orchestrator, authority_status=status)
            current.append(agent)
        parents = current or parents


def _uncertain_cluster(b: _Builder, count: int) -> None:
    """Shared infrastructure, timing and tooling, and no principal evidence at all."""
    for index in range(count):
        agent = f"unc-{index}"
        b.work(agent, 9000 + (index % 30), deployment="dep-shared-infra", definition="def-unknown",
               state=None, tools=("http_get",))
        b.fixture.truth[agent] = Truth(None, "unresolved", None, agent)


def _edge_cases(b: _Builder, count: int) -> None:
    fixture = b.fixture
    per_case = max(1, count // 10)

    for index in range(per_case):  # impostors naming a verified fleet as parent
        agent = f"impostor-{index}"
        b.fact(agent, "agent_tool_invocation_observed", 12000 + index, parent_agent_ref="legit-orch",
               tool_name="wallet_scan", deployment_id="dep-impostor")
        fixture.truth[agent] = Truth(None, "unresolved", "legit-orch", "legit-orch")

    for index in range(per_case):  # the parent was never observed
        agent = f"orphan-{index}"
        b.fact(agent, "agent_tool_invocation_observed", 12100 + index,
               parent_agent_ref=f"never-seen-{index}", tool_name="fetch", deployment_id="dep-orphan")
        fixture.truth[agent] = Truth(None, "unresolved", None, agent)

    for index in range(max(1, per_case // 3)):  # A -> B -> C -> A
        members = [f"cycle-{index}-{slot}" for slot in range(3)]
        for slot, member in enumerate(members):
            parent = members[(slot + 1) % 3]
            b.spawn(parent, member, 12200 + index + slot, state=None, deployment="dep-cycle")
            fixture.truth[member] = Truth(None, "unresolved", parent, None, cyclic=True)

    for index in range(per_case):  # one claim, no binding: stays a claim
        agent = f"claim-{index}"
        b.fact(agent, "agent_task_started", 12300 + index, reported_principal_ref="someone@example.test",
               reported_principal_namespace="email", deployment_id="dep-claims")
        fixture.truth[agent] = Truth(None, "unresolved", None, agent)

    # Provider-asserted claims resolve as inferred, never verified.
    fixture.bindings.append(PrincipalBinding(
        tenant_id=TENANT, kind="claim", principal_entity_id="org:vendor", namespace="vendor",
        claim_ref="vendor-acct-1", evidence_class="PROVIDER_ASSERTED", evidence_refs=("binding:vendor-1",),
    ))
    for index in range(per_case):
        agent = f"vendor-{index}"
        b.fact(agent, "agent_task_started", 12400 + index, reported_principal_ref="vendor-acct-1",
                reported_principal_namespace="vendor", deployment_id=f"dep-vendor-{index}")
        fixture.truth[agent] = Truth("org:vendor", "inferred", None, agent)

    # Competing claims: both retained, neither promoted.
    fixture.bindings.append(PrincipalBinding(
        tenant_id=TENANT, kind="claim", principal_entity_id="org:rival", namespace="vendor",
        claim_ref="rival-acct", evidence_class="PROVIDER_ASSERTED", evidence_refs=("binding:rival",),
    ))
    for index in range(max(1, per_case // 2)):
        agent = f"conflict-{index}"
        for claim in ("vendor-acct-1", "rival-acct"):
            b.fact(agent, "agent_task_started", 12500 + index, reported_principal_ref=claim,
                   reported_principal_namespace="vendor", deployment_id=f"dep-conflict-{index}")
        fixture.truth[agent] = Truth("org:vendor|org:rival", "inferred", None, agent)

    # A chain deeper than the minimum durable depth and than the processed depth.
    chain_length = 70 if count >= 70 else max(2, count // 2)
    chain = [f"chain-{level}" for level in range(chain_length)]
    fixture.authorities.append(AuthorityRecord(
        tenant_id=TENANT, authority_ref="grant-chain", grantor_entity_id="human:h3",
        grantee_entity_id=chain[0], grantor_kind="principal", delegation_allowed=True,
    ))
    for level, agent in enumerate(chain):
        parent = chain[level - 1] if level else None
        if parent:
            b.spawn(parent, agent, 13000 + level, state="deployment_verified", deployment="dep-chain")
        b.fact(agent, "agent_task_started", 13000 + level, deployment_id="dep-chain",
               execution_verification_state="deployment_verified")
        # Past the processed depth (64) the chain is not walked, so only the shared
        # deployment associates these levels: visible and suspected, never verified.
        attribution = "verified" if level < 64 else "suspected_cluster"
        fixture.truth[agent] = Truth("human:h3", attribution, parent, chain[0],
                                     authority_status="verified" if level < 64 else None)

    # Unlinked agents on a deployment most linked members share with one principal.
    for index in range(4):
        agent = f"linked-infra-{index}"
        fixture.bindings.append(PrincipalBinding(
            tenant_id=TENANT, kind="agent", principal_entity_id="org:infra-owner", agent_entity_id=agent,
            evidence_class="DETERMINISTIC_BINDING", evidence_refs=(f"binding:{agent}",),
        ))
        b.fact(agent, "agent_task_started", 13500 + index, deployment_id="dep-owned")
        fixture.truth[agent] = Truth("org:infra-owner", "verified", None, agent)
    for index in range(max(1, per_case // 2)):
        agent = f"prob-{index}"
        b.fact(agent, "agent_task_started", 13600 + index, deployment_id="dep-owned")
        fixture.truth[agent] = Truth("org:infra-owner", "suspected_cluster", None, agent)


def build_fixture(tier: int, seed: int = 7) -> Fixture:
    """Build a shuffled fixture of roughly ``tier`` agents."""
    rng = random.Random(seed)
    fixture = Fixture(tier=tier)
    b = _Builder(fixture, rng)
    legit = max(1, int(tier * 0.55))
    malicious = max(1, int(tier * 0.25))
    uncertain = max(1, int(tier * 0.1))
    edge = max(10, tier - legit - malicious - uncertain)
    _legit_swarm(b, legit)
    _malicious_swarm(b, malicious)
    _uncertain_cluster(b, uncertain)
    _edge_cases(b, edge)
    fixture.populations = {"legit": legit, "malicious": malicious, "uncertain": uncertain, "edge": edge}

    # Replays: the same event ids delivered again must change nothing.
    replays = [dict(row) for row in rng.sample(fixture.facts, k=max(1, len(fixture.facts) // 50))]
    fixture.replayed_events = len(replays)
    fixture.facts.extend(replays)
    # Late observations: arrival order is unrelated to occurrence order.
    rng.shuffle(fixture.facts)
    # Same ids under another tenant must never affect this tenant's lineage.
    fixture.foreign_facts = [
        {**row, "tenant_id": OTHER_TENANT, "source_event_id": f"foreign-{i}"}
        for i, row in enumerate(fixture.facts[: max(1, len(fixture.facts) // 100)])
    ]
    return fixture


def load(engine: Any, fixture: Fixture) -> None:
    for record in fixture.authorities:
        engine.upsert_authority(record)
    for binding in fixture.bindings:
        engine.upsert_binding(binding)
    engine.ingest(fixture.facts)
    engine.ingest(fixture.foreign_facts)


def score(engine: Any, fixture: Fixture) -> dict[str, Any]:
    """Compare a resolved engine to ground truth. Returns counts and rates."""
    rows = engine.rows()
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for row in rows.values():
        by_agent.setdefault(row["agent_entity_id"], []).append(row)
    known = {"verified", "inferred"}
    false_principal = missing = wrong_parent = wrong_root = authority_mismatch = 0
    unknown_to_known = cycle_wrong = class_wrong = 0
    for agent, truth in fixture.truth.items():
        agent_rows = by_agent.get(agent)
        if not agent_rows:
            missing += 1
            continue
        allowed = set((truth.principal or "").split("|")) if truth.principal else set()
        for row in agent_rows:
            if row["attribution_class"] in known and row["principal_entity_id"] not in allowed:
                false_principal += 1
            if row["attribution_class"] in known and truth.attribution not in known:
                unknown_to_known += 1
        attributed = [r for r in agent_rows if r["attribution_class"] == truth.attribution]
        if not attributed:
            class_wrong += 1
        reference = agent_rows[0]
        if truth.cyclic:
            if reference["lineage_status"] != "cyclic":
                cycle_wrong += 1
        else:
            if reference["parent_agent_id"] != truth.parent and not (
                truth.parent and reference["lineage_status"] == "unresolved_parent"
            ):
                wrong_parent += 1
            if truth.root and reference["root_agent_id"] != truth.root:
                wrong_root += 1
        if truth.authority_status is not None:
            match = [r for r in agent_rows if r["principal_entity_id"] in allowed]
            if not match or match[0]["authority_resolution_status"] != truth.authority_status:
                authority_mismatch += 1
    total = len(fixture.truth) or 1
    keys = list(rows)
    node_ids = set(by_agent)
    return {
        "agents_in_truth": len(fixture.truth),
        "agents_resolved": len(node_ids),
        "false_principal_attribution": false_principal,
        "false_principal_attribution_rate": false_principal / total,
        # A principal must never be an observed agent (human and agent never merge).
        "false_agent_merge": sum(1 for principal, _ in keys if principal in node_ids),
        "false_agent_split": len(node_ids - set(fixture.truth)),
        "missing_lineage": missing,
        "incorrect_parent": wrong_parent,
        "incorrect_root_principal": wrong_root,
        "authority_mismatch": authority_mismatch,
        "unknown_converted_to_known": unknown_to_known,
        "attribution_class_mismatch": class_wrong,
        "duplicate_lineage_rows": len(keys) - len(set(keys)),
        "cycle_handling_errors": cycle_wrong,
    }
