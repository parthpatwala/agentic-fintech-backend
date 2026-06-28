---
baseline_commit: c1caaf475491c939c7b78bdc84f601d22fe7d5c6
---

# Story 4.2: Mandate-Gated Settlement Endpoint

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a mock AI Agent,
I want to submit my signed Payment Mandate to `POST /api/complete` and receive a confirmed Stripe payment intent ID,
So that I can prove the full Human-Not-Present commerce cycle — from cryptographic authorization to payment settlement — completed successfully.

## Acceptance Criteria

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

## Tasks / Subtasks

- [x] T1: Add `CompleteResponse` to `app/models/schemas.py`
- [x] T2: Add `settle_invoice()` and `write_mandate_audit()` to `app/services/invoice.py`
- [x] T3: Replace stub in `app/routers/complete.py` with full settlement handler (mandatory call order)
- [x] T4: Create `tests/test_complete.py` covering all ACs (mocked DB session + mocked Stripe)
- [x] T5: Fix `tests/test_crypto.py` regression — stub removal breaks `test_mandate_dep_valid_returns_200`
- [x] T6: Verify all existing tests still pass (`uv run pytest tests/ -x -q`)
- [x] T7: Ruff clean (`uv run ruff check app/ tests/`)

### Review Findings

- [x] [Review][Patch] Outer DB transaction never committed after settlement writes [app/routers/complete.py:28-77]
- [x] [Review][Patch] No guard that Stripe PaymentIntent status is `"succeeded"` before persisting settlement [app/routers/complete.py:43-77]
- [x] [Review][Defer] Concurrent duplicate settlement requests can both pass `status == "pending"` check (TOCTOU race) [app/routers/complete.py:28-39] — deferred, prototype scope; needs row-level lock or idempotency
- [x] [Review][Defer] Stripe charge succeeds but DB commit fails leaves orphaned payment with no compensation [app/routers/complete.py:42-77] — deferred, distributed-transaction concern for production

---

## Developer Context

### Mandatory Settlement Handler Call Order (BINDING)

From [architecture.md §Process Patterns](_bmad-output/planning-artifacts/architecture.md). **Do not reorder.**

1. Receive `(raw_jwt: str, payload: PaymentMandatePayload)` from AP2 Dependency
2. Query invoice by `payload.session_id` via `invoice.get_invoice()` — **404** if not found
3. Check `invoice.status == "pending"` — **409** if already `"settled"`
4. Convert `invoice.total_amount` to cents; call `settlement.create_payment_intent(amount_cents, invoice.currency.lower())`
5. On Stripe success: `async with session.begin()` → `settle_invoice()` → `write_mandate_audit()` → commit
6. On `stripe.error.StripeError`: return **502** — **no DB writes**
7. Return `CompleteResponse`

**Critical:** Steps 2–3 happen **before** Stripe (FR-10). Steps 5–6 happen **after** Stripe returns. Never open a DB transaction before the Stripe call completes.

### `CompleteResponse` — Add to `app/models/schemas.py`

```python
from typing import Literal  # add to existing imports if missing

class CompleteResponse(BaseModel):
    session_id: UUID
    stripe_payment_intent_id: str
    status: Literal["settled"]
    settled_at: datetime
```

[Source: prd.md §8 API Contracts — `POST /api/complete`]

### `app/services/invoice.py` — New Functions (T2)

Add two functions. **All DB writes for settlement live here** — not in the router.

```python
import hashlib  # only if used here — prefer hash in router, see below

async def settle_invoice(
    session: AsyncSession,
    invoice: Invoice,
    stripe_payment_intent_id: str,
    settled_at: datetime,
) -> Invoice:
    """Mark invoice settled. Caller owns the transaction (async with session.begin())."""
    invoice.status = "settled"
    invoice.stripe_payment_intent_id = stripe_payment_intent_id
    invoice.settled_at = settled_at
    await session.flush()
    return invoice


async def write_mandate_audit(
    session: AsyncSession,
    session_id: uuid.UUID,
    agent_id: str,
    mandate_jwt_hash: str,
    settlement_timestamp: datetime,
) -> MandateAudit:
    """Insert mandate_audit row. Caller owns the transaction."""
    audit = MandateAudit(
        session_id=session_id,
        agent_id=agent_id,
        mandate_jwt_hash=mandate_jwt_hash,
        settlement_timestamp=settlement_timestamp,
    )
    session.add(audit)
    await session.flush()
    return audit
```

