"""Role-pair join rules: vendor-neutral, tenant-safe, weak evidence never proves."""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone

import pytest

from shared.agent_lineage.vocabulary import PRINCIPAL_PROOF_EVIDENCE_CLASSES
from shared.integration_contracts import correlation, source_roles
from shared.integration_contracts.correlation import (
    JOIN_KEY_EVIDENCE,
    JOIN_KEY_KINDS,
    JOIN_RULES,
    CorrelationObservation,
    ObservedObjectRef,
    SignedRequestRef,
    correlate,
    join_keys_for,
)
from shared.integration_contracts.correlation_token import issue_correlation_token, token_verifier
from shared.integration_contracts.source_roles import SOURCE_ROLES

T0 = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
KEYS = {"k1": b"s" * 32}
VERIFY = token_verifier(KEYS, now=T0)

INVENTORY = ObservedObjectRef(
    provider_family="shopify",
    source_account_realm="live",
    source_account_key="store-1",
    object_type="inventory_level",
    object_id="gid://shopify/InventoryLevel/1",
)


def _obs(oid: str, role: str, *, tenant: str = "tenant_a", family: str = "vendor", at: datetime = T0, **kw):
    return CorrelationObservation(
        tenant_id=tenant, observation_id=oid, source_role=role, provider_family=family, occurred_at=at, **kw
    )


def _token(tenant: str = "tenant_a", task_ref: str | None = None) -> str:
    return issue_correlation_token(tenant_id=tenant, key_id="k1", secret=KEYS["k1"], task_ref=task_ref, now=T0).token


# --- registry shape ---------------------------------------------------------


def test_every_rule_names_known_roles_and_keys() -> None:
    for pair, keys in JOIN_RULES.items():
        assert pair <= set(SOURCE_ROLES)
        assert set(keys) <= set(JOIN_KEY_KINDS)
    assert set(JOIN_KEY_EVIDENCE) == set(JOIN_KEY_KINDS)


def test_join_keys_are_symmetric_and_strongest_first() -> None:
    for a in SOURCE_ROLES:
        for b in SOURCE_ROLES:
            assert join_keys_for(a, b) == join_keys_for(b, a)
    keys = join_keys_for("tool_bridge", "system_of_record")
    assert list(keys) == sorted(keys, key=JOIN_KEY_KINDS.index)


def test_join_logic_contains_no_vendor_names() -> None:
    """Joins are keyed by role pair. Vendor names belong in provider modules.

    Docstrings may use a vendor as an example; executable code may not.
    """
    vendors = re.compile(r"shopify|stripe|ramp|cloudflare|openai|grok|xai|github|anthropic|cursor", re.I)
    for module in (correlation, source_roles):
        source = inspect.getsource(module)
        code = re.sub(r'"""[\s\S]*?"""', "", source)
        code = "\n".join(line.split("#", 1)[0] for line in code.splitlines())
        assert not vendors.search(code), module.__name__


# --- verdicts ---------------------------------------------------------------


def test_staff_account_effect_alone_does_not_name_an_agent() -> None:
    """Shopify's AI connector acts through a staff account.

    With only the system-of-record record and a runtime record near in time,
    the link stays a candidate: timing never proves an agent acted.
    """
    effect = _obs("shop-1", "system_of_record", family="shopify", object_refs=(INVENTORY,), actor_refs=("staff:42",))
    runtime = _obs("bot-1", "agent_runtime", family="xai", at=T0 + timedelta(seconds=20))
    verdict = correlate(runtime, effect, token_verifier=VERIFY)
    assert verdict.status == "candidate"
    assert verdict.evidence_class == "TEMPORALLY_CORRELATED"
    assert not verdict.proves_link


