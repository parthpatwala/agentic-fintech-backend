"""Tests for POST /api/complete — Story 4.2.

Covers settlement ACs using ASGITransport with mocked DB session and mocked Stripe.
Full PostgreSQL record assertions deferred to Story 5.1.
"""

import hashlib
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest
import stripe
from httpx import ASGITransport, AsyncClient

from app.db.session import get_db_session
from app.main import app

_SESSION_ID = uuid4()
_MANDATE_PAYLOAD: dict[str, object] = {
    "session_id": str(_SESSION_ID),
    "amount": 79.99,
    "currency": "USD",
    "agent_id": "test-agent",
    "exp": int(time.time()) + 300,
}


def _valid_token(private_key) -> str:
    return jwt.encode(_MANDATE_PAYLOAD, private_key, algorithm="EdDSA")


def _pending_invoice(session_id: UUID, total: str = "79.99") -> MagicMock:
    inv = MagicMock()
    inv.session_id = session_id
    inv.agent_id = "test-agent"
    inv.total_amount = Decimal(total)
    inv.currency = "USD"
    inv.status = "pending"
    return inv


def _settled_invoice(session_id: UUID) -> MagicMock:
    inv = _pending_invoice(session_id)
    inv.status = "settled"
    return inv


@pytest.fixture
def mock_session():
    session = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=cm)
    session.add = MagicMock()
    return session


@pytest.fixture(autouse=True)
def setup_public_key_state(ed25519_key_pair):
    _, public_key, _ = ed25519_key_pair
    app.state.public_key = public_key
    yield
    del app.state.public_key


@pytest.fixture(autouse=True)
def override_db(mock_session):
    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_db_session] = _get_session
    yield
    app.dependency_overrides.pop(get_db_session, None)


_COMPLETE_PATH = "/api/complete"


def _mock_payment_intent(intent_id: str = "pi_3TestComplete") -> MagicMock:
    mock_intent = MagicMock()
    mock_intent.id = intent_id
    mock_intent.status = "succeeded"
    return mock_intent


async def _post_complete(client: AsyncClient, token: str):
    return await client.post(_COMPLETE_PATH, json={"payment_mandate": token})


@pytest.mark.asyncio
async def test_complete_happy_path_returns_200(ed25519_key_pair) -> None:
    private_key, _, _ = ed25519_key_pair
    token = _valid_token(private_key)
    invoice = _pending_invoice(_SESSION_ID)

    with (
        patch(
            "app.routers.complete.invoice_service.get_invoice",
            new_callable=AsyncMock,
            return_value=invoice,
        ),
        patch(
            "app.routers.complete.settlement_service.create_payment_intent",
            new_callable=AsyncMock,
            return_value=_mock_payment_intent(),
        ) as mock_stripe,
        patch(
            "app.routers.complete.invoice_service.settle_invoice",
            new_callable=AsyncMock,
        ) as mock_settle,
        patch(
            "app.routers.complete.invoice_service.write_mandate_audit",
            new_callable=AsyncMock,
        ) as mock_audit,
    ):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            response = await _post_complete(client, token)

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == str(_SESSION_ID)
    assert data["stripe_payment_intent_id"] == "pi_3TestComplete"
    assert data["status"] == "settled"
    assert data["settled_at"]

    mock_stripe.assert_awaited_once_with(amount=7999, currency="usd")
    mock_settle.assert_awaited_once()
    mock_audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_unknown_session_returns_404(ed25519_key_pair) -> None:
    private_key, _, _ = ed25519_key_pair
    token = _valid_token(private_key)

    with (
        patch(
            "app.routers.complete.invoice_service.get_invoice",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.routers.complete.settlement_service.create_payment_intent",
            new_callable=AsyncMock,
        ) as mock_stripe,
    ):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            response = await _post_complete(client, token)

    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "session_not_found"
    mock_stripe.assert_not_called()


@pytest.mark.asyncio
async def test_complete_already_settled_returns_409(ed25519_key_pair) -> None:
    private_key, _, _ = ed25519_key_pair
    token = _valid_token(private_key)
    invoice = _settled_invoice(_SESSION_ID)

    with (
        patch(
            "app.routers.complete.invoice_service.get_invoice",
            new_callable=AsyncMock,
            return_value=invoice,
        ),
        patch(
            "app.routers.complete.settlement_service.create_payment_intent",
            new_callable=AsyncMock,
        ) as mock_stripe,
    ):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            response = await _post_complete(client, token)

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "session_already_settled"
    mock_stripe.assert_not_called()


@pytest.mark.asyncio
async def test_complete_stripe_error_returns_502(ed25519_key_pair) -> None:
    private_key, _, _ = ed25519_key_pair
    token = _valid_token(private_key)
    invoice = _pending_invoice(_SESSION_ID)

    with (
        patch(
            "app.routers.complete.invoice_service.get_invoice",
            new_callable=AsyncMock,
            return_value=invoice,
        ),
        patch(
            "app.routers.complete.settlement_service.create_payment_intent",
            new_callable=AsyncMock,
            side_effect=stripe.error.StripeError("Stripe test error"),
        ),
        patch(
            "app.routers.complete.invoice_service.settle_invoice",
            new_callable=AsyncMock,
        ) as mock_settle,
        patch(
            "app.routers.complete.invoice_service.write_mandate_audit",
            new_callable=AsyncMock,
        ) as mock_audit,
    ):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            response = await _post_complete(client, token)

    assert response.status_code == 502
    assert response.json()["detail"]["reason"] == "payment_failed"
    mock_settle.assert_not_called()
    mock_audit.assert_not_called()


