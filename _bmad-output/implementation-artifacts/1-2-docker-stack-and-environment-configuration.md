---
baseline_commit: d960de8019a154b950b85b91334fb42820c53dc4
---

# Story 1.2: Docker Stack & Environment Configuration

Status: done

## Story

As a developer,
I want a `Dockerfile` and `docker-compose.yml` that bring up the FastAPI app and a PostgreSQL database together,
So that I can run the entire stack with `docker compose up` without installing Python or PostgreSQL on the host.

## Acceptance Criteria

1. `docker compose up --build` starts both `app` and `postgres` services without errors
2. The `postgres` service passes its `pg_isready` healthcheck before the `app` service begins accepting requests (`depends_on: condition: service_healthy`)
3. `GET http://localhost:8000/health` returns HTTP 200 with `{"status": "ok"}`
4. The `app` and `postgres` services communicate over a named Docker network (not the default bridge)
5. `docker compose down -v` stops all containers and destroys the named PostgreSQL volume cleanly
6. `.env.example` is committed listing every required environment variable with a description and no real secret values
7. `Dockerfile` base image is exactly `python:3.12-slim` — pinned, never `latest`

## Tasks / Subtasks

- [x] Task 1: Create `.dockerignore` (AC: 7)
  - [x] Exclude `.venv/`, `.git/`, `_bmad/`, `_bmad-output/`, `.agents/`, `keys/`, `.ruff_cache/`, `__pycache__/`, `*.pyc`, `tests/`, `*.md` (except README.md), `.env`

- [x] Task 2: Create `Dockerfile` (AC: 1, 7)
  - [x] Use `FROM python:3.12-slim` as the base (pinned, never `latest`)
  - [x] Copy uv binary from the official image: `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/`
  - [x] Set `WORKDIR /app`
  - [x] Copy `pyproject.toml` and `uv.lock` first (enables Docker layer caching of deps)
  - [x] Run `uv sync --frozen --no-cache --no-dev` (production deps only — excludes ruff/pytest)
  - [x] Copy remaining application source with `COPY . .`
  - [x] Set `CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`

- [x] Task 3: Create minimal `app/main.py` with `/health` endpoint (AC: 3)
  - [x] Create `app/main.py` with `FastAPI` app instance
  - [x] Add `GET /health` returning `{"status": "ok"}` with HTTP 200
  - [x] No lifespan handler, no router imports yet (those are Story 1.4)

- [x] Task 4: Create `docker-compose.yml` (AC: 1, 2, 4, 5)
  - [x] Define `postgres` service using `postgres:17-alpine`
  - [x] Configure postgres healthcheck: `pg_isready -U ${POSTGRES_USER}` with `interval: 5s`, `timeout: 5s`, `retries: 5`
  - [x] Define `app` service with `build: .` and `depends_on: postgres: condition: service_healthy`
  - [x] Map port `8000:8000` on the `app` service
  - [x] Mount `./keys:/app/keys:ro` on the `app` service (read-only; keys are gitignored but needed at runtime)
  - [x] Use `env_file: [.env]` on the `app` service
  - [x] Define a named network (e.g., `fintech_net`) and attach both services to it
  - [x] Define a named volume (`postgres_data`) for PostgreSQL data persistence
  - [x] Set `restart: unless-stopped` on both services

- [x] Task 5: Create `.env.example` (AC: 6)
  - [x] Document all required environment variables with name, example value, and description (see Dev Notes for complete list)
  - [x] Use placeholder values — NO real secrets

- [x] Task 6: Create `.env` locally (NOT committed — already gitignored)
  - [x] Copy `.env.example` to `.env` and fill in real values for local testing
  - [x] Note: `DATABASE_URL` must use `postgres` as the hostname (the Docker Compose service name)

- [x] Task 7: Verify the full stack (AC: 1, 2, 3, 4, 5)
  - [x] Run `docker compose up --build` — both services must start ✅ (`agentic-fintech-backend-app-1` Up, `agentic-fintech-backend-postgres-1` Up)
  - [x] Confirm `postgres` healthcheck passes before `app` starts ✅ (`postgres` status: `(healthy)` before `app` started)
  - [x] Run `curl http://localhost:8000/health` — must return `{"status": "ok"}` ✅
  - [x] Run `docker compose down -v` — must complete cleanly ✅ (containers, volume, and network all removed)
  - [x] Run `uv run ruff check .` — must still pass zero violations ✅

### Review Findings

