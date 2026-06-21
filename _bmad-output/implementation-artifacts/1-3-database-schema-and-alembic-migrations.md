---
baseline_commit: d960de8019a154b950b85b91334fb42820c53dc4
---

# Story 1.3: Database Schema & Alembic Migrations

Status: done

## Story

As a developer,
I want the PostgreSQL schema defined in SQLAlchemy ORM models and managed by Alembic,
So that the database tables are version-controlled and automatically applied on container startup.

## Acceptance Criteria

**Given** the `postgres` service is running and `DATABASE_URL` is set
**When** `docker compose exec app alembic upgrade head` is executed
**Then** both the `invoices` and `mandate_audit` tables are created without errors

**And** the `invoices` table has exactly these columns:
- `session_id` — UUID, PRIMARY KEY
- `agent_id` — VARCHAR, NOT NULL
- `items` — JSONB, NOT NULL
- `total_amount` — NUMERIC(10,2), NOT NULL
- `currency` — VARCHAR(3), NOT NULL
- `status` — VARCHAR(20), NOT NULL, DEFAULT `'pending'`
- `stripe_payment_intent_id` — VARCHAR, NULLABLE
- `created_at` — TIMESTAMPTZ, NOT NULL, DEFAULT NOW()
- `settled_at` — TIMESTAMPTZ, NULLABLE

**And** the `mandate_audit` table has exactly these columns:
- `id` — SERIAL, PRIMARY KEY
- `session_id` — UUID, NOT NULL, FK → `invoices.session_id`
- `agent_id` — VARCHAR, NOT NULL
- `mandate_jwt_hash` — VARCHAR(64), NOT NULL
- `settlement_timestamp` — TIMESTAMPTZ, NOT NULL, DEFAULT NOW()

**Given** `alembic downgrade -1` is executed
**When** the command completes
**Then** both tables are dropped and the schema returns to its prior state

