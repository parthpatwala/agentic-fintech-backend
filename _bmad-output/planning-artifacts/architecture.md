---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
lastStep: 8
status: 'complete'
completedAt: '2026-06-20'
inputDocuments:
  - "_bmad-output/planning-artifacts/prds/prd-agentic-fintech-backend-2026-06-20/prd.md"
workflowType: 'architecture'
project_name: 'agentic-fintech-backend'
user_name: 'Parth'
date: '2026-06-20'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**

19 FRs across 7 feature areas, resolving to 5 discrete architectural components:

| Component | FRs | Architectural Role |
|---|---|---|
| UCP Discovery endpoint | FR-1, FR-2 | Static-ish JSON response with a JWK derived from `public_key.pem` at startup |
| AP2 Cryptographic Middleware | FR-3 through FR-6 | Pre-handler verification layer on `POST /api/complete` only |
| Session & Settlement handlers | FR-7 through FR-13 | Two route handlers with DB reads/writes and one external SDK call |
| Persistence layer | FR-14, FR-15 | Two-table PostgreSQL schema (invoices, mandate_audit) |
| Test harness | FR-16 through FR-18 | pytest suite with isolated DB fixtures |

Key architectural implications from FRs:

- **FR-2 (JWK derivation):** `public_key.pem` loaded and converted to JWK format once at startup, cached in application state via a FastAPI `lifespan` startup handler.
- **FR-3 (Mandate in body):** Mandate transport is `payment_mandate` JSON body field. FastAPI **Dependency** (not raw Starlette middleware) is the correct pattern — provides full access to the parsed request body and typed HTTP exceptions.
- **FR-10 (Session linkage before Stripe):** `POST /api/complete` handler call order is fixed: verify mandate → check invoice state → call Stripe → write audit.
- **FR-12 (mandate_jwt_hash):** Raw JWT string must be passed through the dependency to the handler (not just the decoded payload) for SHA-256 hashing.
- **FR-15 (FK constraint):** Settlement is a single atomic transaction: Stripe success → DB invoice update → mandate_audit write, all-or-nothing.

**Non-Functional Requirements:**

| NFR | Architectural Implication |
|---|---|
| NFR-2: `sk_test_` gate at startup | Pydantic `Settings` validator rejects non-test keys; fails fast on misconfiguration |
| NFR-3: Algorithm confusion protection | PyJWT called with `algorithms=["EdDSA"]` explicitly at every call site; centralized in the Dependency |
| NFR-4/5: Docker-only runtime | `python:3.12-slim` base image, pinned `requirements.txt`, no host Python dependency |
| NFR-6: Structured JSON logs | JSON logging config applied once at app startup; consistent field schema across all emitters |

**Scale & Complexity:**

- Primary domain: Backend API (REST, no UI)
- Complexity level: Low — prototype/PoC, single-developer, no multi-tenancy, no auth flows, no background workers
- Estimated architectural components: 5
- Async surface: FastAPI async-capable; Stripe SDK calls synchronous — acceptable for prototype scope

### Technical Constraints & Dependencies

| Constraint | Source | Implication |
|---|---|---|
| FastAPI framework | PRD §4 | Routes, dependencies, Pydantic models, lifespan hooks |
| PostgreSQL via Docker Compose | FR-14 | Python DB driver required (asyncpg or psycopg2) |
| PyJWT + `cryptography` library | PRD §4 | EdDSA algorithm requires `cryptography` installed alongside PyJWT |
| Stripe Python SDK (test mode only) | FR-11, NFR-2 | Sync SDK; `sk_test_` prefix validated at boot |
| Ed25519 key files in `keys/` | FR-2, FR-4, NFR-1 | Both files gitignored; paths configurable via env vars |
| Docker-only runtime | NFR-4/5 | Compose orchestrates app + postgres; no host-level installs required |
| pytest suite | FR-16–18 | Test DB isolation via separate `TEST_DATABASE_URL` or transaction rollback fixture |

### Cross-Cutting Concerns Identified

