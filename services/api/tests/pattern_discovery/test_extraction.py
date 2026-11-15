"""Schema-on-read extraction: typing, privacy, learned identifiers, free text."""
from __future__ import annotations

from intelligence.pattern_discovery.extraction import (
    classify_value, digest, extract_events, extract_payload, flatten, message_template, outcome_of,
    text_tokens,
)

from .scenarios import T, fraud_ring, normal_traffic


def test_semantic_types_come_from_value_shape_before_key_hints():
    assert classify_value("someone@example.com")[0] == "email"
    assert classify_value("0x" + "a" * 40)[0] == "wallet"
    assert classify_value("4242 4242 4242 4242")[0] == "payment_instrument"
    assert classify_value("4242 4242 4242 4241") is None  # fails Luhn: not a card
    assert classify_value("203.0.113.7")[0] == "ip"
    assert classify_value("https://rpc.example.io/v1")[0] == "host"
    assert classify_value("2026-11-01T10:00:00Z")[0] == "timestamp"
    assert classify_value("abc-123", "meta.device_id") == ("device", 0.7)
    assert classify_value("hello world", "free_text") is None


def test_sensitive_values_never_leave_extraction_in_clear():
    out = extract_payload({"email": "Someone@Example.com", "card": "4242424242424242",
                           "ip": "203.0.113.7", "wallet": "0x" + "B" * 40}, T)
    by_type = {a["type"]: a["value"] for a in out["attributes"]}
    assert by_type["email"] == digest(T, "email", "someone@example.com")
    assert by_type["payment_instrument"].startswith("h:") and "4242" not in by_type["payment_instrument"]
    assert by_type["ip"].startswith("h:")
    assert by_type["wallet"] == "0x" + "b" * 40  # public on-chain identifier, kept (normalised)
    assert all(a["claim_state"] == "inferred" for a in out["attributes"])


def test_digest_is_tenant_salted():
    assert digest("t1", "email", "a@b.co") != digest("t2", "email", "a@b.co")


def test_flatten_is_shape_level_and_bounded():
    leaves = dict(flatten({"a": {"b": [1, {"c": 2}]}, "d": "x"}))
    assert leaves == {"a.b[]": 1, "a.b[].c": 2, "d": "x"} or "a.b[].c" in leaves
    deep = {"k": {"k": {"k": {"k": {"k": {"k": {"k": {"k": 1}}}}}}}}
    assert any(isinstance(v, dict) and v.get("__truncated__") for _p, v in flatten(deep))


def test_message_templates_collapse_variable_parts():
    a = message_template("Card 4242 declined for order 991 at 10.1.2.3")
    b = message_template("card 1881 declined for order 12 at 10.9.9.9")
    assert a == b
    assert a[0] == "card <*> declined for order <*> at <*>"


def test_identifiers_embedded_in_free_text_are_found():
    toks = dict(text_tokens("refund to bob@example.com via https://pay.example.net/x from 0x" + "d" * 40))
    assert set(toks) == {"email", "host", "wallet"}


def test_outcomes_are_read_from_type_or_payload():
    assert outcome_of("payment_failed", {}) == "fail"
    assert outcome_of("checkout", {"status": "succeeded"}) == "ok"
    assert outcome_of("checkout", {"success": False}) == "fail"
    assert outcome_of("api_call", {"status": 502}) == "fail"
    assert outcome_of("browse", {}) is None


def test_counterparties_and_tokens():
    out = extract_payload({"status": "declined", "to": "0x" + "c" * 40, "delegated_by": "u9"}, T,
                          event_type="withdraw")
    assert out["token"] == "withdraw!fail"
    rels = {(c["relation"], c["entity"]) for c in out["counterparties"]}
    assert ("TRANSACTS_WITH", "wallet:0x" + "c" * 40) in rels
    assert ("DELEGATED_BY", "user:u9") in rels


def test_learned_identifier_field_is_promoted_but_categories_are_not():
    result = extract_events(normal_traffic(3, 3, users=40) + fraud_ring(3), T)
    learned = result.stats["learned_identifier_fields"]
    assert any(f.endswith(":partner_ref") for f in learned)
    assert not any(f.endswith(":status") for f in learned)
    ring_event = next(e for e in result.events if e.entity == "user:r0" and e.event_type == "login")
    assert any(a.type == "field:partner_ref" and a.extractor == "learned_identifier" for a in ring_event.attributes)


def test_foreign_tenant_rows_are_ignored():
    rows = normal_traffic(1, 1, users=3) + normal_traffic(2, 1, users=3, tenant="other")
    result = extract_events(rows, T)
    assert result.stats["skipped"]["foreign_tenant"] == len([r for r in rows if r["tenant_id"] == "other"])
    assert all(e.entity for e in result.events)


def test_observations_are_candidates_not_facts():
    result = extract_events(fraud_ring(4), T)
    obs = result.candidate_observations(T, limit=50)
    assert obs and all(o["claim_state"] == "inferred" and o["extractor"] for o in obs)
    assert len({o["observation_id"] for o in obs}) == len(obs)
