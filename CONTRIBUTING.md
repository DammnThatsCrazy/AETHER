# Contributing to Aether

Aether is governed by source-of-truth documentation, canonical contracts, and release discipline.

## Development Setup

See [DEVELOPMENT.md](DEVELOPMENT.md) for the full local setup guide. Quick start:

```bash
git clone https://github.com/DammnThatsCrazy/AETHER.git
cd AETHER

pip install -e ".[backend]" --ignore-installed PyJWT
npm ci

cp .env.example .env
cp frontend/aether/.env.example frontend/aether/.env.local

docker compose up -d postgres
make serve-backend          # → http://localhost:8000

cd frontend/aether && npm run dev   # → http://localhost:5175
cd frontend/kyber  && npm run dev   # → http://localhost:5174
```

## Environment

Set `AETHER_ENV=local` in `.env` for development. This enables in-memory fallbacks for Kafka and Neptune — only PostgreSQL is required locally. Set `VITE_AETHER_ENV=local-mocked` in `frontend/aether/.env.local` to develop the UI without a running backend.

## Code Standards

- Python 3.10+
- Node 18+
- Formatting: `ruff format .`
- Linting: `ruff check .` and `npm run lint`
- Type hints on all public functions

## Testing

```bash
make test                                      # All tests
make verification-disposition BASE=origin/main EXECUTE=1  # Normal PR authority
make ci-check                                  # Broad repository consistency evidence
```

Tests must pass locally and in CI before merge.

## Pull Request Requirements

Every PR must answer:

1. What product/runtime area changed?
2. Did contracts change?
3. Did SDK behavior change?
4. Did provider/connector behavior change?
5. Did graph projections change?
6. Did 360/lens behavior change?
7. Did docs need to change?
8. Did release notes need to change?
9. Did version metadata need to change?
10. Did generated docs need to be updated?

## Required Checks

- Lint
- Tests
- Contract validation
- SDK parity validation
- Docs source-of-truth validation
- Version consistency validation

## No Drift Rule

A PR is incomplete if it changes runtime behavior but does not update the docs/contracts/tests that describe that behavior.

## Repo Consistency Preflight

Before opening or updating a PR:

1. If docs or generator inputs changed, run `make docs-generate` and review any source-linked drift.
2. Run `make verification-disposition BASE=<base> EXECUTE=1`.
3. Commit all generated docs and sync outputs.
4. Do not hand-edit generated docs.
5. Do not bypass TypeScript/package export failures.
6. If backend routes, schemas, contracts, SDK public types, Profile 360, or Kyber surfaces changed, update the required ownership-map surfaces.
7. Use `make ci-check` for broad local or release evidence when needed; PR merge-readiness is determined by the verification disposition.

See `docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md` for the enforced source-to-derived ownership map.

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

## License

This project is **proprietary and confidential**. See `LICENSE` for details.
All contributions become property of Aether Platform under the same license terms.
By submitting a contribution, you confirm you have the right to do so and agree
to these terms.