1. **Startup validation** — Key loading (JWK derivation), Stripe key format check, DB connectivity. Single `lifespan` context manager; fails fast with clear error messages.
2. **Cryptographic key management** — `public_key.pem` loaded once at startup, cached as application state. Never re-read per request.
3. **Database session management** — Per-request session scoping; atomic transactions on settlement path.
4. **Error taxonomy** — Missing mandate → 422 | Invalid signature → 401 | Wrong session state → 404/409 | Stripe failure → 502. Consistent across all handlers.
5. **Test isolation** — Test suite never touches the development database. Separate `TEST_DATABASE_URL` or rollback fixture per test.
6. **Algorithm confusion hardening** — JWT verification centralized in one Dependency; no handler calls PyJWT directly.
7. **Structured logging** — JSON format configured once at boot; all emitters use consistent field schema (`timestamp`, `level`, `event`, `session_id`, `detail`).

---

## Starter Template Evaluation

### Primary Technology Domain

Backend API (Python/FastAPI) — no frontend, no UI, REST-only, prototype scope.

### Starter Options Considered

Four established FastAPI starters were evaluated: `fastapi/full-stack-fastapi-template`, `ivan-borovets/fastapi-clean-example`, `eugeneliukindev/fastapi-clean-layered-arch-example`, and `iam-abbas/FastAPI-Production-Boilerplate`. All disqualified: front-ends, DDD/CQRS, Redis/Celery — none fit a 2-table, 5-component prototype whose primary complexity is cryptographic protocol compliance, not application scale.

### Selected Approach: Custom Scaffold from Scratch

**Rationale:** The PRD specifies a precise, narrow requirement set (AP2/UCP protocol, 3 endpoints, 2 DB tables, Stripe Sandbox, pytest). A bespoke scaffold containing only what is needed is cleaner, faster to reason about, and avoids abstraction layers that would obscure the protocol implementation — which is the entire point of this prototype.

**Package manager:** `uv` (replaces pip). Modern, fast, reproducible. Lock file (`uv.lock`) committed; `pyproject.toml` is the single source of truth for dependencies.

**Project initialization commands:**

```bash
uv init agentic-fintech-backend
cd agentic-fintech-backend
uv add fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg alembic \
    pyjwt cryptography stripe python-json-logger pydantic-settings \
    pytest pytest-asyncio httpx typer
uv add --dev ruff
```

### Architectural Decisions Established by Scaffold

**Language & Runtime:** Python 3.12, managed by `uv`, `pyproject.toml` + `uv.lock`.

**Database driver:** `asyncpg` — native async PostgreSQL driver; required for SQLAlchemy 2.0 async mode with FastAPI.

**ORM & Migrations:** SQLAlchemy 2.0 async mode + Alembic. Schema version-controlled from day one.

**Settings management:** `pydantic-settings` `BaseSettings` — reads from `.env`; `sk_test_` validator on `STRIPE_API_KEY` at startup.

**Linting/formatting:** Ruff — single tool replacing flake8 + black + isort; configured in `pyproject.toml`.

**New components added (user-directed):**

1. **Mock Catalog** — A static product inventory (`catalog/products.json`) served inline inside the `/.well-known/ucp` discovery response. The `UCPProfile` Pydantic model gains a `catalog: list[ProductItem]` field. This enables agents to discover purchasable items without a separate catalog API call — self-contained discovery.

2. **Agent Client Script** (`scripts/agent_client.py`) — A CLI simulation script using `typer` that:
   - Accepts a natural language budget/item prompt (e.g., `"Buy wireless headphones if under $100"`)
   - Fetches `GET /.well-known/ucp` to retrieve the live catalog and server public key
   - Parses the budget constraint from the prompt (regex: `under \$(\d+)` / `if.*<\s*\$(\d+)`)
   - Filters catalog items meeting the constraint; selects the first match
   - Calls `POST /api/checkout` with the selected item as an invoice
   - Loads `keys/private_key.pem` and signs a `PaymentMandatePayload` JWT (EdDSA)
   - Calls `POST /api/complete` with the signed mandate in `payment_mandate` body field
   - Prints the full settlement result to stdout

---

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
- Async DB driver: asyncpg + SQLAlchemy 2.0 async — required before any DB code is written
- JWT library configuration: PyJWT with `algorithms=["EdDSA"]` — required before any mandate handling
- Mandate transport: JSON body field `payment_mandate` — required before AP2 dependency is written
- Settings validation: pydantic-settings with `sk_test_` validator — required before Stripe SDK is initialized
- Package manager: `uv` — required before any dependencies are installed