@pytest.mark.asyncio
async def test_complete_stripe_status_not_succeeded_returns_502(
    ed25519_key_pair,
) -> None:
    private_key, _, _ = ed25519_key_pair
    token = _valid_token(private_key)
    invoice = _pending_invoice(_SESSION_ID)
    mock_intent = _mock_payment_intent()
    mock_intent.status = "requires_payment_method"

    with (
        patch(
            "app.routers.complete.invoice_service.get_invoice",
            new_callable=AsyncMock,
            return_value=invoice,
        ),
        patch(
            "app.routers.complete.settlement_service.create_payment_intent",
            new_callable=AsyncMock,
            return_value=mock_intent,
        ),
        patch(
            "app.routers.complete.invoice_service.settle_invoice",
            new_callable=AsyncMock,
        ) as mock_settle,
        patch(
            "app.routers.complete.invoice_service.write_mandate_audit",
            new_callable=AsyncMock,
        ) as mock_audit,
    ):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            response = await _post_complete(client, token)

    assert response.status_code == 502
    assert response.json()["detail"]["reason"] == "payment_failed"
    mock_settle.assert_not_called()
    mock_audit.assert_not_called()


@pytest.mark.asyncio
async def test_complete_commits_session_after_settlement(
    ed25519_key_pair, mock_session
) -> None:
    private_key, _, _ = ed25519_key_pair
    token = _valid_token(private_key)
    invoice = _pending_invoice(_SESSION_ID)
    mock_session.commit = AsyncMock()

    with (
        patch(
            "app.routers.complete.invoice_service.get_invoice",
            new_callable=AsyncMock,
            return_value=invoice,
        ),
        patch(
            "app.routers.complete.settlement_service.create_payment_intent",
            new_callable=AsyncMock,
            return_value=_mock_payment_intent(),
        ),
        patch(
            "app.routers.complete.invoice_service.settle_invoice",
            new_callable=AsyncMock,
        ),
        patch(
            "app.routers.complete.invoice_service.write_mandate_audit",
            new_callable=AsyncMock,
        ),
    ):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            await _post_complete(client, token)

    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_duplicate_settlement_returns_409(ed25519_key_pair) -> None:
    """Second call with same mandate for already-settled session → 409."""
    private_key, _, _ = ed25519_key_pair
    token = _valid_token(private_key)
    invoice = _settled_invoice(_SESSION_ID)

    with patch(
        "app.routers.complete.invoice_service.get_invoice",
        new_callable=AsyncMock,
        return_value=invoice,
    ):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            response = await _post_complete(client, token)

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "session_already_settled"


@pytest.mark.asyncio
async def test_complete_calls_settle_and_audit_in_transaction(
    ed25519_key_pair, mock_session
) -> None:
    private_key, _, _ = ed25519_key_pair
    token = _valid_token(private_key)
    invoice = _pending_invoice(_SESSION_ID)

    with (
        patch(
            "app.routers.complete.invoice_service.get_invoice",
            new_callable=AsyncMock,
            return_value=invoice,
        ),
        patch(
            "app.routers.complete.settlement_service.create_payment_intent",
            new_callable=AsyncMock,
            return_value=_mock_payment_intent(),
        ),
        patch(
            "app.routers.complete.invoice_service.settle_invoice",
            new_callable=AsyncMock,
        ) as mock_settle,
        patch(
            "app.routers.complete.invoice_service.write_mandate_audit",
            new_callable=AsyncMock,
        ) as mock_audit,
    ):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            await _post_complete(client, token)

    mock_session.begin.assert_called_once()
    mock_settle.assert_awaited_once()
    mock_audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_mandate_hash_is_sha256_hex(ed25519_key_pair) -> None:
    private_key, _, _ = ed25519_key_pair
    token = _valid_token(private_key)
    invoice = _pending_invoice(_SESSION_ID)
    expected_hash = hashlib.sha256(token.encode()).hexdigest()

    with (
        patch(
            "app.routers.complete.invoice_service.get_invoice",
            new_callable=AsyncMock,
            return_value=invoice,
        ),
        patch(
            "app.routers.complete.settlement_service.create_payment_intent",
            new_callable=AsyncMock,
            return_value=_mock_payment_intent(),
        ),
        patch(
            "app.routers.complete.invoice_service.settle_invoice",
            new_callable=AsyncMock,
        ),
        patch(
            "app.routers.complete.invoice_service.write_mandate_audit",
            new_callable=AsyncMock,
        ) as mock_audit,
    ):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            await _post_complete(client, token)

    mock_audit.assert_awaited_once()
    assert mock_audit.call_args.kwargs["mandate_jwt_hash"] == expected_hash
    assert len(expected_hash) == 64
