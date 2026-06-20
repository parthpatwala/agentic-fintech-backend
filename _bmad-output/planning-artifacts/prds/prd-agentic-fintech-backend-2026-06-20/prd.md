---
title: Agentic Banking Backend
status: draft
created: 2026-06-20
updated: 2026-06-20
---

# PRD: Agentic Banking Backend

## 0. Document Purpose

This PRD defines the requirements for a prototype backend that demonstrates a complete Human-Not-Present (HNP) autonomous machine commerce cycle using the Universal Commerce Protocol (UCP) and Agent Payments Protocol (AP2). It is the authoritative source for downstream architecture, epic, and story work. All terms used in FRs, UJs, and SMs are defined in §3 Glossary; no synonyms are introduced elsewhere in this document. The Assumptions Index in §9 lists every inferred decision for explicit confirmation. An addendum file captures technical mechanism detail that lives downstream of this PRD.

---

## 1. Vision

The Agentic Banking Backend is a Python/FastAPI prototype that acts as a compliant UCP merchant endpoint — capable of being autonomously discovered, negotiated with, and settled by an external AI Agent without any human present at transaction time. It demonstrates the complete "agentic commerce handshake": from machine-readable capability declaration, through cryptographically verified mandate exchange, to a mock payment settlement recorded in a persistent database.

The core insight this prototype makes concrete is that autonomous machine-to-machine commerce requires a different trust model than human-present checkout. Rather than relying on session cookies or interactive authorization, the HNP flow relies on a chain of cryptographically signed Mandates — Verifiable Digital Credentials that prove an AI Agent has been explicitly authorized by a human user to act within defined constraints. This prototype implements the server (merchant/verifier) side of that chain using the published AP2 and UCP open standards.

For Parth as the builder, this prototype is both a learning vehicle and a crisp demonstration artifact: a running Docker environment that a visitor can clone, configure with a Stripe test key, and observe a complete agentic transaction cycle end-to-end with a single command sequence.

---

## 2. Target User

### 2.1 Jobs To Be Done

- **Learn by building:** Understand the UCP/AP2 protocol stack by implementing the merchant/verifier side of the handshake at code level.
- **Demonstrate capability:** Show a complete, observable HNP commerce cycle to technical stakeholders or collaborators.
- **Establish a scaffold:** Create a working, well-tested prototype that can serve as the foundation for more complete UCP/AP2 implementations.
- **Validate the stack:** Confirm that FastAPI + Ed25519 + PyJWT + Stripe Sandbox + PostgreSQL compose cleanly for this domain.

### 2.2 Non-Users (v1)

- End consumers transacting in production.
- Non-technical stakeholders who cannot read JSON payloads or run Docker.
- Production AI agent platforms expecting full UCP compliance beyond the `dev.ucp.shopping.checkout` and `dev.ucp.shopping.ap2_mandate` capabilities.

### 2.3 Key User Journeys

**UJ-1. Mock Agent completes an autonomous purchase against the backend.**

- **Persona + context:** A mock AI Agent (simulated by Postman or a test script), acting on behalf of a pre-authorized human user who is not present.
- **Entry state:** The Agent has read the UCP Discovery Profile and knows the server's capabilities and signing key. It holds a pre-signed Payment Mandate (JWT, EdDSA) representing the user's authorization.
- **Path:**
  1. Agent sends `POST /api/checkout` with a structured invoice payload (items, amounts, currency, session ID).
  2. Server validates the payload, persists an invoice record, returns a session token and checkout context.
  3. Agent signs the checkout context into a Payment Mandate using its private key.
  4. Agent sends `POST /api/complete` with the signed Payment Mandate in the request body.
  5. Server middleware verifies the EdDSA signature against the server-resident public key; rejects if invalid.
  6. On verification pass, server calls Stripe Sandbox SDK to execute a mock charge.
  7. Server persists the settlement outcome and returns a success response with the Stripe payment intent reference.
- **Climax:** The Agent receives a 200 response containing the Stripe payment intent ID. The human operator can observe the charge in the Stripe test dashboard.
- **Resolution:** Invoice record, session state, and mandate audit entry are all written to PostgreSQL. The cycle is complete and auditable.
- **Edge case:** If the Payment Mandate signature is invalid or the mandate is malformed, the middleware returns HTTP 401 with a structured error. No charge is attempted. The rejection is logged.

**UJ-2. Parth validates the implementation with the automated test suite.**