**Important Decisions (Shape Architecture):**
- FastAPI Dependency (not Starlette middleware) for AP2 mandate verification
- `lifespan` context manager for startup validation (key loading, Stripe key check, DB connectivity)
- Alembic for DB migrations from day one
- Separate `TEST_DATABASE_URL` for test isolation
- `catalog/products.json` as the authoritative product source (loaded at startup, served in discovery)

**Deferred Decisions (Post-MVP):**
- Full AP2 Mandate schema (Intent Mandate, open/closed states) — post-prototype
- OAuth 2.0 Identity Linking — post-prototype
- Async Stripe SDK — prototype uses sync Stripe SDK with `asyncio.to_thread` wrapper if needed

### Data Architecture

| Decision | Choice | Rationale |
|---|---|---|
| ORM | SQLAlchemy 2.0 async | Native async; aligns with FastAPI async handlers |
| DB driver | asyncpg | Required for SQLAlchemy async with PostgreSQL |
| Migration tool | Alembic | Version-controlled schema; standard with SQLAlchemy |
| Session scoping | Per-request via FastAPI Dependency | Clean lifecycle; no session leaks |
| Transaction pattern | Explicit `async with session.begin()` blocks on write paths | Atomic settlement (FR-10 → FR-13) |
| Test DB isolation | Separate `TEST_DATABASE_URL` + schema recreation per session | Dev DB never touched by tests |

**Database schema:**

