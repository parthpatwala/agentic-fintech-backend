---
baseline_commit: f796d0a
---

# Story 3.2: Checkout Session Endpoint

Status: done

## Story

As a mock AI Agent,
I want to submit a structured invoice to `POST /api/checkout` and receive a session token and checkout context,
So that I have all the information needed to construct and sign my Payment Mandate for the settlement step.

## Acceptance Criteria

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

## Tasks / Subtasks

- [x] T1: Add `LineItem`, `CheckoutRequest`, `CheckoutContext`, `CheckoutResponse` to `app/models/schemas.py`
- [x] T2: Create `app/services/invoice.py` with `create_invoice()` and `get_invoice()` functions
- [x] T3: Create `app/routers/checkout.py` with `POST /api/checkout` handler
- [x] T4: Register `checkout` router in `app/main.py`
- [x] T5: Create `tests/test_checkout.py` covering all ACs
- [x] T6: Verify all existing tests still pass (`uv run pytest tests/ -x -q`)
- [x] T7: Ruff clean (`uv run ruff check app/ tests/`)

### Review Findings (2026-06-27)

**Decision-needed:**
- [x] [Review][Decision→Defer] ISO 4217 allowlist covers only 20 of ~170 valid currencies — valid codes like "AED", "THB", "CZK" return 422. Narrow allowlist intentional for prototype (USD/EUR/GBP sufficient for demo). [app/models/schemas.py:3-10] — deferred

**Patches:**
- [x] [Review][Patch] IntegrityError catch too broad — catches FK, CHECK, and column constraint violations as 409, not just PK conflicts [app/routers/checkout.py:38-44]
- [x] [Review][Patch] NUMERIC overflow unhandled — total > 99,999,999.99 causes PostgreSQL DataError (not IntegrityError), returns HTTP 500 [app/routers/checkout.py:23-26]

**Deferred:**
- [x] [Review][Defer] Sub-cent total DB precision mismatch — multi-dp prices can produce totals DB rounds to 2dp while response returns unrounded float [app/routers/checkout.py:58] — deferred, prototype edge case
- [x] [Review][Defer] Whitespace-only agent_id accepted — min_length=1 passes a single space [app/models/schemas.py:52] — deferred, semantic validation
- [x] [Review][Defer] Empty item name accepted — `name: str` has no min_length constraint [app/models/schemas.py:45] — deferred, semantic validation
- [x] [Review][Defer] get_invoice defined but never called or tested — dead code until Story 4.2 [app/services/invoice.py:36-43] — deferred, intentional stub
- [x] [Review][Defer] PaymentMandatePayload.currency lacks ISO 4217 validation — inconsistency with CheckoutRequest [app/models/schemas.py:80] — deferred, Story 3.1 scope
- [x] [Review][Defer] No authentication on POST /api/checkout — infrastructure concern not introduced by this story [app/routers/checkout.py] — deferred, pre-existing

---

## Developer Context

### Canonical API Contracts (from PRD §8 — BINDING)

```python
# REQUEST MODELS (add to app/models/schemas.py)

class LineItem(BaseModel):
    name: str
    quantity: int = Field(..., ge=1)          # >= 1
    unit_price: float = Field(..., gt=0)      # > 0, major currency units (e.g. 19.99)

class CheckoutRequest(BaseModel):
    session_id: UUID
    agent_id: str = Field(..., min_length=1)
    currency: str                              # ISO 4217 — must be validated (see below)
    items: list[LineItem] = Field(..., min_length=1)  # non-empty

# RESPONSE MODELS (add to app/models/schemas.py)

class CheckoutContext(BaseModel):
    session_id: UUID
    total_amount: float    # server-computed sum of quantity × unit_price
    currency: str
    server_timestamp: datetime

class CheckoutResponse(BaseModel):
    session_token: str     # server-generated opaque token (UUIDv4 string)
    checkout_context: CheckoutContext
```

### Currency Validation — CRITICAL

The AC requires `"XYZ"` to return HTTP 422. A plain `pattern=r"^[A-Z]{3}$"` accepts "XYZ" — **DO NOT use regex alone**.

Use a Pydantic field validator against a hardcoded ISO 4217 allowlist:

