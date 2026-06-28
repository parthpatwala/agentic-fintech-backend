---
baseline_commit: 9c945c7
---

# Story 5.1: Automated Pytest Test Suite

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want a comprehensive pytest suite that covers all cryptographic paths, API endpoint contracts, and database interaction assertions,
So that I can verify the entire system's correctness — including all error conditions — with a single `pytest` command.

## Acceptance Criteria

**Given** the test environment has `TEST_DATABASE_URL` set to a test database
**When** `pytest` is executed from the project root
**Then** all tests pass with zero failures
**And** the development database is never read from or written to during the test run

Cryptographic path coverage (FR-16) — all 6 cases tested explicitly:
- Valid EdDSA mandate with correct key → dependency returns `(raw_jwt, payload)` tuple
- JWT signed with wrong private key → HTTP 401
- JWT with tampered payload → HTTP 401
- Request body missing `payment_mandate` field → HTTP 422
- JWT with `alg: "HS256"` → HTTP 401
- Valid JWT missing `amount` field in payload → HTTP 422

API endpoint coverage (FR-17):
- `GET /.well-known/ucp` → HTTP 200, `version == "2026-04-08"`, both capabilities present, `signing_keys[0].crv == "Ed25519"`, catalog has 5 items
- `POST /api/checkout` happy path → HTTP 201, `total_amount` computed correctly
- `POST /api/checkout` empty items → HTTP 422
- `POST /api/checkout` duplicate `session_id` → HTTP 409
- `POST /api/complete` happy path → HTTP 200, all four response fields present
- `POST /api/complete` unknown `session_id` → HTTP 404, no Stripe call
- `POST /api/complete` already-settled session → HTTP 409, no Stripe call
- `POST /api/complete` Stripe SDK raises → HTTP 502

DB interaction coverage (FR-18) — each assertion checks exact record contents:
- After `POST /api/checkout`: `invoices` row has `status == "pending"` and correct `total_amount`
- After successful `POST /api/complete`: `invoices` row has `status == "settled"` and non-null `stripe_payment_intent_id`
- After successful `POST /api/complete`: `mandate_audit` row exists with correct `session_id` and non-empty `mandate_jwt_hash`
- After Stripe failure on `POST /api/complete`: `invoices.status` remains `"pending"` and no `mandate_audit` row exists

## Tasks / Subtasks

- [x] T1: Add `TEST_DATABASE_URL` to `.env.example` and publish Postgres port in `docker-compose.yml` for host-side test access
- [x] T2: Extend `tests/conftest.py` with session-scoped test DB fixtures (engine init, schema recreate, per-test cleanup)
- [x] T3: Create `tests/test_db_integration.py` with FR-18 integration tests (real PostgreSQL, mocked Stripe only)
- [x] T4: Add `@pytest.mark.integration` marker; register in `pyproject.toml`; skip integration tests when `TEST_DATABASE_URL` unset
- [x] T5: Audit existing suite against FR-16/FR-17 checklist — add any missing cases without duplicating existing tests
- [x] T6: Verify full suite passes (`uv run pytest tests/ -q`) with and without `TEST_DATABASE_URL`
- [x] T7: Ruff clean (`uv run ruff check app/ tests/`)

### Review Findings

- [x] [Review][Patch] Dev DB guard uses substring match and rejects valid test DB names like `my_fintech_db` [tests/conftest.py:34]
- [x] [Review][Defer] `session.commit()` before Stripe widens duplicate-settlement TOCTOU window [app/routers/complete.py:42] — deferred, prototype scope; needs `SELECT FOR UPDATE` for production
- [x] [Review][Defer] Redundant `session.commit()` after `session.begin()` context exits [app/routers/complete.py:96] — deferred, pre-existing from Story 4.2 review patch
- [x] [Review][Defer] Publishing host port `5432:5432` may conflict with local Postgres installations [docker-compose.yml:11] — deferred, documented env concern

---

## Developer Context

### Scope Boundary — What This Story Owns vs. What Already Exists

**Already implemented (91 tests passing as of baseline `9c945c7`) — DO NOT rewrite:**

| Module | Tests | FR Coverage |
|---|---|---|
| `tests/test_crypto.py` | 15 | FR-16 (all 6 crypto paths + log assertions) |
| `tests/test_discovery.py` | 10 | FR-17 discovery profile |
| `tests/test_checkout.py` | 15 | FR-17 checkout HTTP paths (mocked DB) |
| `tests/test_complete.py` | 9 | FR-17 complete HTTP paths (mocked DB + mocked Stripe) |
| `tests/test_settlement.py` | 6 | Stripe service unit tests |
| `tests/test_startup.py` | 8 | Lifespan validation |
| `tests/test_state_init.py` | 12 | Catalog/JWK startup |
| `tests/test_health.py` | 3 | Health endpoint |
| `tests/test_models.py` | 14 | ORM model tests |

