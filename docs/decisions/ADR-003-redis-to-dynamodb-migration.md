---
title: "ADR-003: Cache Backend Migration — Redis to DynamoDB On-Demand"
slug: decisions/adr-003-redis-to-dynamodb
section: reference
visibility: I
audience: [architect, dev-senior, ops]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
toc_depth: 2
---

# ADR-003: Cache Backend Migration — Redis → DynamoDB On-Demand (E1)

**Status:** Accepted | **Date:** 2026-05-26

## Context

The original production cache backend was Redis (Elasticache). As part of the
E1 engineering milestone, the team evaluated cost, operational burden, and
scaling characteristics of the cache layer.

Redis Elasticache issues encountered:
- Minimum cluster cost ~$100/month even at low traffic.
- Requires VPC placement and dedicated subnet groups.
- Multi-AZ failover adds complexity for a stateless cache workload.

## Decision

Replace Redis with **DynamoDB On-Demand** as the production cache backend for:
- Rate-limit counters
- Quota tracking buckets
- Session tokens

DynamoDB On-Demand charges per read/write unit consumed — cost is zero at zero
traffic. No cluster management required. SDK-compatible with `boto3`.

**Local development:** The `AETHER_ENV=local` flag enables in-memory fallback
in `Backend Architecture/aether-backend/shared/cache.py`. No DynamoDB or Redis
dependency is required to run locally.

**Legacy rollback:** The `docker-compose --profile legacy` profile re-enables
Redis + standalone `ml-serving` for rollback to the pre-E1/E2 architecture.

## Consequences

**Positive:**
- Eliminates ~$100/month base cost at low traffic.
- No VPC cluster management.
- `AETHER_ENV=local` in-memory fallback makes local dev dependency-free.

**Negative:**
- DynamoDB read/write costs scale with traffic — may exceed Redis at very high
  throughput (>10M writes/day).
- Atomic increment semantics differ from Redis INCR — application code must use
  DynamoDB conditional expressions.
- LocalStack required for streaming-equivalent local dev (`--profile streaming`).

## Review Trigger

Re-evaluate if monthly DynamoDB costs exceed $200 at sustained traffic, or if
atomic counter semantics become a correctness bottleneck.
