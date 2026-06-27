# Deferred Work

## Deferred from: code review of 3-2-checkout-session-endpoint (2026-06-27)

- **ISO 4217 allowlist covers only 20 of ~170 valid currencies** — "AED", "THB", "CZK" etc. return 422 erroneously. Intentionally narrow for prototype (USD/EUR/GBP sufficient for demo); expand with `pycountry` or a full inline set when broader currency support is needed.
- **Sub-cent total DB precision mismatch** — multi-dp unit prices (e.g. $0.001) produce Decimal totals with >2dp; PostgreSQL NUMERIC(10,2) rounds on insert, so DB value differs from response `total_amount`. Prototype scope — real prices use 2dp.
- **Whitespace-only `agent_id` accepted** — `min_length=1` passes `" "` (single space). Add `strip_whitespace=True` or a validator if agent identity is security-sensitive.
- **Empty item `name` accepted** — `name: str` has no `min_length` constraint; blank names stored in JSONB.
- **`get_invoice` defined but never called** — stub for Story 4.2 which looks up invoices by session_id for settlement; no tests cover it yet.
- **`PaymentMandatePayload.currency` lacks ISO 4217 validation** — inconsistency with `CheckoutRequest.currency`; Story 3.1 scope.
- **No authentication on `POST /api/checkout`** — endpoint is fully open; authentication/authorization is an infrastructure concern deferred to a later story.

## Deferred from: code review of 3-1-ap2-mandate-verification-dependency (2026-06-22)

- **`aud`/`iss` claim validation in `jwt.decode`** — single-purpose Ed25519 key pair, no cross-service reuse in this prototype; revisit if key sharing across services is introduced.
- **JTI replay protection** — valid JWT can be resubmitted until expiry; deduplication store (Redis/DB) required; out of scope for Story 3.1 stub handler.
- **`amount: float` → `Decimal` for monetary precision** — schema-level change with downstream impact; same prototype pattern as `price: float` in Story 2.1.
- **Rate limiting on `POST /api/complete`** — infrastructure/middleware concern; not introduced by Story 3.1.
- **Non-`PyJWTError` from cryptography layer propagates as 500** — PyJWT wraps most EdDSA crypto exceptions; edge case not reproducible with current library versions; add broad catch if library is upgraded.
- **`nbf` claim absence** — no lower temporal bound on token validity; not required by AP2 spec.
- **`client_ip` logs proxy IP, not real client** — `request.client.host` reflects proxy behind reverse-proxy/LB; needs `X-Forwarded-For` / `Forwarded` header handling; infrastructure concern.
- **Parallel-test race condition from `app.state` mutation** — `setup_public_key_state` fixture mutates a module-level singleton; race manifests only under `pytest-xdist`; not used in this project.

## Deferred from: code review of 2-2-ucp-discovery-profile-endpoint (2026-06-22)

- **Unguarded `app.state.jwk`/`catalog` at request time** — If lifespan is bypassed the handler will 500. Accepted as startup invariant — FastAPI will not serve requests if the lifespan context manager raises, so `app.state` is guaranteed populated when the handler runs.
- **`exc.doc` exposes full catalog file content in JSONDecodeError** — `exc.doc` stores the raw parse input and can appear in logs. Catalog contains no secrets; accept for prototype. Add catalog-size limit if data grows sensitive.
- **`IsADirectoryError` / `UnicodeDecodeError` not caught for catalog path** — Same deferred pattern from Story 2.1. Rare edge in local Docker setup; handle for production hardening.
- **No `Cache-Control` headers on discovery response** — Discovery profile is static per-startup. Adding `Cache-Control: public, max-age=3600` would reduce unnecessary repeat fetches. Deferred to post-prototype.
- **`crypto.derive_jwk()` unexpected exception type** — Pre-existing Story 2.1 deferred: derive_jwk may raise outside (ValueError, TypeError) from cryptography internals. Add broad except → RuntimeError wrap if hardening.
- **`_FAKE_JWK.x = "fake_x"` not base64url-valid** — Isolation tests intentionally use dummy values; real base64url compliance is verified in `test_state_init.py`. If future tests exercise JWK consumers, use `base64.urlsafe_b64encode(bytes(32)).rstrip(b"=").decode()`.
- **No test for absent `app.state` attributes in handler** — Tests inject state via fixture; missing-state path is untested. A negative fixture covering this path would confirm 500 behavior under partial startup failure.

## Deferred from: code review of 2-1-static-product-catalog-and-application-state-initialization (2026-06-22)

- **`price: float` vs `Decimal`** — Architecture explicitly defines `price: float` for `ProductItem`; monetary precision is a prototype-scope concern. Revisit before any production settlement math uses catalog prices directly.
- **ISO 4217 currency not validated on `ProductItem`** — `currency: str` accepts any string; hardcoded catalog has valid USD values. Add a pattern constraint (e.g. `Field(pattern=r"^[A-Z]{3}$")`) when the catalog becomes user-editable.
- **Empty `signing_keys` list not prevented in `UCPProfile`** — No `min_length=1` on the field; Story 2.2 always populates it from `app.state.jwk`. Add the constraint in Story 2.2.
- **Duplicate product `id` values load without error** — A uniqueness check is not enforced at load time; the hardcoded catalog has unique IDs. Add a set-based check if the catalog ever becomes writable.
- **`app.state.catalog` is a mutable list** — Could be mutated by a request handler. Prototype scope; convert to tuple or frozen structure before any write-path handler exists.
- **`IsADirectoryError` and other `OSError` variants not caught for catalog path** — Same deferred pattern as `public_key_path`; rare edge in local dev; add broad `OSError` catch for production hardening.
- **Malformed-JSON test doesn't verify process exit code** — Same deferred pattern from Story 1.4; subprocess-level exit code testing deferred to Story 5.x.
- **Relative `catalog_path` depends on process CWD** — Same pattern as `public_key_path`; documented in `.env.example`; acceptable for prototype Docker deployment.

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
