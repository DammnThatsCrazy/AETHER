from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AWS_ROOT = ROOT / "AWS Deployment" / "aether-aws"


@contextmanager
def aws_module_path():
    original = list(sys.path)
    for prefix in ("shared", "config", "scripts"):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(AWS_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in ("shared", "config", "scripts"):
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


def test_monitoring_fails_closed_in_live_mode_without_aws_data(monkeypatch):
    monkeypatch.setenv("AETHER_STUB_AWS", "0")

    with aws_module_path():
        module = importlib.import_module("scripts.monitoring.monitoring_ops")
        importlib.reload(module)
        monkeypatch.setattr(module.aws_client, "safe_call", lambda *args, **kwargs: None)

        with pytest.raises(RuntimeError, match="ecs.describe_services"):
            module.check_all_services("production")


def test_cost_report_fails_closed_in_live_mode_without_aws_data(monkeypatch):
    monkeypatch.setenv("AETHER_STUB_AWS", "0")

    with aws_module_path():
        module = importlib.import_module("scripts.cost.cost_ops")
        importlib.reload(module)
        monkeypatch.setattr(module.aws_client, "safe_call", lambda *args, **kwargs: None)

        with pytest.raises(RuntimeError, match="Cost Explorer service cost query"):
            module.estimate_service_costs("production")


def test_dr_validation_uses_real_command_results_in_live_mode(monkeypatch):
    monkeypatch.setenv("AETHER_STUB_AWS", "0")

    with aws_module_path():
        module = importlib.import_module("scripts.dr.disaster_recovery")
        importlib.reload(module)

        class Result:
            def __init__(self, ok: bool):
                self.ok = ok

        calls = []

        def fake_run_cmd(command: str):
            calls.append(command)
            return Result(ok=False)

        monkeypatch.setattr(module, "run_cmd", fake_run_cmd)
        ctx = module.RecoveryContext(scope=module.FailoverScope.REGION)

        assert module.validate_recovery(ctx) is False
        assert calls
        assert ctx.errors == ["Validation failed: 0/7"]