- **Persona + context:** Parth as developer, verifying that all cryptographic paths, API contracts, and database interactions behave correctly.
- **Entry state:** Docker Compose environment running; test database seeded.
- **Path:**
  1. Runs `pytest` from the project root.
  2. Suite exercises: valid mandate → full cycle pass; tampered mandate → 401 rejection; missing fields → 422; Stripe mock returns expected test response.
  3. All tests pass; coverage output printed.
- **Climax:** Zero failures. All critical paths covered.
- **Resolution:** Parth can commit with confidence. Green CI is the gate signal.

---

## 3. Glossary

- **UCP (Universal Commerce Protocol)** — Open standard for interoperable agentic commerce. Defines discovery, checkout, identity linking, order management, and payment capabilities. Governed at ucp.dev.
- **AP2 (Agent Payments Protocol)** — Open protocol (Apache 2.0, Google-led) that defines how AI Agents carry and present cryptographically signed Mandates as proof of human authorization for machine-to-machine payment transactions.
- **UCP Discovery Profile** — The machine-readable JSON document served at `/.well-known/ucp` that declares the server's protocol version, supported capabilities, route paths, and public signing keys.
- **Capability** — A named, versioned unit of commerce functionality declared in the UCP Discovery Profile. This prototype declares `dev.ucp.shopping.checkout` and `dev.ucp.shopping.ap2_mandate`.
- **Mandate** — A Verifiable Digital Credential (VDC): a tamper-evident, cryptographically signed JSON object that represents a specific authorization granted by a human user to an AI Agent.
- **Payment Mandate** — The specific Mandate type that authorizes a payment transaction. Presented by the Agent to the merchant/verifier at settlement time. Implemented in this prototype as a JWT signed with EdDSA (Ed25519).
- **HNP (Human-Not-Present)** — The transaction modality where no human is actively present or confirming the transaction at execution time. The Agent acts within pre-authorized Mandate constraints.
- **Mandate Verification** — The server-side process of validating a Payment Mandate's cryptographic signature, structural integrity, and scope before permitting settlement.
- **Session** — A transient, server-side record that links a `POST /api/checkout` invocation (invoice + context) to a subsequent `POST /api/complete` invocation (mandate + settlement). Persisted in PostgreSQL.
- **Invoice** — The structured record of items, amounts, and currency submitted by the Agent at checkout. The canonical input to a Session.
- **Settlement** — The act of executing a payment after Mandate Verification passes. In this prototype, settlement is always a Stripe Sandbox mock charge.
- **Stripe Sandbox** — The Stripe test environment. No real money moves. Activated by a `sk_test_...` API key.
- **EdDSA / Ed25519** — The digital signature algorithm used for Payment Mandates. Ed25519 is the specific curve. EdDSA is the algorithm identifier string used in PyJWT.
- **PyJWT** — The Python JWT library used to encode and decode Payment Mandates. Configured with the `EdDSA` algorithm.
- **`public_key.pem`** — The Ed25519 public key resident on the server, used to verify Payment Mandate signatures.
- **`private_key.pem`** — The Ed25519 private key used by the mock Agent to sign Payment Mandates. In the prototype, both keys reside in the `keys/` directory.

---

## 4. Features

### 4.1 UCP Public Discovery Profile

**Description:** The server exposes a publicly accessible, machine-readable JSON document at `/.well-known/ucp`. Any UCP-compliant platform or AI Agent can fetch this document to autonomously discover the server's capabilities, route paths, and public signing key without prior configuration. This endpoint is the entry point for any agent interaction and must conform to UCP protocol version `2026-04-08`. Realizes UJ-1.

**Functional Requirements:**

#### FR-1: Discovery endpoint availability

The server MUST serve `GET /.well-known/ucp` without authentication, returning `Content-Type: application/json` and HTTP 200.

**Consequences (testable):**
- An unauthenticated `GET /.well-known/ucp` returns HTTP 200 with `Content-Type: application/json`.
- The response body is valid JSON.

#### FR-2: Discovery Profile content

The Discovery Profile JSON MUST include: `ucp.version` set to `"2026-04-08"`; `ucp.capabilities` listing `"dev.ucp.shopping.checkout"` and `"dev.ucp.shopping.ap2_mandate"`; route paths for the checkout and complete endpoints; and a `signing_keys` array containing the server's Ed25519 public key in JWK format.

