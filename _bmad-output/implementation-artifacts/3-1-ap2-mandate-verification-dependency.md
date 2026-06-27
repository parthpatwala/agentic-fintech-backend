---
baseline_commit: f796d0a
---

# Story 3.1: AP2 Mandate Verification Dependency

Status: done

## Story

As a developer,
I want a reusable FastAPI Dependency that extracts and cryptographically verifies the Payment Mandate from `POST /api/complete` requests before any handler logic executes,
So that the settlement endpoint is protected against invalid, tampered, and algorithm-confused mandates at the framework level.

## Acceptance Criteria

**Given** a valid EdDSA-signed JWT with payload fields `session_id`, `amount`, `currency`, `agent_id` is present in the `payment_mandate` body field
**When** the dependency executes
**Then** it returns a `(raw_jwt: str, payload: PaymentMandatePayload)` tuple with no HTTP errors raised

**Given** the request body has no `payment_mandate` field
**When** the dependency executes
**Then** HTTP 422 is raised before any handler logic runs

**Given** a JWT in `payment_mandate` was signed with a different private key than the one whose public counterpart is loaded in `app.state.public_key`
**When** the dependency executes
**Then** HTTP 401 is raised with `detail.reason == "invalid_signature"`

**Given** a JWT where the payload was modified after signing (tampered)
**When** the dependency executes
**Then** HTTP 401 is raised with `detail.reason == "invalid_signature"`

**Given** a JWT specifying `alg: "HS256"` or `alg: "none"` in the header
**When** the dependency executes
**Then** HTTP 401 is raised (PyJWT rejects non-EdDSA algorithms)

**Given** a structurally valid EdDSA JWT whose payload is missing the `amount` field
**When** the dependency executes
**Then** HTTP 422 is raised

**And** for every rejection case, a structured JSON log entry is emitted with `level: "ERROR"`, `event: "mandate_rejected"`, `reason` describing the failure, and `ip` containing the client IP address
**And** PyJWT is called with `algorithms=["EdDSA"]` — never with `algorithms=None` or a list including `"none"` or `"HS256"`
**And** the dependency lives exclusively in `app/dependencies.py`; PyJWT is imported only in `app/services/crypto.py`

## Tasks / Subtasks

- [x] Task 1: Implement `verify_mandate` in `app/services/crypto.py` (AC: all crypto ACs)
  - [x] Replace the `NotImplementedError` stub with `jwt.decode(token, public_key, algorithms=["EdDSA"])`
  - [x] Add `import jwt` at the top of the file (PyJWT)
  - [x] Change return type from `None` to `dict[str, object]` and fix signature
  - [x] Keep function synchronous (no I/O, CPU-only)

- [x] Task 2: Add `CompleteRequest` and `PaymentMandatePayload` to `app/models/schemas.py` (AC: missing-field 422, payload validation)
  - [x] Add `from uuid import UUID` import
  - [x] Add `CompleteRequest(BaseModel)` with `payment_mandate: str`
  - [x] Add `PaymentMandatePayload(BaseModel)` with `session_id: UUID`, `amount: float`, `currency: str`, `agent_id: str`

- [x] Task 3: Create `app/dependencies.py` — AP2 mandate verification FastAPI Dependency (AC: all)
  - [x] Implement `ap2_mandate(request: Request, body: CompleteRequest) -> tuple[str, PaymentMandatePayload]` as a sync function
  - [x] Follow the MANDATORY call order: extract → format check → EdDSA verify → payload validate → return
  - [x] Catch `jwt.exceptions.PyJWTError` → log + raise `HTTPException(status_code=401, detail={"reason": "invalid_signature"})`
  - [x] Catch `ValidationError` (from Pydantic) → log + raise `HTTPException(status_code=422, detail={"reason": "missing_mandate_fields"})`
  - [x] Extract client IP as `request.client.host if request.client else "unknown"`
  - [x] Log every rejection: `logger.error("mandate_rejected", extra={"event": "mandate_rejected", "reason": ..., "ip": ...})`
  - [x] Do NOT import `jwt` directly — call `crypto.verify_mandate()`; `jwt` is only in `crypto.py`

