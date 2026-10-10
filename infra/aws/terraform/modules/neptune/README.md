# AETHER Neptune Module

## Overview

This module provisions an Amazon Neptune graph database cluster for AETHER. Neptune stores relationship graphs such as user social connections, knowledge graphs, and recommendation engine data.

## VPC-Only Access

Neptune **cannot be accessed publicly**. There is no public endpoint.

All access must originate from within the VPC — specifically from ECS tasks running in the private subnets.

### Connecting from ECS tasks

1. Your ECS task's security group (`ecs_sg`) is already permitted inbound access on port `8182` by the Neptune security group.
2. Use the **cluster endpoint** (writer) for writes and the **reader endpoint** for read queries.
3. Endpoints are available from the root module's `neptune_endpoint` and `neptune_reader_endpoint` outputs, or via SSM / Secrets Manager if you store them there post-deploy.

### Connection example (Python, Gremlin)

```python
from gremlin_python.driver import client, serializer

cluster_endpoint = "your-cluster-endpoint.neptune.amazonaws.com"
port = 8182

gremlin_client = client.Client(
    f"wss://{cluster_endpoint}:{port}/gremlin",
    "g",
    message_serializer=serializer.GraphSONMessageSerializer(),
)
```

### IAM Authentication

IAM database authentication is **enabled**. When connecting from ECS:

1. Assign the ECS task role an inline policy granting `neptune-db:*` on the cluster ARN.
2. Sign the WebSocket connection request with AWS SigV4. The `requests-aws4auth` library handles this for Python.

## Ports

| Protocol | Port | Usage |
|----------|------|-------|
| HTTPS / WSS | 8182 | Gremlin (WebSocket), SPARQL, openCypher |

## Maintenance

- Automated backups: 7-day retention, taken in the `03:00–04:00` UTC window.
- Minor version upgrades are applied automatically.
- Deletion protection is enabled in production; disable it in Terraform before destroying.
