---
stepsCompleted: [1, 2, 3, 4]
status: 'complete'
completedAt: '2026-06-20'
inputDocuments:
  - "_bmad-output/planning-artifacts/prds/prd-agentic-fintech-backend-2026-06-20/prd.md"
  - "_bmad-output/planning-artifacts/architecture.md"
---

# agentic-fintech-backend - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for agentic-fintech-backend, decomposing the requirements from the PRD and Architecture into implementable stories.

## Requirements Inventory

### Functional Requirements

FR-1: The server MUST serve `GET /.well-known/ucp` without authentication, returning `Content-Type: application/json` and HTTP 200.
FR-2: The Discovery Profile JSON MUST include `ucp.version: "2026-04-08"`, capabilities (`dev.ucp.shopping.checkout`, `dev.ucp.shopping.ap2_mandate`), route paths for checkout and complete, a `signing_keys` JWK array (Ed25519 public key), and a `catalog` array of ProductItem objects.
FR-3: The AP2 middleware MUST extract the Payment Mandate JWT from the `payment_mandate` field of the JSON request body on `POST /api/complete`. Requests missing the field return HTTP 422; non-JWT values return HTTP 401.
FR-4: The middleware MUST verify the Payment Mandate JWT signature using PyJWT with `algorithms=["EdDSA"]` and the server-resident `public_key.pem`. Invalid signature or wrong algorithm returns HTTP 401.
FR-5: The middleware MUST validate that the decoded Mandate payload contains required fields: `session_id`, `amount`, `currency`, `agent_id`. Missing fields return HTTP 422.
FR-6: The middleware MUST log all verification failures with timestamp, failure reason, and request source IP. No rejected mandate reaches the endpoint handler.
FR-7: `POST /api/checkout` MUST accept a JSON body: `session_id` (UUID), `agent_id` (str), `currency` (ISO 4217), `items` (list of `{name, quantity, unit_price}`). Missing fields return HTTP 422.
FR-8: Upon successful validation, the server MUST persist an Invoice record to PostgreSQL with `session_id`, `agent_id`, `items` (JSONB), `total_amount` (server-computed), `currency`, `status: "pending"`, and `created_at`.
FR-9: The checkout response MUST include `session_token` (server-generated) and `checkout_context` (`session_id`, `total_amount`, `currency`, `server_timestamp`).
FR-10: Before calling Stripe, `POST /api/complete` MUST verify that `session_id` from the mandate corresponds to an existing invoice with `status: "pending"`. Unknown → 404, already-settled → 409.
FR-11: The endpoint MUST call Stripe Python SDK to create a `PaymentIntent` in Test Sandbox Mode using mandate `amount`, `currency`, and `payment_method: "pm_card_visa"`. Stripe exception → 502, DB NOT updated.
FR-12: On Stripe success, the server MUST atomically: update invoice `status: "settled"`, record `stripe_payment_intent_id` and `settled_at`; and insert a `mandate_audit` row with `session_id`, `agent_id`, `mandate_jwt_hash` (SHA-256 of raw JWT), and `settlement_timestamp`.
FR-13: `POST /api/complete` MUST return HTTP 200 with `session_id`, `stripe_payment_intent_id`, `status: "settled"`, and `settled_at`.
FR-14: PostgreSQL MUST be defined as a named service in `docker-compose.yml` with a persistent named volume; the FastAPI service MUST declare a health-check dependency on it.
FR-15: The schema MUST define: `invoices` table (`session_id` PK UUID, `agent_id`, `items` JSONB, `total_amount` NUMERIC, `currency` VARCHAR(3), `status`, `stripe_payment_intent_id` nullable, `created_at`, `settled_at` nullable) and `mandate_audit` table (`id` serial PK, `session_id` FK → invoices, `agent_id`, `mandate_jwt_hash` VARCHAR(64), `settlement_timestamp`).
FR-16: The pytest suite MUST cover all six cryptographic path cases: valid mandate → pass; tampered payload → 401; wrong private key → 401; missing Authorization-equivalent field → 422; unsupported algorithm → 401; missing required Mandate fields → 422.
FR-17: The pytest suite MUST cover every API endpoint with at minimum one happy-path test and one test per defined error condition, including Discovery profile content assertions (version, capabilities, signing_keys, catalog shape).
FR-18: Tests MUST use a test-scoped PostgreSQL instance (separate `TEST_DATABASE_URL`) and assert exact DB records written — not just status codes — for checkout creation, invoice status transitions, and mandate_audit inserts.
FR-19: `README.md` MUST contain: system architecture overview, Docker Compose service topology, all required environment variables with descriptions, local PostgreSQL setup, step-by-step execution playbook (setup → run → test transaction → verify in Stripe dashboard), and pytest execution instructions.

