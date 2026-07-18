"""Controller-side objective step executor (the real replacement for the
worker-bridge echo no-op).

Proves: the assigned specialist worker is resolved from the real registry and
runs; only approved read-only tools execute; output is bounded (no secrets,
prompts, or unbounded payloads); PROPOSED mutations are produced as STAGED
proposals (never committed here); evidence/lineage is attached; and failures are
typed.
"""

from __future__ import annotations

from config.settings import WorkerType
from models.core import TaskResult

from agent_controller.runtime import step_executor as se


class FakeWorker:
    def __init__(self, worker_type: WorkerType, *, success: bool = True, data=None,
                 confidence: float = 0.9, source: str = "https://src.example",
                 error: str = ""):
        self.worker_type = worker_type
        self.data_source = "general_web"
        self._success = success
        self._data = data if data is not None else {"title": "Acme"}
        self._confidence = confidence
        self._source = source
        self._error = error
        self.ran = False

    def run(self, task):
        self.ran = True
        return TaskResult(
            task_id=task.task_id, worker_type=self.worker_type, success=self._success,
            data=dict(self._data), confidence=self._confidence,
            source_attribution=self._source, error=self._error,
        )


def _envelope(**overrides):
    env = {
        "run_id": "run_1", "tenant_id": "t1", "objective_id": "obj_1",
        "controller": "discovery", "queue": "discovery", "attempt": 1,
        "payload": {"target_url": "https://acme.example", "entity_id": "ent-9"},
        "plan_id": "plan_1", "step_id": "step_1",
    }
    env.update(overrides)
    return env


# ── Happy path: resolve, run, bound, propose, attribute ─────────────────────

def test_executes_assigned_worker_and_returns_bounded_output():
    worker = FakeWorker(WorkerType.WEB_CRAWLER, data={
        "title": "Acme", "status_code": 200,
        "api_key": "SECRET", "authorization": "Bearer x",
        "prompt": "leak me", "completion": "and me",
        "big": "x" * 5000, "links": [{"href": f"h{i}"} for i in range(100)],
    })
    out = se.execute_step(_envelope(), worker_registry={WorkerType.WEB_CRAWLER: worker})
    assert worker.ran is True
    assert out["status"] == "succeeded" and out["worker_type"] == "web_crawler"
    # Bounds: secrets redacted, raw provider payloads dropped, sizes capped.
    assert out["output"]["api_key"] == "[redacted]"
    assert out["output"]["authorization"] == "[redacted]"
    assert "prompt" not in out["output"] and "completion" not in out["output"]
    assert len(out["output"]["big"]) == se._MAX_STRING_LEN
    assert len(out["output"]["links"]) == se._MAX_LIST_ITEMS


def test_oversized_output_is_summarized_not_emitted():
    worker = FakeWorker(WorkerType.WEB_CRAWLER, data={
        f"field_{i}": "y" * 400 for i in range(200)
    })
    out = se.execute_step(_envelope(), worker_registry={WorkerType.WEB_CRAWLER: worker})
    assert out["output"].get("_bounded") is True


def test_produces_staged_proposals_never_committed():
    worker = FakeWorker(WorkerType.WEB_CRAWLER, data={"title": "Acme", "rank": 3})
    out = se.execute_step(_envelope(), worker_registry={WorkerType.WEB_CRAWLER: worker})
    props = out["proposed_mutations"]
    assert len(props) == 1
    proposal = props[0]
    # Backend staged-mutation contract shape; discovery → class 1 (additive).
    assert proposal["mutation_class"] == 1
    assert proposal["operation"] == "upsert"
    assert proposal["target"] == {"kind": "vertex", "vertex_type": "ENTITY", "vertex_id": "ent-9"}
    assert proposal["diff"]["properties"] == {"title": "Acme", "rank": 3}
    # A proposal carries NO commit/approval status — it is a proposal only.
    assert "status" not in proposal
    assert proposal.get("committed") is None


def test_enrichment_worker_proposes_class_two():
    worker = FakeWorker(WorkerType.ENTITY_RESOLVER, data={"canonical_name": "Acme Inc"})
    out = se.execute_step(
        _envelope(controller="enrichment", payload={"entity_id": "ent-9", "worker_type": "entity_resolver"}),
        worker_registry={WorkerType.ENTITY_RESOLVER: worker},
    )
    assert out["proposed_mutations"][0]["mutation_class"] == 2


