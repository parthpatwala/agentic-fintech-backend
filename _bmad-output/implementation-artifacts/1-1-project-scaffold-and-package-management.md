---
baseline_commit: NO_VCS
---

# Story 1.1: Project Scaffold & Package Management

Status: done

## Story

As a developer,
I want the project directory initialized with `uv`, all Python dependencies declared in `pyproject.toml`, a committed lock file, and linting configured,
So that any contributor can reproduce the exact environment with a single `uv sync` command.

## Acceptance Criteria

1. `uv sync` runs without errors from a clean clone; `.venv/` is created automatically
2. `uv.lock` is committed to version control and resolves all packages deterministically
3. `ruff check .` passes with zero violations on all scaffold code
4. `.gitignore` excludes `keys/`, `.env`, `.venv/`, `__pycache__/`, `*.pyc`, `*.pyo`, `.pytest_cache/`, `dist/`, `*.egg-info/`
5. Full directory structure exists with `__init__.py` in all Python packages: `app/`, `app/routers/`, `app/models/`, `app/services/`, `app/db/`, `tests/`, `catalog/`, `scripts/`, `alembic/`, `keys/`
6. `pyproject.toml` declares all required production and dev dependencies (see Tasks)
7. Ruff configured as a dev dependency with lint + format rules in `pyproject.toml`; `pytest` configured with `asyncio_mode = "auto"`

## Tasks / Subtasks

- [x] Task 1: Initialize project with uv (AC: 1, 2)
  - [x] From project root run: `uv init --app` — this creates `pyproject.toml`, `.python-version`, and minimal scaffold
  - [x] Delete any auto-generated `main.py` or `hello.py` from `uv init` output (we use a custom structure)
  - [x] Verify `.python-version` contains `3.12`