**Explicitly deferred from Stories 3.2 and 4.2 — THIS story delivers:**

> "Full DB assertion tests (with `TEST_DATABASE_URL`) are implemented in Story 5.1."

**Out of scope for Story 5.1:**
- `scripts/agent_client.py` → Story 5.2
- README / structured logging → Story 5.3
- `tests/test_agent_client.py` → Story 5.2 (architecture lists it; not required for FR-16–18)

### The Core Deliverable: FR-18 Integration Test Infrastructure

Stories 3.2 and 4.2 intentionally use mocked `AsyncSession` because no test DB existed. Story 5.1 adds:

1. **`TEST_DATABASE_URL`** — separate DSN pointing to a dedicated test database (not `fintech_db`)
2. **Host-accessible Postgres** — `docker-compose.yml` must expose port `5432` so host-side `pytest` can connect
3. **Session-scoped schema recreation** — drop/create all tables once per pytest session via `Base.metadata`
4. **Per-test table truncation** — clean slate before each integration test
5. **`tests/test_db_integration.py`** — end-to-end HTTP tests that write/read real PostgreSQL rows

### Infrastructure Changes (T1)

**`.env.example` — add:**

```bash
# Separate test database — used ONLY by pytest integration tests (Story 5.1+)
# Hostname must be "localhost" when running pytest on the host machine
# Create the database once: docker compose exec postgres psql -U postgres -c "CREATE DATABASE fintech_test_db;"
TEST_DATABASE_URL=postgresql+asyncpg://postgres:changeme@localhost:5432/fintech_test_db
```

**`docker-compose.yml` — add to `postgres` service:**

```yaml
ports:
  - "5432:5432"
```

Without port publishing, host-side `pytest` cannot reach the Compose Postgres instance. This is the fix for the deferred item in `deferred-work.md`: *"DATABASE_URL hostname unusable from host"*.

**Do NOT change `DATABASE_URL`** — it stays `postgres:5432` for the app container. Only `TEST_DATABASE_URL` uses `localhost`.

### Test DB Fixture Design (T2) — EXACT PATTERN

Extend `tests/conftest.py`. Keep existing `ed25519_key_pair` fixture unchanged.

```python
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.db import Base

pytest_plugins = []  # do not add unless needed


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests requiring TEST_DATABASE_URL and live PostgreSQL",
    )


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set — integration tests skipped")
    if "fintech_db" in url and "fintech_test_db" not in url:
        pytest.fail(
            "TEST_DATABASE_URL must point to a dedicated test database "
            "(e.g. fintech_test_db), not the development fintech_db"
        )
    return url


@pytest.fixture(scope="session")
async def test_engine(test_database_url):
    engine = create_async_engine(test_database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def integration_db_session(test_engine):
    """Yield a real AsyncSession; truncate tables before and after each test."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(text(f"TRUNCATE {table.name} RESTART IDENTITY CASCADE"))
        await session.commit()
        yield session
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(text(f"TRUNCATE {table.name} RESTART IDENTITY CASCADE"))
        await session.commit()
```

**Critical isolation rules:**
- Integration tests MUST use `integration_db_session` — never `DATABASE_URL` / dev DB
- Guard against accidental dev DB use: fail fast if `TEST_DATABASE_URL` contains `fintech_db` without `_test_`
- Unit tests (existing modules) continue using mocked sessions — no regression

### Integration Test Module (T3) — `tests/test_db_integration.py`

Mark entire module: `pytestmark = pytest.mark.integration`

**Required test cases (map directly to FR-18 ACs):**

| Test function | AC | Key assertions |
|---|---|---|
| `test_checkout_persists_pending_invoice` | Checkout DB write | POST `/api/checkout` → query `invoices` by `session_id`; assert `status=="pending"`, `total_amount` matches computed sum, `agent_id`, `currency`, `items` JSONB |
| `test_complete_settles_invoice_and_writes_audit` | Settlement DB write | Seed invoice via checkout POST → POST `/api/complete` with valid JWT → query `invoices` assert `status=="settled"`, non-null `stripe_payment_intent_id`, non-null `settled_at`; query `mandate_audit` assert row exists with matching `session_id`, 64-char hex `mandate_jwt_hash` |
| `test_complete_stripe_failure_leaves_invoice_pending` | Rollback on 502 | Seed invoice → mock Stripe to raise → POST complete → assert invoice still `pending`, zero `mandate_audit` rows |
| `test_checkout_duplicate_session_id_returns_409_in_db` | Idempotency | POST checkout twice with same `session_id` → 409 on second; assert exactly one invoice row |