**Consequences (testable):**
- `ucp.version` equals `"2026-04-08"`.
- `ucp.capabilities` contains both `"dev.ucp.shopping.checkout"` and `"dev.ucp.shopping.ap2_mandate"`.
- `signing_keys` contains at least one JWK entry with `"kty": "OKP"` and `"crv": "Ed25519"`.
- Route paths for `/api/checkout` and `/api/complete` are declared.

**Out of Scope:**
- `supported_versions` multi-version advertising.
- Platform profile negotiation via `UCP-Agent` header.

**Notes:** `[ASSUMPTION: JWK representation of the Ed25519 public key is derived from public_key.pem at server startup and embedded in the profile response. If key rotation is needed, the server must restart — acceptable for prototype scope.]`

---

### 4.2 AP2 Cryptographic Handshake Middleware

**Description:** A FastAPI middleware layer intercepts all requests to `POST /api/complete` and performs Payment Mandate verification before the request reaches the endpoint handler. The middleware extracts the JWT Payment Mandate from the request, verifies its EdDSA signature against the server-resident `public_key.pem`, and checks structural validity. Requests that fail verification are rejected before any business logic executes. Realizes UJ-1 (step 5), UJ-2.

**Functional Requirements:**

#### FR-3: Mandate extraction

The middleware MUST extract the Payment Mandate JWT from the `payment_mandate` field of the JSON request body of `POST /api/complete` requests. This mirrors the JSON-RPC body payload structure used in multi-party A2A/MCP message exchanges and aligns with the AP2 transport specification.

**Consequences (testable):**
- A request to `POST /api/complete` with no `payment_mandate` field in the body returns HTTP 422.
- A request with a `payment_mandate` value that is not a valid JWT string (not three dot-separated base64url segments) returns HTTP 401.
- The `Authorization` header is NOT used or required for mandate transport on this endpoint.

#### FR-4: EdDSA signature verification

The middleware MUST verify the Payment Mandate JWT signature using PyJWT with the `EdDSA` algorithm and the server-resident `public_key.pem`. Verification MUST fail if the signature does not match or the algorithm is not EdDSA.

**Consequences (testable):**
- A JWT signed with the correct `private_key.pem` passes verification.
- A JWT signed with a different private key returns HTTP 401.
- A JWT with a tampered payload (modified after signing) returns HTTP 401.
- A JWT specifying a different algorithm (e.g., `HS256`) is rejected.

#### FR-5: Mandate structural validation

The middleware MUST validate that the decoded Mandate payload contains required fields: `session_id`, `amount`, `currency`, and `agent_id`. `[ASSUMPTION: These are the minimum required Mandate fields for prototype scope. Full AP2 Mandate schema has additional fields — a subset is used here for tractability.]`

**Consequences (testable):**
- A valid JWT missing `session_id` returns HTTP 422.
- A valid JWT missing `amount` returns HTTP 422.
- A fully valid JWT passes through to the endpoint handler.

#### FR-6: Rejection logging

The middleware MUST log all verification failures with: timestamp, failure reason (missing token / invalid signature / structural error), and the request source IP. No rejected mandate reaches the endpoint handler.

**Consequences (testable):**
- A rejection event produces a structured log entry with `timestamp`, `reason`, and `ip`.
- No Stripe API call is made when verification fails.

---

### 4.3 Checkout Session Initiation

**Description:** `POST /api/checkout` is the Agent's first call in the commerce cycle. The Agent submits a structured Invoice payload describing the intended purchase. The server validates the payload, creates a Session record in PostgreSQL, and returns a session token and checkout context that the Agent will use when constructing its signed Payment Mandate. Realizes UJ-1 (steps 1–2).

**Functional Requirements:**

#### FR-7: Invoice payload acceptance

`POST /api/checkout` MUST accept a JSON body containing: `session_id` (client-supplied UUID), `items` (array of objects with `name`, `quantity`, `unit_price`), `currency` (ISO 4217 string, e.g. `"USD"`), and `agent_id` (string identifying the calling agent).

**Consequences (testable):**
- A well-formed payload returns HTTP 201 with a response body containing `session_token` and `checkout_context`.
- A payload missing `items` returns HTTP 422.
- A payload with `currency` not matching ISO 4217 pattern returns HTTP 422. `[ASSUMPTION: ISO 4217 validation is a simple regex/enum check, not a live currency registry lookup.]`

#### FR-8: Session persistence

