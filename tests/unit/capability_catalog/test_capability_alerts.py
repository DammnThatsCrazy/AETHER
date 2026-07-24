"""Capability alerts + access-intelligence export (PR 4 lane AAI-4-NOESIS-ALERTS-EXPORTS).

Handlers are called directly with a fake ``Request`` — the established pattern in this
suite (``test_capability_risk_routes``/``test_capability_authority_routes``) — so
permission gates and tenant scoping are exercised without standing up the middleware.

Three tests carry the weight of this file:

``test_noesis_agentic_adapter_is_reachable_through_evaluate``
    The wiring proof. ``services/noesis/adapters/agentic_intelligence_adapter.py`` was
    imported only by its own unit test — built, correct, and unreachable in production.
    This test drives the *real* production call path (route handler → service → adapter →
    ``obs_agent_risk_signals``) and asserts against the adapter's own literal output
    (its answer prose, its claim text and classification, its ``sources`` list), not
    against a stub. If the adapter is unwired, or swapped for a lookalike, this fails.

``test_alerts_unknown_is_never_reported_as_zero``
    An undecidable rule must produce ``alerts_known: false`` with ``null`` counts, never
    "0 alerts", which reads as all-clear. The whole response is walked recursively and
    any zero-valued number anywhere fails it, so a future field cannot reintroduce the
    lie sideways. ``_zero_numbers`` is copied from ``test_capability_risk.py`` on
    purpose — the invariant is the same one, one layer up.

``test_export_truncation_is_disclosed``
    A bounded export that hit its limit and said nothing is worse than no export.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest

from repositories.agentic_observability_repos import AgentRiskSignalRepository
from repositories.repos import reset_in_memory_stores
from shared.auth.auth import TenantContext
from shared.common.common import BadRequestError, ForbiddenError

import services.agent_access_intelligence.alert_routes as alert_routes
import services.agent_access_intelligence.risk_service as risk_service
from services.agent_access_intelligence.alerts import (
    AGENTIC_RISK_SIGNAL_CODE,
    AGENTIC_RISK_SIGNAL_INTENT,
    DEFAULT_RULES,
    DURABLE_EXPORT_TYPE,
    EXPORT_DATASETS,
    NON_ALERTABLE_FINDING_CODES,
    RULE_SET_ID,
    AlertRule,
    CapabilityAlertService,
    capability_alert_service,
)
from services.agent_access_intelligence.catalog_service import capability_catalog_service
from services.agent_access_intelligence.identity import IDENTITY_FIELDS
from services.agentic_observability.models import RiskLevel
from services.noesis.adapters.agentic_intelligence_adapter import (
    AgenticIntelligenceAdapter,
)
from services.agent_access_intelligence.scanning import CapabilityFinding, FindingCode


# ── harness ───────────────────────────────────────────────────────────────────


class StubDeclarations:
    """Stands in for the declarations lane, exactly as ``test_capability_risk`` does, so
    identity/drift behaviour here is driven by this file rather than by that module's
    write path."""

    def __init__(
        self,
        digests: Optional[dict[str, str]] = None,
        *,
        truncated: bool = False,
    ) -> None:
        self.digests = dict(digests or {})
        self.truncated = truncated

    async def digest_map(
        self, tenant_id: str, *, limit: int = 1000
    ) -> tuple[dict[str, dict], bool]:
        return (
            {
                k: {"digest": v, "fields": list(IDENTITY_FIELDS)}
                for k, v in self.digests.items()
            },
            self.truncated,
        )


def _request(tenant_id: str = "t1", permissions: list[str] | None = None):
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        permissions=permissions if permissions is not None else ["read", "write"],
    )
    return SimpleNamespace(
        state=SimpleNamespace(tenant=tenant),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.fixture(autouse=True)
def _stub_declarations(monkeypatch):
    """No declarations on file, and a complete declaration window, unless a test says
    otherwise."""
    stub = StubDeclarations()
    monkeypatch.setattr(risk_service, "capability_declaration_service", stub)
    return stub


@pytest.fixture(autouse=True)
def _no_scan_findings(monkeypatch):
    """Findings come from whatever a test asks for, not from the scanning heuristics —
    so alert thresholds here do not move when that module's rules change."""
    monkeypatch.setattr(risk_service, "scan_capabilities", lambda records: [])


def _stub_scan(monkeypatch, findings_by_capability: dict[str, list[CapabilityFinding]]):
    def _scan(records):
        out: list[CapabilityFinding] = []
        for record in records:
            out.extend(findings_by_capability.get(record.get("capability_id"), []))
        return out

    monkeypatch.setattr(risk_service, "scan_capabilities", _scan)