Import `MandateAudit` from `app.models.db` alongside existing `Invoice` import.

**Do NOT add Stripe imports to `invoice.py`.** Service boundary is binding.

### `app/routers/complete.py` — EXACT IMPLEMENTATION (T3)

Replace the entire stub. Match `checkout.py` patterns: `async` handler, `Annotated` deps, structured `HTTPException` detail dicts with `reason` keys.

```python
import hashlib
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.dependencies import ap2_mandate
from app.models.schemas import CompleteResponse, PaymentMandatePayload
from app.services import invoice as invoice_service
from app.services import settlement as settlement_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/complete")
async def complete(
    mandate: Annotated[tuple[str, PaymentMandatePayload], Depends(ap2_mandate)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CompleteResponse:
    raw_jwt, payload = mandate

    # Step 2: Session linkage
    invoice = await invoice_service.get_invoice(session, payload.session_id)
    if invoice is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "session_not_found"},
        )

    # Step 3: Idempotency guard
    if invoice.status != "pending":
        raise HTTPException(
            status_code=409,
            detail={"reason": "session_already_settled"},
        )

    # Step 4: Stripe charge (outside DB transaction)
    amount_cents = int(invoice.total_amount * Decimal("100"))
    try:
        payment_intent = await settlement_service.create_payment_intent(
            amount=amount_cents,
            currency=invoice.currency.lower(),
        )
    except stripe.error.StripeError as exc:
        logger.error(
            "settlement_failed",
            extra={
                "event": "settlement_failed",
                "session_id": str(payload.session_id),
                "detail": str(exc),
            },
        )
        raise HTTPException(
            status_code=502,
            detail={"reason": "payment_failed"},
        ) from exc

    # Step 5: Atomic DB write
    settled_at = datetime.now(UTC)
    mandate_jwt_hash = hashlib.sha256(raw_jwt.encode()).hexdigest()

    async with session.begin():
        await invoice_service.settle_invoice(
            session=session,
            invoice=invoice,
            stripe_payment_intent_id=payment_intent.id,
            settled_at=settled_at,
        )
        await invoice_service.write_mandate_audit(
            session=session,
            session_id=invoice.session_id,
            agent_id=invoice.agent_id,
            mandate_jwt_hash=mandate_jwt_hash,
            settlement_timestamp=settled_at,
        )

    return CompleteResponse(
        session_id=invoice.session_id,
        stripe_payment_intent_id=payment_intent.id,
        status="settled",
        settled_at=settled_at,
    )
```

**Notes:**
- `import stripe` is allowed **only** for `stripe.error.StripeError` exception typing in the router — no Stripe API calls in the router. All API calls stay in `settlement.py`.
- Use `invoice.currency.lower()` — not `payload.currency`. Invoice is the billing source of truth; Story 4.1 deferred note applies.
- Use `invoice.agent_id` for audit — matches the checkout record being settled.
- `mandate_jwt_hash` = SHA-256 hex digest (64 chars) of the **raw JWT string**, not the decoded payload. [FR-12]
- `settled_at` and `settlement_timestamp` should use the **same** `datetime.now(UTC)` value for consistency within one settlement.
- Do **not** validate mandate `amount`/`currency` against invoice in this story — not in AC; deferred to Story 5.1 DB assertions if needed.

### Amount Conversion — Decimal to Cents

```python
amount_cents = int(invoice.total_amount * Decimal("100"))
```

Examples:
- `Decimal("79.99")` → `7999`
- `Decimal("179.97")` → `17997`

Use `Decimal("100")` not `100` to avoid float precision issues. `invoice.total_amount` is `Numeric(10,2)` mapped to Python `Decimal`.