Upon successful validation, the server MUST persist an Invoice record to PostgreSQL containing: `session_id`, `agent_id`, `items` (JSON), `total_amount` (computed server-side), `currency`, `status: "pending"`, and `created_at` timestamp.

**Consequences (testable):**
- After a successful `POST /api/checkout`, a record with the submitted `session_id` and `status: "pending"` exists in the `invoices` table.
- `total_amount` equals the sum of `quantity × unit_price` for all items.

#### FR-9: Checkout context response

The response MUST include: `session_token` (a server-generated token binding this session), `checkout_context` (a JSON object the Agent must incorporate when signing its Payment Mandate, containing `session_id`, `total_amount`, `currency`, and `server_timestamp`).

**Consequences (testable):**
- The response `checkout_context.total_amount` matches the server-computed total.
- The response `checkout_context.session_id` matches the submitted `session_id`.

---

### 4.4 Mandate Verification and Payment Settlement

**Description:** `POST /api/complete` is the Agent's final call. Having passed the AP2 Middleware (FR-3 through FR-6), the endpoint executes the mock payment via Stripe Sandbox, persists the settlement outcome, and returns a confirmation. This endpoint only executes if the Mandate is cryptographically valid. Realizes UJ-1 (steps 5–7).

**Functional Requirements:**

#### FR-10: Session linkage

Before calling Stripe, the endpoint MUST verify that the `session_id` in the verified Mandate corresponds to an existing Invoice with `status: "pending"` in PostgreSQL. Mismatched or already-settled sessions MUST be rejected.

**Consequences (testable):**
- A valid mandate referencing an unknown `session_id` returns HTTP 404.
- A valid mandate referencing a `session_id` with `status: "settled"` returns HTTP 409.

#### FR-11: Stripe Sandbox mock charge

The endpoint MUST call the Stripe Python SDK to create a `PaymentIntent` in Test Sandbox Mode using: `amount` from the verified Mandate (in minor currency units), `currency`, and `payment_method: "pm_card_visa"` (Stripe test token). `[ASSUMPTION: pm_card_visa is the Stripe sandbox test payment method. A real AP2 Payment Mandate would carry tokenized payment instrument references — in this prototype, a fixed test token is used.]`

**Consequences (testable):**
- A successful Stripe call returns a `PaymentIntent` with `status: "succeeded"`.
- If the Stripe SDK raises an exception, the endpoint returns HTTP 502 and does NOT update the invoice status.

#### FR-12: Settlement persistence

On Stripe success, the server MUST update the Invoice record in PostgreSQL: set `status: "settled"`, record `stripe_payment_intent_id`, and write `settled_at` timestamp. A separate `mandate_audit` record MUST be written containing: `session_id`, `agent_id`, `mandate_jwt_hash` (SHA-256 of the raw JWT string), and `settlement_timestamp`.

**Consequences (testable):**
- After successful `POST /api/complete`, the invoice record has `status: "settled"` and a non-null `stripe_payment_intent_id`.
- A `mandate_audit` row exists for the `session_id`.
- Calling `POST /api/complete` a second time with the same `session_id` returns HTTP 409 (already settled).

#### FR-13: Success response

The endpoint MUST return HTTP 200 with: `session_id`, `stripe_payment_intent_id`, `status: "settled"`, and `settled_at`.

**Consequences (testable):**
- Response body contains all four fields on success.

---

### 4.5 Persistence Layer

**Description:** A PostgreSQL instance managed by Docker Compose provides durable storage for Invoice records, Session state, and Mandate audit entries. The schema is version-controlled and applied at container startup. Realizes UJ-1, UJ-2.

**Functional Requirements:**

#### FR-14: PostgreSQL via Docker Compose

PostgreSQL MUST be defined as a named service in `docker-compose.yml` with a persistent named volume. The FastAPI application service MUST declare a dependency on the PostgreSQL service. `[ASSUMPTION: Database credentials are injected via environment variables (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB) defined in a .env file that is gitignored.]`

**Consequences (testable):**
- `docker compose up` brings up both services; the API service waits for PostgreSQL to be healthy before accepting requests.
- A `docker compose down -v` destroys state; `docker compose up` re-initializes a clean schema.

#### FR-15: Schema definition

