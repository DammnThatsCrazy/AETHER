# Contributing to Aether

## Development Setup

```bash
# Clone and install
git clone https://github.com/DammnThatsCrazy/Aether.git
cd Aether
pip install -e ".[dev,backend,ml]"

# Run tests
make test

# Start local development stack
docker compose up redis kafka postgres -d
export AETHER_ENV=local
make serve-backend
```

## Environment

Set `AETHER_ENV=local` for development. This enables in-memory fallbacks for all infrastructure (Redis, PostgreSQL, Neptune, Kafka). No external services are required for local development.

## Code Standards

- Python 3.9+
- Formatting: `ruff format .`
- Linting: `ruff check .`
- Type hints on all public functions
- Docstrings on all classes and public methods

## Testing

```bash
make test              # All tests
make test-security     # Extraction defense tests only
make test-ml           # ML model tests only
```

Tests must pass locally and in CI before merge.

## Branching

- `main` — production-ready code
- Feature branches — `feat/description`
- Bugfix branches — `fix/description`

## Commit Messages

Follow conventional commits:
- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation only
- `refactor:` code restructuring
- `test:` adding/updating tests

## Pull Requests

1. Create a branch from `main`
2. Make changes with tests
3. Run `make test` locally
4. Push and create PR
5. CI must pass before merge
6. Squash merge to `main`

## Architecture

See `docs/ARCHITECTURE.md` for system design. Key directories:

```
Backend Architecture/aether-backend/   Python FastAPI backend (31 services)
ML Models/aether-ml/                   ML training + serving
Agent Layer/                           Autonomous agent workers
security/                              Model extraction defense
packages/                              Web, iOS, Android, React Native SDKs
```

## Subsystem Documentation

| Subsystem | Doc |
|-----------|-----|
| Architecture | `docs/ARCHITECTURE.md` |
| API Endpoints | `docs/BACKEND-API.md` |
| Intelligence Graph | `docs/INTELLIGENCE-GRAPH.md` |
| Identity Resolution | `docs/IDENTITY-RESOLUTION.md` |
| Extraction Defense | `docs/MODEL-EXTRACTION-DEFENSE.md` |
| Operations | `docs/OPERATIONS-RUNBOOK.md` |
| Production Readiness | `docs/PRODUCTION-READINESS.md` |
| Secret Rotation | `docs/SECRET-ROTATION.md` |

## License

This project is **proprietary and confidential**. See `LICENSE` for details.
All contributions become property of Aether Platform under the same license terms.
By submitting a contribution, you confirm you have the right to do so and agree
to these terms.