def test_tool_call_returning_object_id_binds_deterministically() -> None:
    verified = INVENTORY.model_copy(update={"account_verification_ref": "conn_1:store-1"})
    effect = _obs("shop-1", "system_of_record", family="shopify", object_refs=(verified,))
    call = _obs("mcp-1", "tool_bridge", family="shopify", at=T0 - timedelta(seconds=3), object_refs=(INVENTORY,))
    verdict = correlate(call, effect)
    assert verdict.status == "linked"
    assert verdict.key_kind == "shared_object_ref"
    assert verdict.evidence_class in PRINCIPAL_PROOF_EVIDENCE_CLASSES
    assert verdict.supporting_keys == ("shared_object_ref", "time_window")


def test_object_match_on_declared_accounts_is_tenant_declared() -> None:
    """Without a verified account on either side, the scope rests on the tenant's word."""
    effect = _obs("shop-1", "system_of_record", object_refs=(INVENTORY,))
    call = _obs("mcp-1", "tool_bridge", at=T0 - timedelta(seconds=3), object_refs=(INVENTORY,))
    verdict = correlate(call, effect)
    assert verdict.status == "candidate"
    assert verdict.key_kind == "declared_object_ref"
    assert verdict.evidence_class == "TENANT_DECLARED"


def test_verification_ref_is_evidence_not_scope() -> None:
    verified = INVENTORY.model_copy(update={"account_verification_ref": "conn_1:store-1"})
    assert verified.scope_key == INVENTORY.scope_key
    effect = _obs("shop-1", "system_of_record", object_refs=(INVENTORY,))
    call = _obs("mcp-1", "tool_bridge", object_refs=(verified,))
    assert correlate(call, effect).key_kind == "shared_object_ref"


def test_object_match_far_apart_in_time_does_not_bind() -> None:
    effect = _obs("shop-1", "system_of_record", object_refs=(INVENTORY,))
    call = _obs("mcp-1", "tool_bridge", at=T0 - timedelta(days=2), object_refs=(INVENTORY,))
    verdict = correlate(call, effect)
    assert verdict.status == "rejected" and verdict.reason == "no_join_key_matched"


def test_object_ref_must_match_full_account_scope() -> None:
    other_store = INVENTORY.model_copy(update={"source_account_key": "store-2"})
    effect = _obs("shop-1", "system_of_record", object_refs=(INVENTORY,))
    call = _obs("mcp-1", "tool_bridge", object_refs=(other_store,))
    assert correlate(call, effect).key_kind == "time_window"


def test_aether_token_in_payment_metadata_binds_without_timing() -> None:
    token = _token()
    task = _obs("bot-1", "agent_runtime", correlation_tokens=(token,))
    charge = _obs("pay-1", "system_of_record", family="stripe", at=T0 + timedelta(hours=6), correlation_tokens=(token,))
    verdict = correlate(task, charge, token_verifier=VERIFY)
    assert verdict.status == "linked" and verdict.key_kind == "aether_correlation_token"


def test_token_needs_a_verifier() -> None:
    token = _token()
    task = _obs("bot-1", "agent_runtime", correlation_tokens=(token,))
    charge = _obs("pay-1", "system_of_record", at=T0 + timedelta(hours=6), correlation_tokens=(token,))
    assert correlate(task, charge).status == "rejected"


def test_conflicting_tokens_reject_even_when_timing_matches() -> None:
    task = _obs("bot-1", "agent_runtime", correlation_tokens=(_token(),))
    charge = _obs("pay-1", "system_of_record", correlation_tokens=(_token(),))
    verdict = correlate(task, charge, token_verifier=VERIFY)
    assert verdict.status == "rejected" and verdict.reason == "conflicting_correlation_tokens"


def test_token_copied_from_another_tenant_never_links() -> None:
    foreign = _token(tenant="tenant_b")
    task = _obs("bot-1", "agent_runtime", correlation_tokens=(foreign,))
    charge = _obs("pay-1", "system_of_record", at=T0 + timedelta(hours=6), correlation_tokens=(foreign,))
    assert correlate(task, charge, token_verifier=VERIFY).status == "rejected"