- [x] Task 4: Create stub `app/routers/complete.py` (AC: allows dependency to be tested via HTTP)
  - [x] Define `router = APIRouter()` with `POST /api/complete` that `Depends(ap2_mandate)` and returns `{"status": "stub"}`
  - [x] This stub is replaced in Story 4.2 — do NOT add DB or Stripe logic here
  - [x] Import `Annotated` from `typing` and use `Depends` pattern properly

- [x] Task 5: Register `complete` router in `app/main.py` (AC: endpoint is reachable)
  - [x] Add `from app.routers import complete` import
  - [x] Add `app.include_router(complete.router)` after `app.include_router(discovery.router)`

- [x] Task 6: Create `tests/conftest.py` with shared `ed25519_key_pair` fixture (AC: test isolation)
  - [x] Move the `ed25519_key_pair` fixture from `tests/test_state_init.py` to `tests/conftest.py`
  - [x] Remove the fixture from `tests/test_state_init.py` (conftest makes it automatically available)
  - [x] Verify `tests/test_state_init.py` tests still pass after the move

- [x] Task 7: Write `tests/test_crypto.py` — 10 tests covering all 6 story ACs (AC: all)
  - [x] `setup_public_key_state` autouse fixture: sets `app.state.public_key` from `ed25519_key_pair`; deletes after test
  - [x] `test_verify_mandate_valid_returns_payload` — `crypto.verify_mandate()` direct unit test
  - [x] `test_verify_mandate_wrong_key_raises_decode_error` — direct unit test
  - [x] `test_verify_mandate_tampered_raises_decode_error` — direct unit test
  - [x] `test_mandate_dep_valid_returns_200` — valid JWT → 200 via stub endpoint
  - [x] `test_mandate_dep_missing_payment_mandate_returns_422` — missing field → 422
  - [x] `test_mandate_dep_wrong_key_returns_401` — wrong private key → 401
  - [x] `test_mandate_dep_tampered_payload_returns_401` — tampered payload → 401
  - [x] `test_mandate_dep_alg_hs256_returns_401` — HS256 token → 401
  - [x] `test_mandate_dep_alg_none_returns_401` — crafted "none" alg token → 401
  - [x] `test_mandate_dep_missing_amount_returns_422` — missing `amount` field → 422

## Dev Notes

### What this story does and does NOT do

**Story 3.1 scope (do now):**
- Implement `verify_mandate` in `app/services/crypto.py` (was a `NotImplementedError` stub)
- Create `app/dependencies.py` with the AP2 mandate verification FastAPI Dependency
- Add `CompleteRequest` and `PaymentMandatePayload` Pydantic models to `app/models/schemas.py`
- Create a **stub** `app/routers/complete.py` with just enough handler to make the dependency testable
- Write `tests/conftest.py` (shared fixtures) and `tests/test_crypto.py` (10 tests)

**Story 3.1 does NOT do:**
- Any DB reads/writes — that is Story 4.2
- Any Stripe calls — that is Story 4.2
- The full `POST /api/complete` settlement logic — that is Story 4.2
- The `POST /api/checkout` endpoint — that is Story 3.2
- `app/services/invoice.py` — not touched this story
- `app/services/settlement.py` — not touched this story

### MANDATORY: AP2 Dependency call order (from architecture.md §Process Patterns)

This order is BINDING. Do not reorder. Do not merge steps.

1. Extract `payment_mandate` from body (`body.payment_mandate`)
2. Validate JWT format — `raw_jwt.count(".") != 2` → log + raise HTTP 401
3. Verify EdDSA signature via `crypto.verify_mandate(raw_jwt, public_key)` — on `jwt.DecodeError` → log + raise HTTP 401
4. Validate `PaymentMandatePayload` fields via `PaymentMandatePayload.model_validate(payload_dict)` — on `ValidationError` → log + raise HTTP 422
5. Return `(raw_jwt, payload)` tuple

### Exact implementation for `app/services/crypto.py`

Replace the stub `verify_mandate` with:

```python
import jwt  # PyJWT

def verify_mandate(token: str, public_key: Ed25519PublicKey) -> dict[str, object]:
    """Verify an AP2 Payment Mandate JWT using EdDSA.

    Returns the decoded payload dict if signature is valid.
    Raises jwt.exceptions.DecodeError for format errors, invalid signatures,
    or non-EdDSA algorithms (InvalidSignatureError and InvalidAlgorithmError
    are both subclasses of DecodeError).
    """
    return jwt.decode(token, public_key, algorithms=["EdDSA"])
```

