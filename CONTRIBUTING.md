# Contributing to Aether

## Development Setup

```bash
# Clone and install
git clone https://github.com/DammnThatsCrazy/Aether.git
cd Aether
pip install -e ".[dev,backend,ml]"

# Install Node workspace deps (shared, ui, web, react-native, kyber, aether)
npm ci

# Run tests
make test
npm test

# Start local infrastructure only (no application services)
docker compose up -d postgres redis kafka zookeeper clickhouse

# Start backend in dev mode
export AETHER_ENV=local
make serve-backend          # backend → http://localhost:8000
make serve-ml               # ML serving → http://localhost:8080

# Optional: start the Kyber operator control surface
cd apps/kyber && npm run dev   # → http://localhost:5174

# Optional: start the Aether customer app
cd apps/aether && npm run dev  # → http://localhost:5175

# Full stack via docker compose (backend + ml + kyber + infra)
docker compose up -d
# → backend    http://localhost:8000
# → ml-serving http://localhost:8080
# → kyber      http://localhost:8081  (host port 8081 → container 8080)
# apps/aether is dev-only; run separately: cd apps/aether && npm run dev
```

## Environment

Set `AETHER_ENV=local` for development. This enables in-memory fallbacks for all infrastructure (Redis, PostgreSQL, Neptune, Kafka). No external services are required for local development.

## Code Standards

- Python 3.10+
- Node 18+
- Formatting: `ruff format .`
- Linting: `ruff check .` and `npm run lint`
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
Backend Architecture/aether-backend/   Python FastAPI backend (55 routers)
ML Models/aether-ml/                   ML training + serving
Agent Layer/                           Autonomous agent workers
security/                              Model extraction defense
packages/shared/                       Canonical TypeScript contracts (@aether/shared)
packages/ui/                           Shared React component library (@aether/ui)
packages/web/                          Web SDK (@aether/web)
packages/react-native/                 React Native SDK (@aether/react-native)
packages/ios/                          Native iOS SDK
packages/android/                      Native Android SDK
apps/kyber/                            Operator control surface (React SPA, port 5174)
apps/aether/                           Customer web app (React SPA, port 5175)
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
