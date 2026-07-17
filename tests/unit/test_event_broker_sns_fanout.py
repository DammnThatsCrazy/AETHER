"""Event producer SNS fanout selection (per-role consumer queues).

With per-role SNS-subscribed consumer queues (Terraform modules/sqs), a
producer that sends directly to its own SQS_QUEUE_URL would starve every other
consumer role. When SNS_TOPIC_ARN is set alongside the sns_sqs broker, the
producer must publish through the SNS fanout topic instead; without it, the
historical direct-SQS path is preserved.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

_BACKEND_PREFIXES = ("config", "services", "shared", "dependencies")


@contextmanager
def backend_on_path():
    """Import backend modules against a clean cache, then restore the parent's."""
    original_path = list(sys.path)
    saved: dict[str, object] = {}
    for prefix in _BACKEND_PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                saved[name] = sys.modules.pop(name)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original_path
        for prefix in _BACKEND_PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)
        sys.modules.update(saved)


_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/111122223333/AETHER-staging-events-identity-worker"
_TOPIC_ARN = "arn:aws:sns:us-east-1:111122223333:AETHER-staging-fanout"


def _connect_producer(monkeypatch, events, *, sns_topic_arn: str) -> tuple[object, MagicMock, MagicMock]:
    """Connect an EventProducer against mocked boto3 clients."""
    monkeypatch.setenv("EVENT_BROKER", "sns_sqs")
    monkeypatch.setenv("SQS_QUEUE_URL", _QUEUE_URL)
    if sns_topic_arn:
        monkeypatch.setenv("SNS_TOPIC_ARN", sns_topic_arn)
    else:
        monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)

    sqs_client = MagicMock(name="sqs_client")
    sns_client = MagicMock(name="sns_client")
    boto3_mock = MagicMock(name="boto3")
    boto3_mock.client.side_effect = lambda service: {"sqs": sqs_client, "sns": sns_client}[service]
    monkeypatch.setattr(events, "_boto3_events", boto3_mock)
    monkeypatch.setattr(events, "BOTO3_EVENTS_AVAILABLE", True)

    producer = events.EventProducer()
    asyncio.run(producer.connect())
    return producer, sqs_client, sns_client


def _make_event(events):
    return events.Event(
        topic=events.Topic.SDK_EVENTS_VALIDATED,
        tenant_id="tenant-1",
        source_service="test",
        payload={"k": "v"},
    )


def test_publish_uses_sns_fanout_when_topic_arn_set(monkeypatch):
    with backend_on_path():
        import shared.events.events as events

        producer, sqs_client, sns_client = _connect_producer(
            monkeypatch, events, sns_topic_arn=_TOPIC_ARN
        )
        event = _make_event(events)
        asyncio.run(producer.publish(event))

        assert sns_client.publish.call_count == 1
        kwargs = sns_client.publish.call_args.kwargs
        assert kwargs["TopicArn"] == _TOPIC_ARN
        assert events.Event.deserialize(kwargs["Message"]).event_id == event.event_id
        # Direct SQS sends would land in this process's own consumer queue
        # only — every other per-role queue would starve.
        sqs_client.send_message.assert_not_called()


def test_publish_falls_back_to_direct_sqs_without_topic_arn(monkeypatch):
    with backend_on_path():
        import shared.events.events as events

        producer, sqs_client, sns_client = _connect_producer(
            monkeypatch, events, sns_topic_arn=""
        )
        asyncio.run(producer.publish(_make_event(events)))

        assert sqs_client.send_message.call_count == 1
        assert sqs_client.send_message.call_args.kwargs["QueueUrl"] == _QUEUE_URL
        sns_client.publish.assert_not_called()


def test_close_clears_sns_client(monkeypatch):
    with backend_on_path():
        import shared.events.events as events

        producer, _, _ = _connect_producer(monkeypatch, events, sns_topic_arn=_TOPIC_ARN)
        asyncio.run(producer.close())
        assert producer._sns_client is None
