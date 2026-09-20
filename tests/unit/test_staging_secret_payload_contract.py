"""Tests for the raw Secrets Manager payload contract used by ECS."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_staging_secret_payload_contract.py"
SPEC = importlib.util.spec_from_file_location("staging_secret_payload_contract", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def _runner(values: dict[str, str | dict[str, str]], missing: set[str] | None = None):
    missing = missing or set()

    def run(args, **kwargs):
        name = args[args.index("--secret-id") + 1].removeprefix("aether/")
        if name in missing:
            return subprocess.CompletedProcess(args, 1, "", "AccessDenied")
        value = values[name]
        secret = value if isinstance(value, str) else json.dumps(value)
        return subprocess.CompletedProcess(
            args,
            0,
            json.dumps({"ARN": f"arn:aws:secretsmanager:::secret:aether/{name}", "SecretString": secret}),
            "",
        )

    return run


def _values() -> dict[str, str]:
    values = {
        name: f"raw-{name}"
        for name in checker.required_secret_names("pilot")
        if name not in {"stripe-secret-key", "stripe-webhook-secret"}
    }
    values.update({
        "stripe-secret-key": "sk_test_example",
        "stripe-webhook-secret": "whsec_example",
    })
    for name in checker.PILOT_PRICE_SECRETS:
        values[name] = f"price_{name.removeprefix('stripe-price-')}"
    return values


def test_pilot_accepts_raw_test_mode_payloads():
    assert checker.payload_errors(lane="pilot", runner=_runner(_values())) == []


def test_rejects_json_wrapped_payload_without_exposing_value():
    values = _values()
    values["stripe-secret-key"] = {"value": "sk_test_secret_that_must_not_be_printed"}  # type: ignore[assignment]
    errors = checker.payload_errors(lane="pilot", runner=_runner(values))
    assert any("stripe-secret-key" in error and "JSON-wrapped" in error for error in errors)
    assert "sk_test_secret_that_must_not_be_printed" not in " ".join(errors)


def test_rejects_missing_secret_and_wrong_stripe_mode():
    values = _values()
    values["stripe-secret-key"] = "sk_live_not_for_staging"
    errors = checker.payload_errors(
        lane="pilot",
        runner=_runner(values, missing={"stripe-price-delta"}),
    )
    assert any("stripe-price-delta" in error for error in errors)
    assert any("must use a Stripe test key" in error for error in errors)


def test_full_requires_deferred_workforce_secrets():
    values = _values()
    values.update({name: f"raw-{name}" for name in checker.FULL_ONLY_SECRETS})
    errors = checker.payload_errors(lane="full", runner=_runner(values, missing=set(checker.FULL_ONLY_SECRETS)))
    assert any("kyber-google-client-id" in error for error in errors)
    assert any("kyber-google-client-secret" in error for error in errors)


def test_full_does_not_require_pilot_price_secrets():
    values = _values()
    for name in checker.PILOT_PRICE_SECRETS:
        values.pop(name, None)
    values.update({name: f"raw-{name}" for name in checker.FULL_ONLY_SECRETS})

    assert set(checker.PILOT_PRICE_SECRETS).isdisjoint(
        checker.required_secret_names("full")
    )
    assert checker.payload_errors(lane="full", runner=_runner(values)) == []
