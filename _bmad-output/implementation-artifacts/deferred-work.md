# Deferred Work

## Deferred from: code review of 1-1-project-scaffold-and-package-management (2026-06-20)

- **Alembic async env.py** — `asyncpg` is async-only; no sync PostgreSQL driver present. Story 1.3 must rewrite Alembic's generated `env.py` to use async pattern (`asyncio.run()` + `run_sync(context.run_migrations)`). Default `alembic init` template will not work out of the box.
- **pytest exit code 5 in CI** — `pytest` with no tests collected exits with code 5 (non-zero). Standard CI pipelines (GitHub Actions) treat this as a build failure. Address when CI is configured (post-scope for this prototype).
- **`.env.example` absent** — `.gitignore` contains `!.env.example` negation but the file doesn't exist until Story 1.2. Contributors on fresh clones have no template for required env vars. Intentionally deferred to Story 1.2.