### NonFunctional Requirements

NFR-1: `keys/private_key.pem` and `keys/public_key.pem` MUST NOT be committed to version control; `.gitignore` MUST exclude the `keys/` directory.
NFR-2: The Stripe API key MUST be injected via `STRIPE_API_KEY` environment variable; the application MUST refuse to start if the key is unset or does not begin with `sk_test_`.
NFR-3: PyJWT MUST be configured with `algorithms=["EdDSA"]` explicitly at every call site; algorithm confusion attacks (`alg: none`, `HS256`) MUST be rejected at the library level.
NFR-4: All runtime dependencies MUST run inside Docker containers; no host-level Python or database installation is required beyond Docker Desktop.
NFR-5: The application image MUST use a pinned base image (`python:3.12-slim`); all Python dependencies are pinned via `uv.lock`.
NFR-6: The application MUST emit structured JSON logs (via `python-json-logger`) at INFO for normal operations and ERROR for failures. Log fields: `timestamp`, `level`, `event`, `session_id` (where applicable), `detail`.

### Additional Requirements

- **Scaffold (Architecture):** Custom scaffold from scratch using `uv` as package manager; `pyproject.toml` + `uv.lock` (no pip/requirements.txt). Init: `uv init` + `uv add` for all dependencies.
- **Mock Catalog (Architecture):** `catalog/products.json` — static product inventory (5 items with id, name, price, currency); loaded once at startup into `app.state.catalog`; served inline in the UCP discovery profile.
- **Agent Client Script (Architecture):** `scripts/agent_client.py` — CLI simulation script (typer); accepts natural language budget prompt; fetches UCP catalog; applies budget constraint; signs AP2 Payment Mandate JWT with `private_key.pem`; calls checkout then complete; prints result.
- **Database Driver (Architecture):** `asyncpg` as the native async PostgreSQL driver for SQLAlchemy 2.0 async mode.
- **ORM & Migrations (Architecture):** SQLAlchemy 2.0 async mode + Alembic; schema version-controlled from day one.
- **Settings (Architecture):** `pydantic-settings` `BaseSettings`; `sk_test_` validator on `STRIPE_API_KEY` at startup.
- **FastAPI Dependency Pattern (Architecture):** AP2 mandate verification implemented as a FastAPI Dependency (not Starlette middleware); returns `(raw_jwt: str, payload: PaymentMandatePayload)` tuple.
- **Lifespan Handler (Architecture):** FastAPI `lifespan` context manager handles startup: load `public_key.pem` → derive JWK → load `catalog/products.json` → validate Stripe key → check DB connectivity. Fails fast with clear errors.
- **Test Isolation (Architecture):** Separate `TEST_DATABASE_URL` env var; test DB schema recreated per session; development DB never touched by tests.
- **Linting (Architecture):** Ruff configured in `pyproject.toml` (replaces flake8 + black + isort).
- **Mandatory Call Order (Architecture — binding):** AP2 Dependency MUST execute: extract → validate JWT format → verify EdDSA → decode payload → return tuple. Settlement handler MUST execute: receive tuple → query invoice → check status → call Stripe → atomic DB write → return response. Reordering is forbidden.
- **Service Boundaries (Architecture — binding):** PyJWT never called outside `app/services/crypto.py`; DB writes never outside `app/services/invoice.py`; Stripe never called outside `app/services/settlement.py`.