- [x] [Review][Patch] Unpinned `ghcr.io/astral-sh/uv:latest` in Dockerfile — pinned to `ghcr.io/astral-sh/uv:0.11` [Dockerfile:4]
- [x] [Review][Patch] Postgres healthcheck missing `start_period` — added `start_period: 30s` [docker-compose.yml:11-15]
- [x] [Review][Defer] Root process in container — no `USER` instruction; container runs as root [Dockerfile] — deferred, prototype scope; harden post-PoC
- [x] [Review][Defer] Credential drift: `POSTGRES_PASSWORD` in `POSTGRES_*` vars can diverge from the password embedded in `DATABASE_URL` — deferred, operational concern documented in `.env.example`
- [x] [Review][Defer] Volume locks Postgres credentials on first boot — changing creds without `down -v` causes auth failures — deferred, standard Docker Postgres behaviour
- [x] [Review][Defer] Missing PEM keys yield false-healthy `/health` — deferred, Story 1.4 adds real startup validation
- [x] [Review][Defer] `alembic/` excluded from image; no in-container migration runner — deferred, by design; migrations run from host per story spec
- [x] [Review][Defer] Shallow `/health` endpoint — no DB or config readiness — deferred, Story 1.4 scope boundary
- [x] [Review][Defer] `DATABASE_URL` hostname `postgres` unusable from host — deferred, documented in `.env.example`
- [x] [Review][Defer] Password special characters silently break DSN — deferred, prototype scope
- [x] [Review][Defer] `POSTGRES_DB` change after volume init — deferred, operational concern
- [x] [Review][Defer] No Dockerfile `HEALTHCHECK` instruction — deferred, prototype
- [x] [Review][Defer] Stale image on rebuild without `--build` — deferred, expected Docker behaviour
- [x] [Review][Defer] Secret files outside `.env`/`.env.*` patterns can reach image — deferred, prototype scope
- [x] [Review][Defer] README.md not copied before `uv sync` — deferred, no impact on current `uv sync --no-dev` flow

## Dev Notes

### Story 1.1 Learnings (MUST carry forward)

- **Keys are PKCS8/PEM format** — `keys/private_key.pem` (`-----BEGIN PRIVATE KEY-----`) and `keys/public_key.pem` (`-----BEGIN PUBLIC KEY-----`) were regenerated in Story 1.1 code review. PyJWT EdDSA works correctly. Do NOT regenerate.
- **Keys gitignore** — `.gitignore` uses `keys/*.pem` (not `keys/`), so the `keys/` directory itself is tracked. The Docker Compose volume mount `./keys:/app/keys:ro` works because the directory exists on disk.
- **`uv sync --frozen --no-cache --no-dev`** — always use `--no-dev` for Docker production images. This was a code review patch from Story 1.1. Without it, `ruff` and `pytest` would be installed in the production image.
- **Ruff excludes** — `pyproject.toml` already excludes `_bmad`, `_bmad-output`, `.agents`, `.venv`, `alembic/versions`. The new `.dockerignore` must also exclude these so they don't bloat the build context.
- **Security `"S"` rules active** — ruff is configured with `select = ["E", "F", "I", "B", "UP", "S"]`. Any code written in this story (app/main.py) must be bandit-clean.

### Exact `Dockerfile` content

```dockerfile
FROM python:3.12-slim

# Install uv from official image (no pip, no brew)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency manifest first — maximizes Docker layer cache reuse
COPY pyproject.toml uv.lock ./

# Install production dependencies only; --no-dev excludes ruff/pytest from the image
RUN uv sync --frozen --no-cache --no-dev

# Copy application source (after deps for better caching)
COPY . .

# Run with the venv's uvicorn directly (no activation needed)
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Why `.venv/bin/uvicorn` directly?** — `uv run` is not available at container runtime without uv in the container PATH at CMD-time. Using the venv path directly is simpler and more predictable.

### Exact `docker-compose.yml` content

```yaml
services:
  postgres:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - fintech_net

  app:
    build: .
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./keys:/app/keys:ro
    networks:
      - fintech_net

networks:
  fintech_net:
    driver: bridge

volumes:
  postgres_data:
```

**Note:** No `version:` key — `version` at the top of `docker-compose.yml` is deprecated in Compose v2 (Docker Compose ≥ 2.0). Omit it.

### Exact `.env.example` content

```bash
# PostgreSQL service configuration (matches Docker Compose service)
POSTGRES_USER=postgres
POSTGRES_PASSWORD=changeme
POSTGRES_DB=fintech_db