```python
from pydantic import field_validator

_VALID_ISO_4217 = frozenset({
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY",
    "INR", "SGD", "MXN", "BRL", "KRW", "ZAR", "HKD", "SEK",
    "NOK", "DKK", "NZD", "PLN",
})

class CheckoutRequest(BaseModel):
    session_id: UUID
    agent_id: str = Field(..., min_length=1)
    currency: str
    items: list[LineItem] = Field(..., min_length=1)

    @field_validator("currency")
    @classmethod
    def currency_must_be_iso4217(cls, v: str) -> str:
        if v not in _VALID_ISO_4217:
            raise ValueError(f"currency '{v}' is not a supported ISO 4217 code")
        return v
```

Define `_VALID_ISO_4217` at module level in `schemas.py` (not inside the class). Pydantic v2 `field_validator` raises `ValueError` which FastAPI maps to HTTP 422.

### Total Amount Computation — Use Decimal, Return Float

Architecture: `total_amount` is stored as `NUMERIC(10,2)` in PostgreSQL. Compute with `Decimal` to avoid floating-point drift, then convert to `float` for the response:

```python
from decimal import Decimal

total = sum(
    Decimal(str(item.unit_price)) * item.quantity
    for item in body.items
)
# Store Decimal in DB (SQLAlchemy Numeric accepts it)
# Return float(total) in CheckoutResponse
```

**DO NOT** compute `sum(item.unit_price * item.quantity ...)` directly — floating-point arithmetic on `float` can produce values like `79.989999...`.

### Session Token

`session_token` is a server-generated opaque identifier. For this prototype, use `str(uuid.uuid4())`. No signing, no state in the token. Story 4.2 uses `session_id` (from the mandate payload) to look up the invoice — the token is not verified server-side.

### `app/services/invoice.py` — EXACT BOUNDARY (Architecture Binding)

All SQLAlchemy operations MUST live here. Routers MUST NOT call SQLAlchemy directly. The service receives data dicts and returns ORM objects.

```python
# app/services/invoice.py

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Invoice


async def create_invoice(
    session: AsyncSession,
    session_id: uuid.UUID,
    agent_id: str,
    items: list[dict],
    total_amount: Decimal,
    currency: str,
) -> Invoice:
    """Insert a new invoice with status='pending'. Caller owns the transaction.

    Raises sqlalchemy.exc.IntegrityError if session_id already exists (PK violation).
    """
    invoice = Invoice(
        session_id=session_id,
        agent_id=agent_id,
        items=items,                   # list of dicts — stored as JSONB
        total_amount=total_amount,     # Decimal accepted by Numeric(10,2)
        currency=currency,
        status="pending",
    )
    session.add(invoice)
    await session.flush()              # sends INSERT, raises IntegrityError on PK conflict
    return invoice


async def get_invoice(
    session: AsyncSession,
    session_id: uuid.UUID,
) -> Invoice | None:
    """Fetch an invoice by session_id. Returns None if not found."""
    result = await session.execute(
        select(Invoice).where(Invoice.session_id == session_id)
    )
    return result.scalar_one_or_none()
```

**Key:** `await session.flush()` sends the INSERT without committing. The caller's `session.begin()` context manager commits on success or rolls back on exception. This matches the architecture mandate: "Explicit `async with session.begin()` blocks on write paths".

### `app/routers/checkout.py` — EXACT IMPLEMENTATION

```python
# app/routers/checkout.py

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.schemas import CheckoutContext, CheckoutRequest, CheckoutResponse
from app.services import invoice as invoice_service

router = APIRouter()


@router.post("/api/checkout", status_code=201)
async def checkout(
    body: CheckoutRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CheckoutResponse:
    total = sum(
        Decimal(str(item.unit_price)) * item.quantity for item in body.items
    )
    session_token = str(uuid.uuid4())
    items_data = [item.model_dump() for item in body.items]

    try:
        async with session.begin():
            await invoice_service.create_invoice(
                session=session,
                session_id=body.session_id,
                agent_id=body.agent_id,
                items=items_data,
                total_amount=total,
                currency=body.currency,
            )
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail={"reason": "session_id_already_exists"},
        )

    return CheckoutResponse(
        session_token=session_token,
        checkout_context=CheckoutContext(
            session_id=body.session_id,
            total_amount=float(total),
            currency=body.currency,
            server_timestamp=datetime.now(UTC),
        ),
    )
```