**Integration test setup pattern:**

Integration tests need the FastAPI app wired to the real test DB, not mocks. Override `get_db_session` to yield from `integration_db_session`:

```python
@pytest.fixture
def integration_client(integration_db_session, ed25519_key_pair):
    """AsyncClient with real DB session and injected public key."""
    _, public_key, _ = ed25519_key_pair
    app.state.public_key = public_key

    async def _get_session():
        yield integration_db_session

    app.dependency_overrides[get_db_session] = _get_session
    yield ASGITransport(app=app)  # or yield client factory
    app.dependency_overrides.pop(get_db_session, None)
    del app.state.public_key
```

**Stripe MUST be mocked** in integration tests — only DB is real:

```python
with patch(
    "app.routers.complete.settlement_service.create_payment_intent",
    new_callable=AsyncMock,
    return_value=mock_payment_intent,
):
    ...
```

Never call real Stripe in DB integration tests. Stripe behavior is already covered in `test_complete.py` and `test_settlement.py`.

**JWT signing for integration tests:**

Reuse token helpers from `test_crypto.py` or `test_complete.py`. Ensure:
- `session_id` in JWT payload matches checkout request `session_id`
- `amount` matches invoice `total_amount`
- `agent_id` matches checkout `agent_id`
- Include `exp` claim (required by `verify_mandate`)

**DB query helpers — use SQLAlchemy directly:**

```python
from sqlalchemy import select
from app.models.db import Invoice, MandateAudit

async def _get_invoice(session, session_id):
    result = await session.execute(
        select(Invoice).where(Invoice.session_id == session_id)
    )
    return result.scalar_one_or_none()

async def _count_audits(session, session_id):
    result = await session.execute(
        select(MandateAudit).where(MandateAudit.session_id == session_id)
    )
    return len(result.scalars().all())
```

Import ORM models directly in tests — this is the one exception to "no DB access outside invoice.py" (tests are not production code).

### FR-16 / FR-17 Audit (T5) — Gap Check

Run this checklist before marking done. Add tests ONLY if a case is missing:

**FR-16 (all present in `test_crypto.py`):**
- [x] Valid mandate → dependency passes (`test_mandate_dep_valid_returns_404_when_no_invoice`)
- [x] Wrong key → 401 (`test_mandate_dep_wrong_key_returns_401`)
- [x] Tampered → 401 (`test_mandate_dep_tampered_payload_returns_401`)
- [x] Missing field → 422 (`test_mandate_dep_missing_payment_mandate_returns_422`)
- [x] HS256 → 401 (`test_mandate_dep_alg_hs256_returns_401`)
- [x] Missing amount → 422 (`test_mandate_dep_missing_amount_returns_422`)

**FR-17 (all present across existing modules):**
- [x] Discovery profile content (`test_discovery.py`)
- [x] Checkout happy + empty items + duplicate session (`test_checkout.py`)
- [x] Complete happy + 404 + 409 + 502 (`test_complete.py`)

**Likely no new FR-16/FR-17 tests needed** unless audit reveals a gap. Focus effort on FR-18 integration tests.

### pytest Configuration (T4)

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "integration: tests requiring TEST_DATABASE_URL and live PostgreSQL",
]
```

**Running tests:**

```bash
# Unit tests only (no Postgres required) — skips integration
uv run pytest tests/ -q -m "not integration"

