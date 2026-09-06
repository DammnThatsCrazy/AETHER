"""Reconciled Control Plane — §9.1/§9.2/§19 source-authority engine tests (Phase 3).

Covers the Phase-3 source-authority repositories (rule + equivalence-key
create/get/list/delete with CP-11 tenant-or-global scoping and cross-tenant
privacy) and the engine verbs over them:

* ``apply_precedence`` — §9.1 precedence resolution: first-in-precedence wins,
  most-specific property rule wins, validity windows respected, exact-duplicate
  rule ambiguity raises, conflicts surface as ``resolved: False`` (never
  fabricated away).
* ``equivalence_group`` — §9.2 semantic-equivalence grouping: equal normalized
  ``key_components`` group; unknown normalization rules and same-scope key
  ambiguity raise; an unconfigured domain yields singletons + an unmatched
  flag instead of invented equivalence (§19 — transport idempotency is not
  semantic deduplication). Grouping preserves source evidence untouched.
* Flag-OFF parity: both modules import and are callable while every RCP flag
  is OFF.

No live database is touched: the module-local ``_reset_authority_stores``
fixture empties the source-authority stores before/after every test, and the
module-local ``_authority_db_free`` fixture pins the repository ``get_pool``
import to None.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.managed_integrations import flags
from services.managed_integrations.contracts import (
    ObservationEquivalenceKeyView,
    SourceAuthorityRuleView,
)
from services.managed_integrations.source_authority import (
    apply_precedence,
    equivalence_group,
)
from services.managed_integrations.source_authority_repository import (
    get_observation_equivalence_key_repository,
    get_source_authority_rule_repository,
    reset_source_authority_stores,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENV_1 = "env-1"

# Wide margins so rule-window assertions never depend on the machine clock.
PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset_authority_stores() -> None:
    """Empty the source-authority in-memory stores before and after each test."""
    reset_source_authority_stores()
    yield
    reset_source_authority_stores()


@pytest.fixture
def _authority_db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``get_pool`` to None on the source-authority repository module so
    repo reads/writes always hit the in-memory stores (mirrors the executor /
    change-set-flow db-free fixtures)."""

    async def _no_pool():
        return None

    monkeypatch.setattr(
        "services.managed_integrations.source_authority_repository.get_pool",
        _no_pool,
    )


def _rule(**overrides) -> SourceAuthorityRuleView:
    kwargs = {
        "rule_id": "rule-1",
        "domain": "order",
        "property_path": "order.lifecycle_state",
        "source_precedence": ["shopify", "sdk"],
    }
    kwargs.update(overrides)
    return SourceAuthorityRuleView(**kwargs)


def _key(**overrides) -> ObservationEquivalenceKeyView:
    kwargs = {
        "key_id": "key-1",
        "domain": "payments",
        "candidate_types": ["payment_settled", "payment_succeeded"],
        "key_components": ["transaction_ref"],
    }
    kwargs.update(overrides)
    return ObservationEquivalenceKeyView(**kwargs)


# ── §9.1 rule repository ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_create_then_scoped_get_round_trips(_authority_db_free) -> None:
    repo = get_source_authority_rule_repository()
    created = await repo.create(_rule(tenant_id=TENANT_A, environment_id=ENV_1, policy_ref="pol-1"))
    assert created["rule_id"] == "rule-1"
    assert created["domain"] == "order"
    assert created["source_precedence"] == ["shopify", "sdk"]
    assert created["tenant_id"] == TENANT_A
    assert created["created_at"]  # DB-default-equivalent stamp always present

    row = await repo.get(rule_id="rule-1", tenant_id=TENANT_A)
    assert row is not None
    assert row["policy_ref"] == "pol-1"
    assert row["environment_id"] == ENV_1


