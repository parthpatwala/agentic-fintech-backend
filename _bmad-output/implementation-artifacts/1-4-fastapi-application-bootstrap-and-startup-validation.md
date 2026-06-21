---
baseline_commit: d960de8019a154b950b85b91334fb42820c53dc4
---

# Story 1.4: FastAPI Application Bootstrap & Startup Validation

Status: done

## Story

As a developer,
I want the FastAPI application to validate all required configuration at boot via a `lifespan` handler,
So that misconfigured environments fail immediately with a clear error message rather than crashing silently at runtime.

## Acceptance Criteria

**Given** all environment variables are correctly set and key files exist
**When** `docker compose up` starts the app service
**Then** the lifespan handler completes successfully
**And** `GET /health` returns HTTP 200 with `{"status": "ok"}`
**And** startup logs confirm: configuration validated and database connected

**Given** `STRIPE_API_KEY` is set to a value not beginning with `sk_test_`
**When** the app attempts to start
**Then** a `ValueError` is raised with a message indicating the key must begin with `sk_test_`
**And** the process exits with a non-zero code

**Given** `PUBLIC_KEY_PATH` points to a file that does not exist
**When** the app attempts to start
**Then** a `FileNotFoundError` is raised including the configured path in the message
**And** the process exits with a non-zero code

**Given** the PostgreSQL service is unreachable
**When** the app attempts to start
**Then** a database connectivity error is raised and the process exits with a non-zero code

## Tasks / Subtasks

- [x] Task 1: Create `app/config.py` — pydantic-settings `Settings`
  - [x] Define `Settings(BaseSettings)` with `database_url`, `stripe_api_key`, `public_key_path` fields
  - [x] Add `@field_validator("stripe_api_key")` that raises `ValueError` if value does not start with `sk_test_`
  - [x] Configure `SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")`
  - [x] Replace `os.environ["DATABASE_URL"]` in `app/db/session.py` with lazy engine initialization

- [x] Task 2: Refactor `app/db/session.py` — lazy engine initialization
  - [x] Remove the module-level `os.environ["DATABASE_URL"]` and `create_async_engine` call
  - [x] Add `init_engine(database_url: str) -> AsyncEngine` function that sets module-level `_engine` and `_session_factory`
  - [x] Add `async def dispose_engine() -> None` for lifespan teardown
  - [x] Update `get_db_session()` to use `_session_factory` (raises `RuntimeError` if not initialized)
  - [x] Add `pool_pre_ping=True` to `create_async_engine` call

- [x] Task 3: Rewrite `app/main.py` — add full lifespan handler
  - [x] Configure Python structured JSON logging using `python-json-logger` at the top of the lifespan
  - [x] Instantiate `Settings()` inside the lifespan (not at module scope)
  - [x] Open `settings.public_key_path` in binary mode; let `FileNotFoundError` propagate naturally
  - [x] Store raw key bytes in `app.state.public_key_bytes` (Story 2.1 will derive the JWK from this)
  - [x] Call `db_session.init_engine(settings.database_url)` and immediately run `SELECT 1` connectivity check
  - [x] Log `"configuration validated"` and `"database connected"` at INFO level using the JSON logger
  - [x] `yield` (app serves requests)
  - [x] Teardown: call `await db_session.dispose_engine()`

- [x] Task 4: Update `tests/test_health.py` to work with the new lifespan
  - [x] Added `autouse` fixture that patches `app.main.check_db_connectivity` via `AsyncMock`
  - [x] All existing health tests pass (HTTP 200, `{"status": "ok"}`)

- [x] Task 5: Write `tests/test_startup.py` — startup validation unit tests
  - [x] Test: valid `Settings` construction succeeds (sk_test_ key + real key path)
  - [x] Test: `Settings` with invalid `STRIPE_API_KEY` raises `pydantic.ValidationError` containing `"sk_test_"`
  - [x] Test: lifespan raises `FileNotFoundError` when `public_key_path` points to a nonexistent file
  - [x] Test: lifespan raises `OperationalError` when DB is unreachable (mocked)

### Review Findings (2026-06-21)