### UX Design Requirements

N/A — This is an API-only backend prototype with no frontend or UI. All interaction is via HTTP clients (Postman, `scripts/agent_client.py`, pytest).

### FR Coverage Map

FR-1: Epic 2 — GET /.well-known/ucp endpoint availability
FR-2: Epic 2 — Discovery Profile content (version, capabilities, signing_keys, catalog)
FR-3: Epic 3 — Mandate extraction from JSON body
FR-4: Epic 3 — EdDSA signature verification
FR-5: Epic 3 — Mandate structural validation
FR-6: Epic 3 — Rejection logging
FR-7: Epic 3 — Invoice payload acceptance (POST /api/checkout)
FR-8: Epic 3 — Session persistence to PostgreSQL
FR-9: Epic 3 — Checkout context response
FR-10: Epic 4 — Session linkage before Stripe call
FR-11: Epic 4 — Stripe Sandbox mock charge
FR-12: Epic 4 — Atomic settlement persistence + mandate_audit
FR-13: Epic 4 — Settlement success response
FR-14: Epic 1 — PostgreSQL via Docker Compose
FR-15: Epic 1 — Database schema (invoices + mandate_audit tables)
FR-16: Epic 5 — Cryptographic path pytest coverage
FR-17: Epic 5 — API endpoint pytest coverage
FR-18: Epic 5 — Database interaction pytest coverage
FR-19: Epic 5 — README completeness

NFR-1: Epic 1 — Keys gitignored (.gitignore covers keys/ directory)
NFR-2: Epic 1 — Stripe key sk_test_ validation (pydantic-settings validator in lifespan)
NFR-3: Epic 3 — Algorithm confusion protection (algorithms=["EdDSA"] in crypto.py)
NFR-4: Epic 1 — Docker-only runtime (Dockerfile + docker-compose)
NFR-5: Epic 1 — Pinned base image (python:3.12-slim) + uv.lock
NFR-6: Epic 5 — Structured JSON logs (python-json-logger configured at startup)

## Epic List

### Epic 1: Project Foundation & Containerized Environment
The developer can clone the project, run `docker compose up`, and have a healthy, containerized FastAPI + PostgreSQL stack with the correct database schema ready to receive API calls — no host-level setup required beyond Docker Desktop.
**FRs covered:** FR-14, FR-15
**NFRs covered:** NFR-1, NFR-2, NFR-4, NFR-5
**Architecture items:** uv scaffold, pyproject.toml + uv.lock, Dockerfile, docker-compose.yml, Alembic + initial migration (invoices + mandate_audit), pydantic-settings BaseSettings with sk_test_ validator, lifespan skeleton, .env.example, .gitignore, ruff config

### Epic 2: UCP Machine-Readable Discovery & Product Catalog
Any UCP-compliant AI Agent can fetch `GET /.well-known/ucp` and autonomously discover the server's capabilities, supported AP2 payment extension, API routes, public signing key (JWK), and full product catalog — all in a single unauthenticated HTTP call.
**FRs covered:** FR-1, FR-2
**Architecture items:** catalog/products.json (5 products), JWK derivation from public_key.pem at lifespan startup, app.state.catalog + app.state.jwk population

### Epic 3: AP2 Cryptographic Handshake & Checkout Session
A mock AI Agent can initiate a secure checkout session by submitting a structured invoice and receiving a checkout context, while the server's AP2 Dependency layer stands guard over the settlement endpoint — cryptographically rejecting any mandate that is missing, tampered, or algorithmically confused.
**FRs covered:** FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, FR-9
**NFRs covered:** NFR-3