**Critical notes:**
- `status_code=201` on the decorator — `POST /api/checkout` MUST return 201, not 200
- `async with session.begin()` — architecture-mandated write pattern; IntegrityError raised inside this block causes automatic rollback before our `except` clause handles it
- `get_db_session` returns a plain `AsyncSession` without an active transaction — `session.begin()` starts one
- `datetime.now(UTC)` — use timezone-aware UTC datetime (Pydantic serializes it as ISO 8601 with `+00:00`)

### `app/main.py` — Register Checkout Router

Add these two lines mirroring the existing `complete` router pattern:

```python
from app.routers import checkout, complete, discovery  # add checkout

app.include_router(checkout.router)    # add after discovery.router
```

### DB ORM Model Reference (READ — do not re-create)

`app/models/db.py` already defines `Invoice` with these columns:
- `session_id: Mapped[uuid.UUID]` — UUID primary key
- `agent_id: Mapped[str]` — VARCHAR NOT NULL
- `items: Mapped[dict]` — JSONB NOT NULL (stores list of dicts)
- `total_amount: Mapped[Decimal]` — NUMERIC(10,2) NOT NULL
- `currency: Mapped[str]` — VARCHAR(3) NOT NULL
- `status: Mapped[str]` — VARCHAR(20), default `"pending"`
- `stripe_payment_intent_id: Mapped[str | None]` — nullable
- `created_at`, `settled_at` — TIMESTAMPTZ, set by server_default

**Do NOT recreate or modify `db.py`.** The model is ready.

### DB Session Dependency (READ — do not re-create)

`app/db/session.py` already defines `get_db_session()`:

```python
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    if _session_factory is None:
        raise RuntimeError("DB engine not initialized — was lifespan skipped?")
    async with _session_factory() as session:
        yield session
```

This yields a session WITHOUT an active transaction. The router's `async with session.begin()` opens the transaction.

---

## Architecture Compliance

| Constraint | How This Story Complies |
|---|---|
| `app/services/invoice.py` owns ALL DB reads/writes | `create_invoice()`, `get_invoice()` in invoice service only; router calls service |
| No SQLAlchemy imports in routers | `checkout.py` imports `invoice_service` and `get_db_session` — no `select`, no ORM objects |
| PyJWT never outside `app/services/crypto.py` | checkout.py and invoice.py have no jwt imports |
| `async with session.begin()` on write paths | Used in `checkout()` handler wrapping `create_invoice()` |
| One router per endpoint group | `app/routers/checkout.py` — `POST /api/checkout` only |
| HTTP 201 for checkout (not 200) | `status_code=201` on `@router.post` decorator |
| Error taxonomy: malformed checkout → 422 | Pydantic validators on `LineItem` (ge, gt), `CheckoutRequest` (min_length, currency) |
| Error taxonomy: duplicate session_id → 409 | `IntegrityError` caught → `HTTPException(409)` |
| Structured log: `event`, `session_id` | Emit `logger.info("checkout_created", extra={"event": "checkout_created", "session_id": str(body.session_id)})` on success |

---

## Testing Approach

**Current state:** Tests use `ASGITransport` (no lifespan) with manual `app.state` injection. This story follows the same pattern but overrides the `get_db_session` dependency.

### Fixture pattern for DB override

```python
# in tests/test_checkout.py (NOT conftest.py — keep it story-local)

from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.db.session import get_db_session

@pytest.fixture(autouse=True)
def override_db(mock_session):
    async def _get_session():
        yield mock_session
    app.dependency_overrides[get_db_session] = _get_session
    yield
    app.dependency_overrides.pop(get_db_session, None)

@pytest.fixture
def mock_session():
    session = AsyncMock()
    # session.begin() must work as an async context manager
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=cm)
    return session
```

### Valid checkout — test response structure + total_amount

```python
_VALID_BODY = {
    "session_id": str(uuid4()),
    "agent_id": "agent-001",
    "currency": "USD",
    "items": [
        {"name": "Wireless Headphones", "quantity": 1, "unit_price": 79.99},
        {"name": "USB-C Hub", "quantity": 2, "unit_price": 49.99},
    ],
}

@pytest.mark.asyncio
async def test_checkout_valid_returns_201(mock_session) -> None:
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=_VALID_BODY)
    assert response.status_code == 201
    data = response.json()
    assert data["session_token"]  # non-empty string
    ctx = data["checkout_context"]
    assert ctx["session_id"] == _VALID_BODY["session_id"]
    # total_amount = 79.99*1 + 49.99*2 = 179.97
    assert abs(ctx["total_amount"] - 179.97) < 0.001
    assert ctx["currency"] == "USD"
    assert ctx["server_timestamp"]  # non-empty ISO 8601

@pytest.mark.asyncio
async def test_checkout_duplicate_session_id_returns_409(mock_session) -> None:
    # Make flush() raise IntegrityError
    mock_session.flush = AsyncMock(side_effect=IntegrityError(None, None, None))
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=_VALID_BODY)
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "session_id_already_exists"
```