- [x] [Review][Patch] `dispose_engine` does not reset `_session_factory` — stale reference passes None-check after teardown [session.py:21-25]
- [x] [Review][Patch] `test_startup_db_unreachable_raises` does not mock `open()` — CI without `keys/` raises FileNotFoundError before OperationalError [tests/test_startup.py:75-97]
- [x] [Review][Patch] `test_health.py` autouse fixture only patches `check_db_connectivity` — Settings() and open() fail in clean CI [tests/test_health.py:12-15]
- [x] [Review][Patch] DB connectivity failure leaves engine open — dispose_engine not called when check_db_connectivity raises [main.py:57-59]
- [x] [Review][Patch] `init_engine` double-call silently orphans previous engine and connection pool [session.py:14-18]
- [x] [Review][Patch] `check_db_connectivity` uses untyped `engine` parameter with `# type: ignore` [main.py:34]
- [x] [Review][Patch] Bare `'sk_test_'` prefix alone passes stripe key validation [config.py:17-23]
- [x] [Review][Patch] `PermissionError` not caught when opening key file — no actionable startup message [main.py:48-53]
- [x] [Review][Patch] Empty key file not detected — zero bytes stored, downstream JWT verify silently fails [main.py:50-51]
- [x] [Review][Defer] DATABASE_URL with sync scheme gives cryptic driver error — prototype scope, .env.example documents correct format
- [x] [Review][Defer] /health always returns 200 regardless of actual state — by design for Story 1.4, deep health check is Story 5.x scope
- [x] [Review][Defer] AC-2/AC-3 non-zero exit code relies on uvicorn behavior rather than explicit sys.exit() — standard FastAPI pattern

- [x] Task 6: Verify in Docker
  - [x] `docker compose up -d --build` — both services healthy, lifespan logs visible in `docker compose logs app`
  - [x] `GET http://localhost:8000/health` returns `{"status": "ok"}`
  - [x] `STRIPE_API_KEY=sk_live_bad_key` → `ValidationError` raised at startup with `"sk_test_"` message
  - [x] `uv run ruff check .` — zero violations
  - [x] `uv run pytest -v` — 22/22 passed, no regressions

## Dev Notes

### What this story is and is NOT

**Story 1.4 scope (do now):**
- `app/config.py` with Settings + Stripe key validator
- `app/db/session.py` refactored to lazy engine init (fixes the `os.environ` crash-on-import deferred from Story 1.3 code review)
- `app/main.py` lifespan: JSON logging setup, public key file load, DB connectivity ping
- Tests for all four AC failure modes

**Deferred to Story 2.1 (do NOT do now):**
- JWK derivation from `public_key.pem` → `app.state.jwk`
- `catalog/products.json` loading → `app.state.catalog`
- `app.state.public_key` (the actual cryptographic key object ready for JWT verify)

Story 2.1 will expand the lifespan with those additional steps. Story 1.4 just establishes the lifespan skeleton and the two critical validations: Stripe key gate + DB connectivity.

### Current state of `app/main.py` (to replace)

```python
from fastapi import FastAPI

app = FastAPI(title="Agentic Fintech Backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

No lifespan. No imports from config or db. This is the starting point for the UPDATE.

### Current state of `app/db/session.py` (to replace)

```python
import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ["DATABASE_URL"]          # ← crashes at import if var missing

engine = create_async_engine(DATABASE_URL, echo=False)  # ← created at import time, never disposed

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

Both issues (crash-on-import and never-disposed engine) were flagged in the Story 1.3 code review and explicitly deferred to this story.

### Exact `app/config.py` to create

```python
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    stripe_api_key: str
    public_key_path: str = "keys/public_key.pem"

    @field_validator("stripe_api_key")
    @classmethod
    def stripe_key_must_be_test(cls, v: str) -> str:
        if not v.startswith("sk_test_"):
            raise ValueError(
                "STRIPE_API_KEY must begin with 'sk_test_' — "
                "production keys are not permitted in this prototype"
            )
        return v
```

**Why field names are lowercase:**
`pydantic-settings` maps snake_case field names to their UPPER_CASE env var equivalents by default. `database_url` → reads `DATABASE_URL`, `stripe_api_key` → reads `STRIPE_API_KEY`, `public_key_path` → reads `PUBLIC_KEY_PATH`. No aliases needed.