**Key facts:**
- PyJWT 2.13.0 is installed; it accepts `Ed25519PublicKey` objects directly (no PEM serialization needed)
- `algorithms=["EdDSA"]` is the ONLY allowed value — never pass `None`, `["HS256"]`, or `["none"]`
- `jwt.decode` with `algorithms=["EdDSA"]` on a token with `alg: "HS256"` raises `jwt.exceptions.InvalidAlgorithmError` (subclass of `DecodeError`)
- `jwt.decode` with `algorithms=["EdDSA"]` on a token with `alg: "none"` raises `jwt.exceptions.DecodeError`
- `jwt.decode` on a tampered or wrong-key JWT raises `jwt.exceptions.InvalidSignatureError` (subclass of `DecodeError`)
- Catch `jwt.DecodeError` in the DEPENDENCY (not here) — this function raises, does not handle

### Exact implementation for `app/dependencies.py` (CREATE)

```python
import logging

import jwt
from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError

from app.models.schemas import CompleteRequest, PaymentMandatePayload
from app.services import crypto

logger = logging.getLogger(__name__)


def ap2_mandate(
    request: Request,
    body: CompleteRequest,
) -> tuple[str, PaymentMandatePayload]:
    """AP2 mandate verification FastAPI Dependency.

    Call order is MANDATORY (architecture.md §Process Patterns):
    1. extract → 2. format check → 3. EdDSA verify → 4. payload validate → 5. return tuple
    """
    raw_jwt = body.payment_mandate
    client_ip = request.client.host if request.client else "unknown"

    # Step 2: JWT format — must be exactly 3 dot-separated segments
    if raw_jwt.count(".") != 2:
        logger.error(
            "mandate_rejected",
            extra={"event": "mandate_rejected", "reason": "invalid_jwt_format", "ip": client_ip},
        )
        raise HTTPException(status_code=401, detail={"reason": "invalid_jwt_format"})

    # Step 3: EdDSA signature verification
    public_key = request.app.state.public_key
    try:
        payload_dict = crypto.verify_mandate(raw_jwt, public_key)
    except jwt.DecodeError as exc:
        logger.error(
            "mandate_rejected",
            extra={"event": "mandate_rejected", "reason": "invalid_signature", "ip": client_ip},
        )
        raise HTTPException(status_code=401, detail={"reason": "invalid_signature"}) from exc

    # Step 4: Payload structural validation
    try:
        payload = PaymentMandatePayload.model_validate(payload_dict)
    except ValidationError as exc:
        logger.error(
            "mandate_rejected",
            extra={"event": "mandate_rejected", "reason": "missing_mandate_fields", "ip": client_ip},
        )
        raise HTTPException(status_code=422, detail={"reason": "missing_mandate_fields"}) from exc

    return raw_jwt, payload
```

**Why `jwt.DecodeError` (not subclasses)?** `InvalidSignatureError` and `InvalidAlgorithmError` are both subclasses of `DecodeError` — catching the base class handles all signature, algorithm, and format failures in one place.

**Why `import jwt` here?** The dependency needs to catch `jwt.DecodeError`. This is the ONLY place besides `crypto.py` that imports `jwt`. This is unavoidable — catching exceptions from a library requires importing it. The key constraint is that `jwt.decode()` is only ever CALLED from `crypto.py`.

### `app/models/schemas.py` additions

Add at the end of the file (after `UCPDiscoveryProfile`):

```python
from uuid import UUID  # add to existing imports at top

class CompleteRequest(BaseModel):
    payment_mandate: str  # JWT string (EdDSA-signed)

class PaymentMandatePayload(BaseModel):
    session_id: UUID
    amount: float
    currency: str
    agent_id: str
```

`UUID` in `PaymentMandatePayload.session_id` coerces a UUID string from the decoded JWT payload automatically via Pydantic.

### Stub `app/routers/complete.py` (CREATE)

