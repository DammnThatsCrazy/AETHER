"""The six Social Silver projectors are registered and own no canonical activity.

The Silver dispatcher fans a Bronze event out to an ordered projector list; the
``projector-ownership-registry.json`` contract mirrors that order and declares,
per projector, the table it owns and whether it may own canonical-activity
emission. The M3 social projectors are observation-only facts (``no_activity``):
they must be present in ``_ALL_PROJECTORS`` (the final six, matching the
registry order), route their six event types, and stay out of every
``ownedActivityEventTypes`` in the registry.
"""
from __future__ import annotations

import json
from pathlib import Path

# conftest.py has prepended the worktree backend path, so `services.silver`
# resolves to THIS checkout.
from services.silver.dispatcher import (  # noqa: E402
    _ALL_PROJECTORS,
    _TYPE_MAP,
    SilverDispatcher,
)

_SOCIAL_CLASS_NAMES = (
    "SocialIdentityProjector",
    "SocialConnectionProjector",
    "SocialInteractionProjector",
    "SocialContentProjector",
    "SocialCommunityMembershipProjector",
    "SocialMetricProjector",
)

# event type -> (projector class name, registry table, projector table const)
_SOCIAL_ROUTING = {
    "social_identity_observed": (
        "SocialIdentityProjector", "silver_social_identity_facts"),
    "social_connection_observed": (
        "SocialConnectionProjector", "silver_social_connection_facts"),
    "social_interaction_observed": (
        "SocialInteractionProjector", "silver_social_interaction_facts"),
    "social_content_observed": (
        "SocialContentProjector", "silver_social_content_facts"),
    "social_community_membership_observed": (
        "SocialCommunityMembershipProjector", "silver_social_community_facts"),
    "social_metric_observed": (
        "SocialMetricProjector", "silver_social_metric_facts"),
}

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY = json.loads(
    (
        _REPO_ROOT / "packages" / "shared" / "contracts"
        / "projector-ownership-registry.json"
    ).read_text(encoding="utf-8")
)


def _registry_names() -> list[str]:
    return [entry["name"] for entry in _REGISTRY["projectors"]]


# ── registration in the dispatcher ─────────────────────────────────────────


def test_social_projectors_present_in_all_projectors():
    names = [type(p).__name__ for p in _ALL_PROJECTORS]
    for cls_name in _SOCIAL_CLASS_NAMES:
        assert cls_name in names


def test_social_projectors_are_the_final_six_in_dispatcher_order():
    names = [type(p).__name__ for p in _ALL_PROJECTORS]
    assert names[-6:] == list(_SOCIAL_CLASS_NAMES)


def test_each_social_event_type_routes_to_exactly_one_projector():
    for event_type, (cls_name, _table) in _SOCIAL_ROUTING.items():
        assert event_type in _TYPE_MAP
        assert [type(p).__name__ for p in _TYPE_MAP[event_type]] == [cls_name]
        dispatcher = SilverDispatcher()
        assert dispatcher.handles(event_type)
        assert dispatcher.projectors_for(event_type) == [cls_name]


def test_social_types_are_not_dispatched_to_unrelated_projectors():
    # No comms/touchpoint/exposure/... projector claims a social event type.
    for event_type in _SOCIAL_ROUTING:
        names = {type(p).__name__ for p in _TYPE_MAP[event_type]}
        assert len(names) == 1


# ── ownership registry alignment ────────────────────────────────────────────


def test_registry_has_24_projectors_in_dispatcher_order():
    dispatcher_names = [type(p).__name__ for p in _ALL_PROJECTORS]
    assert len(dispatcher_names) == 24
    assert len(_REGISTRY["projectors"]) == 24
    assert _registry_names() == dispatcher_names


def test_each_social_registry_entry_declares_its_table_and_event_type():
    for event_type, (cls_name, table) in _SOCIAL_ROUTING.items():
        entry = next(e for e in _REGISTRY["projectors"] if e["name"] == cls_name)
        assert entry["table"] == table
        assert entry["eventTypes"] == [event_type]
        assert entry["unregisteredEventTypes"] == [event_type]
        assert entry["eventFamilies"] == []
        assert entry["ownedActivityEventTypes"] == []


def test_social_registry_entries_are_observation_only_no_activity_owners():
    for cls_name in _SOCIAL_CLASS_NAMES:
        entry = next(e for e in _REGISTRY["projectors"] if e["name"] == cls_name)
        assert entry["activityRole"] == "no_activity"
    # ... and no registry entry anywhere grants a social event type an activity.
    owned = [
        (e["name"], et)
        for e in _REGISTRY["projectors"]
        for et in e.get("ownedActivityEventTypes", [])
    ]
    social_types = set(_SOCIAL_ROUTING)
    assert all(et not in social_types for (_n, et) in owned)
