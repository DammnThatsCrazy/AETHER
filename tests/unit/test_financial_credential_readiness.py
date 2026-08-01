"""Financial credential-readiness certification — cohort truth + fail-closed proof.

Offline, no network. Pins:
  * the real financial cohort is EXACTLY the five payment rails + two stablecoin
    observers, all CREDENTIAL_WAITING;
  * ``evaluate`` marks the real cohort READY and the strict CLI exits 0;
  * the ``--json`` evidence bundle is serializable and carries no secret material;
  * FAIL-CLOSED: a synthetic SCAFFOLDED descriptor and a dishonest PARTNER_LIVE
    descriptor (no live evidence) both resolve NOT-READY and the strict verdict
    is FAIL.
"""

from __future__ import annotations

import json

from scripts import financial_credential_readiness as fcr

EXPECTED_COHORT = {
    ("payments", "privy"),
    ("payments", "stripe_onramp"),
    ("payments", "coinbase"),
    ("payments", "moonpay"),
    ("payments", "bridge"),
    ("stablecoin_chain", "evm"),
    ("stablecoin_chain", "svm"),
}

# Real secret material markers that must never appear in the evidence bundle.
_SECRET_MARKERS = (
    "TOPSECRET",
    "hunter2",
    "tok_secret",
    "sk_live_",
    "sk_test_",
    "AKIA",
    "-----BEGIN",
    "Bearer ",
)


def test_financial_cohort_is_exactly_seven_credential_waiting():
    (CredentialReadiness, _iter, _rank, _run) = fcr._load()
    descriptors = fcr.financial_descriptors()
    got = {(d.domain, d.provider) for d in descriptors}
    assert got == EXPECTED_COHORT
    assert len(descriptors) == 7
    for d in descriptors:
        assert d.implementation_state == CredentialReadiness.CREDENTIAL_WAITING


def test_domain_filter_partitions_the_cohort():
    payments = fcr.financial_descriptors("payments")
    assert {d.provider for d in payments} == {
        "privy",
        "stripe_onramp",
        "coinbase",
        "moonpay",
        "bridge",
    }
    assert all(d.domain == "payments" for d in payments)

    stablecoin = fcr.financial_descriptors("stablecoin_chain")
    assert {d.provider for d in stablecoin} == {"evm", "svm"}
    assert all(d.domain == "stablecoin_chain" for d in stablecoin)


def test_non_financial_domain_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        fcr.financial_descriptors("interop")


def test_evaluate_marks_the_real_cohort_ready():
    (CredentialReadiness, _iter, readiness_rank, run_certification) = fcr._load()
    descriptors = fcr.financial_descriptors()
    verdict = fcr.evaluate(descriptors, run_certification, readiness_rank, CredentialReadiness)

    assert verdict["all_ready"] is True
    assert verdict["strict_verdict"] == "PASS"
    assert verdict["summary"]["total"] == 7
    assert verdict["summary"]["ready"] == 7
    assert verdict["not_ready"] == []
    for p in verdict["providers"]:
        assert p["ready"] is True
        assert p["failed_checks"] == []
        assert p["state"] == "credential_waiting"


def test_main_strict_exits_zero_on_real_cohort():
    assert fcr.main(["--strict"]) == 0
    assert fcr.main(["--domain", "payments", "--strict"]) == 0
    assert fcr.main(["--domain", "stablecoin_chain", "--strict"]) == 0


def test_json_bundle_is_serializable_and_secret_free(capsys):
    rc = fcr.main(["--json"])
    assert rc == 0
    out = capsys.readouterr().out
    bundle = json.loads(out)  # JSON-serializable
    assert bundle["strict_verdict"] == "PASS"
    assert bundle["summary"]["ready"] == 7

    text = json.dumps(bundle)
    for marker in _SECRET_MARKERS:
        assert marker not in text, f"secret marker {marker!r} leaked into --json bundle"


def _synthetic_fail_closed_cohort(CredentialReadiness):
    from shared.certification import AdapterCertificationDescriptor

    scaffolded = AdapterCertificationDescriptor(
        provider="ghost",
        domain="payments",
        adapter="GhostAdapter",
        implementation_state=CredentialReadiness.SCAFFOLDED,
        first_release=True,
    )
    # PARTNER_LIVE with NO live evidence (no last_certified_at) — dishonest.
    dishonest_partner_live = AdapterCertificationDescriptor(
        provider="mirage",
        domain="stablecoin_chain",
        adapter="MirageObserver",
        implementation_state=CredentialReadiness.PARTNER_LIVE,
        first_release=True,
    )
    return [scaffolded, dishonest_partner_live]


def test_fail_closed_on_scaffolded_and_dishonest_partner_live():
    (CredentialReadiness, _iter, readiness_rank, run_certification) = fcr._load()
    cohort = _synthetic_fail_closed_cohort(CredentialReadiness)

    verdict = fcr.evaluate(cohort, run_certification, readiness_rank, CredentialReadiness)

    assert verdict["all_ready"] is False
    assert verdict["strict_verdict"] == "FAIL"
    assert verdict["summary"]["ready"] == 0

    by_provider = {p["provider"]: p for p in verdict["providers"]}

    # SCAFFOLDED ranks below CREDENTIAL_WAITING → not ready.
    assert by_provider["ghost"]["ready"] is False

    # Dishonest PARTNER_LIVE fails the honest_status check → not ready.
    assert by_provider["mirage"]["ready"] is False
    assert "honest_status" in by_provider["mirage"]["failed_checks"]


def test_main_strict_fails_closed_on_synthetic_cohort(monkeypatch):
    (CredentialReadiness, _iter, _rank, _run) = fcr._load()
    cohort = _synthetic_fail_closed_cohort(CredentialReadiness)
    monkeypatch.setattr(fcr, "financial_descriptors", lambda domain=None: cohort)
    assert fcr.main(["--strict"]) == 1
