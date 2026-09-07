"""Unit tests for the Phase-4 §29 fleet upgrade controller engine.

Exercises ``services.managed_integrations.fleet_controller`` (§28/§29 tenant
update-channel operationalization, §30 platform upgrade-behavior routing, §40
ring ceilings) over the module-local in-memory stores with ``get_pool`` pinned
to None — the same columnar path the engine uses without a live Postgres.

Coverage anchors (the §28-40 boundary contracts):

* Channel eligibility table exactness — a channel auto-delivers exactly the
  release classes its name promises (``pinned`` nothing; ``security_auto``
  security only; ``patch_auto`` security+patch; ``compatible_auto`` security+
  patch+compatible, excluding the stable/major line; ``managed_stable`` adds
  ``stable`` but never ``latest``).
* The §29 ``latest`` pseudo-tag guard fires on EVERY channel — for both a
  ``latest`` candidate class and a ``latest`` candidate ref.
* Fail-closed gates: no tenant policy → review; policy ceiling
  ``olympus_internal`` → review (no tenant traffic); class not deliverable on
  the channel → review.
* §40 cap honoring: an eligible plan carries the policy ``max_ring`` through
  to ``planned_ring``.
* §30 behavior routing: fully_managed → automatic; compatible_managed_artifact
  → review (optional §30 policy); host_release/others → action with the
  no-hidden-promise reason; a kind with no §30 row → review, never automatic.
* Integration-kind → §30 key mapping (ios/android native kinds → host_release)
  with the documented None fallback.
* set_policy create/update, plan row round-trip + mark_rollout, cross-tenant
  privacy (CP-08), and flag-OFF import parity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from services.managed_integrations.contracts import (
    MANAGED_RELEASE_CHANNELS,
    PLATFORM_UPGRADE_BEHAVIORS,
)
from services.managed_integrations.fleet_controller import (
    CHANNEL_ELIGIBLE_CLASSES,
    eligibility_for,
    execution_path_for,
    plan_upgrade,
    platform_behavior,
    reject_latest,
    set_policy,
)
from services.managed_integrations.fleet_controller_repository import (
    UNKNOWN_UPGRADE_BEHAVIOR,
    get_fleet_upgrade_plan_repository,
    reset_fleet_controller_stores,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENV_1 = "env-1"
ENV_2 = "env-2"
INTEGRATION = "mi-conn-1"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)

LATEST_GUARD_REASON = (
    "managed_stable is not uncontrolled latest (§29): refusing pseudo-tag "
    "'latest'"
)
HOST_MEDIATED_REASON = "host-mediated §30 behavior: surfaced for tenant/host action"


@pytest.fixture(autouse=True)
def _fleet_db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``get_pool`` to None and empty the fleet stores.

    Mirrors the sibling ``db_free`` fixtures: the in-memory path is the
    unit-test reference for the SQL path's tenancy WHERE clauses.
    """

    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr(
        "services.managed_integrations.fleet_controller_repository.get_pool",
        _no_pool,
    )
    reset_fleet_controller_stores()
    yield
    reset_fleet_controller_stores()


def _integration(**overrides: Any) -> dict:
    """One ``ManagedIntegrationRepository``-shaped registration row.

    The engine reads only the integration ref, ``integration_kind`` and
    ``release_channel`` (when no explicit channel is passed); the rest mirrors
    the registration row shape so tests exercise realistic rows.
    """
    base: dict[str, Any] = {
        "managed_integration_id": INTEGRATION,
        "tenant_id": TENANT_A,
        "environment_id": ENV_1,
        "integration_kind": "connector_aether_hosted",
        "source_ref": "connectors/checkout@1.4.0",
        "source_origin": "olympus",
        "source_owner": "olympus",
        "release_channel": "managed_stable",
        "health_state": "available",
        "lifecycle_state": "active",
        "desired_state_ref": "rcds_mi-conn-1",
        "observed_state_ref": "rcobs_mi-conn-1",
        "last_reconcile_result": "actionable_drift",
    }
    base.update(overrides)
    return base


async def _set_policy(
    *,
    channel: str = "managed_stable",
    max_ring: str = "100%",
    tenant_ref: str = TENANT_A,
    environment_id: str = ENV_1,
    at: datetime = NOW,
) -> dict:
    return await set_policy(
        tenant_ref=tenant_ref,
        environment_id=environment_id,
        channel=channel,
        max_ring=max_ring,
        at=at,
    )