### Epic 4: Autonomous Payment Settlement
The AI Agent can complete the full Human-Not-Present commerce cycle: a signed Payment Mandate passes cryptographic verification, triggers a Stripe Sandbox charge, and produces a durable settlement record with a mandate audit trail in PostgreSQL — the agent receives a confirmed payment intent ID.
**FRs covered:** FR-10, FR-11, FR-12, FR-13

### Epic 5: End-to-End Validation, Agent Simulation & Documentation
The developer can validate the entire system with a single pytest command, execute a realistic natural-language-prompted agentic purchase from the terminal using scripts/agent_client.py, and onboard any collaborator from scratch using only the README.
**FRs covered:** FR-16, FR-17, FR-18, FR-19
**NFRs covered:** NFR-6
**Architecture items:** scripts/agent_client.py (typer CLI + full purchase simulation loop)

---

## Epic 1: Project Foundation & Containerized Environment

The developer can clone the project, run `docker compose up`, and have a healthy, containerized FastAPI + PostgreSQL stack with the correct database schema ready to receive API calls — no host-level setup required beyond Docker Desktop.

### Story 1.1: Project Scaffold & Package Management

As a developer,
I want the project directory initialized with `uv`, all Python dependencies declared in `pyproject.toml`, a committed lock file, and linting configured,
So that any contributor can reproduce the exact environment with a single `uv sync` command.

**Acceptance Criteria:**

**Given** the repo is cloned fresh
**When** `uv sync` is run in the project root
**Then** all dependencies install without errors and `.venv/` is created
**And** `uv.lock` is committed and resolves all packages deterministically
**And** `ruff check .` passes with zero violations on the scaffold code
**And** `.gitignore` excludes `keys/`, `.env`, `.venv/`, `__pycache__/`, and `*.pyc`
**And** the directory structure exists: `app/`, `app/routers/`, `app/models/`, `app/services/`, `app/db/`, `tests/`, `catalog/`, `scripts/`, `alembic/`, `keys/`
**And** `pyproject.toml` declares all required dependencies: `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pyjwt`, `cryptography`, `stripe`, `python-json-logger`, `pydantic-settings`, `pytest`, `pytest-asyncio`, `httpx`, `typer`
**And** Ruff is configured as a dev dependency with format and lint rules in `pyproject.toml`

---

### Story 1.2: Docker Stack & Environment Configuration

As a developer,
I want a `Dockerfile` and `docker-compose.yml` that bring up the FastAPI app and a PostgreSQL database together,
So that I can run the entire stack with `docker compose up` without installing Python or PostgreSQL on the host.

**Acceptance Criteria:**

**Given** Docker Desktop is running and a `.env` file is present with valid values
**When** `docker compose up --build` is executed
**Then** both `app` and `postgres` services start successfully
**And** the `postgres` service passes its healthcheck (`pg_isready`) before the `app` service begins accepting requests
**And** `GET http://localhost:8000/health` returns HTTP 200 with `{"status": "ok"}`
**And** the app and postgres services communicate over a named Docker network

**Given** `docker compose down -v` is executed
**When** the command completes
**Then** all containers stop and the named PostgreSQL volume is destroyed cleanly

**And** `.env.example` is committed listing every required environment variable with a description and no real secret values
**And** the `Dockerfile` base image is exactly `python:3.12-slim` (pinned, no `latest`)

---

### Story 1.3: Database Schema & Alembic Migrations

As a developer,
I want the PostgreSQL schema defined in SQLAlchemy ORM models and managed by Alembic,
So that the database tables are version-controlled and automatically applied on container startup.

**Acceptance Criteria:**