```sql
-- invoices table
CREATE TABLE invoices (
    session_id    UUID PRIMARY KEY,
    agent_id      VARCHAR NOT NULL,
    items         JSONB NOT NULL,
    total_amount  NUMERIC(10,2) NOT NULL,
    currency      VARCHAR(3) NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'pending',
    stripe_payment_intent_id VARCHAR,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settled_at    TIMESTAMPTZ
);

-- mandate_audit table
CREATE TABLE mandate_audit (
    id                   SERIAL PRIMARY KEY,
    session_id           UUID NOT NULL REFERENCES invoices(session_id),
    agent_id             VARCHAR NOT NULL,
    mandate_jwt_hash     VARCHAR(64) NOT NULL,
    settlement_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Authentication & Security

| Decision | Choice | Rationale |
|---|---|---|
| Mandate verification | PyJWT `decode()` with `algorithms=["EdDSA"]` | Explicit algorithm list prevents algorithm confusion attacks (NFR-3) |
| Key loading | At startup via `lifespan`; cached in `app.state` | Never re-read per request (A-1) |
| Stripe key validation | `pydantic-settings` validator: must start with `sk_test_` | Fails fast; never allows production key (NFR-2) |
| Key file paths | Configurable via `KEY_PUBLIC_PATH` env var | Not hardcoded; works in Docker and local |
| JWT hash for audit | SHA-256 of raw JWT string | Deterministic audit trail; not the decoded payload |
| `private_key.pem` | Used only by `scripts/agent_client.py`; never loaded by server | Server is verifier-only; principle of least privilege |

### API & Communication Patterns

| Decision | Choice | Rationale |
|---|---|---|
| API style | REST / JSON | Protocol requirement; no GraphQL needed |
| JSON field naming | `snake_case` throughout | Python convention; matches Pydantic defaults |
| Response format | Direct Pydantic model (no envelope wrapper) | PRD schemas are authoritative; envelope adds no value for prototype |
| Error format | FastAPI `HTTPException` with structured `detail` dict | Consistent; parseable by client scripts |
| Date format | ISO 8601 strings (Pydantic default) | Interoperable; UCP/AP2 compatible |
| Discovery endpoint | `GET /.well-known/ucp` — no auth, public | UCP spec requirement (FR-1) |
| Mandate transport | `payment_mandate` JSON body field on `POST /api/complete` | AP2/A2A/MCP JSON-RPC body alignment (DL-006) |

**Error HTTP taxonomy (canonical, no deviations):**

| Condition | HTTP Code |
|---|---|
| Missing `payment_mandate` field | 422 (Pydantic validation) |
| Invalid/tampered JWT signature | 401 |
| Missing required mandate fields | 422 |
| Unknown `session_id` | 404 |
| Already-settled session | 409 |
| Stripe SDK exception | 502 |
| Malformed checkout payload | 422 |

### Infrastructure & Deployment

| Decision | Choice | Rationale |
|---|---|---|
| Package manager | `uv` | Fast, reproducible, lock file committed |
| Container runtime | Docker + Docker Compose | NFR-4/5; no host dependencies |
| Base image | `python:3.12-slim` | Pinned; minimal attack surface |
| PostgreSQL | Docker Compose named service with health check | App waits for DB readiness before accepting requests |
| Secrets | `.env` file (gitignored); `.env.example` committed | Standard pattern; never hardcoded |
| ASGI server | `uvicorn` with standard extras | FastAPI recommended; hot reload in dev |
| Linting | Ruff | Single tool for format + lint; configured in `pyproject.toml` |

---

## Implementation Patterns & Consistency Rules

### Naming Conventions

**Database (snake_case, plural table names):**
- Tables: `invoices`, `mandate_audit` (not `Invoice`, not `invoice`)
- Columns: `session_id`, `total_amount`, `created_at` (not `sessionId`, not `TotalAmount`)
- FK constraint naming: `fk_mandate_audit_session_id`
- Index naming: `ix_invoices_status`, `ix_mandate_audit_session_id`

**API endpoints (lowercase, hyphen-separated path segments):**
- `GET /.well-known/ucp` — discovery (no trailing slash)
- `POST /api/checkout` — checkout session
- `POST /api/complete` — settlement

**Python code (PEP 8, snake_case everywhere):**
- Functions: `verify_mandate()`, `get_db_session()`, `load_public_key()`
- Files: `crypto.py`, `invoice.py`, `settlement.py`
- Classes: `CheckoutRequest`, `PaymentMandatePayload`, `InvoiceDB`
- Constants: `SUPPORTED_CAPABILITIES`, `UCP_VERSION`

**JSON fields (snake_case, matching Pydantic model field names):**
- `session_id`, `agent_id`, `total_amount`, `payment_mandate`, `settled_at`
- Never camelCase in request/response bodies

### Structure Patterns

**One router per endpoint group** — `discovery.py`, `checkout.py`, `complete.py`. No mixed concerns in a single router file.

**Services are pure functions or stateless classes** — no FastAPI dependencies injected into services. Services receive data, return data. Dependencies inject services into routes.

**All DB access goes through `app/services/invoice.py`** — No SQLAlchemy session calls in routers or other service files. Invoice service owns all DB reads and writes.

**Crypto operations are centralized in `app/services/crypto.py`** — PyJWT is never imported anywhere else. No router or handler calls PyJWT directly.

**`catalog/products.json` is the single source of truth for products** — loaded once at startup into `app.state.catalog`; never read from disk per request.

### Format Patterns

**API responses:** Direct Pydantic model serialization. No wrapper envelope. `model_dump()` with `mode="json"` for datetime serialization.

**Structured log events (JSON):**
```json
{"timestamp": "2026-06-20T14:00:00Z", "level": "INFO", "event": "checkout_created", "session_id": "...", "detail": "..."}
{"timestamp": "2026-06-20T14:00:01Z", "level": "ERROR", "event": "mandate_rejected", "reason": "invalid_signature", "ip": "..."}
```
Fields always present: `timestamp`, `level`, `event`. Optional but standardized: `session_id`, `reason`, `ip`, `detail`.

**pytest test naming:**
- Test files: `test_<module>.py`
- Test functions: `test_<behaviour>_<condition>()` — e.g., `test_checkout_missing_items_returns_422()`, `test_mandate_tampered_payload_returns_401()`

### Process Patterns

**AP2 Dependency call order (MUST NOT be reordered):**
1. Extract `payment_mandate` from body
2. Validate JWT format (three dot-separated segments)
3. Verify EdDSA signature via `crypto.py`
4. Decode and validate `PaymentMandatePayload` fields
5. Return `(raw_jwt: str, payload: PaymentMandatePayload)` tuple to handler

**Settlement handler call order (MUST NOT be reordered):**
1. Receive `(raw_jwt, payload)` from AP2 Dependency
2. Query invoice by `session_id` — 404 if not found
3. Check `status == "pending"` — 409 if already settled
4. Call Stripe SDK `PaymentIntents.create()`
5. On success: begin DB transaction → update invoice → insert mandate_audit → commit
6. On Stripe exception: return 502, do NOT update DB
7. Return `CompleteResponse`

**All AI agents MUST:**
- Never call PyJWT outside of `app/services/crypto.py`
- Never write to the DB outside of `app/services/invoice.py`
- Never hardcode the Stripe key, key file paths, or DB URL
- Never reorder the AP2 Dependency or Settlement handler call sequences
- Never use `algorithms=None` or omit `algorithms` when calling PyJWT

---

## Project Structure & Boundaries

### Complete Project Directory

```
agentic-fintech-backend/
├── pyproject.toml               # uv-managed deps, ruff config, pytest config
├── uv.lock                      # committed lock file
├── .env.example                 # all required env vars with descriptions
├── .env                         # gitignored — local secrets
├── .gitignore
├── ruff.toml                    # or inline in pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── README.md
│
├── catalog/
│   └── products.json            # static product inventory (source of truth)
│
├── keys/                        # gitignored entirely
│   ├── private_key.pem          # mock agent signing key
│   └── public_key.pem           # server verification key
│
├── scripts/
│   └── agent_client.py          # CLI simulation script (typer)
│
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app factory + lifespan context manager
│   ├── config.py                # pydantic-settings BaseSettings + validators
│   ├── dependencies.py          # AP2 mandate verification FastAPI Dependency
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── discovery.py         # GET /.well-known/ucp (catalog + JWK embedded)
│   │   ├── checkout.py          # POST /api/checkout
│   │   └── complete.py          # POST /api/complete
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schemas.py           # Pydantic request/response models (from PRD §8)
│   │   └── db.py                # SQLAlchemy ORM mapped classes
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── crypto.py            # JWK derivation, EdDSA verify (PyJWT owner)
│   │   ├── invoice.py           # All DB reads/writes (SQLAlchemy session owner)
│   │   └── settlement.py        # Stripe SDK wrapper
│   │
│   └── db/
│       ├── __init__.py
│       └── session.py           # Async engine factory + session dependency
│
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py  # invoices + mandate_audit tables
│
└── tests/
    ├── __init__.py
    ├── conftest.py              # pytest fixtures: test app, test DB, test keys
    ├── test_discovery.py        # FR-1, FR-2: profile content + catalog assertions
    ├── test_checkout.py         # FR-7, FR-8, FR-9: invoice creation paths
    ├── test_complete.py         # FR-10 to FR-13: settlement paths
    ├── test_crypto.py           # FR-16: all EdDSA cryptographic path cases
    └── test_agent_client.py     # end-to-end script smoke tests