The schema MUST define three tables:
- `invoices`: `session_id` (PK, UUID), `agent_id`, `items` (JSONB), `total_amount` (NUMERIC), `currency` (VARCHAR 3), `status` (VARCHAR), `stripe_payment_intent_id` (nullable), `created_at`, `settled_at` (nullable).
- `mandate_audit`: `id` (PK, serial), `session_id` (FK → invoices), `agent_id`, `mandate_jwt_hash` (VARCHAR), `settlement_timestamp`.

**Consequences (testable):**
- Schema applies without error on first startup.
- All columns are present and typed as specified.
- `mandate_audit.session_id` references `invoices.session_id` with a FK constraint.

---

### 4.6 Automated Test Suite

**Description:** A pytest suite covers all cryptographic validation rules, API endpoint contracts, and database interaction layers from the initial implementation. Tests are not retrofitted — they are written alongside each feature. Realizes UJ-2.

**Functional Requirements:**

#### FR-16: Cryptographic path coverage

The pytest suite MUST include test cases for: valid mandate → verification pass; tampered payload → 401; wrong private key → 401; missing `Authorization` header → 401; unsupported algorithm → 401; missing required Mandate fields → 422.

**Consequences (testable):**
- Running `pytest` exercises all six cryptographic path cases.
- All six cases have explicit `assert response.status_code == <expected>` assertions.

#### FR-17: API endpoint coverage

The pytest suite MUST include tests for every defined API endpoint covering: the happy path, each defined error condition (missing fields, wrong session state, Stripe failure simulation), and the discovery profile content assertions (FR-1, FR-2).

**Consequences (testable):**
- Each endpoint has at minimum one happy-path test and one error-path test per error condition defined in §4.
- Discovery profile test asserts `ucp.version`, `ucp.capabilities`, and `signing_keys` shape.

#### FR-18: Database interaction coverage

Tests MUST use a test-scoped PostgreSQL instance (or in-memory equivalent) and assert that: Invoice records are written correctly on checkout, Invoice status transitions correctly on settlement, and `mandate_audit` records are written on settlement. `[ASSUMPTION: pytest fixtures handle test DB setup/teardown. A separate test database or SQLite-compatible ORM layer is used for isolation — if SQLite is not viable with the schema, a Docker-based test DB is acceptable.]`

**Consequences (testable):**
- Tests do not mutate the development database.
- Each DB interaction test asserts the exact record written, not just a status code.

---

### 4.7 Developer Documentation

**Description:** A `README.md` at the project root is a first-class deliverable. It enables any developer to clone the repo, configure their environment, and observe a complete agentic transaction cycle end-to-end without additional assistance.

**Functional Requirements:**

#### FR-19: README completeness

The `README.md` MUST contain: system architecture overview (component diagram or narrative), Docker Compose service topology, all required environment variables with descriptions, local PostgreSQL setup notes, step-by-step execution playbook (setup → run → test transaction → verify in Stripe dashboard), and pytest execution instructions.

**Consequences (testable):**
- A developer following only the README can successfully run `docker compose up` and `pytest` without consulting external sources.
- All environment variable names in the README match those expected by the application code.

---

## 5. Non-Goals (Explicit)

- **No OAuth 2.0 Identity Linking.** User identity and platform authorization via OAuth is out of scope. The prototype assumes pre-authorized key-pair trust.
- **No production payment rails.** All payments are Stripe Sandbox only. No ACH, card network, or real payment processing.
- **No production key management.** No KMS, no HSM, no key rotation automation. Keys reside as PEM files in the `keys/` directory.
- **No live multi-party routing.** AP2's role-based architecture (Merchant ↔ Credential Provider ↔ Payment Network) is not fully implemented. The prototype implements the merchant/verifier role only.
- **No UCP `supported_versions` negotiation.** Single-version profile only.
- **No `UCP-Agent` header processing.** Platform profile fetching and capability intersection is out of scope.
- **No Cart Mandate generation.** The server does not sign a Cart Mandate for the Agent; the checkout context is a simplified substitute.
- **No A2A or MCP transport.** REST (HTTP/JSON) only.
- **No Human-Present (HP) flows.** The prototype implements HNP only.
- **No UI.** The product has no frontend. Interaction is via Postman or test scripts.

---

## 6. MVP Scope

### 6.1 In Scope

