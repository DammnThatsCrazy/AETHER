---
title: Local Development Operations
slug: ops-local-development
section: operations
visibility: I
audience: [dev-junior, dev-senior, ops]
status: experimental
since_version: "0.1.0"
---

# Local Development Operations

## Overview

This guide covers operational procedures for running Aether locally,
including service dependencies, database setup, and common debugging
workflows.

## Service Dependencies

| Service | Port | Required |
|---|---|---|
| Backend API | 8000 | Yes |
| PostgreSQL | 5432 | Yes |
| Redis | 6379 | Yes |
| Frontend (Aether) | 3000 | Optional |
| Frontend (Kyber) | 3001 | Optional |

## Starting the Stack

```bash
docker-compose up -d     # Infrastructure services
make dev                  # Application services
```

## Database Operations

```bash
# Run migrations
python scripts/run_migrations.py

# Reset local database
docker-compose down -v
docker-compose up -d
python scripts/run_migrations.py
```

## Common Issues

| Issue | Resolution |
|---|---|
| Port conflict | Check for running services: `lsof -i :PORT` |
| Migration failure | Reset database and re-run migrations |
| npm ci failure | Delete `node_modules` and retry |