- [x] Task 2: Configure `pyproject.toml` with all dependencies (AC: 1, 6, 7)
  - [x] Set `[project]` metadata: name, version, description, `requires-python = ">=3.12"`
  - [x] Add all production dependencies to `[project].dependencies` (see Dev Notes for exact list)
  - [x] Add dev dependencies using PEP 735 `[dependency-groups]` table: `dev = ["ruff", "pytest", "pytest-asyncio"]`
  - [x] Add `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.format]` sections (see Dev Notes)
  - [x] Add `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and `testpaths = ["tests"]`
  - [x] Run `uv sync` — this generates `uv.lock` and installs into `.venv/`

- [x] Task 3: Create full directory structure (AC: 5)
  - [x] Create all directories listed in AC-5
  - [x] Add empty `__init__.py` to: `app/`, `app/routers/`, `app/models/`, `app/services/`, `app/db/`, `tests/`
  - [x] `catalog/`, `scripts/`, `alembic/`, `keys/` do NOT get `__init__.py` (not Python packages)
  - [x] Create placeholder files to prevent empty dirs from being ignored by git: `catalog/.gitkeep`, `scripts/.gitkeep`, `keys/.gitkeep`

- [x] Task 4: Create `.gitignore` (AC: 4)
  - [x] Create `.gitignore` at project root excluding all items listed in AC-4
  - [x] Critically: `keys/` must be excluded — contains cryptographic key files that MUST NOT be committed

- [x] Task 5: Verify linting passes (AC: 3)
  - [x] Run `uv run ruff check .` — fix any violations in scaffold code
  - [x] Run `uv run ruff format .` — apply formatting to all Python files
  - [x] Confirm `uv run ruff check .` reports zero issues after formatting

- [x] Task 6: Verify test runner works (AC: 1)
  - [x] Create `tests/__init__.py` (empty)
  - [x] Run `uv run pytest tests/ -v` — should report "no tests ran" or "0 passed" with no errors (not a failure)

### Review Findings

- [x] [Review][Decision] OpenSSH key format incompatible with PyJWT EdDSA — Resolved: regenerated keys in PKCS8/PEM format using `cryptography` library. PyJWT sign+verify round-trip confirmed working.
- [x] [Review][Patch] `keys/` gitignore rule excludes `keys/.gitkeep` — Fixed: changed `keys/` to `keys/*.pem` + `keys/*.pem.*` [`.gitignore`]
- [x] [Review][Patch] `.ruff_cache/` not in `.gitignore` — Fixed: added `.ruff_cache/` entry [`.gitignore`]
- [x] [Review][Patch] No security lint rules in ruff config — Fixed: added `"S"` to `[tool.ruff.lint].select`; `ruff check .` still passes [`pyproject.toml`]
- [x] [Review][Patch] Docker `uv sync` note missing `--no-dev` flag — Fixed: updated to `uv sync --frozen --no-cache --no-dev` [story Dev Notes]
- [x] [Review][Defer] Alembic async env.py — no sync PostgreSQL driver present; Story 1.3 must rewrite the generated `env.py` to use async Alembic pattern (`asyncio.run()` + `run_sync`) — deferred to Story 1.3
- [x] [Review][Defer] pytest exit code 5 fails default CI pipelines — no CI configured yet — deferred to post-scope CI setup story
- [x] [Review][Defer] `.env.example` absent until Story 1.2 — `.gitignore` negation rule correct; file creation is intentionally deferred

## Dev Notes

### Exact `pyproject.toml` structure

```toml
[project]
name = "agentic-fintech-backend"
version = "0.1.0"
description = "Agentic Banking Backend — UCP/AP2 prototype"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastapi[standard]",
    "sqlalchemy[asyncio]",
    "asyncpg",
    "alembic",
    "pyjwt",
    "cryptography",
    "stripe",
    "python-json-logger",
    "pydantic-settings",
    "httpx",
    "typer",
]

[dependency-groups]
dev = [
    "ruff",
    "pytest",
    "pytest-asyncio",
]

[tool.ruff]
target-version = "py312"
line-length = 88
exclude = [
    "_bmad",
    "_bmad-output",
    ".agents",
    ".venv",
    "alembic/versions",
]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Critical notes on dependencies:**
- `fastapi[standard]` — includes uvicorn, python-multipart, etc. (NOT bare `fastapi`)
- `sqlalchemy[asyncio]` — enables async engine (NOT bare `sqlalchemy`)
- `pyjwt` — PyPI name is `PyJWT`, but install as `pyjwt` in pyproject; imports as `import jwt`
- `python-json-logger` — enables structured JSON logging; imports as `from pythonjsonlogger import jsonlogger`
- `pydantic-settings` — separate package from pydantic; imports as `from pydantic_settings import BaseSettings`
- `typer` — CLI for `scripts/agent_client.py`; includes `rich` automatically

### uv commands cheat-sheet (uv 0.11.23 — latest as of 2026-06-20)

```bash
# Initialize (run once, from project root)
uv init --app

# Install all deps (production + dev groups)
uv sync --all-groups

# Install production only (e.g., in Docker) — --no-dev excludes ruff/pytest from image
uv sync --frozen --no-cache --no-dev

# Add a new production dep
uv add <package>

# Add a new dev dep
uv add --dev <package>

# Run any command in the venv
uv run <command>

# NEVER edit uv.lock manually — always let uv manage it
```

**Key uv behavior:** `uv sync` automatically creates `.venv/` if missing. `uv run` uses the project's venv without activation. `uv.lock` must be committed — it is the reproducibility guarantee.

### Ruff configuration notes

- `"I"` in select = isort-compatible import sorting (replaces isort)
- `"B"` = bugbear rules (common pitfalls)
- `"UP"` = pyupgrade rules (modernize syntax for Python 3.12)
- `"E"`, `"F"` = pycodestyle + pyflakes (standard lint)
- `_bmad`, `_bmad-output`, `.agents` excluded — these are BMad framework dirs, not project code
- Run `uv run ruff format .` BEFORE `uv run ruff check .` — format first, then lint

### Directory structure to create

```
agentic-fintech-backend/
├── pyproject.toml          ← created in Task 2
├── uv.lock                 ← auto-generated by uv sync
├── .python-version         ← auto-created by uv init (contains "3.12")
├── .gitignore              ← Task 4
├── README.md               ← minimal skeleton (title + placeholder sections only)
│
├── app/
│   ├── __init__.py
│   ├── routers/
│   │   └── __init__.py
│   ├── models/
│   │   └── __init__.py
│   ├── services/
│   │   └── __init__.py
│   └── db/
│       └── __init__.py
│
├── tests/
│   └── __init__.py
│
├── catalog/
│   └── .gitkeep
│
├── scripts/
│   └── .gitkeep
│
├── alembic/
│   └── .gitkeep
│
└── keys/
    └── .gitkeep
```

**Do NOT create in this story** (belong to later stories):
- `Dockerfile`, `docker-compose.yml`, `.env.example` → Story 1.2
- `alembic/env.py`, migration files → Story 1.3
- `app/main.py`, `app/config.py` → Story 1.4
- `app/routers/discovery.py`, etc. → Story 2+
- `catalog/products.json` → Story 2.1
- `scripts/agent_client.py` → Story 5.2

### `.gitignore` content

```gitignore
# Virtual environment
.venv/

# uv
.uv/

# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
*.so
.Python

# Distribution / packaging
dist/
build/
*.egg-info/
*.egg

# Test artifacts
.pytest_cache/
.coverage
htmlcov/
.tox/

# Environment files — NEVER commit secrets
.env
.env.*
!.env.example

# Cryptographic keys — CRITICAL: these must never be committed
keys/

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
```

### README.md skeleton (minimal — full docs in Story 5.3)

```markdown
# agentic-fintech-backend

Agentic Banking Backend — UCP/AP2 prototype demonstrating Human-Not-Present autonomous machine commerce.

## Quick Start

_Full setup instructions coming in Story 5.3._

## Project Structure

_Architecture and component map coming in Story 5.3._
```

### Architecture compliance notes

- **Service boundaries:** This story creates directory structure only. No service implementations yet.
- **No database code in this story** — SQLAlchemy + asyncpg are installed but no models or sessions created here.
- **No FastAPI app instantiation** — `app/main.py` does not exist yet after this story.
- **`keys/` is gitignored immediately** in this story — this is a security-critical requirement (NFR-1). The `keys/.gitkeep` file is committed but the `*.pem` files are excluded.
- **`uv.lock` IS committed** — this is the reproducibility guarantee, unlike `.venv/` which is never committed.

### Project Structure Notes

- All Python packages require `__init__.py`; the `catalog/`, `scripts/`, `alembic/`, `keys/` directories do not
- The `alembic/` directory structure (`env.py`, `script.py.mako`, `versions/`) is created in Story 1.3 by running `alembic init`; do not create it manually here
- Story 1.2 adds `Dockerfile` and `docker-compose.yml`; do not anticipate them here

### References

- [Source: architecture.md#Starter Template Evaluation] — uv init, pyproject.toml structure, all deps
- [Source: architecture.md#Infrastructure & Deployment] — NFR-5: pinned Python 3.12-slim base image (relevant to Dockerfile in 1.2)
- [Source: epics.md#Story 1.1] — all acceptance criteria
- [Source: architecture.md#Implementation Patterns — Service Boundaries] — `keys/` gitignored, `uv.lock` committed
- [External: docs.astral.sh/uv] — uv 0.11.23 docs; `uv init --app`, PEP 735 dependency groups

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- Initial `ruff check .` failed with 3 violations in `_bmad/` framework scripts (E501, I001, UP022). Fixed by adding `exclude = ["_bmad", "_bmad-output", ".agents", ".venv", "alembic/versions"]` to `[tool.ruff]` in `pyproject.toml`. These are BMad framework files outside project scope.

### Completion Notes List

- uv 0.11.23 installed and used (latest stable as of 2026-06-20)
- `uv init --app` run successfully; auto-generated `main.py` deleted; `.python-version = 3.12` confirmed
- `pyproject.toml` written with exact dep list from story spec; 62 packages resolved and installed into `.venv/`
- `uv.lock` (282 KB) generated deterministically
- All 6 Python package directories created with `__init__.py`; 3 non-Python dirs with `.gitkeep`
- `.gitignore` includes all required patterns; `keys/` directory fully excluded (NFR-1 security requirement)
- Ruff exclude list added for `_bmad`, `_bmad-output`, `.agents` dirs to scope linting to project code only
- `ruff format` + `ruff check` → 0 violations
- `pytest tests/ -v` → 0 items collected, exit code 5 (expected — no tests written yet, runner healthy)
- All 7 Acceptance Criteria satisfied

### File List

- `pyproject.toml` (new)
- `uv.lock` (new — auto-generated)
- `.python-version` (new — auto-generated by uv init)
- `.gitignore` (new)
- `README.md` (new — skeleton)
- `app/__init__.py` (new)
- `app/routers/__init__.py` (new)
- `app/models/__init__.py` (new)
- `app/services/__init__.py` (new)
- `app/db/__init__.py` (new)
- `tests/__init__.py` (new)
- `catalog/.gitkeep` (new)
- `scripts/.gitkeep` (new)
- `alembic/.gitkeep` (new)
- `keys/.gitkeep` (new)
