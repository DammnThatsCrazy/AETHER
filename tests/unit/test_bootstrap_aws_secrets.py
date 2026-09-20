"""Safety tests for the AWS Secrets Manager bootstrap boundary."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bootstrap_aws_secrets.py"
SPEC = importlib.util.spec_from_file_location("bootstrap_aws_secrets", SCRIPT)
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class _NotFound(Exception):
    pass


class _Client:
    exceptions = SimpleNamespace(ResourceNotFoundException=_NotFound)

    def __init__(self, metadata: dict):
        self.metadata = metadata
        self.put_calls: list[dict] = []
        self.create_calls: list[dict] = []

    def describe_secret(self, **_kwargs):
        if self.metadata is None:
            raise _NotFound
        return self.metadata

    def put_secret_value(self, **kwargs):
        self.put_calls.append(kwargs)

    def create_secret(self, **kwargs):
        self.create_calls.append(kwargs)


def test_repeated_bootstrap_preserves_existing_generated_secret():
    client = _Client({"VersionIdsToStages": {"version": ["AWSCURRENT"]}})

    result = bootstrap._push_secret(
        client,
        "aether/jwt-secret",
        "new-generated-value",
        False,
        [],
        "alias/aether-staging-secrets",
        preserve_existing=True,
    )

    assert result == "preserved"
    assert client.put_calls == []
    assert client.create_calls == []


def test_bootstrap_can_fill_an_existing_stub_without_current_version():
    client = _Client({"VersionIdsToStages": {}})

    result = bootstrap._push_secret(
        client,
        "aether/jwt-secret",
        "generated-value",
        False,
        [],
        "alias/aether-staging-secrets",
        preserve_existing=True,
    )

    assert result == "updated"
    assert client.put_calls == [
        {"SecretId": "aether/jwt-secret", "SecretString": "generated-value"}
    ]


def test_bootstrap_refuses_to_update_a_secret_pending_deletion():
    client = _Client({"DeletedDate": 123, "VersionIdsToStages": {}})

    with pytest.raises(SystemExit, match="pending deletion"):
        bootstrap._push_secret(
            client,
            "aether/jwt-secret",
            "generated-value",
            False,
            [],
            "alias/aether-staging-secrets",
            preserve_existing=True,
        )

    assert client.put_calls == []
    assert client.create_calls == []