**And** running `alembic upgrade head` twice in a row produces no errors (idempotent via Alembic's version tracking)

## Tasks / Subtasks

- [x] Task 1: Remove `alembic/` from `.dockerignore` so migrations run inside the app container (deferred decision from Story 1.2 review)
  - [x] Delete the `alembic/` exclusion block from `.dockerignore`
  - [x] Verify the remaining `.dockerignore` still excludes `keys/`, `.env`, `.venv/`, `tests/`, etc.

- [x] Task 2: Initialize Alembic with the async template
  - [x] Delete `alembic/.gitkeep` — the directory must be empty for `alembic init` to succeed
  - [x] Run `uv run alembic init -t async alembic` — generates `alembic.ini` + `alembic/env.py` + `alembic/script.py.mako` + `alembic/versions/`
  - [x] Update `alembic.ini`: `prepend_sys_path = .` already set by async template; placeholder `sqlalchemy.url` in place; real URL injected via env in `env.py`
  - [x] `alembic/versions/` already excluded from ruff in `pyproject.toml` — no further change needed

- [x] Task 3: Write `app/models/db.py` — SQLAlchemy 2.0 ORM mapped classes
  - [x] Defined `Base(DeclarativeBase)` — the single metadata object Alembic imports
  - [x] Defined `Invoice` mapped class with all 9 columns (UUID PK, JSONB items, NUMERIC total, TIMESTAMPTZ created/settled)
  - [x] Defined `MandateAudit` mapped class with all 5 columns including FK `fk_mandate_audit_session_id`
  - [x] Index definitions: `ix_invoices_status`, `ix_mandate_audit_session_id` via `__table_args__`

- [x] Task 4: Write `app/db/session.py` — async engine + session factory + FastAPI dependency
  - [x] `create_async_engine` reading `DATABASE_URL` from `os.environ`
  - [x] `async_sessionmaker` with `expire_on_commit=False`
  - [x] `get_db_session()` async generator dependency with proper type annotation

- [x] Task 5: Rewrite `alembic/env.py` for the async pattern
  - [x] Imports `Base` from `app.models.db`; sets `target_metadata = Base.metadata`
  - [x] Overrides `sqlalchemy.url` from `os.environ["DATABASE_URL"]` at top of file
  - [x] Uses `async_engine_from_config` with `pool.NullPool`
  - [x] `asyncio.run(run_async_migrations())` in `run_migrations_online()`
  - [x] `connection.run_sync(do_run_migrations)` bridges async↔sync

- [x] Task 6: Write the initial migration `alembic/versions/001_initial_schema.py`
  - [x] `upgrade()`: creates `invoices` then `mandate_audit` with FK constraint and both indexes
  - [x] `downgrade()`: drops `mandate_audit` first, then `invoices` (FK-safe reverse order)
  - [x] `revision = "001"`, `down_revision = None`

- [x] Task 7: Verify — bring up the stack and run migration checks
  - [x] `docker compose up -d --build` — both services healthy ✅
  - [x] `docker compose exec app .venv/bin/alembic upgrade head` — exits 0, both tables created ✅
  - [x] Second `upgrade head` — exits 0, idempotent (no output = no changes) ✅
  - [x] `docker compose exec app .venv/bin/alembic downgrade -1` — exits 0, both tables dropped ✅
  - [x] Third `upgrade head` — exits 0, tables recreated ✅
  - [x] `\d invoices` / `\d mandate_audit` — all columns, constraints, indexes match spec exactly ✅
  - [x] `docker compose down -v` — clean teardown ✅
  - [x] `uv run ruff check .` — zero violations ✅
  - [x] `uv run pytest -v` — 16/16 passed, zero regressions ✅

## Dev Notes

### Critical Decision from Story 1.2 Deferred Work

The Story 1.2 code review explicitly deferred this decision:

> **`alembic/` excluded from image** — `.dockerignore` excludes `alembic/` so `docker compose exec app alembic upgrade head` would fail; by design for this story. **Story 1.3 must decide: run migrations from host or add alembic back to image.**

**Decision made for Story 1.3:** Remove `alembic/` from `.dockerignore`. Run migrations inside the container via `docker compose exec app alembic upgrade head`. Rationale:
- The container already has `uv sync --no-dev` installed packages including `alembic`.
- No host-side PostgreSQL client or separate `DATABASE_URL` needed.
- The `DATABASE_URL` inside the container already points to `postgres:5432` (the Compose service name) — no URL reconfiguration required.
- Simpler developer experience: one command, no extra env var.

### Critical: Alembic Async env.py Pattern (from Story 1.1 deferred work)

The default `alembic init` template generates a **synchronous** `env.py` that calls `engine_from_config()`. This does NOT work with `asyncpg` — it fails at migration time with a driver error, not at import time.

The deferred work from Story 1.1 captured exactly this issue:
> **Alembic async env.py** — `asyncpg` is async-only; no sync PostgreSQL driver present. Story 1.3 must rewrite Alembic's generated `env.py` to use async pattern (`asyncio.run()` + `run_sync(context.run_migrations)`). Default `alembic init` template will not work out of the box.

**Use the `-t async` template**: `uv run alembic init -t async alembic` — this generates the correct starting point. Then modify it to:
1. Import `Base.metadata` from `app.models.db`
2. Override `sqlalchemy.url` from `os.environ["DATABASE_URL"]`

### Exact `alembic/env.py` content

```python
import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.models.db import Base  # must be imported BEFORE target_metadata is set

config = context.config
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Why `NullPool`?** Prevents Alembic from keeping a connection pool open after the migration completes. Without it, the process may hang waiting for pooled connections to close.

**Why override URL in Python vs `alembic.ini`?** `alembic.ini` supports `%(env_var)s` interpolation but only via `[DEFAULT]` section. Reading from `os.environ` directly in `env.py` is simpler, explicit, and works identically in all contexts (CLI, `docker compose exec`, test fixtures).

### Exact `app/models/db.py` content

```python
import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    items: Mapped[dict] = mapped_column(JSONB, nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    mandate_audits: Mapped[list["MandateAudit"]] = relationship(back_populates="invoice")

    __table_args__ = (Index("ix_invoices_status", "status"),)


class MandateAudit(Base):
    __tablename__ = "mandate_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.session_id", name="fk_mandate_audit_session_id"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    mandate_jwt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    settlement_timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    invoice: Mapped["Invoice"] = relationship(back_populates="mandate_audits")

    __table_args__ = (Index("ix_mandate_audit_session_id", "session_id"),)
```

**ORM pattern notes:**
- Use SQLAlchemy 2.0 `Mapped[]` + `mapped_column()` — not the legacy `Column()` style.
- `UUID(as_uuid=True)` — stores as native PostgreSQL UUID and returns Python `uuid.UUID` objects.
- `JSONB` — from `sqlalchemy.dialects.postgresql`; not `JSON`. JSONB is indexed in PostgreSQL.
- `TIMESTAMP(timezone=True)` — always timezone-aware; matches `TIMESTAMPTZ` in the DDL.
- `server_default=func.now()` — sets default at the DB server level, not the ORM layer. This means the value is set correctly even when the record is inserted without `created_at` specified.
- `Numeric(10, 2)` — matches `NUMERIC(10,2)` from the spec; Python `Mapped[float]` is fine for reads.
- FK constraint name `fk_mandate_audit_session_id` — explicit name matches architecture naming convention.
- Index names `ix_invoices_status`, `ix_mandate_audit_session_id` — match architecture naming convention.

### Exact `app/db/session.py` content

```python
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

**Notes:**
- `expire_on_commit=False` — prevents SQLAlchemy from expiring ORM attributes after `commit()`, which would cause lazy-load errors in async context.
- `echo=False` — no SQL logging to stdout by default; enable for debugging with `echo=True`.
- Direct `os.environ["DATABASE_URL"]` — pydantic-settings `BaseSettings` integration happens in Story 1.4. Using `os.environ` directly here keeps this story self-contained.
- The `get_db_session` dependency is an async generator — FastAPI handles the `yield` lifecycle automatically.

### Exact `alembic/versions/001_initial_schema.py` content

```python
"""initial schema: invoices and mandate_audit tables

Revision ID: 001
Revises:
Create Date: 2026-06-21

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="pending"
        ),
        sa.Column("stripe_payment_intent_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("settled_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_invoices_status", "invoices", ["status"])

    op.create_table(
        "mandate_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.session_id", name="fk_mandate_audit_session_id"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("mandate_jwt_hash", sa.String(64), nullable=False),
        sa.Column(
            "settlement_timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_mandate_audit_session_id", "mandate_audit", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_mandate_audit_session_id", table_name="mandate_audit")
    op.drop_table("mandate_audit")
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_table("invoices")
```

**Migration notes:**
- Tables created in FK dependency order: `invoices` first, then `mandate_audit`.
- `downgrade()` drops in reverse order: `mandate_audit` first, then `invoices`.
- FK constraint name is explicit: `fk_mandate_audit_session_id` — matches architecture spec.
- `server_default=sa.text("NOW()")` in the migration matches `server_default=func.now()` in the ORM model.
- `sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True)` — equivalent to `SERIAL` in PostgreSQL.

### `alembic.ini` key settings

After running `alembic init -t async alembic`, update `alembic.ini`:

```ini
[alembic]
script_location = alembic
prepend_sys_path = .          # ← CRITICAL: allows `from app.models.db import Base` in env.py
sqlalchemy.url = driver://user:pass@localhost/dbname   # ← placeholder; overridden in env.py
```

The `prepend_sys_path = .` tells Alembic to add the project root (`.`) to `sys.path` before importing anything. Without this, `from app.models.db import Base` in `env.py` fails with `ModuleNotFoundError`.

### Story 1.1 and 1.2 Learnings (carry forward)

- **Keys are PKCS8/PEM format** — `keys/private_key.pem` and `keys/public_key.pem` regenerated in Story 1.1. Do NOT touch them.
- **`ruff` S101 suppressed in `tests/**/*.py`** — already set via `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml`.
- **Ruff excludes `_bmad`, `_bmad-output`, `.agents`, `.venv`, `alembic/versions`** — the migration file at `alembic/versions/001_initial_schema.py` is excluded from ruff linting by this existing rule.
- **`uv run` prefix** — all CLI commands require `uv run <tool>` or running inside the activated `.venv`. Use `docker compose exec app alembic upgrade head` (not `uv run`) inside the container since `alembic` is in `.venv/bin/`.
- **Docker Compose v2 — no `version:` key** — already established in Story 1.2; do not add it.
- **`start_period: 30s`** — already in Postgres healthcheck from Story 1.2 code review patch.

### Architecture Compliance

- **`app/models/db.py`** — this is the ORM models file. Alembic `env.py` imports `Base` from here. All future stories that write to the DB use these ORM classes.
- **`app/db/session.py`** — the async session dependency. Future route handlers inject this via `Depends(get_db_session)`.
- **Service boundary**: No route handler calls the engine directly. All DB access goes through `app/services/invoice.py` (Story 3.2+), which accepts an `AsyncSession` injected by the dependency.
- **`alembic/versions/` is ruff-excluded** — the migration file does not need to pass ruff; it is already excluded via `pyproject.toml`.

### Key Commands for Verification

```bash
# Build and start with the new migration files included
docker compose up -d --build

# Run migration — both tables created
docker compose exec app alembic upgrade head

# Idempotency check — must exit 0 with no changes
docker compose exec app alembic upgrade head

# Downgrade — both tables dropped
docker compose exec app alembic downgrade -1

# Re-apply — must succeed again
docker compose exec app alembic upgrade head

# Verify tables exist
docker compose exec postgres psql -U postgres -d fintech_db -c "\dt"

# Verify invoices schema
docker compose exec postgres psql -U postgres -d fintech_db -c "\d invoices"

# Verify mandate_audit schema
docker compose exec postgres psql -U postgres -d fintech_db -c "\d mandate_audit"

# Verify ruff still passes from host
source $HOME/.local/bin/env
uv run ruff check .

# Teardown
docker compose down -v
```

### Gotchas and Edge Cases

1. **`alembic init` fails if directory is not empty** — `alembic/.gitkeep` must be deleted first. The `alembic/` directory itself can remain; Alembic checks for emptiness of the directory, not its existence. Actually: `alembic init` will error if the target directory already exists with content. Safest: `rm alembic/.gitkeep && rmdir alembic && uv run alembic init -t async alembic`.

2. **`from app.models.db import Base` in env.py** — requires `prepend_sys_path = .` in `alembic.ini`. Without it, the import fails when running `alembic` from any directory. This is the single most common async Alembic setup failure.

3. **DATABASE_URL inside Docker uses service name** — when running `docker compose exec app alembic upgrade head`, the `DATABASE_URL` env var in the container already points to `postgres:5432` (correct). No URL substitution needed.

4. **`pool.NullPool` is mandatory** — the default pool class leaves connections open after migration, which can cause the `alembic` process to hang. `NullPool` closes connections immediately.

5. **Migration order matters** — `mandate_audit` has a FK to `invoices.session_id`. Always create `invoices` first in `upgrade()` and drop `mandate_audit` first in `downgrade()`.

6. **Ruff will NOT lint `alembic/versions/`** — already excluded in `pyproject.toml`. Run `ruff check .` freely without false positives from migration files.

7. **`alembic.ini` is at the project root** — it is NOT excluded by `.dockerignore` (only `alembic/` was excluded, and we're removing that exclusion). After this story, `alembic.ini` and `alembic/` are both in the Docker image.

8. **`uv run alembic` vs bare `alembic`** — on the host, use `uv run alembic` or activate the venv first. Inside the container, `alembic` is directly in `.venv/bin/alembic` which is on `PATH` after `uv sync`.

### References

- [Source: architecture.md#Data Architecture] — SQLAlchemy 2.0 async, asyncpg, Alembic, NullPool, per-request session scoping
- [Source: architecture.md#Database schema] — exact SQL DDL for both tables
- [Source: architecture.md#Naming Conventions] — FK name `fk_mandate_audit_session_id`, index names `ix_invoices_status`, `ix_mandate_audit_session_id`
- [Source: epics.md#Story 1.3] — all acceptance criteria
- [Source: deferred-work.md] — async env.py requirement (from Story 1.1), alembic/image decision (from Story 1.2)
- [External: alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic] — official async Alembic pattern
- [External: github.com/sqlalchemy/alembic/blob/main/alembic/templates/async/env.py] — official async env.py template

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.6 (cursor)

### Debug Log References

- `alembic upgrade head` via bare `alembic` command failed with `executable file not found in $PATH` — fixed by calling `.venv/bin/alembic` directly inside the container. `uv sync --no-dev` installs alembic into `.venv/bin/` not into the system PATH. Document in verification commands: always use `.venv/bin/alembic` for `docker compose exec`.
- Ruff `I001` import-ordering on `alembic/env.py` — fixed by `uv run ruff check --fix .` (auto-fixed import block ordering).

### Completion Notes List

- Removed `alembic/` exclusion from `.dockerignore` — resolved deferred decision from Story 1.2 code review
- Initialized Alembic with `-t async` template — `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/` all generated
- `alembic.ini`: `prepend_sys_path = .` confirmed in place (set by async template); placeholder `sqlalchemy.url` retained; real URL injected via `os.environ` in `env.py`
- `app/models/db.py`: SQLAlchemy 2.0 `Mapped[]`/`mapped_column()` style; `Invoice` (9 cols) + `MandateAudit` (5 cols); `ix_invoices_status` + `ix_mandate_audit_session_id` indexes; FK constraint `fk_mandate_audit_session_id`; bidirectional relationships
- `app/db/session.py`: async engine + `async_sessionmaker(expire_on_commit=False)` + `get_db_session()` FastAPI dependency
- `alembic/env.py`: async bridge pattern (`async_engine_from_config` + `NullPool` + `connection.run_sync`); `os.environ["DATABASE_URL"]` override; `Base.metadata` import
- `alembic/versions/001_initial_schema.py`: creates both tables in FK-safe order; `downgrade()` reverses correctly
- `tests/test_models.py`: 14 structural tests covering table names, column presence, PK types, UUID type, JSONB type, FK reference, FK constraint name, relationships, and instantiation
- Verified in Docker: `upgrade head` × 3, `downgrade -1` × 1 — all correct; `\d invoices` + `\d mandate_audit` match spec exactly

### File List

- `.dockerignore` (modified — removed `alembic/` exclusion)
- `alembic.ini` (new — generated by `alembic init -t async`)
- `alembic/env.py` (new — async pattern)
- `alembic/script.py.mako` (new — generated template)
- `alembic/README` (new — generated)
- `alembic/versions/001_initial_schema.py` (new — invoices + mandate_audit)
- `app/models/db.py` (new — Invoice + MandateAudit ORM models)
- `app/db/session.py` (new — async engine + session dependency)
- `tests/test_models.py` (new — 14 ORM structural tests)

## Change Log

- 2026-06-21: Story 1.3 implemented — Alembic async setup, ORM models, DB session, initial migration (Sonnet 4.6)
- 2026-06-21: Code review patches applied — `Mapped[float]` → `Mapped[Decimal]` for `total_amount`; added `server_default=text("'pending'")` to ORM `status` column; wrapped `connectable.dispose()` in `try/finally` in `alembic/env.py`; updated test fixture to use `Decimal("9.99")` (Sonnet 4.6)
