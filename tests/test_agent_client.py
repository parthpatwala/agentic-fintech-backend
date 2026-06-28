"""Unit tests for scripts/agent_client.py (Story 5.2)."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import typer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location(
    "agent_client", _SCRIPTS_DIR / "agent_client.py"
)
agent_client = importlib.util.module_from_spec(_spec)
sys.modules["agent_client"] = agent_client
_spec.loader.exec_module(agent_client)

_CATALOG = [
    {
        "id": "prod_001",
        "name": "Wireless Headphones",
        "price": 79.99,
        "currency": "USD",
    },
    {
        "id": "prod_002",
        "name": "Mechanical Keyboard",
        "price": 129.99,
        "currency": "USD",
    },
    {"id": "prod_003", "name": "USB-C Hub", "price": 49.99, "currency": "USD"},
]

_DISCOVERY_RESPONSE = {
    "ucp": {
        "version": "2026-04-08",
        "capabilities": ["dev.ucp.shopping.checkout"],
        "routes": {"checkout": "/api/checkout", "complete": "/api/complete"},
        "signing_keys": [{"kty": "OKP", "crv": "Ed25519", "x": "abc"}],
        "catalog": _CATALOG,
    }
}


@pytest.fixture
def private_key_pem(tmp_path: Path) -> Path:
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    key_path = tmp_path / "private_key.pem"
    key_path.write_bytes(pem)
    return key_path


def test_parse_budget_under_dollar() -> None:
    assert agent_client.parse_budget("Buy wireless headphones if under $100") == 100.0


def test_select_product_wireless_headphones() -> None:
    selected = agent_client.select_product(
        _CATALOG, "Buy wireless headphones if under $100", 100.0
    )
    assert selected is not None
    assert selected["name"] == "Wireless Headphones"
    assert selected["price"] == 79.99


@patch("agent_client.httpx.Client")
def test_over_budget_exits_without_checkout(
    mock_client_cls: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.get.return_value = MagicMock(
        status_code=200, json=lambda: _DISCOVERY_RESPONSE
    )
    missing_key = tmp_path / "missing_private_key.pem"

    with pytest.raises(typer.Exit) as exc_info:
        agent_client.run_purchase(
            base_url="http://localhost:8000",
            prompt="Buy mechanical keyboard if under $100",
            private_key_path=missing_key,
        )

    assert exc_info.value.exit_code == 0
    mock_client.get.assert_called_once()
    mock_client.post.assert_not_called()
    output = capsys.readouterr().out
    assert "Mechanical Keyboard" in output
    assert "129.99" in output
    assert "No items found within the stated budget" in output


@patch("agent_client.httpx.Client")
def test_connection_error_exits_nonzero(
    mock_client_cls: MagicMock,
    private_key_pem: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.get.side_effect = httpx.ConnectError("connection refused")

    with pytest.raises(typer.Exit) as exc_info:
        agent_client.run_purchase(
            base_url="http://localhost:8000",
            prompt="Buy wireless headphones if under $100",
            private_key_path=private_key_pem,
        )

    assert exc_info.value.exit_code == 1
    output = capsys.readouterr().out
    assert "Connection error: could not reach http://localhost:8000" in output


@patch("agent_client.httpx.Client")
def test_happy_path_calls_checkout_and_complete(
    mock_client_cls: MagicMock,
    private_key_pem: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id = "550e8400-e29b-41d4-a716-446655440000"
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client

    mock_client.get.return_value = MagicMock(
        status_code=200, json=lambda: _DISCOVERY_RESPONSE
    )
    mock_client.post.side_effect = [
        MagicMock(
            status_code=201,
            json=lambda: {
                "session_token": "token-abc",
                "checkout_context": {
                    "session_id": session_id,
                    "total_amount": 79.99,
                    "currency": "USD",
                    "agent_id": "agent-client-demo",
                },
            },
        ),
        MagicMock(
            status_code=200,
            json=lambda: {
                "session_id": session_id,
                "stripe_payment_intent_id": "pi_test_123",
                "status": "settled",
                "settled_at": "2026-06-28T12:00:00Z",
            },
        ),
    ]

    agent_client.run_purchase(
        base_url="http://localhost:8000",
        prompt="Buy wireless headphones if under $100",
        private_key_path=private_key_pem,
    )

    assert mock_client.post.call_count == 2
    checkout_call, complete_call = mock_client.post.call_args_list

    assert checkout_call.args[0] == "/api/checkout"
    checkout_body = checkout_call.kwargs["json"]
    assert checkout_body["agent_id"] == "agent-client-demo"
    assert checkout_body["items"][0]["name"] == "Wireless Headphones"
    assert checkout_body["items"][0]["unit_price"] == 79.99

    assert complete_call.args[0] == "/api/complete"
    assert "payment_mandate" in complete_call.kwargs["json"]
    assert isinstance(complete_call.kwargs["json"]["payment_mandate"], str)

    output = capsys.readouterr().out
    assert "Wireless Headphones" in output
    assert "session_token: token-abc" in output
    assert "Settlement complete!" in output
    assert "stripe_payment_intent_id: pi_test_123" in output
    assert "status: settled" in output
