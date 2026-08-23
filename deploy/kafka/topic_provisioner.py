#!/usr/bin/env python3
"""
Aether Kafka Topic Provisioner (provisioning-ready definition)

Creates, idempotently, exactly the set of Kafka topics Aether declares in its
declarative topic registry. The registry's canonical source is the
``Topic`` enum in ``Backend Architecture/aether-backend/shared/events/events.py``;
the machine-readable copy this script reads lives beside it at
``deploy/kafka/topics.json`` and is verified against the enum by
``deploy/kafka/tests/test_topics_registry_sync.py``.

WHY THIS EXISTS
  modules/msk provisions the MSK cluster with ``auto.create.topics.enable=false``
  (see modules/msk/main.tf). A topic that is never created therefore does not
  exist: the first producer to publish to it fails with
  UNKNOWN_TOPIC_OR_PARTITION instead of the broker materialising it on demand.
  Aether runs 240+ declared topics, so the broker's self-provisioning must be
  replaced by an explicit, declarative provisioning step.

WHEN THIS RUNS
  As an AWS Lambda invoked once by modules/kafka_topic_provisioner
  (``aws_lambda_invocation``) after the MSK cluster exists. It may also be run
  by hand as a CLI for an operator or an ECS init job:

      python topic_provisioner.py \
        --bootstrap-servers "b-1.host:9098,b-2.host:9098" \
        --partitions 3 --replication-factor 3 --dry-run

  Configuration precedence: explicit CLI flag > environment variable >
  built-in default. The Lambda handler passes the same environment in.

RUNTIME DEPENDENCY
  kafka-python (the ``kafka`` package) is required for the AdminClient. It is
  the same library ``scripts/validate_infra.py`` already uses for its Kafka
  connectivity check, so the deploy toolchain already carries it. The Lambda
  packaging must bundle it (see deploy/kafka/requirements.txt); the
  provisioning module's ``archive_file`` hashes whatever is present in the
  deploy/kafka directory at build time.

IDEMPOTENCY
  ``create_topics`` is a no-op for topics that already exist. Re-running after a
  partial failure converges on the full declared set. Deleting a topic is
  explicitly out of scope: provisioning only ever adds the declared topics, it
  never removes what a deployment already has.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from kafka import KafkaAdminClient
    from kafka.admin import NewTopic
    from kafka.errors import TopicAlreadyExistsError
    KAFKA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when kafka-python is absent
    KafkaAdminClient = None  # type: ignore[misc, assignment]
    NewTopic = None  # type: ignore[misc, assignment]
    TopicAlreadyExistsError = None  # type: ignore[misc, assignment]
    KAFKA_AVAILABLE = False

# The registry copy provisioned against. Repo-root-relative so the script runs
# from a checkout or from inside the Lambda zip that embeds it.
_TOPICS_FILE_ENV = "KAFKA_TOPICS_FILE"
_TOPICS_FILE = os.getenv(_TOPICS_FILE_ENV, str(Path(__file__).resolve().parent / "topics.json"))

_BOOTSTRAP_ENV = "KAFKA_BOOTSTRAP_SERVERS"
_PARTITIONS_ENV = "KAFKA_TOPIC_PARTITIONS"
_REPLICATION_ENV = "KAFKA_TOPIC_REPLICATION_FACTOR"
_TIMEOUT_ENV = "KAFKA_TOPIC_CREATE_TIMEOUT_MS"

DEFAULT_PARTITIONS = 3
DEFAULT_REPLICATION_FACTOR = 3
DEFAULT_TIMEOUT_MS = 30_000

# Module-level printer so tests can capture output by monkeypatching it; a
# ``print=print`` default parameter would bind the builtin at def time and be
# immune to monkeypatch.
_print = print


class TopicProvisioningError(RuntimeError):
    """A topic could not be created and the run is not fully converged."""


def load_topic_registry(path: str | Path | None = None) -> list[str]:
    """Read the declarative topic list from the registry JSON.

    Accepts either the envelope document produced by the generator
    (``{"topics": [...]}``) or a bare JSON array, so a hand-written list of the
    same shape also works. Raises if the registry is absent or unreadable —
    provisioning must never silently create zero topics from a bad path.
    """
    resolved = Path(path or _TOPICS_FILE)
    if not resolved.exists():
        raise TopicProvisioningError(
            f"topic registry not found at {resolved}. Set {_TOPICS_FILE_ENV} or "
            "pass --topics-file to point at deploy/kafka/topics.json."
        )
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - malformed registry
        raise TopicProvisioningError(
            f"topic registry {resolved} is not valid JSON: {exc}"
        ) from exc

    if isinstance(data, list):
        topics = [str(t) for t in data]
    elif isinstance(data, dict) and isinstance(data.get("topics"), list):
        topics = [str(t) for t in data["topics"]]
    else:
        raise TopicProvisioningError(
            f"topic registry {resolved} has an unknown shape: expected a JSON "
            "array or an object with a 'topics' list."
        )

    seen: set[str] = set()
    ordered: list[str] = []
    for topic in topics:
        if not topic:
            continue
        if topic not in seen:
            seen.add(topic)
            ordered.append(topic)
    return ordered


def _client(bootstrap_servers: str, timeout_ms: int) -> Any:
    if not KAFKA_AVAILABLE:
        raise TopicProvisioningError(
            "kafka-python is not installed; pip install kafka-python>=2.0.2 "
            "(see deploy/kafka/requirements.txt) to run the topic provisioner."
        )
    if not bootstrap_servers:
        raise TopicProvisioningError(
            f"{_BOOTSTRAP_ENV} is unset. Refusing to guess a broker address: "
            "creating topics against the wrong cluster is worse than creating none."
        )
    return KafkaAdminClient(
        bootstrap_servers=bootstrap_servers,
        request_timeout_ms=timeout_ms,
    )


def create_topics(
    bootstrap_servers: str,
    topics: list[str],
    partitions: int = DEFAULT_PARTITIONS,
    replication_factor: int = DEFAULT_REPLICATION_FACTOR,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Create every declared topic that does not already exist.

    Returns ``{"created": [...], "already_existed": [...]}``. In ``dry_run``
    mode nothing is created and every topic is reported in ``created`` as what
    WOULD be created, so the plan is inspectable without touching a broker.
    """
    if not topics:
        raise TopicProvisioningError("declared topic list is empty; refusing to provision nothing")
    if partitions < 1:
        raise TopicProvisioningError(f"partitions must be >= 1, got {partitions}")
    if replication_factor < 1:
        raise TopicProvisioningError(f"replication_factor must be >= 1, got {replication_factor}")

    if dry_run:
        _print(f"[dry-run] would create {len(topics)} topics on {bootstrap_servers}")
        for topic in topics:
            _print(f"[dry-run]   {topic} (partitions={partitions}, replication={replication_factor})")
        return {"created": list(topics), "already_existed": []}

    admin = _client(bootstrap_servers, timeout_ms)
    try:
        existing = set(admin.list_topics())
    finally:
        admin.close()

    to_create = [t for t in topics if t not in existing]
    already = [t for t in topics if t in existing]

    if not to_create:
        _print(f"All {len(topics)} declared topics already exist; nothing to do.")
        return {"created": [], "already_existed": already}

    admin = _client(bootstrap_servers, timeout_ms)
    try:
        admin.create_topics(
            [
                NewTopic(name=t, num_partitions=partitions, replication_factor=replication_factor)
                for t in to_create
            ],
            timeout_ms=timeout_ms,
            validate_only=False,
        )
    except TopicAlreadyExistsError:
        # A concurrent provisioner won the race for one of ours; converge
        # anyway — the remaining creates still happened, and the next run is a
        # no-op.
        _print("Some topics already existed by the time we created them (race); converging.")
    finally:
        admin.close()

    _print(f"Created {len(to_create)} topic(s); {len(already)} already existed.")
    return {"created": to_create, "already_existed": already}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - operator typo
        raise TopicProvisioningError(f"{name} must be an integer, got {raw!r}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="topic_provisioner",
        description="Idempotently create Aether's declared Kafka topics.",
    )
    parser.add_argument("--bootstrap-servers", default=os.getenv(_BOOTSTRAP_ENV, ""),
                        help=f"Kafka bootstrap broker list (or {_BOOTSTRAP_ENV})")
    parser.add_argument("--topics-file", default=_TOPICS_FILE,
                        help=f"JSON topic registry (default {_TOPICS_FILE})")
    parser.add_argument("--partitions", type=int, default=_int_env(_PARTITIONS_ENV, DEFAULT_PARTITIONS))
    parser.add_argument("--replication-factor", type=int,
                        default=_int_env(_REPLICATION_ENV, DEFAULT_REPLICATION_FACTOR))
    parser.add_argument("--timeout-ms", type=int, default=_int_env(_TIMEOUT_ENV, DEFAULT_TIMEOUT_MS))
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be created without contacting a broker")
    args = parser.parse_args(argv)

    topics = load_topic_registry(args.topics_file)
    result = create_topics(
        bootstrap_servers=args.bootstrap_servers,
        topics=topics,
        partitions=args.partitions,
        replication_factor=args.replication_factor,
        timeout_ms=args.timeout_ms,
        dry_run=args.dry_run,
    )
    if not args.dry_run and not result["created"]:
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TopicProvisioningError as exc:
        _print(f"topic provisioning failed: {exc}", file=sys.stderr)
        sys.exit(1)
