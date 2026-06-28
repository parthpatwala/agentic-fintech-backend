# agentic-fintech-backend

Agentic Banking Backend — a UCP/AP2 prototype demonstrating Human-Not-Present (HNP) autonomous machine commerce. An AI agent discovers products via UCP, creates a checkout session, signs an EdDSA payment mandate, and settles via Stripe Sandbox — all without human interaction at checkout.

## System Architecture

The backend implements the merchant/verifier role in a simplified agentic commerce flow:

1. **UCP Discovery** (`GET /.well-known/ucp`) — returns capabilities, API routes, Ed25519 public key (JWK), and product catalog in one call
2. **Checkout** (`POST /api/checkout`) — validates invoice payload, creates a pending invoice in PostgreSQL
3. **AP2 Mandate Dependency** — cryptographically verifies the EdDSA JWT on `POST /api/complete` before any settlement logic runs
4. **Settlement** (`POST /api/complete`) — charges Stripe Sandbox, updates invoice to `settled`, writes mandate audit trail
5. **Agent Client** (`scripts/agent_client.py`) — CLI demo that runs the full UJ-1 cycle from a natural-language prompt

**Data stores:** PostgreSQL (`invoices`, `mandate_audit` tables) and static `catalog/products.json` loaded at startup.

```mermaid
flowchart LR
  Agent["Agent Client / Postman"] -->|GET /.well-known/ucp| Discovery
  Agent -->|POST /api/checkout| Checkout
  Agent -->|POST /api/complete + JWT| Complete
  Complete --> MandateDep["AP2 Mandate Dependency"]
  MandateDep --> Stripe["Stripe Sandbox"]
  Checkout --> Postgres[(PostgreSQL)]
  Complete --> Postgres
```

## Docker Compose Service Topology

| Service | Image / Build | Ports | Purpose |
|---|---|---|---|
| `postgres` | `postgres:17-alpine` | `5432:5432` (host) | PostgreSQL 17 with persistent volume `postgres_data` |
| `app` | `Dockerfile` build | `8000:8000` | FastAPI + uvicorn; mounts `./keys` read-only |

Both services run on the `fintech_net` bridge network. The `app` service waits for the postgres healthcheck (`pg_isready`) before accepting requests.

**Port conflict:** If a Postgres instance already runs on the host at port 5432, stop it or change the compose port mapping before `docker compose up`.

## Environment Variables

Application settings are loaded from `.env` via `app/config.py` (pydantic-settings). Environment variable names use the uppercase form of each field name.

| Variable | Required | Type | Example | Used By | Description |
|---|---|---|---|---|---|
| `DATABASE_URL` | Yes | string (DSN) | `postgresql+asyncpg://postgres:changeme@postgres:5432/fintech_db` | `app` | Async SQLAlchemy URL. Use hostname `postgres` inside Docker; `localhost` on the host. Must use the `postgresql+asyncpg://` scheme (not `postgresql://`). |
| `STRIPE_API_KEY` | Yes | string | `sk_test_...` | `app` | Stripe test secret key. Must start with `sk_test_`. |
| `PUBLIC_KEY_PATH` | No | path | `/app/keys/public_key.pem` | `app` | Ed25519 public key PEM for mandate verification. Default: `keys/public_key.pem`. |
| `CATALOG_PATH` | No | path | `catalog/products.json` | `app` | Product catalog JSON file. Default: `catalog/products.json`. |
| `POSTGRES_USER` | Yes | string | `postgres` | `postgres` service | Postgres superuser (Docker Compose). |
| `POSTGRES_PASSWORD` | Yes | string | `changeme` | `postgres` service | Postgres password. Must match the password embedded in `DATABASE_URL`. |
| `POSTGRES_DB` | Yes | string | `fintech_db` | `postgres` service | Default database name created on first volume init. |
| `TEST_DATABASE_URL` | No | string (DSN) | `postgresql+asyncpg://postgres:changeme@localhost:5432/fintech_test_db` | `pytest` only | Separate database for integration tests. Not read by `app/config.py`. |

