"""Reconciled Control Plane — §29 fleet upgrade controller engine (Phase 4).

This engine is the *planning half* of the §29 fleet upgrade controller:
release registry / artifact manifest / fleet version inventory / lifecycle /
compatibility matrix are upstream discovery authorities; here the controller
resolves one candidate release for one managed integration against the §28
tenant update channel + the §30 platform upgrade-behavior table + the §40
delivery rings, and persists a ``fleet_upgrade_plans`` row as the composed
plan (§29 upgrade planner). The remaining §29 components (rollback, upgrade
evidence) ride the Phase-2 governed executor and the §40 rollout engine's
delivery facts — this module never creates a rollout or executes anything.

Boundaries (never crossed):

* **Planner only.** ``plan_upgrade`` composes exactly one plan for one
  integration. Nothing here iterates the whole fleet, runs approvals, calls
  an executor, or creates a §40 rollout — ``rollout_ref`` is stamped later by
  the caller via the repository's ``mark_rollout`` when the plan is handed to
  the §40 engine.
* **Plans never execute.** A composed plan records eligibility + the
  execution path (automatic / review / action); §40 rings deliver tenant
  traffic only under tenant update policy + approvals, and execution rides
  the Phase-1/2 governed executor path (Phase-4 boundary). Flag-gated OFF:
  nothing auto-triggers on import or on any call.
* **``managed_stable`` is never uncontrolled ``latest`` (§29).** The
  pseudo-tag ``latest`` is rejected on *every* channel (``reject_latest``) —
  not only on ``managed_stable`` — because no channel auto-delivers a class
  its name does not promise.
* **No hidden promise about customer-controlled binaries (§30).** The
  platform-behavior table maps an integration kind onto a §30 key only where
  the kind name is defensible evidence; ``platform_behavior`` returns None for
  every kind without such evidence (never guessed), and the caller treats None
  as review — never automatic. Host-mediated behaviors resolve to the
  ``action`` path (surfaced for tenant/host action), never ``automatic``.

The §28/§29 channel semantics: a channel auto-delivers exactly the release
classes its name promises. ``pinned`` auto-delivers nothing; ``security_auto``
only security fixes; ``patch_auto`` security + patch; ``compatible_auto``
security + patch + compatible; ``managed_stable`` security + patch +
compatible + stable (the managed band). ``latest`` is a §29 pseudo-tag, not a
release class any channel delivers.

Remote adaptation (§28) — mapping / allowlists / consent / translation /
feature-flag / compatibility projection / source-authority metadata — and
manual migration (host APIs, entitlements, native capability, new processing
purpose) are distinct from the build-time automatic adaptation a plan may
represent (dependency bumps, config migration, codemod, manifest changes).
This engine only classifies who may act on an already-composed candidate;
nothing here performs remote or build-time adaptation itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from services.managed_integrations.contracts import (
    MANAGED_RELEASE_CHANNELS,
    PLATFORM_UPGRADE_BEHAVIORS,
    ROLLOUT_ARTIFACT_KINDS,
    ROLLOUT_RINGS,
    is_rollout_artifact_kind,
    is_rollout_ring,
)
from services.managed_integrations.fleet_controller_repository import (
    CANDIDATE_CLASSES,
    UNKNOWN_UPGRADE_BEHAVIOR,
    FleetUpdatePolicyRow,
    FleetUpgradePlanRow,
    get_fleet_update_policy_repository,
    get_fleet_upgrade_plan_repository,
    is_candidate_class,
    is_release_channel,
)

__all__ = [
    "CANDIDATE_CLASSES",
    "UNKNOWN_UPGRADE_BEHAVIOR",
    "FleetUpdatePolicyRow",
    "FleetUpgradePlanRow",
    "CHANNEL_ELIGIBLE_CLASSES",
    "reject_latest",
    "platform_behavior",
    "eligibility_for",
    "execution_path_for",
    "set_policy",
    "plan_upgrade",
]

# §29 candidate classes a channel may auto-deliver, per §28 channel. The
# channel names are §28/§29 vocabulary: a channel auto-delivers exactly the
# release classes its name promises. ``latest`` is absent from every row on
# purpose — it is never auto-deliverable on ANY channel (§29 warning; enforced
# for every channel, not only managed_stable). ``pinned`` auto-delivers
# nothing: a pinned tenant receives exactly the version they pinned.
# (``CANDIDATE_CLASSES`` / ``is_candidate_class`` are imported from the
# repository module — the single write path owns the storage vocabulary.)
CHANNEL_ELIGIBLE_CLASSES: dict[str, tuple[str, ...]] = {
    "pinned": (),
    "security_auto": ("security",),
    "patch_auto": ("security", "patch"),
    "compatible_auto": ("security", "patch", "compatible"),
    "managed_stable": ("security", "patch", "compatible", "stable"),
}

# Reason emitted by reject_latest for the pseudo-tag (dictated in §29 terms).
_LATEST_GUARD_REASON = (
    "managed_stable is not uncontrolled latest (§29): refusing pseudo-tag "
    "'latest'"
)

# Reasons for the non-automatic paths a fully eligible plan may still take.
_OPTIONAL_POLICY_REASON = (
    "optional policy (§30): review before Olympus-managed delivery"
)
_HOST_MEDIATED_REASON = (
    "host-mediated §30 behavior: surfaced for tenant/host action"
)

# §6 integration kind → §30 platform-upgrade-behavior key. Only rows the kind
# name evidences are present; every other kind resolves to None (→ review,
# never automatic — see platform_behavior). Rows deliberately absent:
#   * sdk_web — §30 discriminates ``web_managed_loader`` (Aether-managed
#     loader) from ``web_pinned_package`` (tenant site bundle). Whether a site
#     loads the SDK through the managed loader or ships the package pinned in
#     its own bundle is tenant build evidence the kind name does not carry —
#     mapping either direction would be a guess.
#   * sdk_react_native — same discrimination problem between
#     ``react_native_js_only`` and ``react_native_native_module`` (whether
#     native modules are linked is not evidenced by the kind).
#   * sdk_other — an unclassified SDK family has no §30 runtime key.
#   * connector_customer_hosted — §30's only connector row is the
#     Aether-hosted connector; the customer-controlled deployment has no table
#     row, and Olympus must never claim it can independently rewrite a
#     customer-controlled binary (§30).
#   * agent_harness / agent_connector — §30 has no agent-runtime row and the
#     kind alone does not evidence where the agent executes.
_KIND_TO_PLATFORM: dict[str, str] = {
    # §30 aether_hosted_connector: connector code running in the Aether
    # backend — fully managed (name evidence exact).
    "connector_aether_hosted": "aether_hosted_connector",
    # Ingestion transports whose pipelines execute in the Aether backend
    # (the backend ingests on the tenant's behalf) — fully managed.
    "api_ingress": "aether_backend_ingestion",
    "stream_ingress": "aether_backend_ingestion",
    "file_import": "aether_backend_ingestion",
    "webhook": "aether_backend_ingestion",
    "warehouse_sync": "aether_backend_ingestion",
    "external_dataset": "aether_backend_ingestion",
    "olympus_curated_feed": "aether_backend_ingestion",
    # §30 runtime_config_mapping: the provider-runtime connection is a
    # managed runtime/connection artifact Aether adjusts only within the
    # approved provider contract — remotely managed.
    "provider_runtime_connection": "runtime_config_mapping",
    # Server-side SDKs embedded in the tenant's own service code — the tenant
    # (or their build) ships the upgrade; repository_or_build.
    "sdk_node": "server_sdk",
    "sdk_python": "server_sdk",
    "sdk_rust": "server_sdk",
    # Desktop SDKs update through the host application's own updater/build
    # pipeline; iOS/Android native SDKs ship inside host app releases.
    "sdk_desktop": "desktop_sdk",
    "sdk_ios": "ios_native_sdk",
    "sdk_android": "android_native_sdk",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _policy_id() -> str:
    return f"rcfpol_{uuid.uuid4().hex[:16]}"


def _plan_id() -> str:
    return f"rcfplan_{uuid.uuid4().hex[:16]}"


# ── pure policy helpers ──────────────────────────────────────────────────────


def reject_latest(candidate_class: str, candidate_ref: str) -> Optional[str]:
    """Return the §29 refusal reason when a candidate is the ``latest`` tag.

    None for a real candidate. The guard fires when the *class* is
    ``latest`` or the *ref* lower-cases to ``latest`` — the pseudo-tag is
    refused on every channel; ``managed_stable`` is not uncontrolled
    ``latest`` (§29).
    """
    if candidate_class == "latest" or str(candidate_ref).lower() == "latest":
        return _LATEST_GUARD_REASON
    return None


def platform_behavior(integration_kind: str) -> Optional[str]:
    """Map a §6 integration kind onto its §30 platform-upgrade-behavior key.

    Returns None for kinds the §30 table does not evidence (see the mapping
    comments above) — never a guess. A caller treats None as *review*: an
    upgrade is never automatic without a §30 row behind it. The returned
    *key* (e.g. ``ios_native_sdk``) resolves to the normalized behavior token
    through ``PLATFORM_UPGRADE_BEHAVIORS`` (e.g. ``host_release``).
    """
    return _KIND_TO_PLATFORM.get(integration_kind)


def _behavior_token_for(integration_kind: str) -> Optional[str]:
    """§30 behavior *token* for an integration kind (None when unmapped).

    Two layers: ``platform_behavior`` maps the kind onto its §30 platform
    key, and the §30 table (``PLATFORM_UPGRADE_BEHAVIORS``) declares the
    normalized token for that key. A plan row stores the token — never the
    key — so the ``behavior`` column stays on the ``is_upgrade_behavior``
    vocabulary.
    """
    key = _KIND_TO_PLATFORM.get(integration_kind)
    if key is None:
        return None
    return PLATFORM_UPGRADE_BEHAVIORS.get(key)


def eligibility_for(channel: str, candidate_class: str) -> bool:
    """Channel auto-deliverability of one candidate class (§28/§29).

    ``pinned`` delivers nothing; each managed channel delivers exactly the
    classes its name promises; ``latest`` is eligible on no channel.
    """
    if not is_release_channel(channel):
        raise ValueError(
            f"unknown §28/§29 release channel {channel!r} — expected one of "
            f"{MANAGED_RELEASE_CHANNELS}"
        )
    return candidate_class in CHANNEL_ELIGIBLE_CLASSES[channel]


def execution_path_for(behavior: str) -> str:
    """§30 behavior → §29 execution path (automatic / review / action).

    * ``fully_managed`` / ``remotely_managed`` → ``automatic`` (Olympus-driven
      through the §40 rings; remotely_managed stays within the approved
      contract).
    * ``compatible_managed_artifact`` → ``review`` (optional policy — §30
      review before Olympus-managed delivery).
    * ``repository_or_build`` / ``host_updater_or_build`` /
      ``deployment_model_dependent`` / ``host_release`` → ``action`` (host
      mediated — surfaced for tenant/host action; no hidden promise that
      Olympus can rewrite a customer-controlled binary).
    * Anything else (including an unknown token) → ``review`` — fail closed,
      never automatic without a §30 row.
    """
    if behavior in ("fully_managed", "remotely_managed"):
        return "automatic"
    if behavior == "compatible_managed_artifact":
        return "review"
    if behavior in (
        "repository_or_build",
        "host_updater_or_build",
        "deployment_model_dependent",
        "host_release",
    ):
        return "action"
    return "review"


# ── §29 verbs ────────────────────────────────────────────────────────────────


async def set_policy(
    *,
    tenant_ref: str,
    environment_id: str,
    channel: str,
    max_ring: str = "100%",
    at: Optional[datetime] = None,
) -> dict:
    """Create-or-update the §28/§29 tenant update policy for one channel.

    The tenant operator sets the channel and the §40 ring ceiling (default
    ``100%`` on create). An existing policy for the same scope keeps its
    ``policy_id``/``created_at`` and only its ceiling is raised or lowered
    (``updated_at`` stamped) — engine-side read-modify-write; the repository
    itself stays a plain create/update store and its unique index is the
    one-policy-per-channel backstop (§29).
    """
    if not is_release_channel(channel):
        raise ValueError(
            f"unknown §28/§29 release channel {channel!r} — expected one of "
            f"{MANAGED_RELEASE_CHANNELS}"
        )
    if not is_rollout_ring(max_ring):
        raise ValueError(
            f"unknown §40 rollout ring {max_ring!r} — expected one of "
            f"{ROLLOUT_RINGS}"
        )
    at = at or _now()
    repo = get_fleet_update_policy_repository()
    existing = await repo.get(
        tenant_ref=tenant_ref,
        environment_id=environment_id,
        channel=channel,
    )
    if existing is None:
        return await repo.create(
            FleetUpdatePolicyRow(
                policy_id=_policy_id(),
                tenant_ref=tenant_ref,
                environment_id=environment_id,
                channel=channel,
                max_ring=max_ring,
                created_at=at,
                updated_at=at,
            )
        )
    updated = await repo.update_max_ring(
        tenant_ref=tenant_ref,
        environment_id=environment_id,
        channel=channel,
        max_ring=max_ring,
        at=at,
    )
    return updated if updated is not None else existing


async def plan_upgrade(
    *,
    tenant_ref: str,
    environment_id: str,
    integration_row: dict,
    candidate_ref: str,
    candidate_class: str,
    artifact_kind: str,
    channel: Optional[str] = None,
    at: Optional[datetime] = None,
    rollout_ref: Optional[str] = None,
) -> dict:
    """Compose and persist one §29 upgrade plan for one managed integration.

    ``integration_row`` is a managed-integration registration row
    (``ManagedIntegrationRepository`` shape); the engine reads
    ``integration_kind``, the integration ref (under its ``managed_integration_id``
    or ``managed_integration_ref`` name) and, when ``channel`` is omitted, the
    row's ``release_channel``. Rows may lack a release channel (the parameter
    exists exactly for that case) — with neither present the call fails closed
    with a ``ValueError`` rather than assuming a channel.

    The candidate is one release artifact (``candidate_ref``, e.g. a version
    or artifact ref — never the pseudo-tag ``latest``) of one §40 artifact
    kind, carrying one §29 candidate class. The decision is deterministic and
    recorded as human-readable ``eligibility_reasons`` (the failing gate, or
    an ``"eligible"`` entry when every gate passed):

    1. §30 behavior of the integration kind — an unknown-but-valid kind has no
       §30 row → eligible False, path ``review`` (never automatic without a
       §30 behavior).
    2. ``latest`` guard (class or ref) → eligible False, path ``review``.
    3. §29 tenant update policy for (tenant, env, channel) — absent policy →
       eligible False, path ``review`` (fail closed; an absent policy never
       auto-delivers).
    4. Policy ceiling ``olympus_internal`` → no tenant traffic is permitted →
       eligible False, path ``review``.
    5. Candidate class not auto-deliverable on the channel → eligible False,
       path ``review``.
    6. Eligible → path by §30 behavior: ``fully_managed``/``remotely_managed``
       → ``automatic``; ``compatible_managed_artifact`` → ``review`` (optional
       §30 policy); host-mediated behaviors → ``action`` (surfaced, never
       automatic). ``planned_ring`` carries the policy ceiling on
       automatic/review paths; host-mediated plans keep it None (Olympus does
       not ring-deliver what the host must ship).

    Nothing here approves, executes or rolls out — ``rollout_ref`` may be
    stamped later by the caller through ``mark_rollout`` when the plan is
    handed to the §40 rollout engine.
    """
    if not isinstance(integration_row, dict):
        raise ValueError("integration_row must be a dict (§29 plan input)")
    integration_ref = integration_row.get("managed_integration_ref") or (
        integration_row.get("managed_integration_id")
    )
    if not integration_ref:
        raise ValueError(
            "integration_row must carry managed_integration_id or "
            "managed_integration_ref (§29 plan input)"
        )
    kind = integration_row.get("integration_kind")
    if not kind:
        raise ValueError(
            "integration_row must carry integration_kind (§29 plan input)"
        )
    effective_channel = channel or integration_row.get("release_channel")
    if not effective_channel:
        raise ValueError(
            "a §28/§29 release channel is required (explicit channel "
            "parameter, or integration_row['release_channel'])"
        )
    if not is_release_channel(effective_channel):
        raise ValueError(
            f"unknown §28/§29 release channel {effective_channel!r} — "
            f"expected one of {MANAGED_RELEASE_CHANNELS}"
        )
    if not is_candidate_class(candidate_class):
        raise ValueError(
            f"unknown §29 candidate class {candidate_class!r} — expected one "
            f"of {CANDIDATE_CLASSES}"
        )
    if not is_rollout_artifact_kind(artifact_kind):
        raise ValueError(
            f"unknown §40 rollout artifact kind {artifact_kind!r} — expected "
            f"one of {ROLLOUT_ARTIFACT_KINDS}"
        )

    # §30 has two layers: the platform key the kind maps to (platform_behavior)
    # and the normalized behavior token that key declares (§30 table). The plan
    # row stores the TOKEN (is_upgrade_behavior vocabulary); a kind with no
    # defensible platform key has no token either.
    behavior_token = _behavior_token_for(kind)
    eligible = False
    path = "review"
    reasons: list[str] = []
    planned_ring: Optional[str] = None

    if behavior_token is None:
        reasons = [f"unknown §30 platform behavior for kind {kind}"]
    elif reject_latest(candidate_class, candidate_ref) is not None:
        reasons = [_LATEST_GUARD_REASON]
    else:
        policy_repo = get_fleet_update_policy_repository()
        policy = await policy_repo.get(
            tenant_ref=tenant_ref,
            environment_id=environment_id,
            channel=effective_channel,
        )
        if policy is None:
            reasons = [
                f"no §29 tenant update policy for channel {effective_channel}"
            ]
        elif policy["max_ring"] == "olympus_internal":
            reasons = ["tenant policy caps delivery at olympus_internal"]
        elif not eligibility_for(effective_channel, candidate_class):
            reasons = [
                f"candidate class {candidate_class!r} is not auto-deliverable "
                f"on channel {effective_channel!r} (§28/§29)"
            ]
        else:
            eligible = True
            path = execution_path_for(behavior_token)
            if path == "automatic":
                reasons = ["eligible"]
            elif path == "review":
                reasons = ["eligible", _OPTIONAL_POLICY_REASON]
            else:  # action — host mediated, never automatic
                reasons = ["eligible", _HOST_MEDIATED_REASON]
            if path in ("automatic", "review"):
                planned_ring = policy["max_ring"]

    plan_repo = get_fleet_upgrade_plan_repository()
    return await plan_repo.create(
        FleetUpgradePlanRow(
            plan_id=_plan_id(),
            tenant_ref=tenant_ref,
            environment_id=environment_id,
            managed_integration_ref=str(integration_ref),
            integration_kind=kind,
            artifact_kind=artifact_kind,
            candidate_ref=candidate_ref,
            candidate_class=candidate_class,
            channel=effective_channel,
            # A gate-1 review plan (no §30 row for the kind) records the honest
            # "unknown" sentinel — never a fabricated §30 token.
            behavior=behavior_token or UNKNOWN_UPGRADE_BEHAVIOR,
            eligible=eligible,
            execution_path=path,
            eligibility_reasons=reasons,
            planned_ring=planned_ring,
            rollout_ref=rollout_ref,
            created_at=at or _now(),
        )
    )
