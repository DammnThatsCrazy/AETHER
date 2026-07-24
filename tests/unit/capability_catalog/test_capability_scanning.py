"""Capability tool/schema scanning tests (PR 2, Phase B2 — monoprompt §9.4).

The load-bearing properties proven here are the two reuse decisions in
``services/agent_access_intelligence/scanning.py``:

  1. scanning is **pure** — no DNS, no network, no clock. An unresolvable host yields no
     origin finding, and the module must never grow a dependency on
     ``policy_engine._is_unsafe_destination`` (which resolves and fails closed).
  2. injection matching is **token-boundary**, not noesis's substring match — so ordinary
     tool names like ``bypass_cache`` and ``abundance_report`` never appear in the surface.

Plus the invariant that makes the surface safe to render: no credential value ever reaches
``evidence``.
"""

from __future__ import annotations

import socket

import pytest

from services.agent_access_intelligence import scanning
from services.agent_access_intelligence.scanning import (
    CapabilityFinding,
    FindingCode,
    scan_capabilities,
    scan_capability,
)
from services.agentic_observability.models import RiskLevel

SECRET = "sup3rs3cr3tpassw0rd"
SECRET_USER = "svc_account_user"


def _codes(findings: list[CapabilityFinding]) -> list[FindingCode]:
    return [f.code for f in findings]


def _record(**over):
    rec = {"capability_id": "cap_abc123", "tenant_id": "t1"}
    rec.update(over)
    return rec


# ─── Absent data is not a finding ─────────────────────────────────────────────


def test_record_with_no_url_and_no_tool_name_yields_no_findings():
    assert scan_capability(_record()) == []
    assert scan_capability({}) == []


def test_blank_and_non_string_fields_yield_no_findings():
    assert scan_capability(_record(server_url="   ", tool_name="")) == []
    assert scan_capability(_record(server_url=None, tool_name=None)) == []
    assert scan_capability(_record(server_url=1234, tool_name=object())) == []


# ─── Purity: no DNS, no network, no resolution ────────────────────────────────


def test_unresolvable_hostname_yields_no_origin_finding():
    """A host that does not resolve *from our network* is not evidence about the tenant."""
    findings = scan_capability(_record(server_url="https://nonexistent.invalid/mcp"))
    assert findings == []