async def _plan(
    integration_row: dict | None = None,
    *,
    candidate_class: str = "security",
    candidate_ref: str = "1.4.1",
    artifact_kind: str = "connector_release",
    channel: str | None = None,
    tenant_ref: str = TENANT_A,
    environment_id: str = ENV_1,
    at: datetime = NOW,
) -> dict:
    return await plan_upgrade(
        tenant_ref=tenant_ref,
        environment_id=environment_id,
        integration_row=integration_row or _integration(),
        candidate_ref=candidate_ref,
        candidate_class=candidate_class,
        artifact_kind=artifact_kind,
        channel=channel,
        at=at,
    )


# ── §28/§29 channel eligibility table exactness ──────────────────────────────


def test_channel_eligibility_table_is_exact_per_channel_name() -> None:
    # A channel auto-delivers exactly the release classes its name promises.
    assert eligibility_for("pinned", "security") is False
    for candidate_class in ("security", "patch", "compatible", "stable", "latest"):
        assert eligibility_for("pinned", candidate_class) is False
    assert eligibility_for("security_auto", "security") is True
    for candidate_class in ("patch", "compatible", "stable", "latest"):
        assert eligibility_for("security_auto", candidate_class) is False
    assert eligibility_for("patch_auto", "security") is True
    assert eligibility_for("patch_auto", "patch") is True
    for candidate_class in ("compatible", "stable", "latest"):
        assert eligibility_for("patch_auto", candidate_class) is False
    assert eligibility_for("compatible_auto", "compatible") is True
    # compatible_auto excludes the stable/major line and the latest tag.
    for candidate_class in ("stable", "latest"):
        assert eligibility_for("compatible_auto", candidate_class) is False


def test_managed_stable_includes_stable_but_never_latest() -> None:
    for candidate_class in ("security", "patch", "compatible", "stable"):
        assert eligibility_for("managed_stable", candidate_class) is True
    assert eligibility_for("managed_stable", "latest") is False
    # The §29 warning is enforced for every channel, not only managed_stable:
    # the pseudo-tag appears in no channel's auto-deliverable set.
    for allowed in CHANNEL_ELIGIBLE_CLASSES.values():
        assert "latest" not in allowed


def test_unknown_channel_raises_not_silently_coerced() -> None:
    with pytest.raises(ValueError, match="§28/§29"):
        eligibility_for("bleeding_edge", "security")
    with pytest.raises(ValueError, match="§28/§29"):
        eligibility_for("", "security")


# ── §29 latest pseudo-tag guard ──────────────────────────────────────────────


@pytest.mark.parametrize("channel", list(MANAGED_RELEASE_CHANNELS))
@pytest.mark.asyncio
async def test_latest_candidate_class_rejected_on_every_channel(channel: str) -> None:
    # Mapped kind (fully_managed) so the guard — not the §30 gate — decides.
    plan = await _plan(
        candidate_class="latest",
        candidate_ref="1.4.1",
        channel=channel,
        integration_row=_integration(release_channel=None),
    )
    assert plan["eligible"] is False
    assert plan["execution_path"] == "review"
    assert plan["eligibility_reasons"] == [LATEST_GUARD_REASON]
    assert plan["planned_ring"] is None


@pytest.mark.parametrize("channel", list(MANAGED_RELEASE_CHANNELS))
@pytest.mark.asyncio
async def test_latest_candidate_ref_rejected_on_every_channel(channel: str) -> None:
    # The pseudo-tag is refused on every channel whether it arrives as the
    # class or as the artifact ref ("latest" — and case-insensitively).
    for tag in ("latest", "LATEST"):
        plan = await _plan(
            candidate_class="stable",
            candidate_ref=tag,
            channel=channel,
            integration_row=_integration(release_channel=None),
        )
        assert plan["eligible"] is False
        assert plan["execution_path"] == "review"
        assert plan["eligibility_reasons"] == [LATEST_GUARD_REASON]


def test_reject_latest_pure_helper() -> None:
    assert reject_latest("latest", "1.4.1") == LATEST_GUARD_REASON
    assert reject_latest("stable", "latest") == LATEST_GUARD_REASON
    assert reject_latest("stable", "LATEST") == LATEST_GUARD_REASON
    assert reject_latest("stable", "1.4.1") is None
    assert reject_latest("security", "release/1.4.1") is None


# ── fail-closed gates ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_absent_tenant_policy_fails_closed_to_review() -> None:
    # No §29 tenant update policy row for (tenant-a, env-1, managed_stable):
    # an absent policy never auto-delivers.
    plan = await _plan()
    assert plan["eligible"] is False
    assert plan["execution_path"] == "review"
    assert plan["eligibility_reasons"] == [
        "no §29 tenant update policy for channel managed_stable"
    ]
    assert plan["planned_ring"] is None
    assert plan["behavior"] == "fully_managed"


