# Local Development Guide

## Prerequisites

- Python 3.10+
- Node.js 18+
- Docker + Docker Compose
- pip

---

## 1. Clone the repo

```bash
git clone https://github.com/DammnThatsCrazy/AETHER.git
cd AETHER
```

---

## 2. Install Python dependencies

```bash
pip install -e ".[backend]" --ignore-installed PyJWT
```

For ML and agent workers as well:

```bash
pip install -e ".[all]" --ignore-installed PyJWT
```

---

## 3. Install Node dependencies

```bash
npm ci
```

This installs all workspace packages (`packages/shared`, `packages/ui`, `packages/web`, `packages/react-native`, `frontend/aether`, `frontend/kyber`, etc.).

---

## 4. Configure environment variables

### Backend

```bash
cp .env.example .env
```

Then open `.env` and set the following required values:

| Variable | How to generate |
|----------|----------------|
| `JWT_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `DATABASE_URL` | `postgresql://aether:aether_dev_password@localhost:5432/aether` (matches docker-compose default) |
| `TSDB_PASSWORD` | `aether_dev_password` (matches docker-compose default) |
| `BYOK_ENCRYPTION_KEY` | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `WATERMARK_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `CANARY_SECRET_SEED` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |

All other variables have safe defaults for `AETHER_ENV=local`.

### Frontend (customer app)

```bash
cp frontend/aether/.env.example frontend/aether/.env.local
```

The default `VITE_AETHER_ENV=local-mocked` works for UI development without a running backend. Set `VITE_AETHER_ENV=local-live` and `VITE_API_BASE_URL=http://localhost:8000` when running the full stack.

### Frontend (operator console)

```bash
cp frontend/kyber/.env.example frontend/kyber/.env.local   # if it exists
```

---

## 5. Start infrastructure

```bash
# Minimal (postgres only — sufficient for backend + onboarding flow)
docker compose up -d postgres

# Full local stack (postgres + redis + backend)
docker compose up -d
```

The backend container builds from `Backend Architecture/aether-backend/Dockerfile` and starts on port 8000.

---

## 6. Start the frontend apps

In separate terminals:

```bash
# Customer app — http://localhost:5175
cd frontend/aether && npm run dev

# Operator console — http://localhost:5174
cd frontend/kyber && npm run dev
```

---

## 7. Verify everything is working

```bash
# Backend health
curl http://localhost:8000/v1/health

# Onboarding flow
open http://localhost:5175/signup
```

The signup flow walks through: **registration → OTP email verification → API key reveal → dashboard**.

---

## Running tests

```bash
make test              # all tests
make test-security     # extraction defense tests
make test-ml           # ML model tests
npm test               # TypeScript/frontend tests
```

---

## Linting and formatting

```bash
ruff format .          # Python formatting
ruff check .           # Python linting
npm run lint           # TypeScript linting
npm run typecheck      # TypeScript type checking
```

---

## Useful make targets

```bash
make setup             # install all Python deps (equivalent to pip install -e ".[all]")
make serve-backend     # start backend with hot reload (AETHER_ENV=local)
make serve-ml          # start ML serving on port 8080
make docs              # generate API docs
```

---

## Directory reference

```
Backend Architecture/aether-backend/   FastAPI backend (55 routers, 400+ endpoints)
ML Models/aether-ml/                   ML training + serving
Agent Layer/                           Autonomous agent workers
security/                              Model extraction defense
packages/shared/                       @aether/shared — canonical TypeScript contracts
packages/ui/                           @aether/ui — shared React component library
packages/web/                          @aether/web — Web SDK
packages/react-native/                 @aether/react-native — React Native SDK
frontend/aether/                       Customer web app (React 19 + Vite, port 5175)
frontend/kyber/                        Operator console (React 19 + Vite, port 5174)
Smart Contracts/                       EVM smart contracts (Hardhat)
Data Ingestion Layer/                  Node.js event ingestion service
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'fastapi'`**
Run `pip install -e ".[backend]" --ignore-installed PyJWT`.

**`JWT_SECRET must be set`**
You haven't created `.env` or left `JWT_SECRET` as the placeholder. See step 4.

**Backend container fails to start**
Check `docker compose logs backend`. Most failures are missing env vars or postgres not ready yet — run `docker compose up -d postgres` first, wait a few seconds, then `docker compose up -d backend`.

**Frontend can't reach API**
Set `VITE_AETHER_ENV=local-live` and `VITE_API_BASE_URL=http://localhost:8000` in `frontend/aether/.env.local`, then restart the dev server.
