"""Tests for the Python SDK's batch-health parsing (Truth Kernel §2.8)."""

from aether_agentic.ingestion import BatchHealth, parse_batch_health


def test_parses_accepted_duplicate_rejected():
    health = parse_batch_health({"accepted": 3, "duplicate": 1, "rejected": 2})
    assert health.accepted == 3
    assert health.duplicate == 1
    assert health.rejected == 2


def test_normalizes_backend_plural_duplicates():
    health = parse_batch_health({"accepted": 5, "duplicates": 4})
    assert health.accepted == 5
    assert health.duplicate == 4
    assert health.rejected == 0


def test_passes_through_sdk_side_counters():
    health = parse_batch_health(
        {"accepted": 1},
        dropped_by_consent=2,
        queue_depth=7,
    )
    assert health.dropped_by_consent == 2
    assert health.queue_depth == 7


def test_missing_counters_default_to_zero():
    health = parse_batch_health({"batchId": "b1"})
    assert health == BatchHealth(0, 0, 0, 0, 0)


def test_none_body_is_safe():
    assert parse_batch_health(None, queue_depth=3).queue_depth == 3


def test_bool_is_not_treated_as_int_counter():
    # A stray boolean must not be read as a count of 1.
    health = parse_batch_health({"accepted": True})
    assert health.accepted == 0


def test_to_dict_shape():
    d = parse_batch_health({"accepted": 2, "rejected": 1}, queue_depth=4).to_dict()
    assert d == {
        "accepted": 2,
        "duplicate": 0,
        "rejected": 1,
        "dropped_by_consent": 0,
        "queue_depth": 4,
    }
