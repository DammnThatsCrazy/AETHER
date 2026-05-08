"""
Aether journey-service — multi-actor journey reconstruction.

Consumes `aether.sdk.events.validated` from Kafka, maintains live journey
state in Redis, persists journeys to Postgres, mirrors structure to Neptune,
and writes per-event sidecar rows to ClickHouse `event_extension` plus
state snapshots / exposures / agent reasoning to Iceberg on S3.

Streaming output is best-effort (sub-minute). The nightly ETL recomputes
canonical journeys + attribution and overwrites stream rows by `as_of`.
"""

__version__ = "0.1.0"
