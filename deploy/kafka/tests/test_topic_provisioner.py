"""Tests for deploy/kafka/topic_provisioner.py.

The provisioner is exercised against a fake KafkaAdminClient so the suite runs
without a broker or kafka-python installed. The real AdminClient path is the
same call sequence (list_topics -> create_topics), so the fake covers the
logic that can diverge from the provisioning contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import lambda_handler as lh
import topic_provisioner as tp

DECLARED_TOPICS = ["aether.sdk.events.raw", "aether.identity.resolved", "aether.ml.prediction"]
FAKE_BOOTSTRAP = "b-1.test:9098,b-2.test:9098"


def make_registry_file(tmp_path: Path, envelope: bool = True) -> Path:
    p = tmp_path / "topics.json"
    if envelope:
        p.write_text(json.dumps({
            "schema_version": 1,
            "source": "test",
            "generated_from_enum": True,
            "topic_count": len(DECLARED_TOPICS),
            "topics": DECLARED_TOPICS,
        }, indent=2), encoding="utf-8")
    else:
        p.write_text(json.dumps(DECLARED_TOPICS), encoding="utf-8")
    return p


class TopicAlreadyExists(Exception):
    """Stand-in for kafka.errors.TopicAlreadyExistsError."""


class FakeNewTopic(SimpleNamespace):
    def __init__(self, name, num_partitions, replication_factor):
        super().__init__(name=name, num_partitions=num_partitions,
                         replication_factor=replication_factor)


class FakeAdminClient:
    """In-memory KafkaAdminClient: pre-seeded topics, records creates.

    ``_seed`` and ``created`` are class attributes so the tests can read them
    without holding a reference to the instance the provisioner constructs
    internally.
    """

    _seed: set[str] = set()
    created: list[tuple[str, int, int]] = []

    def __init__(self, bootstrap_servers=None, request_timeout_ms=None):
        self.bootstrap_servers = bootstrap_servers
        self.topics = set(FakeAdminClient._seed)

    @classmethod
    def reset(cls, seed=()):
        cls._seed = set(seed)
        cls.created = []

    def list_topics(self):
        return dict.fromkeys(self.topics, None)

    def create_topics(self, new_topics, timeout_ms=None, validate_only=False):
        for topic in new_topics:
            if topic.name in self.topics:
                raise TopicAlreadyExists(topic.name)
            self.topics.add(topic.name)
            # Persist at the broker level: a real broker keeps a created topic
            # across client connections, so a second provisioner run in the same
            # test must observe it as existing.
            type(self)._seed.add(topic.name)
            type(self).created.append(
                (topic.name, topic.num_partitions, topic.replication_factor)
            )

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _patch_kafka(monkeypatch):
    FakeAdminClient.reset(seed=("aether.sdk.events.raw",))  # one pre-existing topic
    monkeypatch.setattr(tp, "KAFKA_AVAILABLE", True)
    monkeypatch.setattr(tp, "KafkaAdminClient", FakeAdminClient)
    monkeypatch.setattr(tp, "NewTopic", FakeNewTopic)
    monkeypatch.setattr(tp, "TopicAlreadyExistsError", TopicAlreadyExists)


def _capture(monkeypatch):
    lines = []

    def _print(*args, **kwargs):
        lines.append(" ".join(str(a) for a in args))

    monkeypatch.setattr(tp, "_print", _print)
    return lines


def test_load_topic_registry_envelope(tmp_path):
    p = make_registry_file(tmp_path, envelope=True)
    assert tp.load_topic_registry(p) == DECLARED_TOPICS


def test_load_topic_registry_bare_array(tmp_path):
    p = make_registry_file(tmp_path, envelope=False)
    assert tp.load_topic_registry(p) == DECLARED_TOPICS


def test_load_topic_registry_dedupes_and_drops_blanks(tmp_path):
    p = tmp_path / "reg.json"
    p.write_text(json.dumps(["a.b", "a.b", "", "a.c"]), encoding="utf-8")
    assert tp.load_topic_registry(p) == ["a.b", "a.c"]


def test_load_topic_registry_missing_raises():
    with pytest.raises(tp.TopicProvisioningError):
        tp.load_topic_registry("/nonexistent/topics.json")


def test_load_topic_registry_bad_shape_raises(tmp_path):
    p = tmp_path / "reg.json"
    p.write_text(json.dumps({"not_topics": []}), encoding="utf-8")
    with pytest.raises(tp.TopicProvisioningError):
        tp.load_topic_registry(p)


def test_dry_run_creates_nothing():
    result = tp.create_topics(FAKE_BOOTSTRAP, DECLARED_TOPICS, dry_run=True)
    assert set(result["created"]) == set(DECLARED_TOPICS)
    assert result["already_existed"] == []
    assert FakeAdminClient._seed == {"aether.sdk.events.raw"}  # untouched


def test_create_skips_existing_and_creates_rest():
    result = tp.create_topics(FAKE_BOOTSTRAP, DECLARED_TOPICS, partitions=3, replication_factor=3)
    # aether.sdk.events.raw pre-existed, so it is reported, not re-created.
    assert result["already_existed"] == ["aether.sdk.events.raw"]
    created_names = {name for name, _p, _r in FakeAdminClient.created}
    assert set(result["created"]) == set(DECLARED_TOPICS) - {"aether.sdk.events.raw"}
    assert created_names == set(result["created"])
    # Every created topic used the configured partition/replication.
    assert all(p == 3 and r == 3 for _n, p, r in FakeAdminClient.created)


def test_create_idempotent_second_run_is_noop():
    first = tp.create_topics(FAKE_BOOTSTRAP, DECLARED_TOPICS)
    created_first = len(first["created"])
    FakeAdminClient.created.clear()
    second = tp.create_topics(FAKE_BOOTSTRAP, DECLARED_TOPICS)
    assert second["created"] == []
    assert len(second["already_existed"]) == len(DECLARED_TOPICS)
    assert FakeAdminClient.created == []
    assert created_first == len(DECLARED_TOPICS) - 1  # one was pre-seeded


def test_create_empty_topic_list_refuses():
    with pytest.raises(tp.TopicProvisioningError):
        tp.create_topics(FAKE_BOOTSTRAP, [], dry_run=False)


def test_create_bad_partitions_rejects():
    with pytest.raises(tp.TopicProvisioningError):
        tp.create_topics(FAKE_BOOTSTRAP, DECLARED_TOPICS, partitions=0, dry_run=False)


def test_missing_kafka_library_raises(monkeypatch):
    monkeypatch.setattr(tp, "KAFKA_AVAILABLE", False)
    with pytest.raises(tp.TopicProvisioningError, match="kafka-python"):
        tp.create_topics(FAKE_BOOTSTRAP, DECLARED_TOPICS, dry_run=False)


def test_missing_bootstrap_refuses():
    with pytest.raises(tp.TopicProvisioningError, match="unset"):
        tp.create_topics("", DECLARED_TOPICS, dry_run=False)


def test_main_dry_run_cli(tmp_path, monkeypatch):
    p = make_registry_file(tmp_path)
    lines = _capture(monkeypatch)
    rc = tp.main(["--bootstrap-servers", FAKE_BOOTSTRAP, "--topics-file", str(p), "--dry-run"])
    assert rc == 0
    assert FakeAdminClient._seed == {"aether.sdk.events.raw"}  # nothing created
    assert any("would create" in line for line in lines)


def test_registry_file_present_in_package_dir():
    """The checked-in registry the Lambda archive ships actually exists."""
    p = Path(tp._TOPICS_FILE)
    assert p.exists(), f"expected registry at {p}"
    topics = tp.load_topic_registry(p)
    assert len(topics) >= 200  # the enum carries 240+ declared topics


# ---------------------------------------------------------------------------
# lambda_handler — the Lambda adapter wired to modules/kafka_topic_provisioner
# ---------------------------------------------------------------------------


def test_handler_creates_topics_and_returns_summary(tmp_path):
    """A normal invocation reports ok/declared/created/already_existed."""
    reg = make_registry_file(tmp_path)
    result = lh.handler(
        {"bootstrap_servers": FAKE_BOOTSTRAP, "topics_file": str(reg)},
        None,
    )
    assert result["ok"] is True
    assert result["declared"] == len(DECLARED_TOPICS)
    # aether.sdk.events.raw pre-exists (autouse fixture seeds it).
    assert set(result["created"]) == set(DECLARED_TOPICS) - {"aether.sdk.events.raw"}
    assert result["already_existed"] == ["aether.sdk.events.raw"]


def test_handler_falls_back_to_bootstrap_env(tmp_path, monkeypatch):
    """bootstrap_servers may come from KAFKA_BOOTSTRAP_SERVERS in the Lambda env."""
    reg = make_registry_file(tmp_path)
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", FAKE_BOOTSTRAP)
    result = lh.handler({"topics_file": str(reg)}, None)
    assert result["ok"] is True
    assert len(result["created"]) == len(DECLARED_TOPICS) - 1


def test_handler_provisioning_failure_raises(monkeypatch, tmp_path):
    """A provisioning error must surface as RuntimeError so the apply fails loudly."""
    reg = make_registry_file(tmp_path)
    monkeypatch.setattr(tp, "KAFKA_AVAILABLE", False)  # create_topics raises
    with pytest.raises(RuntimeError, match="kafka topic provisioning failed"):
        lh.handler({"bootstrap_servers": FAKE_BOOTSTRAP, "topics_file": str(reg)}, None)


def test_handler_bad_payload_json_raises(tmp_path):
    with pytest.raises(RuntimeError, match="kafka topic provisioning failed"):
        lh.handler("{not json", None)


def test_prepend_deps_to_syspath_inserts_when_present(tmp_path):
    """A deps/ sibling (pipeline-bundled) is prepended so kafka imports in Lambda."""
    deps = tmp_path / "deps"
    deps.mkdir()
    try:
        inserted = lh._prepend_deps_to_syspath(tmp_path)
        assert inserted == deps
        assert sys.path[0] == str(deps)
    finally:
        # Restore the interpreter path so other tests are unaffected.
        for entry in list(sys.path):
            if entry == str(deps):
                sys.path.remove(entry)


def test_prepend_deps_to_syspath_noop_when_absent(tmp_path):
    """No deps/ means no sys.path mutation (local pytest resolves via the venv)."""
    before = list(sys.path)
    assert lh._prepend_deps_to_syspath(tmp_path) is None
    assert sys.path == before
