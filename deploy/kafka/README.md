# Aether — Kafka Topic Provisioning

Aether declares every event topic in the `Topic` enum at
`Backend Architecture/aether-backend/shared/events/events.py`. The MSK cluster
is provisioned with `auto.create.topics.enable=false` (see
`AWS Deployment/aether-aws/terraform/modules/msk/main.tf`), so **a topic that is
not explicitly created does not exist** — the broker will never materialise it
on first publish.

This directory is the provisioning init for the declared topic set.

## Pieces

| File | Purpose |
|---|---|
| `topics.json` | Machine-readable declarative registry, generated from the `Topic` enum. |
| `topic_provisioner.py` | Standalone, idempotent provisioner (kafka-python `KafkaAdminClient`). Runs as a CLI or is imported by the Lambda handler. |
| `lambda_handler.py` | AWS Lambda handler wrapper (zip-root importable as `lambda_handler.handler`). |
| `requirements.txt` | Runtime dependency for the Lambda packaging. |
| `tests/` | pytest suite: provisioner behaviour (fake AdminClient) + registry drift check against the `Topic` enum. |

## Canonical source of truth

The enum is the canonical registry; `topics.json` is a generated copy. The drift
test `deploy/kafka/tests/test_topics_registry_sync.py` fails if they ever
diverge, so provisioning cannot silently lag a newly added topic.

Regenerate the JSON after adding a topic:

```bash
source .venv/bin/activate
cd "Backend Architecture/aether-backend"
python - <<'PY'
import json
from shared.events.events import declared_topics
open("../../deploy/kafka/topics.json", "w").write(
    json.dumps({"schema_version": 1, "source": "shared.events.events::Topic",
                "generated_from_enum": True, "topic_count": len(declared_topics()),
                "topics": declared_topics()}, indent=2) + "\n")
PY
```

## Wiring

`AWS Deployment/aether-aws/terraform/modules/kafka_topic_provisioner` creates the
Lambda and invokes it once (via `aws_lambda_invocation`) after the MSK cluster
exists, passing the TLS bootstrap brokers. The Lambda is VPC-attached so it can
reach the cluster, and reads the same `topics.json` embedded in its archive.

Run by hand for an operator check or an ECS init job:

```bash
python deploy/kafka/topic_provisioner.py \
  --bootstrap-servers "b-1.host:9098,b-2.host:9098" \
  --partitions 3 --replication-factor 3 --dry-run
```

## Packaging (Lambda archive)

`modules/kafka_topic_provisioner` zips this directory with the archive provider
(`source_dir` walks up from the module to the repo root). The archive provider
only archives what is already on disk, so the release pipeline must prepare the
dependency bundle in-place before `terraform apply` — offline plans must never
need a network fetch:

```bash
cd deploy/kafka
pip install -r requirements.txt --target deps/ --upgrade
# deps/ now carries kafka-python + its transitive deps; certifi is bundled with
# the python3.12 Lambda runtime via boto3, and the MSK TLS endpoint uses the
# public Amazon CA it already trusts.
```

After this, `deploy/kafka/` contains `topic_provisioner.py`, `lambda_handler.py`,
`topics.json`, `deps/` — exactly the zip contents the handler imports.
`lambda_handler.py` prepends `deps/` to `sys.path` before importing the
provisioner (the Lambda runtime does not add a nested `deps/` directory on its
own), and `from topic_provisioner import ...` resolves in the zip root. The
`tests/` and `README.md` are excluded from the archive. Regenerating the zip is
a no-op for drift purposes because `aws_lambda_function.source_code_hash` tracks
`output_base64sha256`, which changes only when the archive content changes.

## Idempotency

`create_topics` only creates topics that do not already exist; re-runs converge
on the declared set and never delete anything. Deleting a topic is deliberately
out of scope.

## Environment contract

| Variable | Meaning | Default |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | Broker list to provision against | *(required)* |
| `KAFKA_TOPICS_FILE` | Path to the registry JSON | `deploy/kafka/topics.json` |
| `KAFKA_TOPIC_PARTITIONS` | Partitions per created topic | `3` |
| `KAFKA_TOPIC_REPLICATION_FACTOR` | Replication factor per topic | `3` |
| `KAFKA_TOPIC_CREATE_TIMEOUT_MS` | AdminClient request timeout | `30000` |