def test_cross_tenant_observations_are_never_joined() -> None:
    token = _token()
    a = _obs("bot-1", "agent_runtime", correlation_tokens=(token,), object_refs=(INVENTORY,))
    b = _obs("shop-1", "system_of_record", tenant="tenant_b", correlation_tokens=(token,), object_refs=(INVENTORY,))
    verdict = correlate(a, b, token_verifier=VERIFY)
    assert verdict.status == "rejected" and verdict.reason == "cross_tenant_join_forbidden"


def test_signed_request_attests_runtime_traffic() -> None:
    edge = _obs("edge-1", "network_observer", family="cloudflare",
                signed_request=SignedRequestRef(request_id="req-9", signature_verified=True))
    runtime = _obs("bot-1", "agent_runtime", at=T0 + timedelta(minutes=30),
                   signed_request=SignedRequestRef(request_id="req-9", signature_verified=False))
    verdict = correlate(edge, runtime)
    assert verdict.status == "linked" and verdict.evidence_class == "CRYPTOGRAPHICALLY_ATTESTED"


def test_unverified_signature_on_both_sides_does_not_attest() -> None:
    edge = _obs("edge-1", "network_observer", signed_request=SignedRequestRef(request_id="r", signature_verified=False))
    runtime = _obs("bot-1", "agent_runtime", signed_request=SignedRequestRef(request_id="r", signature_verified=False))
    assert correlate(edge, runtime).evidence_class == "TEMPORALLY_CORRELATED"


def test_infrastructure_and_actor_refs_stay_candidates() -> None:
    gw = _obs("gw-1", "network_observer", infrastructure_refs=("gateway_request:abc",))
    bridge = _obs("mcp-1", "tool_bridge", infrastructure_refs=("gateway_request:abc",))
    assert correlate(gw, bridge).evidence_class == "INFRASTRUCTURE_CORRELATED"
    grant = _obs("grant-1", "authority_issuer", actor_refs=("oauth_client:bot",))
    effect = _obs("shop-1", "system_of_record", actor_refs=("oauth_client:bot",))
    verdict = correlate(grant, effect)
    assert verdict.status == "candidate" and verdict.evidence_class == "PROVIDER_ASSERTED"


def test_two_systems_of_record_belong_to_domain_reconciliation() -> None:
    order = _obs("shop-1", "system_of_record", object_refs=(INVENTORY,))
    charge = _obs("pay-1", "system_of_record", object_refs=(INVENTORY,))
    verdict = correlate(order, charge)
    assert verdict.status == "no_rule"
    assert verdict.reason == "system_of_record_pairs_belong_to_domain_reconciliation"


def test_unregistered_pair_never_falls_back_to_timing() -> None:
    a = _obs("bot-1", "agent_runtime")
    b = _obs("bot-2", "agent_runtime")
    assert correlate(a, b).status == "no_rule"


def test_same_observation_and_bad_window_rejected() -> None:
    a = _obs("x", "agent_runtime")
    b = _obs("x", "system_of_record")
    assert correlate(a, b).reason == "same_observation"
    with pytest.raises(ValueError):
        correlate(a, _obs("y", "system_of_record"), time_window=timedelta(hours=2))


def test_observation_validation() -> None:
    with pytest.raises(ValueError):
        _obs("x", "agent_runtime", at=datetime(2026, 11, 14))  # naive
    with pytest.raises(ValueError):
        _obs("x", "agent_runtime", actor_refs=("no-namespace",))
    with pytest.raises(ValueError):
        _obs("x", "vendor_magic")


# --- modularity: a new vendor is streams + mapping, no join code ------------


def test_new_vendor_joins_through_existing_rules() -> None:
    """A vendor this module has never heard of joins through role rules alone."""
    token = _token()
    spend_grant = _obs("limit-1", "authority_issuer", family="some_spend_platform", correlation_tokens=(token,))
    agent_task = _obs("task-1", "agent_runtime", family="some_agent_runtime", correlation_tokens=(token,))
    verdict = correlate(spend_grant, agent_task, token_verifier=VERIFY)
    assert verdict.status == "linked"
