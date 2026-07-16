#!/usr/bin/env python3
"""Validate production-shaped durable topology and canonical consumer ownership."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/integration/docker-compose.durable.yml"
REQUIRED_ROLES = {
    "api", "outbox-relay", "stream-worker", "identity-worker", "graph-writer",
    "measurement-worker", "materializer", "maintenance",
}


def validate() -> list[str]:
    errors: list[str] = []
    doc = yaml.safe_load(COMPOSE.read_text(encoding="utf-8")) or {}
    services = doc.get("services") or {}
    for dependency in ("postgres", "redis", "localstack"):
        if dependency not in services:
            errors.append(f"RUNTIME_MISSING_DURABLE_BACKEND:{dependency}")
    if not REQUIRED_ROLES <= set(services):
        errors.append(f"RUNTIME_MISSING_ROLES:{sorted(REQUIRED_ROLES - set(services))}")
    for role in REQUIRED_ROLES:
        env = services.get(role, {}).get("environment") or {}
        if env.get("AETHER_ROLE") != role:
            errors.append(f"RUNTIME_ROLE_MISMATCH:{role}")
    if services.get("api", {}).get("environment", {}).get("AETHER_ROLE") != "api":
        errors.append("RUNTIME_API_ATTACHES_WORKERS")
    source = (ROOT / "Backend Architecture/aether-backend/services/runtime/consumer_specs.py").read_text()
    names = [line.split('name="', 1)[1].split('"', 1)[0]
             for line in source.splitlines() if 'name="' in line]
    if len(names) != len(set(names)):
        errors.append("RUNTIME_DUPLICATE_CONSUMER_OWNER")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Runtime readiness FAILED:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print("Runtime readiness passed: durable backends, role topology, and consumer ownership agree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