# Full suite including integration (requires Postgres + TEST_DATABASE_URL)
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:changeme@localhost:5432/fintech_test_db
docker compose up -d postgres
docker compose exec postgres psql -U postgres -c "CREATE DATABASE fintech_test_db;"  # once
uv run pytest tests/ -q
```

When `TEST_DATABASE_URL` is unset, integration tests skip cleanly (not fail). CI can run unit tests without Postgres; full suite runs when test DB is available.

---

## Architecture Compliance

| Requirement | How Story 5.1 Complies |
|---|---|
| Separate `TEST_DATABASE_URL` | New env var; dedicated `fintech_test_db` database |
| Dev DB never touched | Guard in fixture; truncate-only on test DB |
| Schema recreation per session | `Base.metadata.drop_all/create_all` in session fixture |
| Test naming convention | `test_<behaviour>_<condition>()` — e.g. `test_checkout_persists_pending_invoice` |
| Service boundaries unchanged | Integration tests exercise HTTP layer; no PyJWT/Stripe/DB code moved |
| Mocked Stripe in integration tests | Only PostgreSQL is real; Stripe always patched |

### Mandatory Patterns to Preserve

- **Existing unit tests stay mocked** — do not refactor `test_checkout.py` or `test_complete.py` to use real DB; add parallel integration tests in `test_db_integration.py`
- **ASGITransport skips lifespan** — continue injecting `app.state.public_key` manually in integration fixtures (same as `test_crypto.py`)
- **Error response shape** — assert `detail.reason` keys match existing patterns (`session_not_found`, `session_already_settled`, etc.)

---

## File Structure Requirements

| File | Action | Notes |
|---|---|---|
| `.env.example` | UPDATE | Add `TEST_DATABASE_URL` with localhost DSN |
| `docker-compose.yml` | UPDATE | Publish `5432:5432` on postgres service |
| `tests/conftest.py` | UPDATE | Add integration fixtures + pytest marker registration |
| `tests/test_db_integration.py` | CREATE | FR-18 DB integration tests |
| `pyproject.toml` | UPDATE | Register `integration` marker |

**Do NOT modify:** `app/` production code unless a testability bug is discovered. This story is test infrastructure + integration tests only.

---

## Testing Requirements

**Pre-implementation baseline:** 91 tests pass (`uv run pytest tests/ -q`)

**Post-implementation targets:**
- All 91 existing tests still pass unchanged
- 4+ new integration tests in `test_db_integration.py`
- `uv run pytest tests/ -m "not integration"` passes without `TEST_DATABASE_URL`
- `uv run pytest tests/` passes with `TEST_DATABASE_URL` set and Postgres running
- Ruff clean on all modified files

**Test execution commands for dev agent:**

```bash
# Quick validation (no DB)
uv run pytest tests/ -q -m "not integration"

# Full validation (requires docker compose postgres + TEST_DATABASE_URL)
uv run pytest tests/ -q