def _finding(code: FindingCode, capability_id: str, risk_level: str) -> CapabilityFinding:
    return CapabilityFinding(
        code=code,
        risk_level=risk_level,
        summary=f"synthetic {code.value}",
        evidence=f"evidence for {capability_id}",
        capability_id=capability_id,
    )


async def _seed_capability(
    tenant_id: str = "t1",
    *,
    source_event_id: str = "e1",
    agent_id: Optional[str] = "agentA",
    tool_name: Optional[str] = "search",
    server_name: Optional[str] = "srvX",
    provider: str = "acme",
) -> str:
    result = await capability_catalog_service.record_from_fact({
        "tenant_id": tenant_id,
        "source_event_id": source_event_id,
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": agent_id,
        "tool_name": tool_name,
        "server_name": server_name,
        "server_url": None,
        "provider": provider,
        "risk_level": "high",
    })
    return result["capability_id"]


async def _seed_risk_signal(
    tenant_id: str = "t1",
    *,
    signal_id: str = "sig-1",
    agent_id: str = "agentA",
    risk_level: str = "high",
) -> dict[str, Any]:
    """Write an observed permission risk signal the Noesis adapter will read."""
    row = {
        "signal_id": signal_id,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "risk_level": risk_level,
        "reason_codes": ["over_broad_scope"],
        "policy_flags": [],
        "detected_at": "2026-07-24T00:00:00Z",
        "created_at": "2026-07-24T00:00:00Z",
    }
    await AgentRiskSignalRepository().insert(signal_id, row)
    return row


def _zero_numbers(value: Any, path: str = "$") -> list[str]:
    """Every path in ``value`` holding a numeric zero. ``bool`` is excluded on purpose —
    ``False`` is an ``int`` in Python and ``alerts_known: false`` is the honest answer,
    not a count. Copied from ``test_capability_risk.py``: same invariant, one layer up."""
    hits: list[str] = []
    if isinstance(value, bool):
        return hits
    if isinstance(value, (int, float)):
        if value == 0:
            hits.append(path)
        return hits
    if isinstance(value, dict):
        for key, item in value.items():
            hits.extend(_zero_numbers(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_zero_numbers(item, f"{path}[{index}]"))
    return hits


def _alert(data: dict[str, Any], rule_id: str) -> Optional[dict[str, Any]]:
    return next((a for a in data["alerts"] if a["rule_id"] == rule_id), None)


# ══════════════════════════════════════════════════════════════════════════════
# THE WIRING PROOF — the Noesis adapter is reachable in the production call path
# ══════════════════════════════════════════════════════════════════════════════

async def test_noesis_agentic_adapter_is_reachable_through_evaluate():
    """Route handler → CapabilityAlertService → AgenticIntelligenceAdapter → store.

    Asserted against the adapter's *own* literal output, so this cannot pass against a
    stub or a reimplementation that happens to return the right count.
    """
    # The service holds the real adapter, not a lookalike.
    assert isinstance(capability_alert_service._agentic, AgenticIntelligenceAdapter)

    signal = await _seed_risk_signal(risk_level=RiskLevel.HIGH.value)

    data = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]

    alert = _alert(data, "observed_agent_risk_signals")
    assert alert is not None, "the agentic rule must fire on an observed high risk signal"

    source = alert["evidence_source"]
    assert source["adapter"] == "services.noesis.adapters.agentic_intelligence_adapter"
    assert source["intent"] == AGENTIC_RISK_SIGNAL_INTENT

    # These strings are produced *inside* the adapter (see its `permission_risk_lookup`
    # branch). Reaching them proves the adapter ran.
    assert source["answer"] == "Found 1 risk signals"
    assert source["sources"] == ["obs_agent_risk_signals"]
    assert source["claims"] == [{
        "text": "1 permission risk signals observed",
        "classification": "observed_fact",
        "sufficient": True,
    }]

    # The evidence is the observed row itself, carried through the adapter untouched.
    assert [row["signal_id"] for row in alert["evidence"]] == [signal["signal_id"]]
    assert alert["evidence"][0]["agent_id"] == "agentA"

    # The adapter is consulted on every evaluation, not only when its rule fires: the
    # input descriptor is present regardless, so the path stays exercised.
    assert any(
        i.get("intent") == AGENTIC_RISK_SIGNAL_INTENT and i["available"] is True
        for i in data["inputs"]
    )