@pytest.mark.asyncio
async def test_olympus_internal_policy_cap_permits_no_tenant_traffic() -> None:
    await _set_policy(max_ring="olympus_internal")
    plan = await _plan()
    assert plan["eligible"] is False
    assert plan["execution_path"] == "review"
    assert plan["eligibility_reasons"] == [
        "tenant policy caps delivery at olympus_internal"
    ]


@pytest.mark.asyncio
async def test_class_not_deliverable_on_channel_fails_closed() -> None:
    await _set_policy(channel="pinned")
    # pinned delivers nothing — even a security fix waits for the tenant's pin.
    plan = await _plan(channel="pinned")
    assert plan["eligible"] is False
    assert plan["execution_path"] == "review"
    assert plan["eligibility_reasons"] == [
        "candidate class 'security' is not auto-deliverable on channel "
        "'pinned' (§28/§29)"
    ]
    # security_auto delivers security only: a patch candidate is a review item.
    await _set_policy(channel="security_auto")
    plan = await _plan(candidate_class="patch", channel="security_auto")
    assert plan["eligible"] is False
    assert plan["execution_path"] == "review"
    assert "not auto-deliverable on channel 'security_auto'" in plan[
        "eligibility_reasons"
    ][0]


@pytest.mark.asyncio
async def test_unknown_kind_is_review_never_automatic() -> None:
    # sdk_web has no defensible §30 row (loader vs pinned-package evidence is
    # absent from the kind) — the plan fails closed with the honest
    # "unknown" behavior sentinel rather than a fabricated §30 token.
    await _set_policy()
    plan = await _plan(
        integration_row=_integration(
            managed_integration_id="mi-web-1",
            integration_kind="sdk_web",
        ),
        candidate_ref="web-sdk/2.0.0",
    )
    assert plan["eligible"] is False
    assert plan["execution_path"] == "review"
    assert plan["eligibility_reasons"] == [
        "unknown §30 platform behavior for kind sdk_web"
    ]
    assert plan["behavior"] == UNKNOWN_UPGRADE_BEHAVIOR
    assert plan["planned_ring"] is None


# ── §40 cap honoring ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_policy_max_ring_rides_through_to_planned_ring() -> None:
    await _set_policy(channel="patch_auto", max_ring="5%")
    plan = await _plan(candidate_class="patch", channel="patch_auto")
    assert plan["eligible"] is True
    assert plan["execution_path"] == "automatic"
    assert plan["eligibility_reasons"] == ["eligible"]
    assert plan["planned_ring"] == "5%"


# ── §30 behavior routing ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fully_managed_eligible_plan_is_automatic() -> None:
    await _set_policy()
    plan = await _plan()  # connector_aether_hosted -> fully_managed
    assert plan["behavior"] == "fully_managed"
    assert plan["eligible"] is True
    assert plan["execution_path"] == "automatic"
    assert plan["eligibility_reasons"] == ["eligible"]
    assert plan["planned_ring"] == "100%"


@pytest.mark.asyncio
async def test_host_release_plan_is_action_with_no_hidden_promise() -> None:
    # An iOS native SDK ships inside host app releases (§30 host_release):
    # the plan is eligible within policy but Olympus never ring-delivers a
    # customer-controlled binary — the action is surfaced for tenant/host.
    await _set_policy()
    plan = await _plan(
        integration_row=_integration(
            managed_integration_id="mi-ios-1",
            integration_kind="sdk_ios",
        ),
        candidate_ref="ios-sdk/3.2.0",
        artifact_kind="sdk_compatible_projection",
    )
    assert plan["behavior"] == "host_release"
    assert plan["eligible"] is True
    assert plan["execution_path"] == "action"
    assert plan["eligibility_reasons"] == ["eligible", HOST_MEDIATED_REASON]
    assert plan["planned_ring"] is None


def test_execution_path_for_behavior_routing() -> None:
    # fully_managed / remotely_managed -> automatic (Olympus-driven through
    # the §40 rings; remotely_managed stays within the approved contract).
    assert execution_path_for("fully_managed") == "automatic"
    assert execution_path_for("remotely_managed") == "automatic"
    # compatible_managed_artifact -> review (optional §30 policy before
    # Olympus-managed delivery).
    assert execution_path_for("compatible_managed_artifact") == "review"
    # Host-mediated behaviors -> action; never automatic.
    for behavior in (
        "repository_or_build",
        "host_updater_or_build",
        "deployment_model_dependent",
        "host_release",
    ):
        assert execution_path_for(behavior) == "action"
    # Unknown token -> review (fail closed — never automatic without a §30 row).
    assert execution_path_for("mystery_behavior") == "review"