**Given** the `postgres` service is running and `DATABASE_URL` is set
**When** `alembic upgrade head` is executed (or triggered by the app's startup sequence)
**Then** both the `invoices` and `mandate_audit` tables are created without errors

**And** the `invoices` table has exactly these columns: `session_id` (UUID, PRIMARY KEY), `agent_id` (VARCHAR, NOT NULL), `items` (JSONB, NOT NULL), `total_amount` (NUMERIC(10,2), NOT NULL), `currency` (VARCHAR(3), NOT NULL), `status` (VARCHAR(20), NOT NULL, DEFAULT `'pending'`), `stripe_payment_intent_id` (VARCHAR, NULLABLE), `created_at` (TIMESTAMPTZ, NOT NULL, DEFAULT NOW()), `settled_at` (TIMESTAMPTZ, NULLABLE)

**And** the `mandate_audit` table has exactly these columns: `id` (SERIAL, PRIMARY KEY), `session_id` (UUID, NOT NULL, FK → `invoices.session_id`), `agent_id` (VARCHAR, NOT NULL), `mandate_jwt_hash` (VARCHAR(64), NOT NULL), `settlement_timestamp` (TIMESTAMPTZ, NOT NULL, DEFAULT NOW())

**Given** `alembic downgrade -1` is executed
**When** the command completes
**Then** both tables are dropped and the schema returns to its prior state

**And** running `alembic upgrade head` twice in a row produces no errors (idempotent)

---

### Story 1.4: FastAPI Application Bootstrap & Startup Validation

As a developer,
I want the FastAPI application to validate all required configuration at boot via a `lifespan` handler,
So that misconfigured environments fail immediately with a clear error message rather than crashing silently at runtime.

**Acceptance Criteria:**

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

---

## Epic 2: UCP Machine-Readable Discovery & Product Catalog

Any UCP-compliant AI Agent can fetch `GET /.well-known/ucp` and autonomously discover the server's capabilities, AP2 payment extension support, API routes, Ed25519 public signing key (JWK), and full product catalog — all in a single unauthenticated HTTP call.

### Story 2.1: Static Product Catalog & Application State Initialization

As a UCP-compliant AI Agent,
I want the server to load its product catalog and cryptographic identity at startup,
So that both are available instantly on every discovery request without per-request disk I/O.

**Acceptance Criteria:**

**Given** `catalog/products.json` contains at least one product with `id`, `name`, `price` (float), and `currency` (ISO 4217) fields
**And** `PUBLIC_KEY_PATH` points to a valid Ed25519 public key PEM file
**When** the app starts via its lifespan handler
**Then** `app.state.catalog` is a non-empty list of validated `ProductItem` objects
**And** `app.state.jwk` is a dict with keys `kty: "OKP"`, `crv: "Ed25519"`, and `x` (base64url-encoded string)
**And** `app.state.public_key` holds the loaded Ed25519 public key object ready for JWT verification

**Given** `catalog/products.json` contains exactly 5 items
**When** the lifespan handler completes
**Then** `len(app.state.catalog) == 5`

**Given** `catalog/products.json` is malformed JSON
**When** the app attempts to start
**Then** a JSON parse error is raised and the process exits with a non-zero code

**And** the initial `catalog/products.json` includes these 5 items:
- `prod_001`: Wireless Headphones, $79.99 USD
- `prod_002`: Mechanical Keyboard, $129.99 USD
- `prod_003`: USB-C Hub, $49.99 USD
- `prod_004`: HD Webcam, $89.99 USD
- `prod_005`: Desk Lamp LED, $34.99 USD

---

### Story 2.2: UCP Discovery Profile Endpoint

As a UCP-compliant AI Agent,
I want to call `GET /.well-known/ucp` without any authentication and receive a complete machine-readable profile,
So that I can autonomously determine what this server supports and how to interact with it before initiating any commerce flow.

**Acceptance Criteria:**

**Given** the app is running with a valid catalog and public key loaded in `app.state`
**When** `GET /.well-known/ucp` is called without any authentication headers
**Then** the response is HTTP 200 with `Content-Type: application/json`
**And** `response.json()["ucp"]["version"] == "2026-04-08"`
**And** `response.json()["ucp"]["capabilities"]` contains both `"dev.ucp.shopping.checkout"` and `"dev.ucp.shopping.ap2_mandate"`
**And** `response.json()["ucp"]["routes"]["checkout"] == "/api/checkout"`
**And** `response.json()["ucp"]["routes"]["complete"] == "/api/complete"`
**And** `response.json()["ucp"]["signing_keys"]` is a non-empty list where `signing_keys[0]["kty"] == "OKP"` and `signing_keys[0]["crv"] == "Ed25519"` and `signing_keys[0]["x"]` is a non-empty string
**And** `response.json()["ucp"]["catalog"]` is a list of length 5 where each item has `id`, `name`, `price`, and `currency` fields

---

## Epic 3: AP2 Cryptographic Handshake & Checkout Session

A mock AI Agent can initiate a secure checkout session by submitting a structured invoice and receiving a checkout context, while the AP2 Dependency layer cryptographically guards the settlement endpoint — rejecting mandates that are missing, tampered, or algorithmically confused.

### Story 3.1: AP2 Mandate Verification Dependency

As a developer,
I want a reusable FastAPI Dependency that extracts and cryptographically verifies the Payment Mandate from `POST /api/complete` requests before any handler logic executes,
So that the settlement endpoint is protected against invalid, tampered, and algorithm-confused mandates at the framework level.

**Acceptance Criteria:**

**Given** a valid EdDSA-signed JWT with payload fields `session_id`, `amount`, `currency`, `agent_id` is present in the `payment_mandate` body field
**When** the dependency executes
**Then** it returns a `(raw_jwt: str, payload: PaymentMandatePayload)` tuple with no HTTP errors raised

**Given** the request body has no `payment_mandate` field
**When** the dependency executes
**Then** HTTP 422 is raised before any handler logic runs

**Given** a JWT in `payment_mandate` was signed with a different private key than `public_key.pem`
**When** the dependency executes
**Then** HTTP 401 is raised with reason `"invalid_signature"`

**Given** a JWT where the payload was modified after signing (tampered)
**When** the dependency executes
**Then** HTTP 401 is raised with reason `"invalid_signature"`

**Given** a JWT specifying `alg: "HS256"` or `alg: "none"` in the header
**When** the dependency executes
**Then** HTTP 401 is raised (PyJWT rejects non-EdDSA algorithms)

**Given** a structurally valid EdDSA JWT whose payload is missing the `amount` field
**When** the dependency executes
**Then** HTTP 422 is raised

**And** for every rejection case, a structured JSON log entry is emitted with `level: "ERROR"`, `event: "mandate_rejected"`, `reason` describing the failure, and `ip` containing the client IP address
**And** PyJWT is called with `algorithms=["EdDSA"]` — never with `algorithms=None` or a list including `"none"` or `"HS256"`
**And** the dependency lives exclusively in `app/dependencies.py` and `app/services/crypto.py` — no other file imports PyJWT

---

### Story 3.2: Checkout Session Endpoint

As a mock AI Agent,
I want to submit a structured invoice to `POST /api/checkout` and receive a session token and checkout context,
So that I have all the information needed to construct and sign my Payment Mandate for the settlement step.

**Acceptance Criteria:**

**Given** a valid `CheckoutRequest` body with `session_id` (UUID), `agent_id` (non-empty string), `currency: "USD"`, and a non-empty `items` list where each item has `name`, `quantity >= 1`, and `unit_price > 0`
**When** `POST /api/checkout` is called
**Then** the response is HTTP 201
**And** response body contains `session_token` (non-empty string) and `checkout_context` object
**And** `checkout_context.session_id` equals the submitted `session_id`
**And** `checkout_context.total_amount` equals the server-computed sum of `quantity × unit_price` across all items
**And** `checkout_context.currency` equals the submitted `currency`
**And** `checkout_context.server_timestamp` is a valid ISO 8601 datetime string
**And** the `invoices` table contains exactly one record with the submitted `session_id`, `status: "pending"`, and `total_amount` matching the computed value

**Given** the `items` field is an empty list
**When** `POST /api/checkout` is called
**Then** the response is HTTP 422

**Given** the `currency` field is `"XYZ"` (not a valid ISO 4217 code)
**When** `POST /api/checkout` is called
**Then** the response is HTTP 422

**Given** a `session_id` that already exists in the `invoices` table
**When** `POST /api/checkout` is called again with the same `session_id`
**Then** the response is HTTP 409

---

## Epic 4: Autonomous Payment Settlement

The AI Agent can complete the full Human-Not-Present commerce cycle: a signed Payment Mandate passes cryptographic verification, triggers a Stripe Sandbox charge, and produces a durable settlement record with a mandate audit trail in PostgreSQL — the agent receives a confirmed payment intent ID.

### Story 4.1: Stripe Sandbox Payment Service

As a developer,
I want a self-contained Stripe service module that creates test `PaymentIntent`s using the Stripe Python SDK in sandbox mode,
So that settlement calls are isolated, independently testable with mocks, and structurally guaranteed never to hit production Stripe.

**Acceptance Criteria:**

**Given** `STRIPE_API_KEY` is a valid `sk_test_...` key
**When** `create_payment_intent(amount=7999, currency="usd")` is called from `app/services/settlement.py`
**Then** the Stripe SDK creates a `PaymentIntent` with `status: "succeeded"` using test payment method `pm_card_visa`
**And** the returned object contains a non-empty `id` field (the Stripe PaymentIntent ID)

**Given** the Stripe SDK raises a `stripe.error.StripeError`
**When** `create_payment_intent` is called
**Then** the exception propagates to the caller unchanged (the route handler maps it to HTTP 502)
**And** no database writes occur in the service layer

**And** `app/services/settlement.py` contains all Stripe SDK calls — no other file in `app/` imports the `stripe` module
**And** amount is passed in minor currency units (cents) to the Stripe SDK (e.g., $79.99 → 7999)

---

### Story 4.2: Mandate-Gated Settlement Endpoint

As a mock AI Agent,
I want to submit my signed Payment Mandate to `POST /api/complete` and receive a confirmed Stripe payment intent ID,
So that I can prove the full Human-Not-Present commerce cycle — from cryptographic authorization to payment settlement — completed successfully.

**Acceptance Criteria:**

**Given** a valid EdDSA-signed mandate with `session_id` referencing an existing invoice with `status: "pending"`
**When** `POST /api/complete` is called
**Then** the AP2 Dependency verifies the mandate signature successfully
**And** the handler confirms the invoice `status` is `"pending"`
**And** `app/services/settlement.py` is called and returns a succeeded `PaymentIntent`
**And** within a single atomic DB transaction: `invoices.status` is updated to `"settled"`, `stripe_payment_intent_id` is set, and `settled_at` is written
**And** a `mandate_audit` record is inserted with `session_id`, `agent_id`, `mandate_jwt_hash` (SHA-256 hex of the raw JWT string), and `settlement_timestamp`
**And** the response is HTTP 200 with all four fields: `session_id`, `stripe_payment_intent_id`, `status: "settled"`, `settled_at`

**Given** a valid mandate referencing a `session_id` that does not exist in `invoices`
**When** `POST /api/complete` is called
**Then** the response is HTTP 404
**And** no Stripe call is made

**Given** a valid mandate referencing a `session_id` with `status: "settled"`
**When** `POST /api/complete` is called
**Then** the response is HTTP 409
**And** no Stripe call is made

**Given** the Stripe SDK raises an exception after mandate verification and session lookup both pass
**When** `POST /api/complete` is called
**Then** the response is HTTP 502
**And** the invoice `status` remains `"pending"` (no partial DB write)
**And** no `mandate_audit` record is created

**Given** `POST /api/complete` is called a second time with the same valid mandate for an already-settled session
**When** the endpoint is called
**Then** the response is HTTP 409

---

## Epic 5: End-to-End Validation, Agent Simulation & Documentation

The developer can validate the entire system with a single `pytest` command covering all cryptographic, API, and database interaction paths; execute a realistic natural-language-prompted agentic purchase from the terminal; and onboard any collaborator from scratch using only the README.

### Story 5.1: Automated Pytest Test Suite

As a developer,
I want a comprehensive pytest suite that covers all cryptographic paths, API endpoint contracts, and database interaction assertions,
So that I can verify the entire system's correctness — including all error conditions — with a single `pytest` command.

**Acceptance Criteria:**

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

---

### Story 5.2: Agent Client Simulation Script

As a developer,
I want to run a single terminal command with a natural language budget prompt that executes a complete agentic purchase against the running backend,
So that I can demonstrate the full UJ-1 commerce cycle end-to-end without Postman or manual JSON construction.

**Acceptance Criteria:**

**Given** the backend is running at `http://localhost:8000`
**And** `keys/private_key.pem` is present and contains a valid Ed25519 private key
**When** `uv run scripts/agent_client.py "Buy wireless headphones if under $100"` is executed
**Then** the script prints the catalog fetched from `/.well-known/ucp`
**And** identifies Wireless Headphones ($79.99) as within the $100 budget
**And** calls `POST /api/checkout` with a line item for Wireless Headphones and prints the session token
**And** signs a `PaymentMandatePayload` JWT (EdDSA) using `keys/private_key.pem`
**And** calls `POST /api/complete` with the signed mandate in the `payment_mandate` body field
**And** prints the settlement result including `stripe_payment_intent_id` and `status: "settled"`

**Given** the prompt is `"Buy mechanical keyboard if under $100"`
**When** the script runs
**Then** it identifies the Mechanical Keyboard ($129.99) exceeds the $100 budget
**And** prints a human-readable message: no items found within the stated budget
**And** exits without calling any API endpoint

**Given** the backend is not reachable at `http://localhost:8000`
**When** the script runs
**Then** it prints a connection error message and exits with a non-zero exit code

**And** the script uses `typer` for CLI argument handling
**And** the `BASE_URL` defaults to `http://localhost:8000` but is overridable via `--base-url` flag
**And** the script imports only standard libraries, `httpx`, `jwt`, and `cryptography` — no `app/` modules

---

### Story 5.3: Structured Logging & Developer Documentation

As a developer,
I want structured JSON logs emitted for all application events and a complete README that serves as the sole onboarding guide,
So that I can observe system behavior in a parseable log stream and any collaborator can run the full system from scratch without external help.

**Acceptance Criteria:**

**Given** the app is running
**When** any API endpoint is called
**Then** log entries are emitted in JSON format containing at minimum: `timestamp`, `level`, `event`
**And** mandate rejection log entries include `reason` and `ip` fields
**And** settlement success log entries include `session_id` and `stripe_payment_intent_id` fields
**And** `docker compose logs app | python3 -m json.tool` processes each log line without error (valid JSON per line)

**Given** a developer with Docker Desktop and a valid Stripe `sk_test_` key follows only the README
**When** they complete all steps in the execution playbook in order
**Then** `docker compose up --build` starts both services cleanly
**And** `uv run scripts/agent_client.py "Buy a USB-C Hub if under $60"` completes with a settlement response
**And** `pytest` passes with zero failures

**And** the README contains: system architecture overview, Docker Compose service topology, complete environment variable reference (name, type, example, description), local key generation instructions, step-by-step execution playbook, and pytest execution instructions
**And** every environment variable name referenced in the README matches the variable name expected by `app/config.py`