async def test_noesis_adapter_is_consulted_even_when_its_rule_does_not_fire():
    await _seed_capability()  # a populated tenant with no risk signals at all
    data = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]

    descriptor = next(i for i in data["inputs"] if i.get("intent") == AGENTIC_RISK_SIGNAL_INTENT)
    assert descriptor["available"] is True
    assert descriptor["complete"] is True
    # The adapter cites its source table even with nothing to report — proof it answered
    # rather than being skipped.
    assert descriptor["sources"] == ["obs_agent_risk_signals"]
    assert descriptor["claim_classifications"] == ["observed_fact"]
    assert _alert(data, "observed_agent_risk_signals") is None


async def test_agentic_rule_respects_the_risk_level_floor():
    """A low-severity observed signal is not a high-severity alert."""
    await _seed_risk_signal(signal_id="sig-low", risk_level=RiskLevel.LOW.value)
    data = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]
    assert _alert(data, "observed_agent_risk_signals") is None
    # It was seen, just not matched — the adapter still returned it.
    assert data["counts"]["agentic_signals_examined"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# RULES — visible thresholds, never presented as enforced policy
# ══════════════════════════════════════════════════════════════════════════════

async def test_rule_fires_with_threshold_and_observed_value_visible(monkeypatch):
    cap_id = await _seed_capability()
    _stub_scan(monkeypatch, {
        cap_id: [_finding(FindingCode.CREDENTIAL_IN_URL, cap_id, RiskLevel.HIGH.value)]
    })

    data = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]

    alert = _alert(data, "credential_in_server_url")
    assert alert is not None
    # The rule that fired, its threshold, and the observed value, all in the response.
    assert alert["rule"]["code"] == "credential_in_url"
    assert alert["rule"]["min_count"] == 1
    assert alert["threshold"] == {
        "min_count": 1,
        "min_risk_level": RiskLevel.HIGH.value,
        "code": "credential_in_url",
    }
    assert alert["observed"]["count"] == 1
    assert alert["observed"]["count_is_lower_bound"] is False
    assert alert["observed"]["matched_at_or_above_risk_level"] == RiskLevel.HIGH.value
    assert "threshold is 1" in alert["summary"]
    assert alert["evidence"][0]["capability_id"] == cap_id

    # A count below its threshold does not fire, and the rule that did not fire is still
    # visible in the rule set with its threshold.
    assert _alert(data, "high_risk_finding_volume") is None
    volume = next(r for r in data["rule_set"]["rules"] if r["rule_id"] == "high_risk_finding_volume")
    assert volume["min_count"] == 5

    assert data["alerts_known"] is True
    assert data["counts"]["alerts_triggered"] == 1
    assert data["counts"]["rules_evaluated"] == len(DEFAULT_RULES)


async def test_rule_set_travels_in_every_response_and_says_it_is_a_default():
    data = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]
    rule_set = data["rule_set"]
    assert rule_set["rule_set_id"] == RULE_SET_ID
    assert rule_set["is_default"] is True
    assert "not a policy this platform enforces" in rule_set["disclaimer"]
    # Every rule, fired or not, with its full threshold.
    assert {r["rule_id"] for r in rule_set["rules"]} == {r.rule_id for r in DEFAULT_RULES}
    for rule in rule_set["rules"]:
        assert set(rule) >= {"code", "min_risk_level", "min_count", "severity", "description"}


async def test_severities_reuse_the_platform_risk_level_enum():
    valid = {level.value for level in RiskLevel}
    for rule in DEFAULT_RULES:
        assert rule.severity in valid
        assert rule.min_risk_level in valid


# ══════════════════════════════════════════════════════════════════════════════
# UNKNOWN IS NEVER ZERO
# ══════════════════════════════════════════════════════════════════════════════

async def test_alerts_unknown_is_never_reported_as_zero(_stub_declarations):
    # A populated tenant, so "empty store" is not what makes this pass. The declaration
    # window truncated, so no findings rule can be *cleared* — a capability whose
    # declaration fell outside the window looks undeclared, and undeclared is
    # deliberately not a finding, so real drift would vanish into a clean report.
    await _seed_capability()
    _stub_declarations.truncated = True

    data = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]

    assert data["alerts_known"] is False
    assert data["alerts"] == []
    assert data["undecidable_rules"], "an undecidable rule must be named, not dropped"
    assert {e["rule_id"] for e in data["undecidable_rules"]} == {
        r.rule_id for r in DEFAULT_RULES if r.source == "capability_findings"
    }
    assert data["missing_inputs"]
    assert any("capability_declarations" in entry for entry in data["missing_inputs"])

    # Every count is null. Not 0 — "0 alerts" is an all-clear we have no evidence for.
    assert set(data["counts"]) == {
        "rules_evaluated",
        "alerts_triggered",
        "findings_examined",
        "agentic_signals_examined",
    }
    for key, value in data["counts"].items():
        assert value is None, f"counts.{key} must be null when it could not be computed"

    # And nowhere else in the response either.
    assert _zero_numbers(data) == []

    assert "UNKNOWN" in data["summary"]
    assert "not zero" in data["summary"]