```

### Component Boundaries

**`app/main.py`** — Owns: app factory, router registration, `lifespan` (key loading → catalog loading → Stripe key validation → DB connectivity check). Imports from: all routers, `config.py`, `services/crypto.py`, `db/session.py`.

**`app/dependencies.py`** — Owns: AP2 mandate verification Dependency. Imports from: `services/crypto.py`, `models/schemas.py`. Returns `(raw_jwt: str, payload: PaymentMandatePayload)`. NO DB access, NO Stripe access.

**`app/routers/discovery.py`** — Owns: UCP discovery response construction. Reads: `app.state.catalog`, `app.state.jwk`. Imports from: `models/schemas.py`. No DB, no Stripe, no crypto library calls.

**`app/routers/checkout.py`** — Owns: `POST /api/checkout` handler. Calls: `services/invoice.py`. Returns: `CheckoutResponse`. No Stripe, no crypto.

**`app/routers/complete.py`** — Owns: `POST /api/complete` handler. Depends on: AP2 Dependency. Calls: `services/invoice.py`, `services/settlement.py`. Enforces the mandatory settlement call order.

**`app/services/crypto.py`** — Owns: all PyJWT and `cryptography` library calls. Functions: `load_public_key(path)`, `derive_jwk(public_key)`, `verify_mandate(token, public_key)`. No FastAPI, no DB, no Stripe.

**`app/services/invoice.py`** — Owns: all SQLAlchemy session operations. Functions: `create_invoice(session, data)`, `get_invoice(session, session_id)`, `settle_invoice(session, session_id, stripe_id)`, `write_mandate_audit(session, data)`. No FastAPI, no Stripe, no crypto.

**`app/services/settlement.py`** — Owns: Stripe SDK calls. Functions: `create_payment_intent(amount, currency)`. No DB, no crypto. Returns Stripe `PaymentIntent` object or raises.

**`scripts/agent_client.py`** — Owns: end-to-end simulation. Imports: `httpx`, `jwt`, `cryptography`. Reads `keys/private_key.pem`. Communicates with the running FastAPI server via HTTP. Not imported by the app — standalone script only.

**`catalog/products.json`** — Read once at startup by `lifespan`. Loaded into `app.state.catalog`. Served inline in discovery response. Never written at runtime.

### Updated Pydantic Models (incorporating Mock Catalog)

```python
# app/models/schemas.py additions