### Error Taxonomy (BINDING)

| Condition | HTTP | `detail.reason` | Stripe called? | DB written? |
|---|---|---|---|---|
| Missing/invalid mandate | 401/422 | (dependency) | No | No |
| Unknown `session_id` | 404 | `session_not_found` | No | No |
| Already settled | 409 | `session_already_settled` | No | No |
| Stripe failure | 502 | `payment_failed` | Yes (failed) | No |
| Success | 200 | — | Yes (succeeded) | Yes (atomic) |

### Service Boundary Compliance

| Constraint | How Story 4.2 Complies |
|---|---|
| PyJWT only in `crypto.py` | Unchanged — dependency handles verification |
| DB writes only in `invoice.py` | Router calls `settle_invoice` + `write_mandate_audit` |
| Stripe API calls only in `settlement.py` | Router calls `create_payment_intent` only |
| Mandatory call order | Documented above — enforced in handler |
| Atomic settlement (FR-12) | Single `async with session.begin()` wraps both writes |
| Stripe failure → no DB write (AC) | `except StripeError` before any `session.begin()` |

### Current File States (READ — preserve existing behavior)

**`app/dependencies.py`** — Complete. Returns `(raw_jwt, payload)` tuple. Do not modify unless tests require it.

**`app/services/settlement.py`** — Complete from Story 4.1. `create_payment_intent(amount: int, currency: str)` is ready. Do not add DB logic here.

**`app/models/db.py`** — `Invoice` and `MandateAudit` ORM models exist with all required columns. No schema migration needed.

**`app/routers/complete.py`** — Currently a **sync stub** returning `{"status": "stub"}`. Replace entirely with async handler above.

**`tests/test_crypto.py`** — 13 HTTP tests hit `POST /api/complete`. Most test mandate rejection (401/422) and are unaffected. **One test breaks:**

```python
# test_mandate_dep_valid_returns_200 — expects 200 with stub response
# After Story 4.2: valid mandate + no invoice mock → 404
```

**Fix (T5):** Change `test_mandate_dep_valid_returns_200` to assert **404** with `detail.reason == "session_not_found"`. This proves the AP2 dependency passed (mandate verified) and the handler reached step 2. Full HTTP 200 happy path belongs in `test_complete.py`.

Alternatively, add minimal mocks in that one test — but 404 assertion is cleaner scope separation (crypto module tests dependency; complete module tests settlement).

### Testing Requirements (T4 + T5)

Create `tests/test_complete.py`. Follow `tests/test_checkout.py` patterns:
- `ASGITransport` + `AsyncClient`
- `mock_session` fixture with `async with session.begin()` support
- `app.dependency_overrides[get_db_session]`
- `setup_public_key_state` autouse fixture (copy from `test_crypto.py`) — ASGITransport skips lifespan
- Patch `settlement_service.create_payment_intent` — never hit real Stripe
- Patch or configure `invoice_service.get_invoice` return values

**Required test cases (map to ACs):**

| Test | AC | Key assertions |
|---|---|---|
| `test_complete_happy_path_returns_200` | Happy path | 200; all 4 response fields; Stripe called with correct cents + lowercase currency |
| `test_complete_unknown_session_returns_404` | 404 | 404; `session_not_found`; Stripe **not** called |
| `test_complete_already_settled_returns_409` | 409 | 409; `session_already_settled`; Stripe **not** called |
| `test_complete_stripe_error_returns_502` | 502 | 502; `payment_failed`; `settle_invoice` **not** called |
| `test_complete_duplicate_settlement_returns_409` | Second call 409 | Same as already-settled after first success mock |
| `test_complete_calls_settle_and_audit_in_transaction` | Atomic write | Verify `settle_invoice` + `write_mandate_audit` called inside transaction |
| `test_complete_mandate_hash_is_sha256_hex` | Audit hash | Verify hash passed to `write_mandate_audit` is 64-char hex of raw JWT |

**Mock invoice factory helper:**