async def test_unavailable_findings_input_is_unknown_not_quiet(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("catalog unreachable")

    monkeypatch.setattr(risk_service.capability_risk_service, "findings", _boom)

    data = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]
    assert data["alerts_known"] is False
    assert any("unavailable" in entry for entry in data["missing_inputs"])
    assert all(v is None for v in data["counts"].values())
    assert _zero_numbers(data) == []


async def test_a_fired_alert_survives_an_incomplete_window(monkeypatch, _stub_declarations):
    """Incompleteness suppresses the totals, not the evidence.

    A count over a partial window is a valid *lower bound*, so a rule that already met
    its threshold stays fired; only the claim that this is the complete set is withheld.
    """
    cap_id = await _seed_capability()
    _stub_scan(monkeypatch, {
        cap_id: [_finding(FindingCode.CREDENTIAL_IN_URL, cap_id, RiskLevel.HIGH.value)]
    })
    _stub_declarations.truncated = True

    data = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]

    alert = _alert(data, "credential_in_server_url")
    assert alert is not None, "a real alert must not be hidden by an unrelated truncation"
    assert alert["observed"]["count_is_lower_bound"] is True
    assert "or more" in alert["summary"]
    # ...but the totals are still withheld.
    assert data["alerts_known"] is False
    assert all(v is None for v in data["counts"].values())


# ══════════════════════════════════════════════════════════════════════════════
# observed_only NEVER ALERTS
# ══════════════════════════════════════════════════════════════════════════════

async def test_observed_only_capabilities_never_alert():
    # Three undeclared capabilities — the normal state of a tenant this platform exists
    # to inventory, and far above every default threshold if it were alertable.
    for index in range(3):
        await _seed_capability(source_event_id=f"e{index}", tool_name=f"tool{index}")

    findings = await risk_service.capability_risk_service.findings("t1", limit=500)
    assert findings["identity"]["observed_only"] == 3  # they are counted...
    assert findings["items"] == []                     # ...and are not findings.

    data = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]
    assert data["alerts"] == []
    assert data["alerts_known"] is True
    assert data["counts"]["alerts_triggered"] == 0  # a computed zero, over a complete window


async def test_a_rule_naming_a_non_alertable_code_is_rejected_at_construction():
    assert "observed_only" in NON_ALERTABLE_FINDING_CODES
    assert all(rule.code != "observed_only" for rule in DEFAULT_RULES)

    bad = AlertRule(
        rule_id="undeclared_capabilities",
        source="capability_findings",
        code="observed_only",
        min_risk_level=RiskLevel.LOW.value,
        min_count=1,
        severity=RiskLevel.LOW.value,
        description="would bury every real finding on day one",
    )
    with pytest.raises(ValueError, match="not alertable"):
        CapabilityAlertService(rules=(bad,))


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT — completeness is always stated
# ══════════════════════════════════════════════════════════════════════════════

async def test_export_truncation_is_disclosed():
    for index in range(3):
        await _seed_capability(source_event_id=f"e{index}", tool_name=f"tool{index}")

    cut = (await alert_routes.export_access_intelligence(
        _request("t1"), dataset="catalog", limit=1
    ))["data"]
    assert cut["truncated"] is True
    assert cut["row_count"] == 1
    assert cut["limit"] == 1
    assert cut["completeness"] == {
        "complete": False,
        "truncated": True,
        "limit": 1,
        "rows_returned": 1,
        "reasons": ["export_limit_reached:page_full_at_limit"],
        "statement": cut["completeness"]["statement"],
    }
    assert "INCOMPLETE EXPORT" in cut["completeness"]["statement"]
    assert "complete" in cut["completeness"]["statement"]  # says what it is NOT

    whole = (await alert_routes.export_access_intelligence(
        _request("t1"), dataset="catalog", limit=100
    ))["data"]
    assert whole["truncated"] is False
    assert whole["row_count"] == 3
    assert whole["completeness"]["reasons"] == []


async def test_findings_export_discloses_a_truncated_page(monkeypatch):
    caps = [
        await _seed_capability(source_event_id=f"e{i}", tool_name=f"tool{i}")
        for i in range(3)
    ]
    _stub_scan(monkeypatch, {
        cap: [_finding(FindingCode.INSECURE_TRANSPORT, cap, RiskLevel.HIGH.value)]
        for cap in caps
    })

    data = (await alert_routes.export_access_intelligence(
        _request("t1"), dataset="findings", limit=2
    ))["data"]
    assert data["row_count"] == 2
    assert data["truncated"] is True
    assert any("export_limit_reached" in r for r in data["completeness"]["reasons"])
    assert "3_matching_findings" in " ".join(data["completeness"]["reasons"])