- `GET /.well-known/ucp` UCP Discovery Profile (FR-1, FR-2)
- AP2 EdDSA Mandate verification middleware (FR-3 through FR-6)
- `POST /api/checkout` — Invoice intake + Session creation (FR-7 through FR-9)
- `POST /api/complete` — Mandate settlement + Stripe Sandbox charge (FR-10 through FR-13)
- PostgreSQL schema via Docker Compose (FR-14, FR-15)
- pytest suite covering all cryptographic, API, and DB paths (FR-16 through FR-18)
- `README.md` execution playbook (FR-19)
- Dockerfile + `docker-compose.yml` for the full stack

### 6.2 Out of Scope for MVP

- OAuth 2.0 Identity Linking — deferred; requires a full authorization server implementation
- Production key rotation / KMS — deferred; out of prototype threat model
- Full AP2 Mandate schema compliance — deferred; prototype uses a minimal mandate payload
- Multi-party AP2 role routing — deferred; merchant/verifier role only in this prototype
- `NOTE FOR PM:` Full UCP capability negotiation (`UCP-Agent` header + `supported_versions`) is load-bearing for production UCP compliance and should be the first v2 addition if this prototype graduates.

---

## 7. Success Metrics

**Primary**

- **SM-1: End-to-end agentic cycle completes.** A mock Agent (Postman or test script) can execute the full UJ-1 cycle — `POST /api/checkout` → sign mandate → `POST /api/complete` — and receive a Stripe payment intent ID in the response. Target: demonstrated on first clean `docker compose up`. Validates FR-7 through FR-13.

- **SM-2: Protocol compliance verified by profile assertion.** `GET /.well-known/ucp` returns a parseable UCP profile that a hypothetical UCP platform client would accept (correct version, capabilities, and JWK key shape). Validates FR-1, FR-2.

**Secondary**

- **SM-3: Test suite passes clean.** `pytest` runs to zero failures on a clean environment with no manual setup beyond Docker and a `.env` file. Validates FR-16 through FR-18.

- **SM-4: Mandate rejection is observable.** A tampered or missing mandate causes a `POST /api/complete` to return HTTP 401 and produces a structured log entry with no Stripe charge attempted. Validates FR-4, FR-6.

**Counter-metrics (do not optimize)**

- **SM-C1: Do not optimize mandate verification speed at the expense of completeness.** FR-4 and FR-5 must fully execute — no short-circuit that skips structural validation to improve latency. This is a prototype; correctness over performance.
- **SM-C2: Do not allow the Stripe SDK to be configured outside Test Sandbox Mode.** A performance or convenience optimization that introduces a production API key would invalidate the prototype's safety boundary.

---

## 8. API Contracts

*Pydantic model shapes for all endpoint request and response bodies. These are the canonical contracts downstream implementation MUST match. Field names and types are binding; downstream architecture and stories derive from these.*

### `POST /api/checkout`

**Request — `CheckoutRequest`**
```python
class LineItem(BaseModel):
    name: str
    quantity: int          # >= 1
    unit_price: float      # > 0, in major currency units (e.g. 19.99)

class CheckoutRequest(BaseModel):
    session_id: UUID
    agent_id: str
    currency: str          # ISO 4217, e.g. "USD"
    items: list[LineItem]  # non-empty
```

**Response — `CheckoutResponse`** (HTTP 201)
```python
class CheckoutContext(BaseModel):
    session_id: UUID
    total_amount: float    # server-computed sum of quantity × unit_price
    currency: str
    server_timestamp: datetime

class CheckoutResponse(BaseModel):
    session_token: str     # server-generated opaque token (UUID or signed string)
    checkout_context: CheckoutContext
```

---

### `POST /api/complete`

**Request — `CompleteRequest`**
```python
class CompleteRequest(BaseModel):
    payment_mandate: str   # JWT string (EdDSA-signed); decoded payload is PaymentMandatePayload
```

**Payment Mandate JWT decoded payload — `PaymentMandatePayload`** *(the claims the server verifies after signature validation)*
```python
class PaymentMandatePayload(BaseModel):
    session_id: UUID
    amount: float          # must match invoice total_amount
    currency: str          # must match invoice currency
    agent_id: str
```

**Response — `CompleteResponse`** (HTTP 200)
```python
class CompleteResponse(BaseModel):
    session_id: UUID
    stripe_payment_intent_id: str
    status: Literal["settled"]
    settled_at: datetime
```

---

### `GET /.well-known/ucp`

