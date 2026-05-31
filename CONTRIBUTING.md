# Contributing to Aether

## Development Setup

See [DEVELOPMENT.md](DEVELOPMENT.md) for the full local setup guide. Quick start:

```bash
# Clone and install
git clone https://github.com/DammnThatsCrazy/AETHER.git
cd AETHER

# Install Python backend deps
pip install -e ".[backend]" --ignore-installed PyJWT

# Install Node workspace deps
npm ci

# Configure environment (see DEVELOPMENT.md for required secret values)
cp .env.example .env
cp frontend/aether/.env.example frontend/aether/.env.local

# Start infrastructure
docker compose up -d postgres

# Start backend
make serve-backend          # → http://localhost:8000

# Start frontend apps (separate terminals)
cd frontend/aether && npm run dev   # customer app  → http://localhost:5175
cd frontend/kyber  && npm run dev   # operator UI   → http://localhost:5174
```

## Environment

Set `AETHER_ENV=local` in `.env` for development. This enables in-memory fallbacks for Kafka and Neptune — only PostgreSQL is required locally. Set `VITE_AETHER_ENV=local-mocked` in `frontend/aether/.env.local` to develop the UI without a running backend.

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
frontend/kyber/                        Operator control surface (React SPA, port 5174)
frontend/aether/                       Customer web app (React SPA, port 5175)
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