class ProductItem(BaseModel):
    id: str            # e.g. "prod_001"
    name: str
    price: float       # in major currency units (e.g. 79.99)
    currency: str      # ISO 4217

class UCPRoutes(BaseModel):
    checkout: str      # "/api/checkout"
    complete: str      # "/api/complete"

class JWK(BaseModel):
    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: str             # base64url-encoded public key material

class UCPProfile(BaseModel):
    version: Literal["2026-04-08"]
    capabilities: list[str]
    routes: UCPRoutes
    signing_keys: list[JWK]
    catalog: list[ProductItem]   # ← NEW: static product inventory

class UCPDiscoveryProfile(BaseModel):
    ucp: UCPProfile
```

**`catalog/products.json` (initial inventory):**
```json
[
  {"id": "prod_001", "name": "Wireless Headphones",  "price": 79.99,  "currency": "USD"},
  {"id": "prod_002", "name": "Mechanical Keyboard",  "price": 129.99, "currency": "USD"},
  {"id": "prod_003", "name": "USB-C Hub",            "price": 49.99,  "currency": "USD"},
  {"id": "prod_004", "name": "HD Webcam",            "price": 89.99,  "currency": "USD"},
  {"id": "prod_005", "name": "Desk Lamp LED",        "price": 34.99,  "currency": "USD"}
]
```

### Data Flow

```
scripts/agent_client.py
  │
  ├─ GET /.well-known/ucp ──────────────────→ discovery.py
  │     ← {catalog, signing_keys, routes}         (app.state.catalog + app.state.jwk)
  │
  ├─ [client parses catalog, applies budget constraint, selects item]
  │
  ├─ POST /api/checkout ────────────────────→ checkout.py
  │     {session_id, agent_id, items, currency}     → invoice.py → PostgreSQL (invoices INSERT)
  │     ← {session_token, checkout_context}
  │
  ├─ [client signs PaymentMandatePayload JWT with private_key.pem]
  │
  └─ POST /api/complete ────────────────────→ dependencies.py (AP2 verify)
        {payment_mandate: "<jwt>"}                → complete.py
                                                    → invoice.py (SELECT + UPDATE)
                                                    → settlement.py → Stripe Sandbox
                                                    → invoice.py (mandate_audit INSERT)
        ← {session_id, stripe_payment_intent_id, status, settled_at}
