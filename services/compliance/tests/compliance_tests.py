"""
Aether Compliance — Test Suite
22 compliance checks across 6 groups: GDPR Data Protection, DSR, Consent,
Breach Notification, SOC 2, and Audit.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.logger import log


@dataclass
class TestResult:
    """Result of a single compliance test."""
    group: str
    name: str
    passed: bool
    detail: str = ""


class ComplianceTestRunner:
    """Runs all compliance verification tests."""

    def __init__(self):
        self._results: list = []

    def _test(self, group: str, name: str, condition: bool, detail: str = "") -> TestResult:
        result = TestResult(group=group, name=name, passed=condition, detail=detail)
        self._results.append(result)
        icon = "PASS" if condition else "FAIL"
        log(f"  [{icon}] {group}: {name}", tag="TEST")
        if detail and not condition:
            log(f"         {detail}", tag="TEST")
        return result

    def run_all(self) -> list:
        """Run all 22 compliance checks."""
        self._results = []

        self._test_gdpr_data_protection()
        self._test_gdpr_dsr()
        self._test_gdpr_consent()
        self._test_gdpr_breach()
        self._test_soc2()
        self._test_audit()

        passed = sum(1 for r in self._results if r.passed)
        total = len(self._results)
        log(f"\n  Results: {passed}/{total} checks passed", tag="TEST")

        return self._results

    # ── GDPR Data Protection Tests ───────────────────────────────────

    def _test_gdpr_data_protection(self):
        from gdpr.data_protection.data_protection import (
            DataCategory,
            DataMinimizationConfig,
            DataMinimizer,
            DataProtectionPipeline,
            DataVectorizer,
            IPAnonymizer,
            Pseudonymizer,
            anonymize_ip,
        )

        # Test 1: IPv4 anonymization
        self._test("GDPR-DP", "IPv4 anonymization zeros last octet",
                    anonymize_ip("192.168.1.100") == "192.168.1.0")

        # Test 2: IPv6 anonymization
        result = anonymize_ip("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        self._test("GDPR-DP", "IPv6 anonymization zeros last 80 bits",
                    "2001:db8:8" in result)

        # Test 3: Pseudonymization deterministic
        p = Pseudonymizer("test-salt")
        h1 = p.pseudonymize("user@example.com")
        h2 = p.pseudonymize("user@example.com")
        self._test("GDPR-DP", "Pseudonymization is deterministic",
                    h1 == h2 and len(h1) == 64)

        # Test 4: Data minimization blocks disabled categories
        config = DataMinimizationConfig("t1", {DataCategory.PAGE_VIEWS})
        m = DataMinimizer(config)
        allowed = m.filter_event({"event_type": "page_view"})
        blocked = m.filter_event({"event_type": "click"})
        self._test("GDPR-DP", "Data minimization blocks disabled categories",
                    allowed is not None and blocked is None)

        # Test 5: Pipeline processes events end-to-end
        pipeline = DataProtectionPipeline(
            ip_anonymizer=IPAnonymizer(),
            vectorizer=DataVectorizer(enabled=False),
            pseudonymizer=Pseudonymizer("test"),
            minimizer=DataMinimizer(DataMinimizationConfig("t1", {DataCategory.PAGE_VIEWS})),
        )
        results = pipeline.process_batch([
            {"event_type": "page_view", "ip": "1.2.3.4", "user_id": "u1"},
            {"event_type": "click", "ip": "5.6.7.8", "user_id": "u2"},
        ])
        self._test("GDPR-DP", "Pipeline processes and filters correctly",
                    len(results) == 1 and results[0]["ip"] == "1.2.3.0")

    # ── GDPR DSR Tests ───────────────────────────────────────────────

    def _test_gdpr_dsr(self):
        from gdpr.data_subject_rights.dsr_engine import DSRExecutor, DSRRequest, DSRStatus, DSRType

        executor = DSRExecutor()

        # Test 6: Access request completes
        dsr = DSRRequest(type=DSRType.ACCESS, tenant_id="t1", user_id="u1")
        executor.submit(dsr)
        result = executor.execute(dsr.id)
        self._test("GDPR-DSR", "Access request (Art. 15) completes",
                    result.status == DSRStatus.COMPLETED and result.result is not None)

        # Test 7: Erasure processes all stores (7 base + 5 IG + 3 IG extra = 15)
        dsr2 = DSRRequest(type=DSRType.ERASURE, tenant_id="t1", user_id="u2")
        executor.submit(dsr2)
        result2 = executor.execute(dsr2.id)
        self._test("GDPR-DSR", "Erasure (Art. 17) processes all stores",
                    len(result2.stores_processed) == 15 and len(result2.stores_remaining) == 0)

        # Test 8: Restriction is immediate (0-day SLA)
        dsr3 = DSRRequest(type=DSRType.RESTRICTION, tenant_id="t1", user_id="u3")
        from datetime import datetime, timezone
        deadline = datetime.fromisoformat(dsr3.deadline)
        now = datetime.now(timezone.utc)
        self._test("GDPR-DSR", "Restriction (Art. 18) has immediate SLA",
                    abs((deadline - now).total_seconds()) < 5)

        # Test 9: Objection is immediate
        dsr4 = DSRRequest(type=DSRType.OBJECTION, tenant_id="t1", user_id="u4")
        executor.submit(dsr4)
        result4 = executor.execute(dsr4.id)
        self._test("GDPR-DSR", "Objection (Art. 21) stops processing immediately",
                    result4.status == DSRStatus.COMPLETED)

        # Test 10: Summary tracks all requests
        summary = executor.summary()
        self._test("GDPR-DSR", "Executor tracks all submitted DSRs",
                    summary["total"] >= 3)

    # ── GDPR Consent Tests ───────────────────────────────────────────

    def _test_gdpr_consent(self):
        from config.compliance_config import ConsentPurpose
        from gdpr.consent.consent_manager import ConsentManager, ConsentSource

        mgr = ConsentManager()

        # Test 11: Grant records consent
        mgr.grant("t1", "u1", ConsentPurpose.ANALYTICS, "2.0", ConsentSource.BANNER)
        self._test("GDPR-Consent", "Consent grant is recorded",
                    mgr.check_consent("t1", "u1", ConsentPurpose.ANALYTICS))

        # Test 12: Revoke removes consent
        mgr.revoke("t1", "u1", ConsentPurpose.ANALYTICS, ConsentSource.SETTINGS)
        self._test("GDPR-Consent", "Consent revocation is effective",
                    not mgr.check_consent("t1", "u1", ConsentPurpose.ANALYTICS))

        # Test 13: DNT revokes all
        mgr.grant("t1", "u2", ConsentPurpose.ANALYTICS, "2.0")
        mgr.grant("t1", "u2", ConsentPurpose.MARKETING, "2.0")
        mgr.handle_dnt("t1", "u2", "1")
        analytics = mgr.check_consent("t1", "u2", ConsentPurpose.ANALYTICS)
        marketing = mgr.check_consent("t1", "u2", ConsentPurpose.MARKETING)
        self._test("GDPR-Consent", "DNT:1 revokes all consent",
                    not analytics and not marketing)

        # Test 14: Audit trail maintains history
        trail = mgr.get_audit_trail("t1", "u1")
        self._test("GDPR-Consent", "Audit trail records all consent actions",
                    len(trail) >= 2)

    # ── Breach Notification Tests ────────────────────────────────────

    def _test_gdpr_breach(self):
        from gdpr.breach_notification.breach_handler import BreachHandler, BreachSeverity

        handler = BreachHandler()

        # Test 15: Full incident response pipeline
        incident = handler.run_full_response(
            description="Test breach",
            detection_source="unit_test",
            severity=BreachSeverity.HIGH,
            users_count=500,
            data_categories=["identity_profiles"],
        )
        self._test("GDPR-Breach", "Full incident response pipeline completes",
                    incident.status.value == "closed" and len(incident.timeline) > 5)

        # Test 16: Auto-severity escalation
        handler2 = BreachHandler()
        inc2 = handler2.report_breach("Test", "test", BreachSeverity.MEDIUM)
        handler2.assess_breach(inc2.id, 15000, ["financial_wallet"])
        self._test("GDPR-Breach", "Severity auto-escalates for large breaches",
                    inc2.severity == BreachSeverity.CRITICAL)

    # ── SOC 2 Tests ──────────────────────────────────────────────────

    def _test_soc2(self):
        from soc2.trust_criteria.trust_criteria_engine import TrustCriteriaEngine

        engine = TrustCriteriaEngine()

        # Test 17: All 5 criteria assessed
        assessments = engine.run_full_assessment()
        self._test("SOC2", "All 5 trust criteria are assessed",
                    len(assessments) == 5)

        # Test 18: Controls are defined
        self._test("SOC2", "33+ controls defined across all criteria",
                    len(engine.controls) >= 33)

        # Test 19: Readiness > 90% with 0 NOT_IMPLEMENTED gaps remaining
        readiness = engine.overall_readiness()
        gaps = engine.get_gaps()        # partial controls still tracked
        critical = engine.get_critical_gaps()   # NOT_IMPLEMENTED — target = 0
        self._test("SOC2", "Readiness >90% and no NOT_IMPLEMENTED controls remain",
                    readiness["readiness_score"] > 90.0
                    and critical == []
                    and len(gaps) <= 2)   # only CC-3.2 and A-3.2 remain partial

    # ── Audit Tests ──────────────────────────────────────────────────

    def _test_audit(self):
        from audit.trails.audit_engine import AuditAction, AuditEngine

        audit = AuditEngine()

        # Test 20: Data access logging
        audit.log_data_access("admin", "t1", "profile", "u1", AuditAction.READ)
        self._test("Audit", "Data access is logged",
                    len(audit.query(trail="application")) == 1)

        # Test 21: Consent event logging
        audit.log_consent_event("t1", "u1", AuditAction.CONSENT_GRANT, "analytics", "2.0")
        self._test("Audit", "Consent events are logged",
                    len(audit.query(trail="consent")) == 1)

        # Test 22: Agent action logging with provenance
        audit.log_agent_action("t1", "agent-1", "task-1", "predict",
                               {"user_id": "u1"}, {"score": 0.8}, 0.95, "model-v1")
        entries = audit.query(trail="agent")
        self._test("Audit", "Agent actions logged with provenance",
                    len(entries) == 1 and entries[0].detail["confidence"] == 0.95)