def test_no_proposals_without_entity_or_properties():
    # No entity_id → nothing to propose.
    w1 = FakeWorker(WorkerType.WEB_CRAWLER, data={"title": "Acme"})
    out1 = se.execute_step(_envelope(payload={"target_url": "u"}), worker_registry={WorkerType.WEB_CRAWLER: w1})
    assert out1["proposed_mutations"] == []
    # entity_id but only non-scalar/PII-flagged fields → nothing to propose.
    w2 = FakeWorker(WorkerType.WEB_CRAWLER, data={"_pii_flagged_x": True, "nested": {"a": 1}})
    out2 = se.execute_step(_envelope(payload={"entity_id": "e"}), worker_registry={WorkerType.WEB_CRAWLER: w2})
    assert out2["proposed_mutations"] == []


def test_evidence_and_lineage_attached():
    worker = FakeWorker(WorkerType.WEB_CRAWLER, confidence=0.77)
    out = se.execute_step(_envelope(attempt=3), worker_registry={WorkerType.WEB_CRAWLER: worker})
    ev = out["evidence"][0]
    assert ev["worker_type"] == "web_crawler" and ev["tool"] == "general_web"
    assert ev["source"] == "https://src.example" and ev["confidence"] == 0.77
    lin = out["lineage"]
    assert lin["objective_id"] == "obj_1" and lin["run_id"] == "run_1"
    assert lin["controller"] == "discovery" and lin["step_id"] == "step_1"
    assert lin["attempt"] == 3 and lin["executed_at"]


# ── Typed failures ──────────────────────────────────────────────────────────

def test_worker_failure_is_typed():
    worker = FakeWorker(WorkerType.WEB_CRAWLER, success=False, error="boom")
    try:
        se.execute_step(_envelope(), worker_registry={WorkerType.WEB_CRAWLER: worker})
        assert False, "expected StepWorkerFailed"
    except se.StepWorkerFailed as exc:
        assert "boom" in str(exc)


def test_unavailable_worker_is_typed():
    try:
        se.execute_step(_envelope(), worker_registry={})
        assert False, "expected StepWorkerUnavailable"
    except se.StepWorkerUnavailable:
        pass


def test_commit_controller_has_no_auto_executor():
    # The commit controller has no read-only specialist here — it only ever
    # stages proposals; the executor refuses to run it.
    worker = FakeWorker(WorkerType.WEB_CRAWLER)
    try:
        se.execute_step(_envelope(controller="commit", payload={}),
                        worker_registry={WorkerType.WEB_CRAWLER: worker})
        assert False, "expected StepToolNotApproved"
    except se.StepToolNotApproved:
        pass


# ── Worker resolution precedence + real registry ────────────────────────────

def test_worker_type_resolution_precedence():
    payload = {"worker_type": "api_scanner", "assigned_team": "web_crawler", "entity_id": "e"}
    worker = FakeWorker(WorkerType.API_SCANNER)
    out = se.execute_step(_envelope(payload=payload), worker_registry={WorkerType.API_SCANNER: worker})
    assert out["worker_type"] == "api_scanner"  # explicit payload worker_type wins


def test_assigned_team_and_required_domain_resolution():
    w = FakeWorker(WorkerType.SEMANTIC_TAGGER)
    out = se.execute_step(
        _envelope(controller="enrichment", payload={"assigned_team": "semantic_tagger", "entity_id": "e"}),
        worker_registry={WorkerType.SEMANTIC_TAGGER: w},
    )
    assert out["worker_type"] == "semantic_tagger"


def test_real_registry_discovers_all_specialist_workers():
    registry = se._discovered_registry()
    # Every declared specialist type has a real worker instance.
    assert set(registry) == set(WorkerType)
    web = registry[WorkerType.WEB_CRAWLER]
    assert type(web).__name__ == "WebCrawlerWorker"


def test_all_specialist_workers_are_read_only():
    # Defense in depth: the approved-tool allowlist is exactly the read-only
    # specialist set; no commit-class tool is auto-executable.
    assert se.READ_ONLY_WORKER_TYPES == frozenset(WorkerType)