# SQLAlchemy async connection URL — hostname must match the Compose service name "postgres"
DATABASE_URL=postgresql+asyncpg://postgres:changeme@postgres:5432/fintech_db

# Stripe API key — MUST begin with sk_test_ (validated at startup in Story 1.4)
STRIPE_API_KEY=sk_test_replace_with_your_test_key_here

# Path to the Ed25519 public key PEM file (PKCS8 format)
# In Docker: mounted at /app/keys/public_key.pem via compose volume
PUBLIC_KEY_PATH=/app/keys/public_key.pem
```

### Minimal `app/main.py` for this story

```python
from fastapi import FastAPI

app = FastAPI(title="Agentic Fintech Backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

**Scope boundary:** Do NOT add lifespan handler, router imports, settings loading, or JSON logging here. Those belong to Stories 1.4 and 5.3. The only goal of `app/main.py` in this story is to make `GET /health` return `{"status": "ok"}` so the Docker Compose health-check chain works end-to-end.

### `.dockerignore` content

```
.venv/
.git/
.ruff_cache/
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.coverage
.env
.env.*
keys/
_bmad/
_bmad-output/
.agents/
tests/
alembic/
docs/
```

**Why exclude `keys/`?** Keys are never baked into the image — they are mounted as a volume at runtime (`./keys:/app/keys:ro`). This ensures key files never appear in Docker image layers.

### Environment variable reference

| Variable | Type | Example | Used by |
|---|---|---|---|
| `POSTGRES_USER` | string | `postgres` | Docker Compose postgres service |
| `POSTGRES_PASSWORD` | string | `changeme` | Docker Compose postgres service |
| `POSTGRES_DB` | string | `fintech_db` | Docker Compose postgres service |
| `DATABASE_URL` | DSN string | `postgresql+asyncpg://postgres:changeme@postgres:5432/fintech_db` | SQLAlchemy (Story 1.3+) |
| `STRIPE_API_KEY` | string | `sk_test_...` | pydantic-settings validator (Story 1.4) |
| `PUBLIC_KEY_PATH` | file path | `/app/keys/public_key.pem` | lifespan key loader (Story 1.4) |

**Critical:** `DATABASE_URL` must use `postgres` (the Compose service name) as the hostname — not `localhost`. When running tests locally outside Docker (Story 5.1), a separate `TEST_DATABASE_URL` pointing to `localhost` will be used.

### Architecture compliance notes

- **NFR-4** — All runtime dependencies run inside Docker. No host Python or PostgreSQL required.
- **NFR-5** — Base image is pinned `python:3.12-slim` (not `python:latest`, not `python:3.12`).
- **FR-14** — PostgreSQL is a named service in `docker-compose.yml` with a persistent named volume (`postgres_data`) and the `app` service declares `depends_on: postgres: condition: service_healthy`.
- **Service boundary** — `app/main.py` in this story is a stub. It does not import any services, models, or DB code yet. Full initialization happens in Story 1.4.
- **Keys** — Never committed (`keys/*.pem` in `.gitignore`). Never baked into image (`keys/` in `.dockerignore`). Always mounted at runtime via Compose volume.
- **`uv sync --no-dev`** — Dev tools (`ruff`, `pytest`, `pytest-asyncio`) must not appear in the production image. Confirmed correct from Story 1.1 code review.

### Key commands for verification

```bash
# Build and start the full stack
docker compose up --build

# In another terminal: verify health endpoint
curl http://localhost:8000/health
# Expected: {"status":"ok"}

# Stop and clean up volumes
docker compose down -v

# Verify ruff still passes (from host, not Docker)
source $HOME/.local/bin/env  # if uv not in PATH
uv run ruff check .
```

### Gotchas and edge cases

1. **`DATABASE_URL` hostname is `postgres`** — inside Docker the Compose service name resolves as the hostname. On the host for tests it must be `localhost`. Never mix them up.
2. **Docker Compose v2 syntax** — no `version:` key at the top. Using `version: "3.9"` is deprecated and triggers a warning in Docker Compose ≥ 2.0.
3. **`keys/` in `.dockerignore` is critical** — without this, the key files would be baked into the image layer, which is a security violation. Compose mounts override at runtime.
4. **`uv sync --frozen`** — `--frozen` ensures the lock file is used exactly as committed; it fails if `pyproject.toml` and `uv.lock` are out of sync. This is intentional — the Dockerfile should break if someone adds a dep without locking.
5. **PostgreSQL 17-alpine** — use alpine variant for smaller image. The `pg_isready` command is included in this image.
6. **Ruff `"S"` rules on `app/main.py`** — the return type annotation `dict[str, str]` is required to satisfy type safety. The health endpoint is trivial but must pass the security linter.

### Project Structure Notes

Files created in this story:
- `Dockerfile` (new)
- `.dockerignore` (new)
- `docker-compose.yml` (new)
- `.env.example` (new — committed)
- `.env` (new — gitignored, local only)
- `app/main.py` (new — minimal stub)

Files NOT touched (belong to later stories):
- `app/config.py` → Story 1.4 (full pydantic-settings BaseSettings)
- `alembic/env.py`, `alembic/versions/` → Story 1.3
- `app/routers/` → Story 1.4+
- `catalog/products.json` → Story 2.1

### References

- [Source: architecture.md#Infrastructure & Deployment] — NFR-4/5, pinned base image, Docker Compose pattern
- [Source: architecture.md#Project Structure] — Dockerfile, docker-compose.yml, .env.example in root
- [Source: epics.md#Story 1.2] — all acceptance criteria
- [Source: 1-1-project-scaffold-and-package-management.md#Review Findings] — `--no-dev` flag for Docker, PKCS8 keys confirmed
- [External: docs.astral.sh/uv/guides/integration/fastapi.md] — `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/` pattern, `.venv/bin/uvicorn` CMD
- [External: betterstack.com/community/guides/scaling-python/fastapi-docker-best-practices] — `depends_on: condition: service_healthy` pattern

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.6 (cursor)

### Debug Log References

- `S101 Use of assert detected` in test files — fixed by adding `[tool.ruff.lint.per-file-ignores]` with `"tests/**/*.py" = ["S101"]` to `pyproject.toml`. Standard pytest pattern; asserts in test files are intentional.
- `S101 Use of assert detected` in test files — fixed by adding `[tool.ruff.lint.per-file-ignores]` with `"tests/**/*.py" = ["S101"]` to `pyproject.toml`. Standard pytest pattern; asserts in test files are intentional.
- Full `docker compose up --build -d` executed and verified: both containers started, postgres `(healthy)`, `GET /health` → `{"status":"ok"}`, `docker compose down -v` cleaned up cleanly.

### Completion Notes List

- Created `.dockerignore` — excludes `.venv/`, `keys/`, `_bmad/`, `_bmad-output/`, `.agents/`, `tests/`, `alembic/`, `.env`, `.git/`, `__pycache__/`, `*.pyc`, `.ruff_cache/`, `.pytest_cache/`
- Created `Dockerfile` — base `python:3.12-slim`, uv binary copied from `ghcr.io/astral-sh/uv:latest`, `uv sync --frozen --no-cache --no-dev`, CMD via `.venv/bin/uvicorn`
- Created `app/main.py` — minimal stub with `GET /health` returning `{"status": "ok"}`. No DB imports, no router, no lifespan (those are Story 1.4).
- Created `docker-compose.yml` — Compose v2 syntax (no `version:` key), `postgres:17-alpine` with `pg_isready` healthcheck, named network `fintech_net`, named volume `postgres_data`, `./keys:/app/keys:ro` mount, `depends_on: condition: service_healthy`
- Created `.env.example` — all 6 required variables with descriptions and placeholder values, no real secrets
- Created `.env` (gitignored) — local dev values
- Added `tests/test_health.py` — 2 async tests via `httpx.AsyncClient + ASGITransport`, both passing
- Added `[tool.ruff.lint.per-file-ignores]` to `pyproject.toml` for `tests/**/*.py = ["S101"]`
- Verified: `uv run ruff check .` → 0 violations; `uv run pytest -v` → 2/2 passed; `curl http://127.0.0.1/health` → `{"status":"ok"}`

### File List

- `.dockerignore` (new)
- `Dockerfile` (new)
- `docker-compose.yml` (new)
- `.env.example` (new)
- `.env` (new — gitignored, not committed)
- `app/main.py` (new)
- `tests/test_health.py` (new)
- `pyproject.toml` (modified — added `[tool.ruff.lint.per-file-ignores]`)

## Change Log

- 2026-06-21: Story 1.2 implemented — Docker stack files, minimal FastAPI stub, env files, and health tests created (Sonnet 4.6)