@pytest.mark.asyncio
async def test_rule_create_requires_non_empty_source_precedence(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    with pytest.raises(ValueError, match="§9.1"):
        await repo.create(_rule(source_precedence=[]))


@pytest.mark.asyncio
async def test_rule_get_sees_global_rows_for_any_tenant(_authority_db_free) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(_rule())  # tenant_id NULL = global Olympus rule
    assert await repo.get(rule_id="rule-1", tenant_id=TENANT_A) is not None
    assert await repo.get(rule_id="rule-1", tenant_id=TENANT_B) is not None
    assert await repo.get(rule_id="rule-1") is not None  # Olympus read


@pytest.mark.asyncio
async def test_rule_get_refuses_cross_tenant_private_rows(_authority_db_free) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(_rule(tenant_id=TENANT_A))
    # Tenant B and the global (Olympus) read must never see tenant A's rule.
    assert await repo.get(rule_id="rule-1", tenant_id=TENANT_B) is None
    assert await repo.get(rule_id="rule-1") is None


@pytest.mark.asyncio
async def test_rule_list_scopes_tenant_reads_to_tenant_plus_global(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(_rule(rule_id="global-rule"))
    await repo.create(_rule(rule_id="tenant-a-rule", tenant_id=TENANT_A))
    await repo.create(_rule(rule_id="tenant-b-rule", tenant_id=TENANT_B))

    ids_for_a = {r["rule_id"] for r in await repo.list(tenant_id=TENANT_A)}
    assert ids_for_a == {"global-rule", "tenant-a-rule"}
    # A tenant read never leaks another tenant's private rule.
    assert "tenant-b-rule" not in ids_for_a

    global_ids = {r["rule_id"] for r in await repo.list()}
    assert global_ids == {"global-rule"}

    order_ids = {r["rule_id"] for r in await repo.list(domain="order", tenant_id=TENANT_A)}
    assert order_ids == ids_for_a
    assert await repo.list(domain="payments", tenant_id=TENANT_A) == []


@pytest.mark.asyncio
async def test_rule_list_ordering_is_stable_created_at_desc_rule_id_asc(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    for rule_id in ("rule-c", "rule-a", "rule-b"):
        await repo.create(_rule(rule_id=rule_id, domain="order"))

    rows = await repo.list(domain="order")
    again = await repo.list(domain="order")
    # Stable across calls, newest created_at first; equal timestamps fall back
    # to ascending rule_id (SQL ORDER BY created_at DESC, rule_id ASC parity).
    assert [r["rule_id"] for r in rows] == [r["rule_id"] for r in again]
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps, reverse=True)
    for left, right in zip(rows, rows[1:]):
        if left["created_at"] == right["created_at"]:
            assert left["rule_id"] < right["rule_id"]


@pytest.mark.asyncio
async def test_rule_delete_is_scoped_and_reports_whether_deleted(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(_rule(rule_id="global-rule"))
    await repo.create(_rule(rule_id="tenant-a-rule", tenant_id=TENANT_A))
    await repo.create(_rule(rule_id="tenant-b-rule", tenant_id=TENANT_B))

    # A tenant can delete its own private rule but never a global one.
    assert await repo.delete(rule_id="tenant-a-rule", tenant_id=TENANT_A) is True
    assert await repo.get(rule_id="tenant-a-rule", tenant_id=TENANT_A) is None
    assert await repo.delete(rule_id="global-rule", tenant_id=TENANT_A) is False
    # Nor another tenant's rule.
    assert await repo.delete(rule_id="tenant-b-rule", tenant_id=TENANT_A) is False
    assert await repo.get(rule_id="tenant-b-rule", tenant_id=TENANT_B) is not None

    # The global (Olympus) scope deletes global rows only.
    assert await repo.delete(rule_id="tenant-b-rule") is False
    assert await repo.delete(rule_id="global-rule") is True
    assert await repo.get(rule_id="global-rule") is None
    # Deleting a missing rule reports False.
    assert await repo.delete(rule_id="no-such-rule", tenant_id=TENANT_A) is False


# ── §9.2 equivalence-key repository ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_key_create_get_list_delete_round_trip(_authority_db_free) -> None:
    repo = get_observation_equivalence_key_repository()
    created = await repo.create(
        _key(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            normalization_rules=["trim", "lower"],
            semantic_dedupe_policy="keep_first",
            window="30s",
        )
    )
    assert created["key_components"] == ["transaction_ref"]
    assert created["normalization_rules"] == ["trim", "lower"]

    row = await repo.get(key_id="key-1", tenant_id=TENANT_A)
    assert row is not None
    assert row["semantic_dedupe_policy"] == "keep_first"
    assert row["window"] == "30s"

    # CP-11: private keys are invisible cross-tenant and to the global read.
    assert await repo.get(key_id="key-1", tenant_id=TENANT_B) is None
    assert await repo.get(key_id="key-1") is None

    rows = await repo.list(domain="payments", tenant_id=TENANT_A)
    assert [r["key_id"] for r in rows] == ["key-1"]
    assert await repo.list(domain="order", tenant_id=TENANT_A) == []
    assert await repo.list() == []  # global read sees no tenant rows

    assert await repo.delete(key_id="key-1", tenant_id=TENANT_A) is True
    assert await repo.delete(key_id="key-1", tenant_id=TENANT_A) is False
    assert await repo.list(domain="payments", tenant_id=TENANT_A) == []


@pytest.mark.asyncio
async def test_key_without_normalization_rules_round_trips_as_none(
    _authority_db_free,
) -> None:
    repo = get_observation_equivalence_key_repository()
    await repo.create(_key(tenant_id=TENANT_A))
    row = await repo.get(key_id="key-1", tenant_id=TENANT_A)
    assert row is not None
    assert row["normalization_rules"] is None


# ── §9.1 apply_precedence ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_precedence_first_in_precedence_wins_conflict(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(
        _rule(
            rule_id="order-lifecycle",
            domain="order",
            property_path="order.lifecycle_state",
            source_precedence=["stripe", "shopify"],
            conflict_strategy="authoritative_source",
        )
    )
    result = await apply_precedence(
        [
            {"source": "shopify", "value": "processing"},
            {"source": "stripe", "value": "paid"},
            {"source": "sdk", "value": "active"},
        ],
        domain="order",
        property_path="order.lifecycle_state",
    )
    # The resolved shape carries no "resolved" key — only the unresolved shape
    # reports {"resolved": False, "conflict": True} (§9.1 two-shape contract).
    assert "resolved" not in result
    assert result["resolved_value"] == "paid"
    assert result["resolved_source"] == "stripe"
    assert result["rule_id"] == "order-lifecycle"
    assert result["conflict_strategy"] == "authoritative_source"
    # Precedence-ordered, then remaining observed sources in first-seen order.
    assert result["sources_considered"] == ["stripe", "shopify", "sdk"]


@pytest.mark.asyncio
async def test_apply_precedence_most_specific_property_rule_wins(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(
        _rule(
            rule_id="order-broad",
            domain="order",
            property_path="order",
            source_precedence=["shopify"],
        )
    )
    await repo.create(
        _rule(
            rule_id="order-lifecycle",
            domain="order",
            property_path="order.lifecycle_state",
            source_precedence=["sdk"],
        )
    )
    result = await apply_precedence(
        [
            {"source": "shopify", "value": "fulfilled"},
            {"source": "sdk", "value": "checkout_completed"},
        ],
        domain="order",
        property_path="order.lifecycle_state",
    )
    # The rule for "order.lifecycle_state" beats the "order" prefix rule.
    assert result["rule_id"] == "order-lifecycle"
    assert result["resolved_value"] == "checkout_completed"
    assert result["resolved_source"] == "sdk"

    # For the broader "order" property the broad rule applies (longest match).
    broad = await apply_precedence(
        [{"source": "shopify", "value": "fulfilled"}],
        domain="order",
        property_path="order",
    )
    assert broad["rule_id"] == "order-broad"
    assert broad["resolved_value"] == "fulfilled"


@pytest.mark.asyncio
async def test_apply_precedence_tenant_rule_shadows_global_only_for_that_tenant(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(
        _rule(
            rule_id="global-broad",
            domain="order",
            property_path="order.lifecycle_state",
            source_precedence=["shopify"],
        )
    )
    await repo.create(
        _rule(
            rule_id="tenant-a-specific",
            domain="order",
            property_path="order.lifecycle_state.capture",
            source_precedence=["stripe"],
            tenant_id=TENANT_A,
        )
    )
    observations = [
        {"source": "shopify", "value": "captured"},
        {"source": "stripe", "value": "settled"},
    ]
    for_a = await apply_precedence(
        observations,
        domain="order",
        property_path="order.lifecycle_state.capture",
        tenant_id=TENANT_A,
    )
    assert for_a["rule_id"] == "tenant-a-specific"
    assert for_a["resolved_source"] == "stripe"

    # Tenant B never sees tenant A's rule: the global rule applies.
    for_b = await apply_precedence(
        observations,
        domain="order",
        property_path="order.lifecycle_state.capture",
        tenant_id=TENANT_B,
    )
    assert for_b["rule_id"] == "global-broad"
    assert for_b["resolved_source"] == "shopify"


@pytest.mark.asyncio
async def test_apply_precedence_newest_observed_at_wins_within_source(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(
        _rule(
            domain="order",
            property_path="order.lifecycle_state",
            source_precedence=["sdk"],
        )
    )
    result = await apply_precedence(
        [
            {"source": "sdk", "value": "processing", "observed_at": "2026-09-06T09:00:00Z"},
            {"source": "sdk", "value": "completed", "observed_at": "2026-09-06T10:00:00Z"},
        ],
        domain="order",
        property_path="order.lifecycle_state",
    )
    assert result["resolved_value"] == "completed"
    assert result["resolved_source"] == "sdk"


@pytest.mark.asyncio
async def test_apply_precedence_expired_rule_not_applied(_authority_db_free) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(
        _rule(
            valid_from=datetime(2000, 1, 1, tzinfo=timezone.utc),
            valid_to=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
    )
    result = await apply_precedence(
        [{"source": "shopify", "value": "fulfilled"}],
        domain="order",
        property_path="order.lifecycle_state",
    )
    assert result["resolved"] is False
    assert result["conflict"] is True
    assert "§9.1" in result["reason"]


@pytest.mark.asyncio
async def test_apply_precedence_not_yet_valid_rule_not_applied(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(
        _rule(
            valid_from=datetime(2099, 1, 1, tzinfo=timezone.utc),
            valid_to=FAR_FUTURE,
        )
    )
    result = await apply_precedence(
        [{"source": "shopify", "value": "fulfilled"}],
        domain="order",
        property_path="order.lifecycle_state",
    )
    assert result["resolved"] is False
    assert result["conflict"] is True


@pytest.mark.asyncio
async def test_apply_precedence_no_rule_surfaces_conflict_not_resolution(
    _authority_db_free,
) -> None:
    result = await apply_precedence(
        [{"source": "shopify", "value": "fulfilled"}],
        domain="order",
        property_path="order.lifecycle_state",
    )
    assert result == {
        "resolved": False,
        "conflict": True,
        "reason": (
            "no applicable §9.1 source-authority rule for domain='order' "
            "property_path='order.lifecycle_state'"
        ),
    }


@pytest.mark.asyncio
async def test_apply_precedence_rule_without_overlapping_source_unresolved(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(
        _rule(
            rule_id="stripe-rule",
            domain="order",
            property_path="order.lifecycle_state",
            source_precedence=["stripe"],
        )
    )
    result = await apply_precedence(
        [{"source": "shopify", "value": "fulfilled"}],
        domain="order",
        property_path="order.lifecycle_state",
    )
    assert result["resolved"] is False
    assert result["conflict"] is True
    assert "stripe" in result["reason"]
    assert "shopify" in result["reason"]


@pytest.mark.asyncio
async def test_apply_precedence_duplicate_exact_rule_raises_ambiguity(
    _authority_db_free,
) -> None:
    repo = get_source_authority_rule_repository()
    await repo.create(_rule(rule_id="rule-dup-1"))
    await repo.create(_rule(rule_id="rule-dup-2", source_precedence=["stripe"]))
    with pytest.raises(ValueError, match="§9.1") as exc:
        await apply_precedence(
            [{"source": "shopify", "value": "fulfilled"}],
            domain="order",
            property_path="order.lifecycle_state",
        )
    assert "rule-dup-1" in str(exc.value)
    assert "rule-dup-2" in str(exc.value)


@pytest.mark.asyncio
async def test_apply_precedence_malformed_observation_raises(
    _authority_db_free,
) -> None:
    with pytest.raises(ValueError, match="§9.1"):
        await apply_precedence(
            [{"value": "orphaned"}],  # no "source"
            domain="order",
            property_path="order.lifecycle_state",
        )
    with pytest.raises(ValueError, match="§9.1"):
        await apply_precedence(
            [{"source": "shopify"}],  # no "value"
            domain="order",
            property_path="order.lifecycle_state",
        )


# ── §9.2 equivalence_group ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_equivalence_group_groups_equal_components_and_preserves_evidence(
    _authority_db_free,
) -> None:
    repo = get_observation_equivalence_key_repository()
    await repo.create(_key(key_components=["transaction_ref"]))
    first = {
        "source": "stripe",
        "key_components": {"transaction_ref": "txn-42"},
        "payload": {"amount_cents": 1000},
    }
    second = {
        "source": "shopify",
        "key_components": {"transaction_ref": "txn-42"},
        "payload": {"amount_cents": 1000},
    }
    other = {
        "source": "sdk",
        "key_components": {"transaction_ref": "txn-43"},
    }
    result = await equivalence_group([first, second, other], domain="payments")
    assert result["unmatched_domain"] is False
    assert result["warning"] is None
    assert result["groups"] == [[first, second], [other]]
    # Original observation dicts are preserved untouched — evidence intact.
    assert result["groups"][0][0] is first
    assert first["payload"] == {"amount_cents": 1000}


@pytest.mark.asyncio
async def test_equivalence_group_normalization_lower_and_trim_in_listed_order(
    _authority_db_free,
) -> None:
    repo = get_observation_equivalence_key_repository()
    await repo.create(_key(normalization_rules=["trim", "lower"]))
    result = await equivalence_group(
        [
            {"source": "stripe", "key_components": {"transaction_ref": "  TXN-42 "}},
            {"source": "shopify", "key_components": {"transaction_ref": "txn-42"}},
            {"source": "sdk", "key_components": {"transaction_ref": "TXN-99"}},
        ],
        domain="payments",
    )
    assert len(result["groups"]) == 2
    assert len(result["groups"][0]) == 2  # trimmed+lowered txn-42 == txn-42
    assert len(result["groups"][1]) == 1


@pytest.mark.asyncio
async def test_equivalence_group_component_presence_is_meaningful(
    _authority_db_free,
) -> None:
    repo = get_observation_equivalence_key_repository()
    await repo.create(_key(key_components=["transaction_ref"]))
    # An observation that never carried the component is not equivalent to one
    # whose component value is None — and two observations that both lack it
    # are not equivalent to each other either (missing evidence never
    # fabricates a match, §19).
    result = await equivalence_group(
        [
            {"source": "stripe", "key_components": {}},
            {"source": "shopify", "key_components": {"transaction_ref": None}},
            {"source": "sdk", "key_components": {}},
        ],
        domain="payments",
    )
    assert len(result["groups"]) == 3


@pytest.mark.asyncio
async def test_equivalence_group_unknown_normalization_rule_raises(
    _authority_db_free,
) -> None:
    repo = get_observation_equivalence_key_repository()
    await repo.create(_key(normalization_rules=["lower", "uppercase"]))
    with pytest.raises(ValueError, match="§9.2"):
        await equivalence_group(
            [{"source": "stripe", "key_components": {"transaction_ref": "a"}}],
            domain="payments",
        )


@pytest.mark.asyncio
async def test_equivalence_group_no_key_row_yields_singletons_and_unmatched_flag(
    _authority_db_free,
) -> None:
    first = {"source": "stripe", "key_components": {"transaction_ref": "txn-42"}}
    second = {"source": "shopify", "key_components": {"transaction_ref": "txn-42"}}
    result = await equivalence_group([first, second], domain="payments")
    assert result["unmatched_domain"] is True
    assert result["warning"] is not None
    assert "§19" in result["warning"]
    # Without a governing key the engine never invents equivalence (§19):
    # equal key_components are still grouped alone, evidence preserved.
    assert result["groups"] == [[first], [second]]


@pytest.mark.asyncio
async def test_equivalence_group_tenant_key_scoping_never_leaks(
    _authority_db_free,
) -> None:
    repo = get_observation_equivalence_key_repository()
    # Tenant A's private key defines equivalence on "internal_ref" only.
    await repo.create(
        _key(key_id="tenant-a-key", key_components=["internal_ref"], tenant_id=TENANT_A)
    )
    # Global key for everyone else defines equivalence on "external_id".
    await repo.create(_key(key_id="global-key", key_components=["external_id"]))
    a_obs_1 = {"source": "stripe", "key_components": {"internal_ref": "i-1"}}
    a_obs_2 = {"source": "shopify", "key_components": {"internal_ref": "i-1"}}
    for_a = await equivalence_group([a_obs_1, a_obs_2], domain="payments", tenant_id=TENANT_A)
    assert for_a["unmatched_domain"] is False
    assert for_a["groups"] == [[a_obs_1, a_obs_2]]

    # Tenant B uses the global key; tenant A's private key never leaks — the
    # equal internal_refs cannot group under B's external_id key.
    for_b = await equivalence_group([a_obs_1, a_obs_2], domain="payments", tenant_id=TENANT_B)
    assert for_b["groups"] == [[a_obs_1], [a_obs_2]]


@pytest.mark.asyncio
async def test_equivalence_group_same_scope_duplicate_keys_raise_ambiguity(
    _authority_db_free,
) -> None:
    repo = get_observation_equivalence_key_repository()
    await repo.create(_key(key_id="global-key-a"))
    await repo.create(_key(key_id="global-key-b"))
    with pytest.raises(ValueError, match="§9.2") as exc:
        await equivalence_group(
            [{"source": "stripe", "key_components": {"transaction_ref": "x"}}],
            domain="payments",
        )
    assert "global-key-a" in str(exc.value)
    assert "global-key-b" in str(exc.value)


@pytest.mark.asyncio
async def test_equivalence_group_key_with_no_components_raises(
    _authority_db_free,
) -> None:
    repo = get_observation_equivalence_key_repository()
    await repo.create(_key(key_components=[]))
    with pytest.raises(ValueError, match="§9.2"):
        await equivalence_group(
            [{"source": "stripe", "key_components": {"transaction_ref": "x"}}],
            domain="payments",
        )


@pytest.mark.asyncio
async def test_equivalence_group_missing_key_components_raises(
    _authority_db_free,
) -> None:
    repo = get_observation_equivalence_key_repository()
    await repo.create(_key())
    with pytest.raises(ValueError, match="§9.2"):
        await equivalence_group(
            [{"source": "stripe"}],  # no key_components mapping
            domain="payments",
        )


# ── flag-OFF parity ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_source_authority_modules_import_and_run_with_flags_off() -> None:
    # Every RCP flag defaults OFF, yet the engine verbs are importable and
    # callable — an explicit caller may invoke them; OFF only means nothing
    # *automatically* triggers the plane (same parity as the Phase-0/1 lanes).
    assert flags.enabled() is False
    from services.managed_integrations.source_authority import (
        apply_precedence as _apply,
        equivalence_group as _group,
    )
    from services.managed_integrations.source_authority_repository import (
        reset_source_authority_stores as _reset,
    )

    assert callable(_apply)
    assert callable(_group)
    assert callable(_reset)