**Password URL-encoding:** If `POSTGRES_PASSWORD` contains `@`, `:`, or `/`, URL-encode those characters in `DATABASE_URL`.

## Local Key Generation

The server reads `public_key.pem` for mandate verification. The agent client script reads `private_key.pem` for signing.

### Method A — openssl (preferred, PKCS8 format)

```bash
mkdir -p keys
openssl genpkey -algorithm ed25519 -out keys/private_key.pem
openssl pkey -in keys/private_key.pem -pubout -out keys/public_key.pem
```

### Method B — ssh-keygen

```bash
ssh-keygen -t ed25519 -f ./id_ed25519 -N ""
mv ./id_ed25519 keys/private_key.pem
mv ./id_ed25519.pub keys/public_key.pem
```

`private_key.pem` is used only by `scripts/agent_client.py`. The server never reads the private key.

## Local PostgreSQL Setup

On a fresh clone, `docker compose up` creates the database from Compose environment variables and initializes the `postgres_data` volume.

**Test database (one-time, for integration tests):**

```bash
docker compose exec postgres psql -U postgres -c "CREATE DATABASE fintech_test_db;"
```

Integration tests create tables via `Base.metadata.create_all` — Alembic is not required for pytest. To run migrations manually from the host, use a `localhost` DSN and run `uv run alembic upgrade head`.

## Execution Playbook

Follow these steps in order to run a complete agentic transaction:

1. **Prerequisites:** Docker Desktop, [uv](https://docs.astral.sh/uv/) installed, Stripe test account with an `sk_test_` key

2. **Clone and configure:**
   ```bash
   git clone <repo-url>
   cd agentic-fintech-backend
   cp .env.example .env
   # Edit .env: set STRIPE_API_KEY=sk_test_your_key_here
   # Keep DATABASE_URL hostname as "postgres" (Docker service name) — do not use "localhost" inside Docker
   ```

3. **Generate keys** (see Local Key Generation above)

4. **Start the stack:**
   ```bash
   docker compose up --build
   ```
   Wait for the `startup_complete` log event in the output.

5. **Verify health:**
   ```bash
   curl http://localhost:8000/health
   # {"status":"ok"}
   ```

6. **Run an agent purchase:**
   ```bash
   uv run scripts/agent_client.py "Buy a USB-C Hub if under $60"
   ```
   Expected: USB-C Hub ($49.99) selected, settlement printed with `status: settled` and a `stripe_payment_intent_id`.

7. **Verify in Stripe Dashboard:** Log into Stripe → Developers → Payments (test mode) → find the PaymentIntent matching the printed ID.

8. **Observe structured logs:**
   ```bash
   docker compose logs app --no-log-prefix 2>&1 | tail -20
   ```
   Each line should be valid JSON with `timestamp`, `level`, and `event` fields. Validate with:
   ```bash
   docker compose logs app --no-log-prefix 2>&1 | python3 -m json.tool
   ```

## Running Tests

```bash
# Unit tests only (no Postgres required)
uv run pytest -m "not integration" -q

# Full suite including DB integration tests
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:changeme@localhost:5432/fintech_test_db
uv run pytest -q

# Lint
uv run ruff check app/ tests/
```

Integration tests skip automatically when `TEST_DATABASE_URL` is unset. The development database (`fintech_db`) is never touched during test runs.

## Quick Reference

| Resource | URL / Command |
|---|---|
| API docs | http://localhost:8000/docs |
| UCP discovery | `curl http://localhost:8000/.well-known/ucp` |
| Stop stack | `docker compose down` |
| Agent demo | `uv run scripts/agent_client.py "Buy wireless headphones if under $100"` |

## Project Structure

```
app/           FastAPI application (routers, services, models)
catalog/       Static product catalog (products.json)
keys/          Ed25519 key pair (gitignored)
scripts/       Agent client CLI simulation
tests/         pytest suite
alembic/       Database migrations
```