**Response — `UCPDiscoveryProfile`** (HTTP 200, `Content-Type: application/json`)
```python
class JWK(BaseModel):
    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: str                 # base64url-encoded public key material

class UCPRoutes(BaseModel):
    checkout: str          # "/api/checkout"
    complete: str          # "/api/complete"

class UCPProfile(BaseModel):
    version: Literal["2026-04-08"]
    capabilities: list[str]   # ["dev.ucp.shopping.checkout", "dev.ucp.shopping.ap2_mandate"]
    routes: UCPRoutes
    signing_keys: list[JWK]

class UCPDiscoveryProfile(BaseModel):
    ucp: UCPProfile
```

---

## 9. Cross-Cutting NFRs

### Security

- NFR-1: The `private_key.pem` file MUST NOT be committed to version control. The `.gitignore` MUST exclude `keys/private_key.pem` (and `keys/public_key.pem` if deemed sensitive). `[ASSUMPTION: Both key files are gitignored; the REQUIREMENT.md instructions are used to regenerate them locally.]`
- NFR-2: The Stripe API key MUST be injected via environment variable (`STRIPE_API_KEY`), never hard-coded. The application MUST refuse to start if `STRIPE_API_KEY` is unset or does not begin with `sk_test_`.
- NFR-3: PyJWT MUST be configured to reject tokens that do not specify the `EdDSA` algorithm. Algorithm confusion attacks (e.g., `alg: none`, `HS256`) MUST be rejected at the library level.

### Containerization

- NFR-4: All runtime dependencies (FastAPI, PostgreSQL, application code) MUST run inside Docker containers. No host-level Python or database installations are required to run the prototype beyond Docker Desktop.
- NFR-5: The application image MUST be built from a pinned base image (e.g., `python:3.12-slim`) and use a `requirements.txt` with pinned dependency versions.

### Observability

- NFR-6: The application MUST emit structured (JSON) logs at INFO level for normal operations and ERROR level for verification failures and unhandled exceptions. Log format: `timestamp`, `level`, `event`, `session_id` (where applicable), `detail`.

---

## 10. Open Questions

- **OQ-1:** ~~What is the canonical transport for the Payment Mandate?~~ **RESOLVED (2026-06-20):** Payment Mandate is transported as the `payment_mandate` field in the JSON request body of `POST /api/complete`, mirroring AP2/A2A/MCP JSON-RPC body structure. FR-3 updated accordingly.
- **OQ-2:** Should the checkout context returned by `POST /api/checkout` itself be signed by the server (i.e., returned as a JWT)? This would make the Cart Mandate / checkout context flow closer to AP2 spec. Currently the PRD specifies unsigned JSON for prototype simplicity. *(Carry into architecture phase.)*
- **OQ-3:** ~~Is `2026-06-11` a draft or internal UCP spec version?~~ **RESOLVED (2026-06-20):** `2026-06-11` was a mistaken draft reference. Official stable version `2026-04-08` is locked throughout this PRD.

---

## 11. Assumptions Index

*Every `[ASSUMPTION]` from the document, surfaced for explicit confirmation. Resolved items are marked.*

- **A-1** (§4.1, FR-2 notes): JWK representation of `public_key.pem` is derived at server startup and embedded in the discovery profile. Key rotation requires a server restart.
- **A-2** (§4.2, FR-3): ~~Payment Mandate is transported via `Authorization: Bearer <jwt>` header.~~ **RESOLVED (2026-06-20):** Mandate transported as `payment_mandate` JSON body field. See §8 API Contracts, `CompleteRequest`.
- **A-3** (§4.2, FR-5): ~~Minimum Mandate payload fields TBD.~~ **RESOLVED (2026-06-20):** Mandate payload is `session_id`, `amount`, `currency`, `agent_id`. Pydantic schema `PaymentMandatePayload` defined in §8. Full AP2 Mandate schema not implemented in v1.
- **A-4** (§4.3, FR-7): ISO 4217 currency validation uses a simple regex or enum check, not a live registry.
- **A-5** (§4.4, FR-11): Stripe test payment method is `pm_card_visa`. Real AP2 would carry tokenized payment instrument references.
- **A-6** (§4.5, FR-14): Database credentials injected via `.env` file, gitignored.
- **A-7** (§4.6, FR-18): pytest DB tests use a test-scoped PostgreSQL instance or compatible substitute; development database is never mutated by tests.
- **A-8** (§9, NFR-1): Both `keys/private_key.pem` and `keys/public_key.pem` are gitignored; generated locally per REQUIREMENT.md.