async def test_blast_radius_export_carries_each_row_s_own_unknown_disclosure():
    await _seed_capability()
    data = (await alert_routes.export_access_intelligence(
        _request("t1"), dataset="blast_radius", limit=100
    ))["data"]
    assert data["dataset"] == "blast_radius"
    assert data["row_count"] == 1
    row = data["rows"][0]
    assert row["subject"] == {"kind": "agent", "id": "agentA"}
    # risk_service's own honesty machinery survives the export verbatim.
    assert "exposure_known" in row and "missing_inputs" in row and "counts" in row


async def test_export_rejects_an_unknown_dataset():
    with pytest.raises(BadRequestError, match="Unknown dataset"):
        await alert_routes.export_access_intelligence(
            _request("t1"), dataset="everything", limit=100
        )
    assert set(EXPORT_DATASETS) == {"findings", "blast_radius", "catalog"}


async def test_durable_export_path_is_registered_with_the_canonical_export_service():
    """Reuse, not a parallel export pipeline."""
    from services.export.service import EXPORTERS

    assert DURABLE_EXPORT_TYPE in EXPORTERS

    await _seed_capability()
    payload = await EXPORTERS[DURABLE_EXPORT_TYPE]("t1", {"dataset": "catalog", "limit": 1})
    assert len(payload.rows) == 1
    # Truncation reaches the artifact manifest through per_source.
    assert payload.per_source["truncated_at_limit"] == 1

    whole = await EXPORTERS[DURABLE_EXPORT_TYPE]("t1", {"dataset": "catalog", "limit": 100})
    assert "truncated_at_limit" not in whole.per_source


# ══════════════════════════════════════════════════════════════════════════════
# TENANT SCOPING + PERMISSIONS
# ══════════════════════════════════════════════════════════════════════════════

async def test_evaluate_is_tenant_scoped_and_requires_read(monkeypatch):
    cap_id = await _seed_capability("t1")
    _stub_scan(monkeypatch, {
        cap_id: [_finding(FindingCode.CREDENTIAL_IN_URL, cap_id, RiskLevel.HIGH.value)]
    })
    await _seed_risk_signal("t1", signal_id="sig-t1")

    mine = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]
    assert {a["rule_id"] for a in mine["alerts"]} == {
        "credential_in_server_url", "observed_agent_risk_signals"
    }

    # Another tenant sees neither the finding nor the observed signal.
    other = (await alert_routes.evaluate_capability_alerts(_request("t2"), limit=500))["data"]
    assert other["alerts"] == []
    assert other["counts"]["findings_examined"] == 0
    assert other["counts"]["agentic_signals_examined"] == 0

    with pytest.raises(ForbiddenError):
        await alert_routes.evaluate_capability_alerts(
            _request("t1", permissions=[]), limit=500
        )


async def test_export_is_tenant_scoped_and_requires_read():
    await _seed_capability("t1")

    other = (await alert_routes.export_access_intelligence(
        _request("t2"), dataset="catalog", limit=100
    ))["data"]
    assert other["rows"] == []
    assert other["row_count"] == 0

    with pytest.raises(ForbiddenError):
        await alert_routes.export_access_intelligence(
            _request("t1", permissions=[]), dataset="catalog", limit=100
        )


async def test_alert_severity_ordering_puts_the_worst_first(monkeypatch):
    cap_id = await _seed_capability()
    _stub_scan(monkeypatch, {
        cap_id: [_finding(FindingCode.CREDENTIAL_IN_URL, cap_id, RiskLevel.HIGH.value)]
    })
    await _seed_risk_signal(signal_id="sig-order")

    data = (await alert_routes.evaluate_capability_alerts(_request("t1"), limit=500))["data"]
    assert [a["severity"] for a in data["alerts"]] == [
        RiskLevel.CRITICAL.value, RiskLevel.HIGH.value
    ]


async def test_agentic_rule_code_is_separable_from_scanning_codes():
    """The observability plane's vocabulary must not be confused with scanning's."""
    assert AGENTIC_RISK_SIGNAL_CODE not in {code.value for code in FindingCode}
    agentic = next(r for r in DEFAULT_RULES if r.source == "agentic_risk_signals")
    assert agentic.code == AGENTIC_RISK_SIGNAL_CODE
