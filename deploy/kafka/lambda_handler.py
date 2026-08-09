#!/usr/bin/env python3
"""
Aether Kafka Topic Provisioner — AWS Lambda handler.

Thin adapter over deploy/kafka/topic_provisioner.py for the provisioning
Lambda created by modules/kafka_topic_provisioner. The Lambda is invoked once
by ``aws_lambda_invocation`` after the MSK cluster exists, with an input JSON
carrying the bootstrap broker list:

    {"bootstrap_servers": "b-1.host:9098,b-2.host:9098",
     "partitions": 3, "replication_factor": 3}

The handler surfaces provisioning failures as a raised error so
``aws_lambda_invocation``'s apply fails loudly — a topic silently not created
is exactly the failure mode the MSK auto.create.topics.enable=false posture
exists to prevent, so the deploy must stop rather than run against a half-wired
event bus.

This file sits at the root of the deploy/kafka directory, which is the
``archive_file`` source for the Lambda zip, so the handler is importable as
``lambda_handler.handler`` and the provisioner module it imports is co-located.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# The release pipeline packages kafka-python + transitive deps into a deps/
# sibling of this file (see README "Packaging (Lambda archive)"). The Lambda
# runtime does NOT add a nested deps/ directory to sys.path on its own, so the
# handler prepends it BEFORE importing the provisioner, which imports kafka at
# module load. When deps/ is absent (local pytest in a venv that already has
# kafka-python), the insert is a harmless no-op and imports resolve from the
# existing sys.path.
def _prepend_deps_to_syspath(handler_dir: Path) -> Path | None:
    """Insert a deps/ sibling of the handler into sys.path if it exists.

    Returns the deps directory when inserted, else None. Kept as a named
    function so the bootstrap is unit-testable without reloading this module.
    """
    deps = Path(handler_dir) / "deps"
    if deps.is_dir():
        sys.path.insert(0, str(deps))
        return deps
    return None


_DEPS_DIR = _prepend_deps_to_syspath(Path(__file__).resolve().parent)

from topic_provisioner import (
    DEFAULT_PARTITIONS,
    DEFAULT_REPLICATION_FACTOR,
    TopicProvisioningError,
    create_topics,
    load_topic_registry,
)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001 - Lambda signature
    """Create the declared topics, returning a summary for the apply log."""
    try:
        payload = event or {}
        if isinstance(payload, str):
            payload = json.loads(payload)

        bootstrap_servers = (
            payload.get("bootstrap_servers")
            or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
        )
        partitions = int(payload.get("partitions", DEFAULT_PARTITIONS))
        replication_factor = int(payload.get("replication_factor", DEFAULT_REPLICATION_FACTOR))
        topics_file = payload.get("topics_file") or os.getenv("KAFKA_TOPICS_FILE")

        topics = load_topic_registry(topics_file)
        result = create_topics(
            bootstrap_servers=bootstrap_servers,
            topics=topics,
            partitions=partitions,
            replication_factor=replication_factor,
            dry_run=bool(payload.get("dry_run", False)),
        )
        return {"ok": True, "declared": len(topics), **result}
    except (TopicProvisioningError, ValueError, json.JSONDecodeError) as exc:
        # Raised so aws_lambda_invocation's apply fails loudly rather than
        # acknowledging a provisioned-but-half-wired event bus.
        raise RuntimeError(f"kafka topic provisioning failed: {exc}") from exc
