"""Structured JSON logging tests — Story 5.3."""

import json
import logging
import time
from decimal import Decimal
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from pythonjsonlogger.json import JsonFormatter

from app.db.session import get_db_session
from app.main import _configure_logging, app

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


def _mock_payment_intent(intent_id: str = "pi_3TestLogging") -> MagicMock:
    mock_intent = MagicMock()
    mock_intent.id = intent_id
    mock_intent.status = "succeeded"
    return mock_intent


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


def test_json_log_output_is_valid_json() -> None:
    """Configured JsonFormatter emits parseable JSON with timestamp, level, event."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(event)s",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
        },
    )
    handler.setFormatter(formatter)
    test_logger = logging.getLogger("test.logging.json")
    test_logger.handlers.clear()
    test_logger.propagate = False
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)

    test_logger.info("test_event", extra={"event": "test_event"})

    line = stream.getvalue().strip()
    parsed = json.loads(line)
    assert "timestamp" in parsed
    assert parsed["level"] == "INFO"
    assert parsed["event"] == "test_event"


def test_configure_logging_sets_json_formatter() -> None:
    """_configure_logging applies JsonFormatter to root and uvicorn loggers."""
    _configure_logging()
    root = logging.getLogger()
    assert root.handlers
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(logger_name)
        assert uv_logger.handlers
        assert isinstance(uv_logger.handlers[0].formatter, JsonFormatter)
        assert uv_logger.propagate is False


@pytest.mark.asyncio
async def test_settlement_success_log_fields(caplog, ed25519_key_pair) -> None:
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
            return_value=_mock_payment_intent("pi_3TestLoggingSuccess"),
        ),
        patch(
            "app.routers.complete.invoice_service.settle_invoice",
            new_callable=AsyncMock,
        ),
        patch(
            "app.routers.complete.invoice_service.write_mandate_audit",
            new_callable=AsyncMock,
        ),
        caplog.at_level(logging.INFO, logger="app.routers.complete"),
    ):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            response = await client.post(
                "/api/complete", json={"payment_mandate": token}
            )

    assert response.status_code == 200
    success_records = [
        r for r in caplog.records if getattr(r, "event", None) == "settlement_success"
    ]
    assert success_records
    record = success_records[-1]
    assert getattr(record, "session_id", None) == str(_SESSION_ID)
    assert getattr(record, "stripe_payment_intent_id", None) == "pi_3TestLoggingSuccess"


@pytest.mark.asyncio
async def test_discovery_emits_structured_log(caplog) -> None:
    """GET /.well-known/ucp emits discovery_served structured log."""
    from app.models.schemas import ProductItem

    app.state.jwk = {"kty": "OKP", "crv": "Ed25519", "x": "fake_x"}
    app.state.catalog = [
        ProductItem.model_validate(
            {
                "id": "prod_001",
                "name": "Wireless Headphones",
                "price": 79.99,
                "currency": "USD",
            }
        )
    ]

    with caplog.at_level(logging.INFO, logger="app.routers.discovery"):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            response = await client.get("/.well-known/ucp")

    assert response.status_code == 200
    discovery_records = [
        r for r in caplog.records if getattr(r, "event", None) == "discovery_served"
    ]
    assert discovery_records

    del app.state.jwk
    del app.state.catalog
