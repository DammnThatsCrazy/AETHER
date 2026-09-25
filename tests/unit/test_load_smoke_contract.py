"""Regression guards for the hosted staging load-smoke contract."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_load_smoke_thresholds_match_the_canonical_ingestion_surface() -> None:
    source = (ROOT / "scripts" / "load_smoke.py").read_text(encoding="utf-8")
    assert '"/v1/batch [small-10]"' in source
    assert '"/v1/batch [medium-50]"' in source
    assert '"/v1/ingest/feed' not in source
    assert '"/v1/ingest/events/batch' not in source


def test_locust_ingest_and_identity_payloads_use_deployed_models() -> None:
    path = ROOT / "tests" / "load" / "locustfile.py"
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(path))
    assert '"/v1/batch"' in source
    assert '"batch": events' in source
    assert '"schemaVersion": "1.0.0"' in source
    assert '"anonymous_id"' in source
    assert '"wallets"' in source
    assert '"/v1/ingest/feed"' not in source
    assert '"/v1/ingest/events/batch"' not in source


def test_rehearsal_installs_the_load_runner_before_invoking_load_smoke() -> None:
    source = (ROOT / ".github" / "workflows" / "staging-lifecycle.yml").read_text(
        encoding="utf-8"
    )
    install_start = source.index("- name: Install rehearsal dependencies")
    load_gate = source.index("python scripts/load_smoke.py", install_start)
    install_block = source[install_start:load_gate]

    assert "pyyaml" in install_block
    assert "locust>=2.31,<3" in install_block


def test_every_load_task_set_yields_so_user_mixes_hold() -> None:
    """Locust keeps a user inside a TaskSet until it calls ``interrupt()``.

    Staging rehearsal run 36058790357 served 2,787 requests with 0 failures and
    still failed: all 10 users drew BatchIngestTasks first and never left, so
    every /sdk/identity/resolve threshold "never appeared". Every task set must
    hand control back: if only some did, mixed users (SteadyStateUser,
    BurstUser) would drain out of the yielding sets into the non-yielding ones
    and the advertised traffic mix would decay during a baseline run.
    """
    path = ROOT / "tests" / "load" / "locustfile.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    task_sets = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(getattr(base, "id", None) == "TaskSet" for base in node.bases)
    ]
    assert len(task_sets) > 1

    def yields(method: ast.FunctionDef) -> bool:
        is_task = any(
            isinstance(d, ast.Call) and getattr(d.func, "id", None) == "task"
            or getattr(d, "id", None) == "task"
            for d in method.decorator_list
        )
        calls_interrupt = any(
            isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "interrupt"
            for n in ast.walk(method)
        )
        return is_task and calls_interrupt

    missing = [
        task_set.name for task_set in task_sets
        if not any(yields(m) for m in task_set.body if isinstance(m, ast.FunctionDef))
    ]
    assert not missing, f"task sets that never interrupt back to the user: {missing}"