### Validation error tests — no DB mock needed

```python
@pytest.mark.asyncio
async def test_checkout_empty_items_returns_422() -> None:
    body = {**_VALID_BODY, "items": []}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_checkout_invalid_currency_xyz_returns_422() -> None:
    body = {**_VALID_BODY, "currency": "XYZ"}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_checkout_item_quantity_zero_returns_422() -> None:
    body = {**_VALID_BODY, "items": [{"name": "X", "quantity": 0, "unit_price": 9.99}]}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_checkout_item_price_zero_returns_422() -> None:
    body = {**_VALID_BODY, "items": [{"name": "X", "quantity": 1, "unit_price": 0}]}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 422
```

### DB assertion note

The AC "invoices table contains exactly one record" requires a real PostgreSQL test. This story provides mock-based tests for HTTP behavior. Full DB assertion tests (with `TEST_DATABASE_URL`) are implemented in Story 5.1 (`tests/test_checkout.py` DB fixtures). Do NOT add `asyncpg`/test-DB setup in this story — Story 5.1 owns that.

---

## Key Files in This Story

| File | Action | Notes |
|---|---|---|
| `app/models/schemas.py` | UPDATE | Add `_VALID_ISO_4217`, `LineItem`, `CheckoutRequest`, `CheckoutContext`, `CheckoutResponse` |
| `app/services/invoice.py` | CREATE | `create_invoice()`, `get_invoice()` — SQLAlchemy owner |
| `app/routers/checkout.py` | CREATE | `POST /api/checkout` handler — calls invoice service only |
| `app/main.py` | UPDATE | Import and register `checkout.router` |
| `tests/test_checkout.py` | CREATE | Min 6 tests covering all ACs via mocked DB |

---

## Previous Story Learnings (Stories 3.1, 2.2, 2.1)

- **ASGITransport does not run FastAPI lifespan** — `get_db_session` will call `_session_factory()` which is `None` unless the lifespan ran. Override `get_db_session` via `app.dependency_overrides` — do NOT call `db_session.init_engine()` in tests.
- **`session.begin()` is a context manager** — must be mocked as an object with `__aenter__` / `__aexit__`. Use `MagicMock(return_value=cm)` where `cm` is an `AsyncMock` with both methods (see fixture above).
- **`del app.state.<attr>` in fixture teardown** — Use direct attribute deletion, not `_state.clear()`.
- **`app.dependency_overrides.pop(key, None)` in teardown** — graceful cleanup in case the fixture is not needed for a specific test.
- **Ruff E501 (line > 88)** — Watch for long `extra={}` dicts in logger calls; split across lines. Watch for long test body dicts; use `{**_VALID_BODY, "key": "val"}` spread pattern.
- **HTTP status 201 vs 200** — `@router.post("/api/checkout", status_code=201)` is mandatory. Do not use the default 200.
- **`datetime.now(UTC)` not `datetime.utcnow()`** — `datetime.utcnow()` is deprecated in Python 3.12; always use `datetime.now(UTC)` for timezone-aware datetimes.
- **`MandateVerificationError` wrapper** — `app/services/crypto.py` now raises `MandateVerificationError` (not `jwt.PyJWTError`). Invoice service has no crypto dependency — do not import from crypto.py in invoice.py.

---

## Potential Gotchas / Debug Notes

1. **`IntegrityError` origin**: PostgreSQL raises PK violation when `session_id` already exists. SQLAlchemy wraps this as `sqlalchemy.exc.IntegrityError`. Import from `sqlalchemy.exc`, not `sqlalchemy.dialects.postgresql`.

2. **`session.begin()` inside `get_db_session`**: The existing `get_db_session` uses `async with _session_factory() as session` — `async_sessionmaker` closes the session on exit but does NOT auto-commit. `session.begin()` in the router creates an explicit transaction. Do NOT call `session.commit()` separately when using `session.begin()` — it commits on context manager exit.

