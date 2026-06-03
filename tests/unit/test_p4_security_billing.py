"""CI-gated tests for Phase 4: billing providers + security/compliance scripts."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


def _providers(monkeypatch, *, mode: str):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("AETHER_EXTERNAL_BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_PROVIDER_MODE", mode)
    monkeypatch.delenv("AETHER_STRIPE_BILLING_ENABLED", raising=False)
    with backend_module_path():
        return importlib.import_module("services.billing.providers")


# ── Billing providers ───────────────────────────────────────────────────────

async def test_manual_invoice_provider(monkeypatch):
    p = _providers(monkeypatch, mode="manual_invoice")
    provider = p.get_billing_provider()
    assert provider.provider_type == "manual_invoice"
    assert provider.invoice_export_mode() == "manual_artifact"
    out = await provider.export_invoice(tenant_id="t1", invoice_preview={"line_items": [{"x": 1}]})
    assert out["exported"] is True and out["artifact"] == "manual_invoice_document"
    assert await provider.sync_payment_status(tenant_id="t1") == "externally_managed"


async def test_enterprise_contract_provider(monkeypatch):
    p = _providers(monkeypatch, mode="enterprise_contract")
    provider = p.get_billing_provider()
    assert provider.provider_type == "enterprise_contract"
    assert provider.invoice_export_mode() == "approved_preview"
    out = await provider.export_invoice(tenant_id="t1", invoice_preview={})
    assert out["exported"] is True and "contract" in out["artifact"]


def test_provider_health_and_status_no_secrets(monkeypatch):
    p = _providers(monkeypatch, mode="manual_invoice")
    health = p.provider_health()
    assert health["provider_type"] == "manual_invoice" and health["healthy"] is True
    summary = p.provider_status_summary()
    assert "provider_health" in summary
    blob = json.dumps(summary)
    assert "sk_" not in blob and "whsec" not in blob


# ── Security / compliance scripts ─────────────────────────────────────────────

def test_secret_scan_runs_clean_or_advisory():
    # Advisory mode always exits 0; confirms the scanner runs over the tracked tree.
    res = subprocess.run([sys.executable, "scripts/security/secret_scan.py", "--advisory"],
                         capture_output=True, text=True, cwd=ROOT)
    assert res.returncode == 0
    assert "secret_scan:" in res.stdout


def test_secret_scan_patterns_detect_and_skip():
    import importlib.util
    spec = importlib.util.spec_from_file_location("secret_scan", ROOT / "scripts/security/secret_scan.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    patterns = dict(mod.PATTERNS)
    assert patterns["aws_access_key"].search("AKIAIOSFODNN7EXAMPLE")
    assert patterns["private_key_block"].search("-----BEGIN RSA PRIVATE KEY-----")


def test_compliance_readiness_is_readiness_only():
    res = subprocess.run([sys.executable, "scripts/compliance/readiness.py", "--json"],
                         capture_output=True, text=True, cwd=ROOT)
    assert res.returncode == 0
    report = json.loads(res.stdout)
    disclaimer = report["disclaimer"].lower()
    assert "readiness" in disclaimer and "not legal advice" in disclaimer
    # No control may claim certification/compliance as a status.
    for item in report["controls"]:
        assert item["readiness"] not in ("compliant", "certified", "soc2_compliant")
    assert report["summary"]["total"] >= 10