**Why `extra="ignore"`:**
`.env` may contain `POSTGRES_USER`, `POSTGRES_PASSWORD`, etc. for Docker Compose. These must not cause a validation error on the Settings object.

**Why `@field_validator` not `@validator`:**
`@field_validator` is the Pydantic v2 API (`pydantic-settings` uses Pydantic v2). Never use `@validator` (deprecated, Pydantic v1 API).

**Stripe key validation** raises a `ValueError` whose message bubbles up as a `pydantic.ValidationError` when `Settings()` is instantiated. FastAPI's lifespan catches this as an unhandled exception → process exits with a non-zero code. This satisfies the AC.

### Exact `app/db/session.py` replacement

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    global _engine, _session_factory
    _engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    assert _session_factory is not None, "DB engine not initialized — was lifespan skipped?"
    async with _session_factory() as session:
        yield session
```

**Key changes from Story 1.3 version:**
- No module-level `os.environ` access → no crash-on-import
- `init_engine` called by the lifespan (not at import time) → engine is created after config validation
- `dispose_engine` called in lifespan teardown → no leaked connections
- `pool_pre_ping=True` → stale connection detection (deferred from Story 1.3 code review)
- `assert _session_factory is not None` → immediate, clear error if a route runs before the lifespan completed (future stories safety net)

**Note:** Alembic's `alembic/env.py` still reads `os.environ["DATABASE_URL"]` directly — that is intentional and correct for a CLI tool. Do NOT change it.

### Exact `app/main.py` replacement

```python
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from pythonjsonlogger import jsonlogger
from sqlalchemy import text

from app.config import Settings
from app.db import session as db_session

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Set up JSON structured logging using python-json-logger."""
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


async def check_db_connectivity(engine) -> None:
    """Ping the database with a lightweight SELECT 1. Extracted for testability."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _configure_logging()

    # 1. Validate all configuration — ValidationError raised here exits the process
    settings = Settings()
    logger.info("Configuration validated", extra={"event": "startup"})

    # 2. Load public key file — FileNotFoundError if path is wrong
    try:
        with open(settings.public_key_path, "rb") as f:
            app.state.public_key_bytes = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"PUBLIC_KEY_PATH '{settings.public_key_path}' does not exist. "
            "Generate keys with: openssl genpkey -algorithm ed25519 -out keys/private_key.pem"
        )
    logger.info("Public key loaded", extra={"event": "startup", "path": settings.public_key_path})

    # 3. Initialize DB engine and verify connectivity
    engine = db_session.init_engine(settings.database_url)
    await check_db_connectivity(engine)
    logger.info("Database connected", extra={"event": "startup"})

    logger.info(
        "Startup complete — configuration validated and database connected",
        extra={"event": "startup_complete"},
    )

    yield  # ← app is live from here

    # Teardown
    await db_session.dispose_engine()
    logger.info("Engine disposed", extra={"event": "shutdown"})


