"""Tests for POST /api/checkout — Story 3.2.

Covers all four ACs using ASGITransport with the get_db_session dependency
overridden to avoid requiring a live PostgreSQL instance. Full DB record
assertions (AC1 "invoices table contains exactly one record") are deferred
to Story 5.1 which introduces TEST_DATABASE_URL fixtures.

Session mock must support `async with session.begin()` — see mock_session fixture.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DataError, IntegrityError

from app.db.session import get_db_session
from app.main import app

# ── Shared valid body ─────────────────────────────────────────────────────────

_SESSION_ID = str(uuid4())
_VALID_BODY: dict = {
    "session_id": _SESSION_ID,
    "agent_id": "agent-001",
    "currency": "USD",
    "items": [
        {"name": "Wireless Headphones", "quantity": 1, "unit_price": 79.99},
        {"name": "USB-C Hub", "quantity": 2, "unit_price": 49.99},
    ],
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_session():
    """AsyncSession mock that supports `async with session.begin()`.

    session.begin() returns an async context manager.
    session.add() is a synchronous method in SQLAlchemy — use MagicMock so it
    doesn't produce an un-awaited coroutine warning.
    """
    session = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=cm)
    session.add = MagicMock()
    return session


@pytest.fixture(autouse=True)
def override_db(mock_session):
    """Override get_db_session for every test in this module."""
    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_db_session] = _get_session
    yield
    app.dependency_overrides.pop(get_db_session, None)


# ── AC1: Valid checkout → HTTP 201 with correct response shape ────────────────


@pytest.mark.asyncio
async def test_checkout_valid_returns_201(mock_session) -> None:
    """Valid checkout request → HTTP 201 with session_token and checkout_context."""
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=_VALID_BODY)
    assert response.status_code == 201
    data = response.json()
    assert data["session_token"]
    ctx = data["checkout_context"]
    assert ctx["session_id"] == _SESSION_ID
    assert ctx["currency"] == "USD"
    assert ctx["server_timestamp"]


@pytest.mark.asyncio
async def test_checkout_total_amount_computed_correctly(mock_session) -> None:
    """total_amount = sum(quantity × unit_price) = 79.99*1 + 49.99*2 = 179.97."""
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=_VALID_BODY)
    assert response.status_code == 201
    ctx = response.json()["checkout_context"]
    assert abs(ctx["total_amount"] - 179.97) < 0.001


@pytest.mark.asyncio
async def test_checkout_single_item_total(mock_session) -> None:
    """Single item: total_amount = quantity × unit_price."""
    body = {
        **_VALID_BODY,
        "session_id": str(uuid4()),
        "items": [{"name": "Keyboard", "quantity": 3, "unit_price": 129.99}],
    }
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 201
    ctx = response.json()["checkout_context"]
    assert abs(ctx["total_amount"] - 389.97) < 0.001


@pytest.mark.asyncio
async def test_checkout_session_token_is_nonempty_string(mock_session) -> None:
    """session_token must be a non-empty opaque string."""
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=_VALID_BODY)
    assert isinstance(response.json()["session_token"], str)
    assert len(response.json()["session_token"]) > 0


# ── AC2: Empty items → HTTP 422 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_checkout_empty_items_returns_422() -> None:
    """Empty items list → Pydantic min_length=1 validation → HTTP 422."""
    body = {**_VALID_BODY, "items": []}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 422


# ── AC3: Invalid ISO 4217 currency → HTTP 422 ─────────────────────────────────


@pytest.mark.asyncio
async def test_checkout_invalid_currency_xyz_returns_422() -> None:
    """Currency 'XYZ' not in ISO 4217 allowlist → field_validator → HTTP 422."""
    body = {**_VALID_BODY, "currency": "XYZ"}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_checkout_valid_currency_eur_returns_201(mock_session) -> None:
    """Currency 'EUR' is in the allowlist → HTTP 201."""
    body = {**_VALID_BODY, "session_id": str(uuid4()), "currency": "EUR"}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 201


# ── Validation: item field constraints ───────────────────────────────────────


@pytest.mark.asyncio
async def test_checkout_item_quantity_zero_returns_422() -> None:
    """Item quantity=0 violates ge=1 → HTTP 422."""
    body = {**_VALID_BODY, "items": [{"name": "X", "quantity": 0, "unit_price": 9.99}]}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_checkout_item_price_zero_returns_422() -> None:
    """Item unit_price=0 violates gt=0 → HTTP 422."""
    body = {**_VALID_BODY, "items": [{"name": "X", "quantity": 1, "unit_price": 0}]}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_checkout_item_price_negative_returns_422() -> None:
    """Item unit_price<0 violates gt=0 → HTTP 422."""
    body = {**_VALID_BODY, "items": [{"name": "X", "quantity": 1, "unit_price": -5.0}]}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_checkout_empty_agent_id_returns_422() -> None:
    """agent_id='' violates min_length=1 → HTTP 422."""
    body = {**_VALID_BODY, "agent_id": ""}
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=body)
    assert response.status_code == 422


# ── AC4: Duplicate session_id → HTTP 409 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_checkout_duplicate_session_id_returns_409(mock_session) -> None:
    """PK violation (sqlstate 23505) → HTTP 409 with session_id_already_exists."""
    orig = MagicMock()
    orig.sqlstate = "23505"
    orig.pgcode = None
    mock_session.flush = AsyncMock(
        side_effect=IntegrityError(None, None, orig)
    )
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=_VALID_BODY)
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "session_id_already_exists"


@pytest.mark.asyncio
async def test_checkout_non_unique_integrity_error_propagates(mock_session) -> None:
    """Non-23505 IntegrityError (CHECK violation etc.) is re-raised, not caught as 409.

    ASGITransport surfaces unhandled exceptions directly; a real ASGI server
    converts this to HTTP 500. We verify it is NOT swallowed as 409.
    """
    orig = MagicMock()
    orig.sqlstate = "23514"  # check_violation
    orig.pgcode = None
    mock_session.flush = AsyncMock(
        side_effect=IntegrityError(None, None, orig)
    )
    _transport = ASGITransport(app=app)
    with pytest.raises(IntegrityError):
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            await client.post("/api/checkout", json=_VALID_BODY)


@pytest.mark.asyncio
async def test_checkout_numeric_overflow_returns_422(mock_session) -> None:
    """NUMERIC(10,2) overflow (DataError from PostgreSQL) → HTTP 422."""
    mock_session.flush = AsyncMock(
        side_effect=DataError(None, None, None)
    )
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/checkout", json=_VALID_BODY)
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "total_amount_out_of_range"


# ── Invoice service is called with correct args ───────────────────────────────


@pytest.mark.asyncio
async def test_checkout_calls_create_invoice_with_correct_args(mock_session) -> None:
    """Verify create_invoice receives session_id, agent_id, items, total, currency."""
    with patch(
        "app.routers.checkout.invoice_service.create_invoice",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.return_value = MagicMock()
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            await client.post("/api/checkout", json=_VALID_BODY)

    mock_create.assert_called_once()
    kwargs = mock_create.call_args.kwargs
    assert str(kwargs["session_id"]) == _SESSION_ID
    assert kwargs["agent_id"] == "agent-001"
    assert kwargs["currency"] == "USD"
    assert abs(float(kwargs["total_amount"]) - 179.97) < 0.001
    assert len(kwargs["items"]) == 2