```python
from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import ap2_mandate
from app.models.schemas import PaymentMandatePayload

router = APIRouter()


@router.post("/api/complete")
def complete(
    mandate: Annotated[tuple[str, PaymentMandatePayload], Depends(ap2_mandate)],
) -> dict[str, str]:
    """Stub handler — AP2 dependency guard only. Full settlement implemented in Story 4.2."""
    return {"status": "stub"}
```

**Critical:** Do NOT import `invoice.py`, `settlement.py`, or `db/session.py` in this file. This handler does nothing except exercise the dependency chain.

### `app/main.py` update

Add after the `discovery` import and `app.include_router(discovery.router)`:

```python
from app.routers import complete      # ADD

# ... existing code ...

app.include_router(complete.router)   # ADD after discovery.router
```

### Test isolation for `tests/test_crypto.py`

The dependency reads `request.app.state.public_key`. Since `ASGITransport` does not run the lifespan, inject the real key directly:

```python
@pytest.fixture(autouse=True)
def setup_public_key_state(ed25519_key_pair):
    """Inject real Ed25519 public key into app.state for dependency tests."""
    _, public_key, _ = ed25519_key_pair
    app.state.public_key = public_key
    yield
    del app.state.public_key
```

Note: `ed25519_key_pair` comes from `tests/conftest.py` (Task 6). The fixture is autouse so all tests in the file get the key set.

### Signing test tokens

```python
import jwt
from uuid import uuid4

_MANDATE_PAYLOAD = {
    "session_id": str(uuid4()),  # JWT doesn't serialize UUID natively — use str()
    "amount": 79.99,
    "currency": "USD",
    "agent_id": "test-agent",
}

# Valid token (sign with test private key)
valid_token = jwt.encode(_MANDATE_PAYLOAD, private_key, algorithm="EdDSA")

# Wrong-key token (sign with a DIFFERENT generated key)
other_private = Ed25519PrivateKey.generate()
wrong_key_token = jwt.encode(_MANDATE_PAYLOAD, other_private, algorithm="EdDSA")

# HS256 token (algorithm confusion)
hs256_token = jwt.encode(_MANDATE_PAYLOAD, "secret", algorithm="HS256")

# "none" alg token (craft manually — PyJWT 2.x won't encode with "none")
import base64, json as _json
_h = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
_p = base64.urlsafe_b64encode(_json.dumps(_MANDATE_PAYLOAD).encode()).rstrip(b"=").decode()
none_alg_token = f"{_h}.{_p}."

# Tampered token: sign valid token, then mutate one payload field
import base64 as _b64
parts = valid_token.split(".")
bad_payload = _json.loads(_b64.urlsafe_b64decode(parts[1] + "=="))
bad_payload["amount"] = 0.01  # tamper
parts[1] = _b64.urlsafe_b64encode(_json.dumps(bad_payload).encode()).rstrip(b"=").decode()
tampered_token = ".".join(parts)

# Missing-field token: valid signature, payload lacks 'amount'
no_amount_payload = {k: v for k, v in _MANDATE_PAYLOAD.items() if k != "amount"}
no_amount_token = jwt.encode(no_amount_payload, private_key, algorithm="EdDSA")
```

### conftest.py fixture to create (move from test_state_init.py)

```python
# tests/conftest.py
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


@pytest.fixture
def ed25519_key_pair():
    """Generate a real in-memory Ed25519 key pair — no disk I/O."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_pem = public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return private_key, public_key, pub_pem
```

After creating `conftest.py`, remove the `ed25519_key_pair` fixture from `tests/test_state_init.py` — pytest discovers `conftest.py` automatically and makes its fixtures available to all test files in the same directory.

### Architecture compliance

| Rule | Source |
|---|---|
| `jwt.decode()` called ONLY in `app/services/crypto.py` | architecture.md §Component Boundaries |
| `jwt.DecodeError` import in `app/dependencies.py` is acceptable for exception catching | N/A — boundary only applies to `decode()` calls |
| No DB or Stripe in `app/dependencies.py` | architecture.md §Component Boundaries |
| `algorithms=["EdDSA"]` is the only permitted value | architecture.md §Process Patterns + NFR-3 |
| Dependency lives in `app/dependencies.py` (not in any router) | architecture.md §Project Structure |
| Log format: `event`, `reason`, `ip` fields | architecture.md §Format Patterns |