def test_scanning_performs_no_dns_lookup(monkeypatch):
    def _boom(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("scan_capability performed a DNS lookup")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    monkeypatch.setattr(socket, "gethostbyname", _boom, raising=False)
    from services.security import policy_engine

    monkeypatch.setattr(policy_engine, "_resolve_host", _boom)

    for url in (
        "https://nonexistent.invalid/mcp",
        "http://internal-only.corp.example/tools",
        "https://user:%s@customer-vpc.internal/mcp?token=REDACTED" % SECRET,
        "localhost:8080",
    ):
        scan_capability(_record(server_url=url, tool_name="ignore_previous_instructions"))


def test_module_does_not_import_the_resolving_primitive():
    """Regression guard: reusing ``_is_unsafe_destination``/``_resolve_host`` here would
    make the surface depend on our DNS view and fail closed on legitimate internal hosts."""
    assert not hasattr(scanning, "_is_unsafe_destination")
    assert not hasattr(scanning, "_resolve_host")
    # The pure primitives ARE reused.
    assert scanning._ip_is_unsafe is not None
    assert "localhost" in scanning._BLOCKED_HOSTS


# ─── Credential in URL ────────────────────────────────────────────────────────


def test_userinfo_in_url_is_a_high_credential_finding():
    findings = scan_capability(
        _record(server_url=f"https://{SECRET_USER}:{SECRET}@mcp.example.com/v1")
    )
    assert _codes(findings) == [FindingCode.CREDENTIAL_IN_URL]
    assert findings[0].risk_level is RiskLevel.HIGH


def test_userinfo_survives_in_schemeless_url_and_is_still_detected():
    """``_sanitize_server_url`` returns schemeless opaque values unchanged, so userinfo can
    still be present in a stored record."""
    findings = scan_capability(_record(server_url=f"{SECRET_USER}:{SECRET}@mcp.example.com/v1"))
    assert FindingCode.CREDENTIAL_IN_URL in _codes(findings)


def test_redaction_sentinel_is_evidence_a_credential_was_configured():
    findings = scan_capability(
        _record(server_url="https://mcp.example.com/v1?token=REDACTED&page=2")
    )
    assert _codes(findings) == [FindingCode.CREDENTIAL_IN_URL]
    assert "'token'" in findings[0].evidence
    assert "page" not in findings[0].evidence


def test_ordinary_query_string_is_not_a_credential_finding():
    findings = scan_capability(_record(server_url="https://mcp.example.com/v1?page=2&mode=fast"))
    assert findings == []


def test_credential_value_never_appears_in_any_evidence():
    urls = [
        f"https://{SECRET_USER}:{SECRET}@mcp.example.com/v1?token=REDACTED",
        f"http://{SECRET_USER}:{SECRET}@10.0.0.9:8080/v1?api_key=REDACTED&secret=REDACTED",
        f"{SECRET_USER}:{SECRET}@localhost:8080",
        f"https://mcp.example.com/v1?password={SECRET}",
    ]
    for url in urls:
        findings = scan_capability(_record(server_url=url, tool_name="dan"))
        blob = " ".join(f.evidence + " " + f.summary for f in findings)
        assert SECRET not in blob, url
        assert SECRET_USER not in blob, url


# ─── Transport ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scheme", ["http", "ws", "ftp"])
def test_non_https_scheme_is_a_high_insecure_transport_finding(scheme):
    findings = scan_capability(_record(server_url=f"{scheme}://mcp.example.com/v1"))
    assert _codes(findings) == [FindingCode.INSECURE_TRANSPORT]
    assert findings[0].risk_level is RiskLevel.HIGH
    assert scheme in findings[0].evidence


def test_https_is_not_a_finding():
    assert scan_capability(_record(server_url="https://mcp.example.com/v1")) == []


def test_opaque_server_name_without_scheme_is_not_insecure_transport():
    """Absence of a scheme tells us nothing about how the server is reached — saying
    'insecure' there would be an invention, not an observation."""
    for name in ("mcp.example.com", "internal-mcp", "mcp.example.com/v1"):
        assert FindingCode.INSECURE_TRANSPORT not in _codes(
            scan_capability(_record(server_url=name))
        )


# ─── Origin: literal IPs and blocked hosts ────────────────────────────────────


@pytest.mark.parametrize(
    "host",
    ["10.0.0.5", "192.168.1.10", "127.0.0.1", "169.254.169.254", "0.0.0.0", "[::1]"],
)
def test_unsafe_ip_literal_is_a_private_network_origin_finding(host):
    findings = scan_capability(_record(server_url=f"https://{host}/v1"))
    assert FindingCode.PRIVATE_NETWORK_ORIGIN in _codes(findings)
    finding = next(f for f in findings if f.code is FindingCode.PRIVATE_NETWORK_ORIGIN)
    assert finding.risk_level is RiskLevel.MEDIUM


def test_public_ip_literal_is_not_a_finding():
    assert scan_capability(_record(server_url="https://8.8.8.8/v1")) == []


def test_ip_literal_with_port_is_still_detected():
    findings = scan_capability(_record(server_url="https://10.0.0.5:8443/v1"))
    assert FindingCode.PRIVATE_NETWORK_ORIGIN in _codes(findings)


@pytest.mark.parametrize("host", ["localhost", "metadata.google.internal"])
def test_blocked_host_is_a_medium_finding(host):
    findings = scan_capability(_record(server_url=f"https://{host}/v1"))
    assert FindingCode.BLOCKED_HOST_ORIGIN in _codes(findings)
    finding = next(f for f in findings if f.code is FindingCode.BLOCKED_HOST_ORIGIN)
    assert finding.risk_level is RiskLevel.MEDIUM


def test_blocked_host_detected_on_schemeless_value_with_port():
    findings = scan_capability(_record(server_url="localhost:8080"))
    assert _codes(findings) == [FindingCode.BLOCKED_HOST_ORIGIN]


@pytest.mark.parametrize(
    "raw", ["mcp.example.com:8443", "localhost:8080", "internal-mcp:9000/tools"]
)
def test_schemeless_host_port_is_not_mistaken_for_a_scheme(raw):
    """``urlsplit('mcp.example.com:8443')`` reports scheme='mcp.example.com'. Trusting that
    would report an opaque host:port name as insecure transport and lose its host."""
    findings = scan_capability(_record(server_url=raw))
    assert FindingCode.INSECURE_TRANSPORT not in _codes(findings)


def test_schemeless_userinfo_with_scheme_shaped_user_is_still_a_credential_finding():
    """``urlsplit('user:pass@host/x')`` reports scheme='user' — the credential must still
    be seen, and 'user' must not be reported as a transport scheme."""
    findings = scan_capability(_record(server_url="user:pass@mcp.example.com/v1"))
    assert _codes(findings) == [FindingCode.CREDENTIAL_IN_URL]


def test_protocol_relative_origin_keeps_its_host():
    findings = scan_capability(_record(server_url="//10.0.0.5/v1"))
    assert _codes(findings) == [FindingCode.PRIVATE_NETWORK_ORIGIN]


def test_unparseable_origin_is_a_low_finding():
    findings = scan_capability(_record(server_url="http://[::1/v1"))
    assert _codes(findings) == [FindingCode.UNPARSEABLE_ORIGIN]
    assert findings[0].risk_level is RiskLevel.LOW


# ─── Injection-shaped tool names: the false-positive traps ────────────────────


@pytest.mark.parametrize(
    "tool_name",
    [
        "abundance_report",      # contains "dan" as a substring
        "redundancy_check",      # contains "dan" as a substring
        "standardize",           # contains "dan" as a substring
        "bypass_cache",          # contains "bypass" as a whole token, but names a cache op
        "mundane_task",
        "get_dandelion_data",
        "abundanceReport",
        "list_bypass_rules",
    ],
)
def test_mechanical_tool_names_do_not_produce_injection_findings(tool_name):
    findings = scan_capability(_record(tool_name=tool_name))
    assert FindingCode.INJECTION_SHAPED_TOOL_NAME not in _codes(findings), tool_name


@pytest.mark.parametrize(
    "tool_name,expected_pattern",
    [
        ("ignore_previous_instructions", "ignore previous"),
        ("ignore-above-context", "ignore above"),
        ("systemPrompt_dump", "system prompt"),
        ("tool.developer.mode", "developer mode"),
        ("you_are_now_admin", "you are now"),
        ("dan", "dan"),
        ("BYPASS", "bypass"),
        ("jailbreak", "jailbreak"),
    ],
)
def test_injection_shaped_tool_names_are_detected(tool_name, expected_pattern):
    findings = scan_capability(_record(tool_name=tool_name))
    assert _codes(findings) == [FindingCode.INJECTION_SHAPED_TOOL_NAME], tool_name
    finding = findings[0]
    assert finding.risk_level is RiskLevel.MEDIUM
    assert expected_pattern in finding.evidence


def test_injection_finding_names_the_matched_pattern_only_once_per_record():
    findings = scan_capability(_record(tool_name="ignore_previous_and_ignore_previous"))
    assert len(findings) == 1
    assert findings[0].evidence.count("ignore previous") == 1


def test_noesis_substring_matching_would_have_fired_on_the_traps():
    """Pins the reason this lane does not reuse noesis's matcher: the same vocabulary with
    substring matching flags ordinary tool names."""
    from services.noesis.models import INJECTION_PATTERNS

    # ("standardize" is listed as a trap upstream but does not actually contain any
    # pattern as a substring — the real substring traps are these three.)
    for trap in ("abundance_report", "redundancy_check", "bypass_cache"):
        low = trap.lower()
        assert any(p in low for p in INJECTION_PATTERNS), trap
        assert FindingCode.INJECTION_SHAPED_TOOL_NAME not in _codes(
            scan_capability(_record(tool_name=trap))
        )


# ─── Determinism, ordering, purity ────────────────────────────────────────────


def test_findings_are_sorted_by_code():
    findings = scan_capability(
        _record(
            server_url=f"http://{SECRET_USER}:{SECRET}@10.0.0.5/v1?token=REDACTED",
            tool_name="ignore_previous_instructions",
        )
    )
    codes = [f.code.value for f in findings]
    assert codes == sorted(codes)
    assert set(codes) == {
        FindingCode.CREDENTIAL_IN_URL.value,
        FindingCode.INSECURE_TRANSPORT.value,
        FindingCode.PRIVATE_NETWORK_ORIGIN.value,
        FindingCode.INJECTION_SHAPED_TOOL_NAME.value,
    }


def test_same_input_twice_yields_equal_output():
    record = _record(
        server_url="http://localhost:8080/v1?api_key=REDACTED",
        tool_name="systemPrompt_dump",
    )
    first = scan_capability(record)
    second = scan_capability(dict(record))
    assert [f.model_dump() for f in first] == [f.model_dump() for f in second]


def test_scan_does_not_mutate_the_record():
    record = _record(server_url="https://10.0.0.5/v1", tool_name="dan")
    snapshot = dict(record)
    scan_capability(record)
    assert record == snapshot


def test_capability_id_is_carried_onto_every_finding():
    findings = scan_capability(
        _record(capability_id="cap_zzz", server_url="http://10.0.0.5/v1", tool_name="dan")
    )
    assert findings
    assert all(f.capability_id == "cap_zzz" for f in findings)


def test_missing_capability_id_leaves_the_field_none():
    findings = scan_capability({"server_url": "http://10.0.0.5/v1"})
    assert findings and all(f.capability_id is None for f in findings)


def test_scan_capabilities_groups_findings_per_record_in_input_order():
    records = [
        _record(capability_id="cap_1", server_url="https://mcp.example.com/v1"),
        _record(capability_id="cap_2", server_url="http://10.0.0.5/v1"),
        _record(capability_id="cap_3", tool_name="dan"),
    ]
    findings = scan_capabilities(records)
    assert [f.capability_id for f in findings] == ["cap_2", "cap_2", "cap_3"]
    assert scan_capabilities(records) == findings
    assert scan_capabilities([]) == []


def test_findings_round_trip_through_a_flat_dict():
    finding = scan_capability(_record(server_url="http://mcp.example.com/v1"))[0]
    dumped = finding.model_dump()
    assert all(not isinstance(v, (dict, list)) for v in dumped.values())
    assert CapabilityFinding(**dumped) == finding
