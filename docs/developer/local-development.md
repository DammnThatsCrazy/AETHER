---
title: Local Development
slug: local-development
section: quickstart
visibility: P
audience: [dev-junior, dev-senior]
status: experimental
since_version: "0.1.0"
---

# Local Development

## Prerequisites

- Node.js 18+
- Python 3.11+
- Docker and Docker Compose
- Make

## Setup

```bash
git clone <repo-url>
cd aether
npm ci
pip install -e '.[dev]'
```

## Start Local Services

```bash
docker-compose up -d
```

This starts the local development stack including the backend API,
database, and message queue.

## Run the Frontend

```bash
cd frontend/aether
npm run dev
```

## Run Backend

```bash
cd "Backend Architecture/aether-backend"
python -m uvicorn main:app --reload
```

## Run Tests

```bash
make test          # Full test suite
npm test           # Frontend tests only
python -m pytest   # Backend tests only
```

## Useful Commands

| Command | Purpose |
|---|---|
| `make ci-check` | Full CI validation (canonical gate) |
| `make docs-fix` | Fix and regenerate docs |
| `make repo-doctor` | Consistency check |
| `npm run typecheck` | TypeScript type checking |

## See Also

- [DEVELOPMENT.md](../../DEVELOPMENT.md) for detailed development guide
- [CONTRIBUTING.md](../../CONTRIBUTING.md) for contribution requirements