### Key files in this story

| File | Action | Notes |
|---|---|---|
| `app/services/crypto.py` | UPDATE | Replace `verify_mandate` stub with real PyJWT decode |
| `app/models/schemas.py` | UPDATE | Add `CompleteRequest` + `PaymentMandatePayload` |
| `app/dependencies.py` | CREATE | AP2 FastAPI Dependency (sync function) |
| `app/routers/complete.py` | CREATE | Stub handler for `POST /api/complete` (Story 4.2 fills it in) |
| `app/main.py` | UPDATE | Register `complete` router |
| `tests/conftest.py` | CREATE | Shared `ed25519_key_pair` fixture |
| `tests/test_state_init.py` | UPDATE | Remove `ed25519_key_pair` fixture (now in conftest) |
| `tests/test_crypto.py` | CREATE | 10 tests: 3 unit + 7 HTTP covering all 6 ACs |

### Previous story learnings (from Stories 2.1 and 2.2)

- **ASGITransport does not invoke FastAPI lifespan** — any `app.state.*` values must be manually injected in test fixtures. Use `del app.state.<attr>` in teardown (not `app.state._state.clear()`).
- **Ruff E501** — lines > 88 chars trigger E501. Keep log messages and long strings short or add `# noqa: E501`.
- **`mock_open` for file reads in lifespan** — `tests/test_startup.py` pattern; not relevant here since Story 3.1 tests bypass lifespan.
- **Deferred-work items from prior stories** — unguarded `app.state` access and `OSError` variants are tracked in `deferred-work.md`; do not add handling for them in this story.
- **`SUPPORTED_CAPABILITIES` as `tuple`** — already established; new constants should also be `tuple` or `frozenset` if immutable.

### References