```python
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

def _pending_invoice(session_id: UUID, total: str = "79.99") -> MagicMock:
    inv = MagicMock()
    inv.session_id = session_id
    inv.agent_id = "test-agent"
    inv.total_amount = Decimal(total)
    inv.currency = "USD"
    inv.status = "pending"
    return inv
```

**Mock Stripe PaymentIntent:**

```python
mock_intent = MagicMock()
mock_intent.id = "pi_3TestComplete"
mock_intent.status = "succeeded"
```

**JWT signing:** Reuse token helpers from `test_crypto.py` — copy `_MANDATE_PAYLOAD` pattern or import shared helpers. Ensure `session_id` in JWT matches mock invoice `session_id`.

**DB record assertions deferred:** Full PostgreSQL record verification (exact row contents) is Story 5.1 scope with `TEST_DATABASE_URL`. Story 4.2 uses mocked session like Story 3.2 — verify service functions called with correct args.

### Regression: Existing Test Suite

Before Story 4.2: **82+ tests pass** (76 existing + 6 settlement unit tests from 4.1).

After implementation, expect:
- `test_crypto.py::test_mandate_dep_valid_returns_200` — **must update** (T5)
- All other `test_crypto.py` tests — unchanged (fail at dependency layer before handler)
- All `test_checkout.py`, `test_settlement.py`, etc. — unchanged

Run: `uv run pytest tests/ -x -q`

---

## Previous Story Intelligence (Story 4.1)

- **`asyncio.to_thread` in settlement** — `create_payment_intent` is async; await it in the router.
- **Amount in cents is caller's job** — convert in `complete.py`, not `settlement.py`.
- **Currency lowercase** — `invoice.currency.lower()` before Stripe call; settlement forwards verbatim.
- **`stripe.error.StripeError` catch in router** — service propagates unchanged; router maps to 502.
- **`import stripe` in router** — only for exception type; API calls stay in `settlement.py`. `main.py` also imports stripe for `api_key` config only.
- **Review deferrals carry forward** — idempotency key, amount lower-bound, 3DS `return_url` are production concerns; optional `idempotency_key=f"settle-{session_id}"` noted in deferred-work.md but not required for AC pass.
- **Ruff I001** — import order: stdlib → third-party → local.

---

## Git Intelligence Summary

Recent commits show established patterns:
- `c1caaf4` — checkout endpoint + invoice service (`create_invoice`, `get_invoice`)
- `f796d0a` — UCP discovery with catalog
- Router registration in `main.py`: discovery → checkout → complete
- Test pattern: mocked `AsyncSession` with `session.begin()` context manager mock
- Error responses use `HTTPException(detail={"reason": "..."})` consistently

Story 4.1 settlement service exists locally (may not be committed yet per git status) — implementation should build on `app/services/settlement.py` as documented in Story 4.1 artifact.

---

## Latest Tech Information

**Stripe Python SDK v15.2.1** (pinned in `uv.lock`):
- Sync SDK wrapped with `asyncio.to_thread` in `settlement.py` — do not change
- `PaymentIntent.create` with `confirm=True` + `pm_card_visa` returns `status: "succeeded"` in test mode
- Catch `stripe.error.StripeError` (base class) in router — covers `CardError`, `InvalidRequestError`, etc.

**SQLAlchemy 2.0 async:**
- `async with session.begin()` auto-commits on clean exit, rolls back on exception
- Nested `begin()` on same session raises — do not nest transactions
- `get_db_session` yields session without auto-commit; router owns transaction boundary

**SHA-256 mandate hash:**
```python
hashlib.sha256(raw_jwt.encode("utf-8")).hexdigest()  # 64-char hex string
```

---

## Project Context Reference

No `project-context.md` found in repository. Binding sources for this story:
- [epics.md §Story 4.2](_bmad-output/planning-artifacts/epics.md)
- [architecture.md §Process Patterns — Settlement handler](_bmad-output/planning-artifacts/architecture.md)
- [prd.md §8 — CompleteResponse contract](_bmad-output/planning-artifacts/prds/prd-agentic-fintech-backend-2026-06-20/prd.md)
- [Story 4.1 artifact](_bmad-output/implementation-artifacts/4-1-stripe-sandbox-payment-service.md) — settlement service contract
- [deferred-work.md](_bmad-output/implementation-artifacts/deferred-work.md) — known deferrals