```

### Integration Points

**Internal:**
- `lifespan` → `app.state.catalog` (loaded from `catalog/products.json`)
- `lifespan` → `app.state.public_key` (loaded from `keys/public_key.pem`)
- `lifespan` → `app.state.jwk` (derived from public key)
- All routers → `db/session.py` async session dependency

**External:**
- Stripe Python SDK (sync) → Stripe Test Sandbox API
- `scripts/agent_client.py` → local FastAPI server via `httpx`

---

## Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility:** All technology choices are compatible: FastAPI + SQLAlchemy 2.0 async + asyncpg is the current standard async Python backend stack. PyJWT with `cryptography` for EdDSA is the correct pairing. Stripe Python SDK is sync but this is acceptable given prototype scope and the limited surface area of settlement calls. `uv` is compatible with all dependency management needs.

**Pattern Consistency:** Naming conventions (snake_case JSON, snake_case Python, plural DB tables) are consistent across the entire stack. The "one service owns one concern" pattern is enforced in boundary definitions. Error taxonomy is canonical and used uniformly.

**Structure Alignment:** The project structure directly maps to the 5 architectural components identified in Step 2. Every FR has a named file responsible for it.

### Requirements Coverage Validation ✅

| FR Group | Coverage |
|---|---|
| FR-1, FR-2 (UCP Discovery + Catalog) | `app/routers/discovery.py` + `catalog/products.json` + `app.state` |
| FR-3 to FR-6 (AP2 Middleware) | `app/dependencies.py` + `app/services/crypto.py` |
| FR-7 to FR-9 (Checkout) | `app/routers/checkout.py` + `app/services/invoice.py` |
| FR-10 to FR-13 (Settlement) | `app/routers/complete.py` + `app/services/settlement.py` + `app/services/invoice.py` |
| FR-14, FR-15 (PostgreSQL schema) | `alembic/versions/001_initial_schema.py` + `docker-compose.yml` |
| FR-16 to FR-18 (pytest) | `tests/` directory + `conftest.py` fixtures |
| FR-19 (README) | `README.md` |
| NFR-1 (key gitignore) | `.gitignore` |
| NFR-2 (Stripe key gate) | `app/config.py` pydantic-settings validator |
| NFR-3 (algorithm confusion) | `app/services/crypto.py` — `algorithms=["EdDSA"]` enforced |
| NFR-4/5 (Docker, pinned image) | `Dockerfile` + `docker-compose.yml` |
| NFR-6 (structured logs) | `app/main.py` logging config + `python-json-logger` |

**User Journeys:**
- UJ-1 (mock agent full cycle): Fully covered by `scripts/agent_client.py` end-to-end
- UJ-2 (pytest validation): Fully covered by `tests/` suite

### Implementation Readiness Validation ✅

**Decision Completeness:** All critical decisions documented with rationale. Technology versions resolvable via `uv` (latest at init time, pinned in `uv.lock`). No ambiguous decisions remain.

**Structure Completeness:** Every FR mapped to a specific file. Every boundary defined. Every service has a clear owner and explicit imports-from list.

**Pattern Completeness:** Naming, error taxonomy, call order sequences, and log format all specified. Anti-patterns documented. No conflict point left open.

### Gap Analysis Results

**Critical Gaps:** None.

**Minor Gaps (post-MVP):**
- OQ-2 (server-signed checkout context as JWT) — carried to architecture v2 if prototype graduates
- Full AP2 Mandate schema (Intent Mandate, open/closed states) — post-prototype scope

### Architecture Completeness Checklist

**Requirements Analysis**
- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed (Low/Prototype)
- [x] Technical constraints identified (7 constraints documented)
- [x] Cross-cutting concerns mapped (7 concerns documented)

**Architectural Decisions**
- [x] Critical decisions documented with versions
- [x] Technology stack fully specified (Python 3.12, FastAPI, SQLAlchemy 2.0, asyncpg, Alembic, uv, Ruff)
- [x] Integration patterns defined (Stripe, PostgreSQL, agent_client script)
- [x] Performance considerations addressed (async drivers, sync Stripe acceptable for prototype)

**Implementation Patterns**
- [x] Naming conventions established (snake_case throughout, plural tables)
- [x] Structure patterns defined (one service owns one concern)
- [x] Communication patterns specified (mandatory call order sequences)
- [x] Process patterns documented (error taxonomy, log format, anti-patterns)

**Project Structure**
- [x] Complete directory structure defined (all files named)
- [x] Component boundaries established (imports-from lists per component)
- [x] Integration points mapped (internal app.state, external Stripe + httpx)
- [x] Requirements to structure mapping complete (FR → file table)

### Architecture Readiness Assessment

**Overall Status: READY FOR IMPLEMENTATION**

**Confidence Level:** High

**Key Strengths:**
- Protocol-first design: every architectural decision traces back to UCP/AP2 spec compliance
- Security-by-construction: algorithm confusion protection, key encapsulation, Stripe key gate all enforced structurally
- Single-source-of-truth components: catalog, crypto, and DB operations each have one owner
- End-to-end testability built in: `scripts/agent_client.py` provides a realistic simulation loop from day one
- Clean prototype scope: no accidental complexity; every component maps to a PRD requirement

**Areas for Future Enhancement:**
- Server-signed checkout context (OQ-2) — makes the Cart Mandate flow spec-complete
- Full AP2 Mandate schema compliance (Intent Mandate, open/closed mandate chain)
- OAuth 2.0 Identity Linking (currently explicit non-goal)
- `UCP-Agent` header processing and `supported_versions` negotiation

### Implementation Handoff

**AI Agent Guidelines:**
- Follow all architectural decisions exactly as documented above
- Use implementation patterns consistently — particularly the mandatory call order sequences for AP2 Dependency and Settlement Handler
- Respect component boundaries: no service imports another service; no router calls PyJWT directly
- Refer to `prd.md §8 API Contracts` for exact Pydantic schema field names and types
- `catalog/products.json` is never modified at runtime — it is config, not data

**First Implementation Story:** Scaffold initialization — `uv init`, add all dependencies, create the directory structure, `Dockerfile`, `docker-compose.yml`, `.env.example`, and `pyproject.toml` with Ruff and pytest config. Verify `docker compose up` starts both services cleanly.