- [Source: epics.md#Story 3.1] — acceptance criteria (FR-3, FR-4, FR-5, FR-6, NFR-3)
- [Source: architecture.md#Component Boundaries] — `app/dependencies.py` boundary; PyJWT never imported outside `crypto.py`
- [Source: architecture.md#Process Patterns] — MANDATORY AP2 Dependency call order (5 steps)
- [Source: architecture.md#Authentication & Security] — `algorithms=["EdDSA"]` required; never `None`
- [Source: architecture.md#Format Patterns] — log event: `mandate_rejected`, fields: `reason`, `ip`
- [Source: prd.md§8 API Contracts] — `CompleteRequest`, `PaymentMandatePayload` canonical schemas
- [Source: Story 2.2 dev notes] — ASGITransport limitation; `del app.state.<attr>` teardown pattern

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-5

### Debug Log References

**PyJWT exception hierarchy mismatch** — story dev notes said to catch `jwt.DecodeError` for algorithm confusion. In PyJWT 2.13.0, `InvalidAlgorithmError` is NOT a subclass of `DecodeError`; both are children of `InvalidTokenError`. Tests `test_mandate_dep_alg_hs256_returns_401` and `test_mandate_dep_alg_none_returns_401` initially raised unhandled `InvalidAlgorithmError` through the dependency. Fixed by widening the catch to `jwt.exceptions.PyJWTError` (the root of all JWT errors), which correctly covers `DecodeError`, `InvalidSignatureError`, and `InvalidAlgorithmError`.

### Completion Notes List

- Implemented `verify_mandate` in `app/services/crypto.py`: replaces `NotImplementedError` stub; calls `jwt.decode(token, public_key, algorithms=["EdDSA"])`; returns decoded payload dict; raises PyJWT exceptions on failure
- Added `CompleteRequest` and `PaymentMandatePayload` Pydantic models to `app/models/schemas.py`
- Created `app/dependencies.py`: sync `ap2_mandate` dependency; follows mandatory 5-step call order; catches `jwt.exceptions.PyJWTError` (not `jwt.DecodeError` — see debug log) for all JWT failures; logs all rejections with `event`, `reason`, `ip` fields
- Created stub `app/routers/complete.py`: `POST /api/complete` with `Depends(ap2_mandate)` returning `{"status": "stub"}`; Story 4.2 will add settlement logic
- Updated `app/main.py`: registered `complete` router after `discovery` router
- Created `tests/conftest.py`: shared `ed25519_key_pair` fixture; removed duplicate from `test_state_init.py`
- Created `tests/test_crypto.py`: 10 tests (3 unit + 7 HTTP); `setup_public_key_state` autouse fixture; all 6 ACs covered
- 56/56 tests pass; ruff clean

### File List

- `app/services/crypto.py` (updated — verify_mandate implemented)
- `app/models/schemas.py` (updated — CompleteRequest + PaymentMandatePayload added)
- `app/dependencies.py` (created — AP2 mandate verification dependency)
- `app/routers/complete.py` (created — stub POST /api/complete handler)
- `app/main.py` (updated — complete router registered)
- `tests/conftest.py` (created — shared ed25519_key_pair fixture)
- `tests/test_state_init.py` (updated — ed25519_key_pair fixture removed; now from conftest)
- `tests/test_crypto.py` (created — 10 tests covering all story ACs)

### Change Log

- Story 3.1 implemented: AP2 mandate verification FastAPI Dependency (2026-06-22)

### Review Findings

#### Decision Needed

- [x] [Review][Defer] Add `aud`/`iss` claim validation to `jwt.decode` — deferred: single-purpose Ed25519 key pair, no cross-service reuse in this prototype `[app/services/crypto.py]`

#### Patches

- [x] [Review][Patch] Enforce `exp` claim — add `options={"require": ["exp"]}` to `jwt.decode`; add test for expired-token rejection `[app/services/crypto.py]`
- [x] [Review][Patch] Add `gt=0` validator to `PaymentMandatePayload.amount` — currently accepts zero and negative values, which would reach settlement logic in Story 4.2 `[app/models/schemas.py]`
- [x] [Review][Patch] Guard `app.state.public_key` access — bare attribute read raises `AttributeError` (unstructured 500) if lifespan partially fails; catch and return HTTP 503 `[app/dependencies.py]`
- [x] [Review][Patch] Add `min_length=1` to `PaymentMandatePayload.currency` — empty string passes Pydantic validation today `[app/models/schemas.py]`
- [x] [Review][Patch] Add `max_length=8192` to `CompleteRequest.payment_mandate` — unbounded string allows DoS via oversized body passed through to `jwt.decode` before rejection `[app/models/schemas.py]`
- [x] [Review][Patch] Remove `import jwt` from `app/dependencies.py` — violates AC9 / architecture constraint; introduced `MandateVerificationError` wrapper in `crypto.py`; dependencies.py now PyJWT-free `[app/dependencies.py, app/services/crypto.py]`
- [x] [Review][Patch] Add AC7 caplog log-assertion tests — 2 tests assert `event`, `reason`, `ip` on rejection records; noted JSON formatter intentionally absent from test setup (caplog captures LogRecord objects directly) `[tests/test_crypto.py]`

#### Deferred

- [x] [Review][Defer] JTI replay protection — valid JWT can be resubmitted until expiry; deduplication store (Redis/DB) out of scope for this story `[app/dependencies.py]` — deferred, pre-existing
- [x] [Review][Defer] `amount: float` → `Decimal` for monetary precision — schema-level migration with downstream impact; same pattern as `price: float` in Story 2.1; pre-existing prototype constraint `[app/models/schemas.py]` — deferred, pre-existing
- [x] [Review][Defer] Rate limiting on `POST /api/complete` — infrastructure/middleware concern, not introduced by this story `[app/routers/complete.py]` — deferred, pre-existing
- [x] [Review][Defer] Non-`PyJWTError` from cryptography layer propagates as 500 — EdDSA path in PyJWT wraps most crypto exceptions; not reproducible with current library versions `[app/dependencies.py]` — deferred, pre-existing
- [x] [Review][Defer] `nbf` claim absence — no lower temporal bound on token validity; not required by spec `[app/services/crypto.py]` — deferred, pre-existing
- [x] [Review][Defer] `client_ip` logs proxy address, not real client — `request.client.host` reflects proxy behind reverse-proxy/LB; needs `X-Forwarded-For` handling; infrastructure concern `[app/dependencies.py]` — deferred, pre-existing
- [x] [Review][Defer] Parallel-test race condition from `app.state` mutation — only manifests under `pytest-xdist`; not used in this project `[tests/test_crypto.py]` — deferred, pre-existing