app = FastAPI(title="Agentic Fintech Backend", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

**Key design decisions:**
- `Settings()` instantiated inside the lifespan, not at module scope — prevents crash-on-import in test environments that import `app.main` without all env vars set.
- `_configure_logging()` called first — ensures all subsequent log calls (including startup errors) emit JSON.
- `check_db_connectivity` extracted as a standalone async function — allows `patch("app.main.check_db_connectivity")` in unit tests without needing a real DB.
- `FileNotFoundError` re-raised with an actionable message pointing to the key generation command.
- `app.state.public_key_bytes` stores the raw PEM bytes; Story 2.1 will call `app/services/crypto.py` to parse them into an Ed25519 key object and derive the JWK.

**Import note:** `from pythonjsonlogger import jsonlogger` — the package is `python-json-logger` but the import is `pythonjsonlogger`. Verify with `uv run python -c "from pythonjsonlogger import jsonlogger; print('ok')"`.

### Exact `tests/test_health.py` update

The existing health tests use `AsyncClient(transport=ASGITransport(app=app))`. When used as an `async with` context manager, `ASGITransport` sends ASGI lifespan events — the lifespan runs. After Story 1.4, the lifespan requires env vars and a DB. Update the tests to mock the DB ping and rely on `.env` for settings:

```python
"""Tests for the /health endpoint (Stories 1.2 + 1.4)."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture(autouse=True)
def mock_db_startup():
    """Bypass the DB connectivity check so health tests need no running Postgres."""
    with patch("app.main.check_db_connectivity", new_callable=AsyncMock):
        yield


@pytest.mark.asyncio
async def test_health_returns_200() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_returns_status_ok() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.json() == {"status": "ok"}
```

**Why `autouse=True`:** Every test in this file benefits from the mock — no need to inject it per-test.

**Why NOT mock `Settings()`:** The `.env` file in the project root has valid values (`STRIPE_API_KEY=sk_test_replace_with_your_test_key_here` starts with `sk_test_`). pydantic-settings finds and reads `.env` automatically. `keys/public_key.pem` exists from Story 1.1. So Settings + key file load succeed naturally; only the DB ping needs mocking.

**IMPORTANT:** If tests are ever run in a CI environment without a `.env` file, add `monkeypatch.setenv` calls or create a `tests/conftest.py` with `pytest_configure` to set required vars. This is Story 5.1 scope.

### Exact `tests/test_startup.py` to create

```python
"""Tests for startup validation — Settings validators and lifespan failure modes (Story 1.4)."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.config import Settings


# ── Settings unit tests (no running app needed) ─────────────────────────────


def test_settings_valid_stripe_key() -> None:
    s = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        stripe_api_key="sk_test_valid_key_12345",
        public_key_path="keys/public_key.pem",
    )
    assert s.stripe_api_key.startswith("sk_test_")


def test_settings_invalid_stripe_key_raises() -> None:
    with pytest.raises(ValidationError, match="sk_test_"):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/db",
            stripe_api_key="pk_live_this_is_wrong",
            public_key_path="keys/public_key.pem",
        )


def test_settings_invalid_stripe_key_error_message() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/db",
            stripe_api_key="sk_live_wrong",
            public_key_path="keys/public_key.pem",
        )
    assert "sk_test_" in str(exc_info.value)


# ── Lifespan failure mode tests (via ASGI client) ────────────────────────────


@pytest.mark.asyncio
async def test_startup_missing_public_key_raises_file_not_found() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    with (
        patch("app.main.Settings") as MockSettings,
        patch("app.main.check_db_connectivity", new_callable=AsyncMock),
        patch("app.db.session.init_engine"),
    ):
        instance = MockSettings.return_value
        instance.database_url = "postgresql+asyncpg://user:pass@localhost/db"
        instance.stripe_api_key = "sk_test_fake"
        instance.public_key_path = "/nonexistent/path/public_key.pem"

        with pytest.raises(FileNotFoundError, match="/nonexistent/path/public_key.pem"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as _:
                pass


@pytest.mark.asyncio
async def test_startup_db_unreachable_raises() -> None:
    from sqlalchemy.exc import OperationalError

    from httpx import ASGITransport, AsyncClient

    from app.main import app

    with (
        patch("app.main.Settings") as MockSettings,
        patch("app.db.session.init_engine"),
        patch(
            "app.main.check_db_connectivity",
            new_callable=AsyncMock,
            side_effect=OperationalError("connect failed", None, None),
        ),
    ):
        instance = MockSettings.return_value
        instance.database_url = "postgresql+asyncpg://bad:bad@bad:5432/bad"
        instance.stripe_api_key = "sk_test_fake"
        instance.public_key_path = "keys/public_key.pem"

        with pytest.raises(OperationalError):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as _:
                pass
```

**Test design notes:**
- `Settings(database_url=..., stripe_api_key=..., public_key_path=...)` overrides env vars at instantiation time — pydantic-settings v2 accepts direct keyword arguments. `.env` is not read when all required fields are provided.
- `ValidationError` is from `pydantic`, not `pydantic_settings` — import accordingly.
- `FileNotFoundError` test patches `Settings` to return a fake instance with a bad key path, then lets the `open()` call inside the lifespan fail naturally.
- `OperationalError` test patches `check_db_connectivity` to raise — testing the lifespan's propagation behaviour without needing a real DB.
- Both lifespan failure tests use `pytest.raises` as a context manager wrapping the `AsyncClient` context manager — this correctly catches exceptions that propagate out of the ASGI startup sequence.

### pydantic-settings v2 field mapping rules

In pydantic-settings v2, field names map to env vars by default with case-insensitive matching:

| Field name in Settings | Env var read |
|---|---|
| `database_url` | `DATABASE_URL` |
| `stripe_api_key` | `STRIPE_API_KEY` |
| `public_key_path` | `PUBLIC_KEY_PATH` |

No aliases needed. pydantic-settings automatically uppercases field names when searching environment variables.

### python-json-logger import path

The package is installed as `python-json-logger` but the import module is `pythonjsonlogger`:

```python
from pythonjsonlogger import jsonlogger
```

Verify it is available: `uv run python -c "from pythonjsonlogger import jsonlogger; print('ok')"`.

The `JsonFormatter` fields:
- `asctime` → renamed to `timestamp`
- `levelname` → renamed to `level`
- `name` → renamed to `logger`
- `message` → `message` (unchanged)
- `extra={"event": "..."}` → extra dict fields added to JSON output

### pydantic-settings v2 constructor override

When `Settings(field=value, ...)` is used in tests, pydantic-settings treats the constructor kwargs as the highest-priority source (above env vars and `.env` file). Only missing required fields without defaults fall through to env/file lookup. This means tests can control Settings without monkeypatching the environment.

Exception: if the `.env` file contains a conflicting value AND you do not provide the field as a kwarg, the `.env` value wins over the environment. To fully isolate tests from `.env`, pass all three fields explicitly in the constructor.

### Story 1.3 code review deferred items addressed by this story

The Story 1.3 code review deferred two medium-severity findings to Story 1.4:

1. **`os.environ["DATABASE_URL"]` crashes import without env var** → Fixed by `app/config.py` + lazy `init_engine`.
2. **Async engine created at import time, never disposed** → Fixed by `init_engine` in lifespan + `dispose_engine` in teardown.

Both are addressed by Tasks 1 and 2 of this story.

### Other deferred items (carry forward, do NOT address in 1.4)

From `deferred-work.md` (Story 1.2 review):
- "Missing PEM keys yield false-healthy stack" — now fixed by this story (lifespan raises FileNotFoundError).
- "Shallow /health endpoint" — now fixed by this story (lifespan validates DB before yielding).
- "DATABASE_URL hostname unusable from host" — still deferred (Story 5.1 adds TEST_DATABASE_URL).

These three items should be removed from `deferred-work.md` upon story completion and replaced with the remaining open items.

### Ruff compliance for `app/main.py`

The `S` (security) Ruff rules are enabled. Watch for:
- `S603` / `S605` — no subprocess calls (none in this story, but be aware)
- `S108` — no hardcoded temp paths

The `assert` in `get_db_session()` is not in a test file — it is NOT suppressed by `per-file-ignores`. This is intentional: it is a programming guard, not a test assertion. Ruff `S101` applies to test files only; plain assert in production code under `B` rules is flagged as `B009` if used for flow control, but an assertion with a clear message is acceptable. If Ruff flags it, replace with an explicit `if _session_factory is None: raise RuntimeError(...)`.

### Key commands for verification

```bash
# Build and start (from project root, Docker running)
docker compose up -d --build

# Check startup logs — should show JSON lines with "configuration validated" and "database connected"
docker compose logs app | head -20

# Health check
curl -s http://localhost:8000/health
# Expected: {"status":"ok"}

# Test invalid Stripe key (temporarily edit .env, then restart)
# Set STRIPE_API_KEY=sk_live_badkey in .env, then:
docker compose up app --build
# Expected: container exits with ValidationError containing "sk_test_"
# Reset .env afterward

# Run tests from host
uv run ruff check .
uv run pytest -v
# Expected: all tests pass (health tests + startup tests + model tests)

# Teardown
docker compose down -v
```

### Architecture compliance checklist

- [ ] `Settings` lives exclusively in `app/config.py` — no other file instantiates `Settings`
- [ ] `app/db/session.py` exposes `init_engine`, `dispose_engine`, `get_db_session` — no module-level engine creation
- [ ] `lifespan` in `app/main.py` is the single owner of app startup sequence
- [ ] `check_db_connectivity` extracted as a standalone function (testability)
- [ ] No PyJWT imports in this story — crypto.py is Story 2.1+ scope
- [ ] No catalog loading in this story — `app.state.catalog` is Story 2.1 scope
- [ ] `app.state.public_key_bytes` is set; `app.state.public_key` (parsed key object) is Story 2.1 scope
- [ ] `python-json-logger` is already in `pyproject.toml` dependencies — no `uv add` needed

### References

- [Source: architecture.md#Infrastructure & Deployment] — pydantic-settings BaseSettings, sk_test_ validator, lifespan handler order
- [Source: architecture.md#Component Boundaries — app/main.py] — lifespan owns key loading, catalog loading, Stripe key validation, DB connectivity
- [Source: epics.md#Story 1.4] — all acceptance criteria
- [Source: deferred-work.md] — os.environ crash-on-import, engine never disposed (from Story 1.3 code review)
- [Source: 1-3-database-schema-and-alembic-migrations.md#Completion Notes] — `app/db/session.py` current state and decision to defer to 1.4
- [External: docs.pydantic.dev/latest/concepts/pydantic_settings/] — pydantic-settings v2 BaseSettings, field_validator

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.6 (cursor)

### Debug Log References

- `pythonjsonlogger.jsonlogger` deprecated — fixed by switching import to `pythonjsonlogger.json.JsonFormatter` (the new stable module path in current python-json-logger).
- `test_settings_default_public_key_path` failed because `.env` sets `PUBLIC_KEY_PATH=/app/keys/public_key.pem` which overrides the model default — updated test to use `test_settings_custom_public_key_path` verifying explicit kwarg override instead.
- Lifespan failure tests (FileNotFoundError, OperationalError) failed when using `ASGITransport` — ASGI transport swallows lifespan startup exceptions internally. Fixed by testing the `lifespan(app)` async context manager directly via `async with lifespan(app): pass`.

### Completion Notes List

- `app/config.py` created — `Settings(BaseSettings)` reads `DATABASE_URL`, `STRIPE_API_KEY`, `PUBLIC_KEY_PATH` from env/`.env`; `@field_validator` raises `ValueError` with clear message if `STRIPE_API_KEY` does not start with `sk_test_`; `extra="ignore"` silences Compose-only vars (`POSTGRES_USER` etc.)
- `app/db/session.py` refactored — removed import-time `os.environ["DATABASE_URL"]` and module-level engine; `init_engine()` / `dispose_engine()` owned by lifespan; `pool_pre_ping=True` added; `RuntimeError` on uninitialized `get_db_session`
- `app/main.py` rewritten — JSON logging configured via `pythonjsonlogger.json.JsonFormatter`; `check_db_connectivity()` extracted as standalone function; lifespan order: settings → key file → DB ping → yield → dispose; `app.state.public_key_bytes` set for Story 2.1
- `tests/test_health.py` updated — `autouse` fixture patches `check_db_connectivity`; both health tests pass without needing a running DB
- `tests/test_startup.py` created — 6 tests: 3 Settings unit tests, 1 custom-path test, 2 lifespan failure tests (FileNotFoundError + OperationalError) using direct `lifespan(app)` context manager
- Verified in Docker: startup logs confirm all 4 JSON events; `GET /health` → `{"status":"ok"}`; `sk_live_*` key → `ValidationError` at startup
- `uv run ruff check .` — zero violations; `uv run pytest -v` — 22/22 passed

### File List

**New:**
- `app/config.py`
- `tests/test_startup.py`

**Modified:**
- `app/main.py` (full lifespan, JSON logging via `pythonjsonlogger.json`)
- `app/db/session.py` (lazy engine init, `pool_pre_ping=True`, `dispose_engine`)
- `tests/test_health.py` (`autouse` fixture patching `check_db_connectivity`)

## Change Log

- 2026-06-21: Story 1.4 created — FastAPI bootstrap and startup validation (Sonnet 4.6)
- 2026-06-21: Story 1.4 implemented — app/config.py, refactored session.py, lifespan in main.py, 6 startup tests, 22/22 passing (Sonnet 4.6)
