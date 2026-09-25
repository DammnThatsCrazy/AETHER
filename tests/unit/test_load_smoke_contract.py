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


def test_gate_user_task_sets_yield_so_every_thresholded_request_runs() -> None:
    """Locust keeps a user inside a TaskSet until it calls ``interrupt()``.

    Staging rehearsal run 36058790357 served 2,787 requests with 0 failures and
    still failed: all 10 users drew BatchIngestTasks first and never left, so
    every /sdk/identity/resolve threshold "never appeared". Each task set the
    gate's user class mixes must carry a task that hands control back.
    """
    path = ROOT / "tests" / "load" / "locustfile.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    smoke = (ROOT / "scripts" / "load_smoke.py").read_text(encoding="utf-8")
    user_class = ast.literal_eval(
        next(
            node.value
            for node in ast.parse(smoke).body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "LOCUST_USER_CLASS" for t in node.targets)
        )
    )
    tasks = next(
        stmt.value
        for stmt in classes[user_class].body
        if isinstance(stmt, ast.Assign) and any(getattr(t, "id", None) == "tasks" for t in stmt.targets)
    )
    task_sets = [key.id for key in tasks.keys]
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

    for name in task_sets:
        methods = [m for m in classes[name].body if isinstance(m, ast.FunctionDef)]
        assert any(yields(m) for m in methods), f"{name} never interrupts back to the user"