# Lint
uv run ruff check app/ tests/
```

---

## Previous Story Intelligence (Epic 4 — Story 4.2)

Key learnings that affect integration test design:

- **`await session.commit()` after settlement writes** — complete handler commits after `session.begin()` block; integration tests must account for this when querying post-request state. Use a fresh query after HTTP response, not stale session objects.
- **PaymentIntent status guard** — handler returns 502 if Stripe returns non-`succeeded` status; integration Stripe-failure test should mock `StripeError`, not just bad status (status guard is covered in unit tests).
- **Amount in cents** — `$79.99` → `7999`; integration checkout with single item at `79.99` simplifies mandate amount alignment.
- **SHA-256 mandate hash** — 64-char hex of raw JWT string; integration test should assert exact hash matches `hashlib.sha256(token.encode()).hexdigest()`.
- **Review deferrals** — TOCTOU race and orphaned Stripe charges are out of scope; do not add concurrency integration tests.

From Story 3.2:
- Checkout `total_amount` computation: `sum(quantity × unit_price)` — use simple integers in integration tests to avoid float precision issues (e.g. 1 × 79.99).
- Duplicate `session_id` → 409 via PK violation — integration test verifies only one row persists.

---

## Git Intelligence Summary

Recent commits (`9c945c7` → settlement complete):
- Full commerce cycle implemented: discovery → checkout → complete
- Test pattern established: `ASGITransport` + `app.dependency_overrides[get_db_session]` + service patches
- 91 tests across 9 modules; all use mocks except ORM model tests
- `conftest.py` is minimal (only `ed25519_key_pair`) — Story 5.1 expands it significantly
- Deferred-work.md explicitly tracks `TEST_DATABASE_URL` as Story 5.1 deliverable

---

## Latest Tech Information

**pytest-asyncio (installed):** `asyncio_mode = "auto"` already configured. Session-scoped async fixtures require `@pytest.fixture(scope="session")` with async def — supported in pytest-asyncio 0.23+.

**SQLAlchemy 2.0 async + asyncpg:**
- `create_async_engine("postgresql+asyncpg://...")` — same driver as production
- `Base.metadata.create_all/drop_all` via `conn.run_sync()` — no Alembic needed for test schema (tables match ORM models)
- `TRUNCATE ... RESTART IDENTITY CASCADE` — faster than drop/recreate per test; handles FK order via `CASCADE`

**PostgreSQL 17 (docker-compose):** Alpine image; default port 5432. Test DB creation is one-time manual step or can be scripted in fixture with `CREATE DATABASE IF NOT EXISTS` equivalent (`SELECT 1 FROM pg_database WHERE datname = 'fintech_test_db'`).

---

## Project Context Reference

No `project-context.md` found. Binding sources:
- [epics.md §Story 5.1](_bmad-output/planning-artifacts/epics.md) — FR-16, FR-17, FR-18 acceptance criteria
- [architecture.md §Test isolation](_bmad-output/planning-artifacts/architecture.md) — `TEST_DATABASE_URL` + schema recreation
- [deferred-work.md](_bmad-output/implementation-artifacts/deferred-work.md) — host-side Postgres access deferred to this story
- [Story 3.2 artifact](_bmad-output/implementation-artifacts/3-2-checkout-session-endpoint.md) — DB assertions explicitly deferred here
- [Story 4.2 artifact](_bmad-output/implementation-artifacts/4-2-mandate-gated-settlement-endpoint.md) — DB assertions explicitly deferred here

---

## Dev Agent Record

### Agent Model Used

Composer

### Debug Log References

| Step | Issue | Fix |
|------|-------|-----|
| T3 | Session-scoped async engine caused asyncpg "different loop" RuntimeError | Switched to function-scoped engine with per-request sessions via dependency override |
| T3 | Reused single session across HTTP requests caused "transaction already begun" on complete | Per-request sessions from shared engine (mirrors production `get_db_session`) |
| T3 | Integration test exposed production bug: `get_invoice` autobegin + `session.begin()` conflict | Added `await session.commit()` after status check in `complete.py` |
| T6 | `test_complete_commits_session_after_settlement` expected 1 commit | Updated to expect 2 commits (read txn close + settlement persist) |

### Completion Notes List

- **T1** — Added `TEST_DATABASE_URL` to `.env.example`; published `5432:5432` on postgres service in `docker-compose.yml`.
- **T2** — Extended `conftest.py` with `test_database_url`, `db_engine`, and `db_engine_truncated` fixtures; dev DB guard fails if URL points at `fintech_db`.
- **T3** — Created `tests/test_db_integration.py` with 4 FR-18 tests: checkout persist, settlement + audit, Stripe failure rollback, duplicate session_id idempotency.
- **T4** — Registered `integration` marker in `pyproject.toml` and `pytest_configure`; integration tests skip when `TEST_DATABASE_URL` unset.
- **T5** — Audited FR-16/FR-17 checklist; all cases already covered by existing 91 unit tests; no duplicates added.
- **T6** — 95 passed with integration (`TEST_DATABASE_URL` set); 91 passed unit-only (`-m "not integration"`).
- **T7** — Ruff clean.
- **Production fix** — `complete.py` commits read transaction before Stripe/write path; fixes real DB session conflict discovered by integration tests.

### File List

| File | Action |
|------|--------|
| `.env.example` | MODIFIED |
| `docker-compose.yml` | MODIFIED |
| `pyproject.toml` | MODIFIED |
| `tests/conftest.py` | MODIFIED |
| `tests/test_db_integration.py` | CREATED |
| `tests/test_complete.py` | MODIFIED |
| `app/routers/complete.py` | MODIFIED |

### Change Log

- Story 5.1 implementation complete (Date: 2026-06-28): FR-18 integration test infrastructure with `TEST_DATABASE_URL`; 4 new DB integration tests; production session transaction fix in complete handler.

---

## References

- [Source: epics.md#Story 5.1] — FR-16, FR-17, FR-18 acceptance criteria
- [Source: architecture.md#Test isolation] — separate TEST_DATABASE_URL, schema recreation per session
- [Source: architecture.md#Format Patterns] — pytest naming conventions
- [Source: prd.md §4.6] — FR-16 through FR-18 functional requirements
- [Source: Story 3.2] — checkout DB assertions deferred to Story 5.1
- [Source: Story 4.2] — complete DB assertions deferred to Story 5.1
- [Source: deferred-work.md] — DATABASE_URL host access, TEST_DATABASE_URL addition

---

## Story Completion Status

- Status: done
- Ultimate context engine analysis completed - comprehensive developer guide created
- Implementation complete: 95 tests pass with integration DB; FR-16/17/18 satisfied
- Code review complete (2026-06-28): 1 patch applied (exact DB name guard)