---

## Key Files in This Story

| File | Action | Notes |
|---|---|---|
| `app/models/schemas.py` | UPDATE | Add `CompleteResponse` |
| `app/services/invoice.py` | UPDATE | Add `settle_invoice()`, `write_mandate_audit()` |
| `app/routers/complete.py` | UPDATE | Replace stub with full async settlement handler |
| `tests/test_complete.py` | CREATE | HTTP tests for all settlement ACs |
| `tests/test_crypto.py` | UPDATE | Fix `test_mandate_dep_valid_returns_200` for stub removal |

**Do NOT modify:** `app/services/settlement.py`, `app/dependencies.py`, `app/models/db.py`, Alembic migrations.

---

## References

- [Source: epics.md#Story 4.2] — acceptance criteria (FR-10, FR-12, FR-13)
- [Source: architecture.md#Process Patterns] — settlement handler mandatory call order
- [Source: architecture.md#Component Boundaries] — `complete.py` owns handler; calls invoice + settlement services
- [Source: architecture.md#Error HTTP taxonomy] — 404/409/502 mapping
- [Source: prd.md §8] — `CompleteResponse` field definitions
- [Source: Story 4.1] — cents conversion, currency lowercase, StripeError → 502
- [Source: Story 3.2] — router async pattern, mocked DB test fixtures
- [Source: Story 3.1] — AP2 dependency tuple, JWT test helpers

---

## Dev Agent Record

### Agent Model Used

Composer

### Debug Log References

| Step | Issue | Fix |
|------|-------|-----|
| T5 | `test_crypto.py` valid-mandate test hit `RuntimeError` — complete now requires `get_db_session` | Added autouse `override_db` fixture to all `test_crypto.py` tests |
| T7 | Ruff E501 on long lines in tests and docstring | Added `_post_complete` helper in `test_complete.py`; shortened docstring |

### Completion Notes List

- **T1** — Added `CompleteResponse` Pydantic model with `session_id`, `stripe_payment_intent_id`, `status: Literal["settled"]`, `settled_at`.
- **T2** — Added `settle_invoice()` and `write_mandate_audit()` to `invoice.py`; imports `MandateAudit` from ORM.
- **T3** — Replaced sync stub with async settlement handler enforcing mandatory call order: lookup → status guard → Stripe → atomic DB transaction → response. Maps `StripeError` to 502; 404/409 before Stripe call.
- **T4** — Created `tests/test_complete.py` with 7 tests covering happy path, 404, 409 (×2), 502, atomic transaction, and SHA-256 mandate hash.
- **T5** — Renamed crypto test to `test_mandate_dep_valid_returns_404_when_no_invoice`; added autouse DB session override for all crypto HTTP tests.
- **T6** — Full suite: 89 passed (82 existing + 7 new), 0 failures.
- **T7** — Ruff clean.
- **Review** — Added `await session.commit()` after write block so autobegun read txn persists settlement. Added `payment_intent.status != "succeeded"` guard → 502. Added 2 tests (commit + non-succeeded status).

### File List

| File | Action |
|------|--------|
| `app/models/schemas.py` | MODIFIED |
| `app/services/invoice.py` | MODIFIED |
| `app/routers/complete.py` | MODIFIED |
| `tests/test_complete.py` | CREATED |
| `tests/test_crypto.py` | MODIFIED |

### Change Log

- Story 4.2 implementation complete (Date: 2026-06-28): Mandate-gated settlement endpoint with atomic invoice update and mandate audit; 7 new HTTP tests; crypto test regression fixed.
- Code review patches applied (Date: 2026-06-28): Added `session.commit()` after settlement writes; guard non-`succeeded` PaymentIntent status; 2 additional tests.
