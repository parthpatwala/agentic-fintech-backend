# Deferred Work

## Deferred from: code review of 1-4-fastapi-application-bootstrap-and-startup-validation (2026-06-21)

- **DATABASE_URL sync scheme gives cryptic driver error** — if developer accidentally uses `postgresql://` instead of `postgresql+asyncpg://`, SQLAlchemy raises an internal driver error rather than a clear validation message. Prototype scope; `.env.example` documents the correct scheme.
- **Shallow `/health` always returns 200** — endpoint does not reflect actual Postgres or key state at request time; by design for Story 1.4. Deep readiness semantics deferred to Story 5.x.
- **AC-2/AC-3 non-zero exit code relies on uvicorn** — startup failures propagate exit codes via uvicorn's default error handling rather than an explicit `sys.exit()`. Standard FastAPI/uvicorn pattern; acceptable for this prototype.

## Deferred from: code review of 1-2-docker-stack-and-environment-configuration (2026-06-21)

- **Root process in container** — `Dockerfile` has no `USER` instruction; container runs as root. Real fintech security concern; acceptable for prototype local dev only. Harden before any shared or production deployment.
- **Credential drift** — `POSTGRES_PASSWORD` in `POSTGRES_*` vars can diverge from the password embedded in `DATABASE_URL` by hand editing. No cross-validation possible without a startup check. Documented in `.env.example`.
- **Volume locks credentials on first boot** — Postgres persists the user/password/db created at volume init; changing `.env` without `docker compose down -v` causes auth failures. Standard Docker Postgres behaviour.
- **Missing PEM keys yield false-healthy stack** — On fresh clone, `keys/` may only contain `.gitkeep`; `/health` still returns 200. Story 1.4 startup validation (`PUBLIC_KEY_PATH`) will surface this immediately.
- **`alembic/` excluded from image** — `.dockerignore` excludes `alembic/` so `docker compose exec app alembic upgrade head` would fail; by design for this story. Story 1.3 must decide: run migrations from host or add alembic back to image.
- **Shallow `/health` endpoint** — always returns 200 regardless of postgres or key state. Story 1.4 scope to add real readiness semantics.
- **`DATABASE_URL` hostname unusable from host** — DSN uses `postgres` (Compose service name); host-side `alembic` / `psql` / test runs need `localhost` and port 5432 published. Documented in `.env.example`. Add `TEST_DATABASE_URL` in Story 5.1.
- **Password special characters silently break DSN** — `@`, `:`, `/` in `POSTGRES_PASSWORD` must be URL-encoded in `DATABASE_URL`. No guidance or validation provided. Acceptable for prototype; add note to `.env.example` if passwords become complex.
- **Stale image on rebuild** — `docker compose up` without `--build` reuses the old image after `pyproject.toml`/`uv.lock` changes. Expected Docker behaviour; always use `--build` after dependency changes.
- **No Dockerfile `HEALTHCHECK`** — Docker itself cannot surface app health without it; Compose healthcheck covers local dev. Add for any shared/production deployment.
- **README.md not copied before `uv sync`** — `pyproject.toml` declares `readme = "README.md"` but only `pyproject.toml` + `uv.lock` are copied before `RUN uv sync`. No impact on current `uv sync --no-dev` flow; would matter if a wheel build were added later.

## Deferred from: code review of 1-1-project-scaffold-and-package-management (2026-06-20)

- **Alembic async env.py** — `asyncpg` is async-only; no sync PostgreSQL driver present. Story 1.3 must rewrite Alembic's generated `env.py` to use async pattern (`asyncio.run()` + `run_sync(context.run_migrations)`). Default `alembic init` template will not work out of the box.
- **pytest exit code 5 in CI** — `pytest` with no tests collected exits with code 5 (non-zero). Standard CI pipelines (GitHub Actions) treat this as a build failure. Address when CI is configured (post-scope for this prototype).
- **`.env.example` absent** — `.gitignore` contains `!.env.example` negation but the file doesn't exist until Story 1.2. Contributors on fresh clones have no template for required env vars. Intentionally deferred to Story 1.2.