3. **`Decimal` in `items_data`**: When serializing `LineItem` to dict with `item.model_dump()`, Pydantic v2 returns native Python types (`float` for `unit_price`, `int` for `quantity`). The JSONB column accepts dicts — no custom serialization needed.

4. **`datetime` import for `server_timestamp`**: Need both `from datetime import UTC, datetime` — `UTC` is available in Python 3.11+.

5. **`uuid4()` import**: `import uuid` then `str(uuid.uuid4())` — do not use `from uuid import uuid4` to avoid confusion with the `UUID` type used in models.

---

## Dev Agent Record

### Implementation Plan

- T1: Added `_VALID_ISO_4217` frozenset, `LineItem`, `CheckoutRequest` (with `field_validator` for currency), `CheckoutContext`, `CheckoutResponse` to `schemas.py`. Also added `from datetime import datetime` and `from pydantic import field_validator` imports.
- T2: Created `app/services/invoice.py` — `create_invoice()` inserts with `session.flush()` (caller owns transaction), `get_invoice()` selects by PK. Strictly no SQLAlchemy in routers.
- T3: Created `app/routers/checkout.py` — `POST /api/checkout` with `status_code=201`. Uses `Decimal` for total computation, `async with session.begin()` for the write path, catches `IntegrityError` → HTTP 409. Emits structured `checkout_created` log on success.
- T4: Added `checkout` import and `app.include_router(checkout.router)` to `main.py`, between `discovery` and `complete`.
- T5: Created `tests/test_checkout.py` — 13 tests covering all 4 ACs plus argument validation. `mock_session` fixture sets `session.add = MagicMock()` (sync method) to prevent un-awaited coroutine warnings from `AsyncMock`.
- T6: 74 tests pass, 0 failures, 0 regressions.
- T7: Ruff clean — fixed `B904` (`raise ... from exc`), removed local `Decimal` import and moved `patch` to top-level imports to satisfy `I001`/`F401`.

### Completion Notes

- 13 new tests in `tests/test_checkout.py`; total suite: 74 passing.
- Currency validation uses an allowlist (`_VALID_ISO_4217` frozenset) — "XYZ" correctly returns 422.
- Decimal arithmetic prevents floating-point drift; `float(total)` used only for API response.
- `session.add` set to `MagicMock` (not `AsyncMock`) because SQLAlchemy's `session.add()` is synchronous — avoids RuntimeWarning.
- DB record assertion (AC "invoices table contains exactly one record") deferred to Story 5.1 per story spec.

---

## File List

- `app/models/schemas.py` — updated: added `_VALID_ISO_4217`, `LineItem`, `CheckoutRequest`, `CheckoutContext`, `CheckoutResponse`; added `from datetime import datetime`, `from pydantic import field_validator`
- `app/services/invoice.py` — created: `create_invoice()`, `get_invoice()`
- `app/routers/checkout.py` — created: `POST /api/checkout` handler
- `app/main.py` — updated: import and register `checkout.router`
- `tests/test_checkout.py` — created: 13 tests covering all ACs

---

## Change Log

- 2026-06-27: Implemented Story 3.2 — Checkout Session Endpoint. Added Pydantic models (LineItem, CheckoutRequest with ISO 4217 validator, CheckoutContext, CheckoutResponse), invoice service (create_invoice, get_invoice), checkout router (POST /api/checkout, HTTP 201, IntegrityError → 409), registered router in main.py, created 13-test suite with mocked DB session.

---

## References

- [Source: epics.md#Story 3.2] — acceptance criteria (FR-7, FR-8, FR-9)
- [Source: architecture.md#Component Boundaries] — `invoice.py` owns all DB; `checkout.py` owns handler only
- [Source: architecture.md#Process Patterns] — `async with session.begin()` mandatory for write paths
- [Source: architecture.md#Naming Conventions] — `POST /api/checkout`, snake_case fields
- [Source: prd.md§8 API Contracts] — `CheckoutRequest`, `CheckoutResponse`, `CheckoutContext`, `LineItem` canonical schemas
- [Source: prd.md§9 A-4] — ISO 4217 validation via "simple regex or enum check" — use allowlist (AC requires XYZ → 422)
- [Source: Story 3.1 dev notes] — `app.dependency_overrides` pattern for DB; `MagicMock` for context managers