# ── §6 kind -> §30 key mapping ───────────────────────────────────────────────


def test_native_sdk_kinds_map_to_host_release_behavior() -> None:
    # ios/android native kinds -> the §30 ios/android keys -> host_release
    # (the coordinator-pinned verification).
    assert platform_behavior("sdk_ios") == "ios_native_sdk"
    assert platform_behavior("sdk_android") == "android_native_sdk"
    assert PLATFORM_UPGRADE_BEHAVIORS["ios_native_sdk"] == "host_release"
    assert PLATFORM_UPGRADE_BEHAVIORS["android_native_sdk"] == "host_release"


def test_kind_to_platform_mapping_is_defensible_or_none() -> None:
    # Mapped where the kind name evidences exactly one §30 key...
    assert platform_behavior("connector_aether_hosted") == "aether_hosted_connector"
    assert platform_behavior("api_ingress") == "aether_backend_ingestion"
    assert platform_behavior("warehouse_sync") == "aether_backend_ingestion"
    assert platform_behavior("olympus_curated_feed") == "aether_backend_ingestion"
    assert platform_behavior("provider_runtime_connection") == "runtime_config_mapping"
    assert platform_behavior("sdk_node") == "server_sdk"
    assert platform_behavior("sdk_python") == "server_sdk"
    assert platform_behavior("sdk_desktop") == "desktop_sdk"
    # ...and None where the §30 discrimination is not evidenced by the kind
    # name (never guessed; the caller treats None as review).
    for unmapped in (
        "sdk_web",
        "sdk_react_native",
        "sdk_other",
        "connector_customer_hosted",
        "agent_harness",
        "agent_connector",
    ):
        assert platform_behavior(unmapped) is None


# ── set_policy create/update ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_policy_creates_with_default_100_percent_ring() -> None:
    created = await _set_policy()
    assert created["tenant_ref"] == TENANT_A
    assert created["environment_id"] == ENV_1
    assert created["channel"] == "managed_stable"
    assert created["max_ring"] == "100%"
    row = await set_policy(
        tenant_ref=TENANT_A,
        environment_id=ENV_1,
        channel="managed_stable",
        max_ring="100%",
    )
    # Same scope again: set_policy updates, never duplicates (§29 one per
    # channel) — policy_id stays stable across the update.
    assert row["policy_id"] == created["policy_id"]


@pytest.mark.asyncio
async def test_set_policy_updates_ring_and_stamps_updated_at() -> None:
    created = await _set_policy(at=NOW)
    later = NOW.replace(minute=5)
    updated = await _set_policy(max_ring="20%", at=later)
    assert updated["policy_id"] == created["policy_id"]
    assert updated["max_ring"] == "20%"
    assert datetime.fromisoformat(updated["updated_at"]) == later
    # created_at is untouched — the ceiling move is an update, not a re-create.
    assert datetime.fromisoformat(updated["created_at"]) == NOW


@pytest.mark.asyncio
async def test_set_policy_validates_channel_and_ring() -> None:
    with pytest.raises(ValueError, match="§28/§29"):
        await set_policy(
            tenant_ref=TENANT_A, environment_id=ENV_1, channel="nope", max_ring="5%"
        )
    with pytest.raises(ValueError, match="§40"):
        await set_policy(
            tenant_ref=TENANT_A,
            environment_id=ENV_1,
            channel="managed_stable",
            max_ring="55%",
        )


# ── plan row round-trip + mark_rollout ───────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_row_round_trip_and_mark_rollout() -> None:
    await _set_policy()
    plan = await _plan(candidate_ref="1.4.1", candidate_class="security")
    plan_repo = get_fleet_upgrade_plan_repository()
    row = await plan_repo.get(
        tenant_ref=TENANT_A, environment_id=ENV_1, plan_id=plan["plan_id"]
    )
    assert row is not None
    assert row == plan
    assert row["managed_integration_ref"] == INTEGRATION
    assert row["integration_kind"] == "connector_aether_hosted"
    assert row["artifact_kind"] == "connector_release"
    assert row["candidate_ref"] == "1.4.1"
    assert row["candidate_class"] == "security"
    assert row["channel"] == "managed_stable"
    assert row["behavior"] == "fully_managed"
    assert row["eligible"] is True
    assert row["execution_path"] == "automatic"
    assert row["eligibility_reasons"] == ["eligible"]
    assert row["planned_ring"] == "100%"
    assert row["rollout_ref"] is None

    # The caller hands the plan to the §40 rollout engine later: the stamp is
    # recorded as a delivery fact — the verdict itself never changes.
    stamped = await plan_repo.mark_rollout(
        tenant_ref=TENANT_A,
        environment_id=ENV_1,
        plan_id=plan["plan_id"],
        rollout_ref="rcroll_fleet_1",
    )
    assert stamped is not None
    assert stamped["rollout_ref"] == "rcroll_fleet_1"
    fetched = await plan_repo.get(
        tenant_ref=TENANT_A, environment_id=ENV_1, plan_id=plan["plan_id"]
    )
    assert fetched is not None
    assert fetched["rollout_ref"] == "rcroll_fleet_1"
    assert fetched["eligible"] is True


