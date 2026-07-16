from types import SimpleNamespace

from services.runtime.consumer_specs import CONSUMER_SPECS, consumer_specs_for_role


SETTINGS = SimpleNamespace()


def test_every_consumer_has_exactly_one_production_owner():
    assert len({spec.name for spec in CONSUMER_SPECS}) == len(CONSUMER_SPECS)
    assert all(spec.role != "api" and spec.group_id for spec in CONSUMER_SPECS)


def test_previously_empty_roles_own_required_consumers():
    for role in ("identity-worker", "graph-writer", "measurement-worker"):
        owned = consumer_specs_for_role(role, SETTINGS)
        assert owned
        assert all(spec.required and spec.role == role for spec in owned)


def test_api_owns_no_consumers_and_all_is_complete():
    assert consumer_specs_for_role("api", SETTINGS) == []
    assert consumer_specs_for_role("all", SETTINGS) == list(CONSUMER_SPECS)


def test_role_replicas_share_stable_groups_and_pipelines_are_separate():
    for role in {spec.role for spec in CONSUMER_SPECS}:
        first = consumer_specs_for_role(role, SETTINGS)
        second = consumer_specs_for_role(role, SETTINGS)
        assert [spec.group_id for spec in first] == [spec.group_id for spec in second]
    assert len({spec.group_id for spec in CONSUMER_SPECS}) == len(CONSUMER_SPECS)
