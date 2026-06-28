"""Integration tests for DB persistence (Story 5.1 / FR-18).

Requires TEST_DATABASE_URL and a running PostgreSQL instance.
Skipped automatically when TEST_DATABASE_URL is unset.
"""

import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest
import pytest_asyncio
import stripe
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.session import get_db_session
from app.main import app
from app.models.db import Invoice, MandateAudit

pytestmark = pytest.mark.integration

_CHECKOUT_BODY = {
    "session_id": None,  # set per test
    "agent_id": "integration-agent",
    "currency": "USD",
    "items": [{"name": "Wireless Headphones", "quantity": 1, "unit_price": 79.99}],
}


def _checkout_payload(session_id: UUID) -> dict:
    return {**_CHECKOUT_BODY, "session_id": str(session_id)}


def _mandate_token(private_key, session_id: UUID, amount: float = 79.99) -> str:
    payload = {
        "session_id": str(session_id),
        "amount": amount,
        "currency": "USD",
        "agent_id": "integration-agent",
        "exp": int(time.time()) + 300,
    }
    return jwt.encode(payload, private_key, algorithm="EdDSA")


def _mock_payment_intent(intent_id: str = "pi_integration_test") -> MagicMock:
    mock_intent = MagicMock()
    mock_intent.id = intent_id
    mock_intent.status = "succeeded"
    return mock_intent


async def _get_invoice(engine: AsyncEngine, session_id: UUID) -> Invoice | None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(Invoice).where(Invoice.session_id == session_id)
        )
        return result.scalar_one_or_none()


async def _count_invoices(engine: AsyncEngine) -> int:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(select(func.count()).select_from(Invoice))
        return result.scalar_one()


async def _count_audits(engine: AsyncEngine, session_id: UUID) -> int:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(MandateAudit)
            .where(MandateAudit.session_id == session_id)
        )
        return result.scalar_one()


@pytest_asyncio.fixture
async def integration_client(db_engine_truncated, ed25519_key_pair):
    """AsyncClient with per-request DB sessions (mirrors production get_db_session)."""
    _, public_key, _ = ed25519_key_pair
    app.state.public_key = public_key

    factory = async_sessionmaker(db_engine_truncated, expire_on_commit=False)

    async def _get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, db_engine_truncated
    app.dependency_overrides.pop(get_db_session, None)
    del app.state.public_key


@pytest.mark.asyncio
async def test_checkout_persists_pending_invoice(integration_client) -> None:
    client, engine = integration_client
    session_id = uuid4()
    response = await client.post("/api/checkout", json=_checkout_payload(session_id))
    assert response.status_code == 201

    invoice = await _get_invoice(engine, session_id)
    assert invoice is not None
    assert invoice.status == "pending"
    assert invoice.agent_id == "integration-agent"
    assert invoice.currency == "USD"
    assert float(invoice.total_amount) == pytest.approx(79.99)
    assert invoice.items == [
        {"name": "Wireless Headphones", "quantity": 1, "unit_price": 79.99}
    ]


@pytest.mark.asyncio
async def test_complete_settles_invoice_and_writes_audit(
    integration_client, ed25519_key_pair
) -> None:
    client, engine = integration_client
    private_key, _, _ = ed25519_key_pair
    session_id = uuid4()

    checkout_resp = await client.post(
        "/api/checkout", json=_checkout_payload(session_id)
    )
    assert checkout_resp.status_code == 201

    token = _mandate_token(private_key, session_id)
    expected_hash = hashlib.sha256(token.encode()).hexdigest()

    with patch(
        "app.routers.complete.settlement_service.create_payment_intent",
        new_callable=AsyncMock,
        return_value=_mock_payment_intent("pi_settled_integration"),
    ):
        complete_resp = await client.post(
            "/api/complete", json={"payment_mandate": token}
        )

    assert complete_resp.status_code == 200
    data = complete_resp.json()
    assert data["status"] == "settled"
    assert data["stripe_payment_intent_id"] == "pi_settled_integration"

    invoice = await _get_invoice(engine, session_id)
    assert invoice is not None
    assert invoice.status == "settled"
    assert invoice.stripe_payment_intent_id == "pi_settled_integration"
    assert invoice.settled_at is not None

    assert await _count_audits(engine, session_id) == 1

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(MandateAudit).where(MandateAudit.session_id == session_id)
        )
        audit = result.scalar_one()
    assert audit.agent_id == "integration-agent"
    assert audit.mandate_jwt_hash == expected_hash
    assert len(audit.mandate_jwt_hash) == 64


@pytest.mark.asyncio
async def test_complete_stripe_failure_leaves_invoice_pending(
    integration_client, ed25519_key_pair
) -> None:
    client, engine = integration_client
    private_key, _, _ = ed25519_key_pair
    session_id = uuid4()

    checkout_resp = await client.post(
        "/api/checkout", json=_checkout_payload(session_id)
    )
    assert checkout_resp.status_code == 201

    token = _mandate_token(private_key, session_id)

    with patch(
        "app.routers.complete.settlement_service.create_payment_intent",
        new_callable=AsyncMock,
        side_effect=stripe.error.StripeError("integration test failure"),
    ):
        complete_resp = await client.post(
            "/api/complete", json={"payment_mandate": token}
        )

    assert complete_resp.status_code == 502
    assert complete_resp.json()["detail"]["reason"] == "payment_failed"

    invoice = await _get_invoice(engine, session_id)
    assert invoice is not None
    assert invoice.status == "pending"
    assert invoice.stripe_payment_intent_id is None
    assert await _count_audits(engine, session_id) == 0


@pytest.mark.asyncio
async def test_checkout_duplicate_session_id_returns_409_in_db(
    integration_client,
) -> None:
    client, engine = integration_client
    session_id = uuid4()
    body = _checkout_payload(session_id)

    first = await client.post("/api/checkout", json=body)
    assert first.status_code == 201

    second = await client.post("/api/checkout", json=body)
    assert second.status_code == 409
    assert second.json()["detail"]["reason"] == "session_id_already_exists"

    assert await _count_invoices(engine) == 1
