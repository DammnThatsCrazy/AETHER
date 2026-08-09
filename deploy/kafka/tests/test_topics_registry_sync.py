"""Drift check: deploy/kafka/topics.json must match the canonical Topic enum.

The enum in shared/events/events.py is the single source of truth for Aether's
Kafka topics. The provisioning init reads the generated JSON copy
(deploy/kafka/topics.json), so if the two diverge — a topic added to the enum
but never regenerated — provisioning silently provisions a stale set and every
new producer fails with UNKNOWN_TOPIC_OR_PARTITION against an
auto-create-disabled MSK cluster. This test fails that drift loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.events.events import declared_topics

_REGISTRY = Path(__file__).resolve().parent.parent / "topics.json"


def _load_registry() -> list[str]:
    doc = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return doc
    return list(doc.get("topics", []))


def test_registry_matches_enum_exactly():
    enum_topics = declared_topics()
    registry_topics = _load_registry()

    assert registry_topics == enum_topics, (
        "deploy/kafka/topics.json has drifted from shared.events.events.Topic. "
        "Regenerate it from the enum (see deploy/kafka/README.md) so provisioning "
        "creates exactly the declared topics."
    )


def test_registry_declares_nonempty_set():
    assert len(_load_registry()) >= 200  # 240+ declared today; guards a truncation


def test_registry_metadata_topic_count_matches():
    doc = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and "topic_count" in doc:
        assert doc["topic_count"] == len(doc.get("topics", []))