@pytest.mark.asyncio
async def test_plan_upgrade_uses_row_channel_or_explicit_channel() -> None:
    await _set_policy(channel="patch_auto", max_ring="5%")
    # Row carries no release_channel -> the explicit parameter decides.
    plan = await _plan(
        integration_row=_integration(release_channel=None),
        channel="patch_auto",
        candidate_class="patch",
    )
    assert plan["channel"] == "patch_auto"
    assert plan["eligible"] is True
    assert plan["planned_ring"] == "5%"
    # Row carries release_channel and no parameter is passed -> row decides.
    await _set_policy(channel="security_auto", max_ring="50%")
    plan = await _plan(
        integration_row=_integration(release_channel="security_auto"),
        candidate_class="security",
    )
    assert plan["channel"] == "security_auto"
    assert plan["planned_ring"] == "50%"
    # Neither present -> fail closed with a ValueError, never a silent
    # assumption of some default channel.
    with pytest.raises(ValueError, match="release channel is required"):
        await _plan(integration_row=_integration(release_channel=None))


@pytest.mark.asyncio
async def test_plan_upgrade_validates_its_vocabulary_inputs() -> None:
    await _set_policy()
    with pytest.raises(ValueError, match="§29 candidate class"):
        await _plan(candidate_class="major")
    with pytest.raises(ValueError, match="§40 rollout artifact kind"):
        await _plan(artifact_kind="source_tarball")
    with pytest.raises(ValueError, match="§28/§29 release channel"):
        await _plan(channel="unstable")
    with pytest.raises(ValueError, match="integration_row must carry"):
        await _plan(integration_row={"integration_kind": "sdk_web"})
    with pytest.raises(ValueError, match="integration_kind"):
        await _plan(integration_row=_integration(integration_kind=None))


# ── cross-tenant privacy (CP-08) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_a_plans_are_invisible_to_tenant_b() -> None:
    await _set_policy()
    plan = await _plan()
    plan_repo = get_fleet_upgrade_plan_repository()
    # A scoped get under tenant B (or tenant A / env 2) cannot see the row.
    assert (
        await plan_repo.get(
            tenant_ref=TENANT_B, environment_id=ENV_1, plan_id=plan["plan_id"]
        )
        is None
    )
    assert (
        await plan_repo.get(
            tenant_ref=TENANT_A, environment_id=ENV_2, plan_id=plan["plan_id"]
        )
        is None
    )
    assert await plan_repo.list_for_tenant(tenant_ref=TENANT_B) == []
    # A cross-tenant mark_rollout is a no-op too.
    assert (
        await plan_repo.mark_rollout(
            tenant_ref=TENANT_B,
            environment_id=ENV_1,
            plan_id=plan["plan_id"],
            rollout_ref="rcroll_fleet_9",
        )
        is None
    )


@pytest.mark.asyncio
async def test_tenant_policies_are_scoped_per_tenant_and_environment() -> None:
    await _set_policy(channel="managed_stable", max_ring="5%")
    # Tenant B can set its own (different) ceiling for the same channel.
    await _set_policy(
        tenant_ref=TENANT_B, environment_id=ENV_1, channel="managed_stable",
        max_ring="50%",
    )
    plan_a = await _plan()
    plan_b = await _plan(
        tenant_ref=TENANT_B,
        integration_row=_integration(managed_integration_id="mi-conn-b"),
    )
    assert plan_a["planned_ring"] == "5%"
    assert plan_b["planned_ring"] == "50%"


# ── flag-OFF import parity ───────────────────────────────────────────────────


def test_engine_imports_and_stays_inert_with_flags_off() -> None:
    from services.managed_integrations import flags
    from services.managed_integrations.fleet_controller import plan_upgrade

    assert flags.enabled() is False
    # Importing the engine composes nothing, executes nothing: the only verbs
    # are the pure helpers and explicit per-integration planning calls.
    assert callable(plan_upgrade)
    assert eligibility_for("managed_stable", "security") is True
    assert platform_behavior("sdk_web") is None
