"""Tests for AP2 mandate verification — crypto utilities and dependency (Story 3.1).

Three direct unit tests cover crypto.verify_mandate in isolation.
HTTP tests cover the ap2_mandate FastAPI Dependency via the stub
POST /api/complete endpoint, matching all ACs from Story 3.1.

ASGITransport does not run the FastAPI lifespan, so app.state.public_key is
injected manually in the setup_public_key_state autouse fixture.

AC7 log assertions use pytest caplog; the JSON formatter (_configure_logging) is
intentionally NOT called in tests — caplog captures LogRecord objects directly so
structured fields (event, reason, ip) can be asserted without a production formatter.
"""

import base64
import json
import logging
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.crypto import MandateVerificationError, verify_mandate

# ── Shared mandate payload ────────────────────────────────────────────────────

_SESSION_ID = str(uuid4())
_MANDATE_PAYLOAD: dict[str, object] = {
    "session_id": _SESSION_ID,
    "amount": 79.99,
    "currency": "USD",
    "agent_id": "test-agent",
    "exp": int(time.time()) + 300,  # 5 min from test-module load
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def setup_public_key_state(ed25519_key_pair):
    """Inject real Ed25519 public key into app.state for dependency tests.

    ASGITransport does not run the lifespan, so state must be injected manually.
    """
    _, public_key, _ = ed25519_key_pair
    app.state.public_key = public_key
    yield
    del app.state.public_key


# ── Token helpers (scoped to each test via ed25519_key_pair) ──────────────────


def _valid_token(private_key) -> str:
    return jwt.encode(_MANDATE_PAYLOAD, private_key, algorithm="EdDSA")


def _expired_token(private_key) -> str:
    """Sign a token with exp already in the past."""
    payload = {**_MANDATE_PAYLOAD, "exp": int(time.time()) - 1}
    return jwt.encode(payload, private_key, algorithm="EdDSA")


def _hs256_token() -> str:
    return jwt.encode(_MANDATE_PAYLOAD, "shared-secret", algorithm="HS256")


def _none_alg_token() -> str:
    """Craft a JWT with alg:none manually — PyJWT 2.x forbids encoding with 'none'."""
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()  # noqa: E501
    payload = base64.urlsafe_b64encode(
        json.dumps(_MANDATE_PAYLOAD).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}."


def _tampered_token(private_key) -> str:
    """Sign a valid token, then mutate the payload bytes to break the signature."""
    token = _valid_token(private_key)
    parts = token.split(".")
    decoded = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
    decoded["amount"] = 0.01
    parts[1] = base64.urlsafe_b64encode(
        json.dumps(decoded).encode()
    ).rstrip(b"=").decode()
    return ".".join(parts)


def _wrong_key_token() -> str:
    """Sign with a freshly generated key — different from the one in app.state."""
    other_private = Ed25519PrivateKey.generate()
    return jwt.encode(_MANDATE_PAYLOAD, other_private, algorithm="EdDSA")


def _no_amount_token(private_key) -> str:
    payload = {k: v for k, v in _MANDATE_PAYLOAD.items() if k != "amount"}
    return jwt.encode(payload, private_key, algorithm="EdDSA")


# ── Direct unit tests for crypto.verify_mandate ───────────────────────────────


def test_verify_mandate_valid_returns_payload(ed25519_key_pair) -> None:
    """Valid EdDSA JWT with exp → decoded payload dict returned."""
    private_key, public_key, _ = ed25519_key_pair
    token = _valid_token(private_key)
    result = verify_mandate(token, public_key)
    assert result["session_id"] == _SESSION_ID
    assert result["amount"] == 79.99
    assert result["currency"] == "USD"
    assert result["agent_id"] == "test-agent"


def test_verify_mandate_wrong_key_raises(ed25519_key_pair) -> None:
    """JWT signed with a different private key → MandateVerificationError raised."""
    _, public_key, _ = ed25519_key_pair
    token = _wrong_key_token()
    with pytest.raises(MandateVerificationError):
        verify_mandate(token, public_key)


def test_verify_mandate_tampered_raises(ed25519_key_pair) -> None:
    """JWT with mutated payload bytes → MandateVerificationError raised."""
    private_key, public_key, _ = ed25519_key_pair
    token = _tampered_token(private_key)
    with pytest.raises(MandateVerificationError):
        verify_mandate(token, public_key)


def test_verify_mandate_expired_raises(ed25519_key_pair) -> None:
    """JWT with past exp claim → MandateVerificationError raised."""
    private_key, public_key, _ = ed25519_key_pair
    token = _expired_token(private_key)
    with pytest.raises(MandateVerificationError):
        verify_mandate(token, public_key)


def test_verify_mandate_missing_exp_raises(ed25519_key_pair) -> None:
    """JWT without exp claim → MandateVerificationError raised (exp is required)."""
    private_key, public_key, _ = ed25519_key_pair
    payload_no_exp = {k: v for k, v in _MANDATE_PAYLOAD.items() if k != "exp"}
    token = jwt.encode(payload_no_exp, private_key, algorithm="EdDSA")
    with pytest.raises(MandateVerificationError):
        verify_mandate(token, public_key)


# ── HTTP tests for ap2_mandate FastAPI Dependency ─────────────────────────────


@pytest.mark.asyncio
async def test_mandate_dep_valid_returns_200(ed25519_key_pair) -> None:
    """Valid EdDSA JWT in payment_mandate → stub endpoint returns 200."""
    private_key, _, _ = ed25519_key_pair
    token = _valid_token(private_key)
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/complete", json={"payment_mandate": token})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_mandate_dep_missing_payment_mandate_returns_422() -> None:
    """Body without payment_mandate field → Pydantic validation → 422."""
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/complete", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_mandate_dep_wrong_key_returns_401() -> None:
    """JWT signed with a different private key → dependency returns 401."""
    token = _wrong_key_token()
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/complete", json={"payment_mandate": token})
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "invalid_signature"


@pytest.mark.asyncio
async def test_mandate_dep_tampered_payload_returns_401(ed25519_key_pair) -> None:
    """JWT with tampered payload → dependency returns 401."""
    private_key, _, _ = ed25519_key_pair
    token = _tampered_token(private_key)
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/complete", json={"payment_mandate": token})
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "invalid_signature"


@pytest.mark.asyncio
async def test_mandate_dep_expired_returns_401(ed25519_key_pair) -> None:
    """Expired JWT → dependency returns 401."""
    private_key, _, _ = ed25519_key_pair
    token = _expired_token(private_key)
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/complete", json={"payment_mandate": token})
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "invalid_signature"


@pytest.mark.asyncio
async def test_mandate_dep_alg_hs256_returns_401() -> None:
    """HS256 algorithm confusion token → dependency returns 401."""
    token = _hs256_token()
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/complete", json={"payment_mandate": token})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_mandate_dep_alg_none_returns_401() -> None:
    """Crafted alg:none JWT → dependency returns 401."""
    token = _none_alg_token()
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/complete", json={"payment_mandate": token})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_mandate_dep_missing_amount_returns_422(ed25519_key_pair) -> None:
    """Valid EdDSA JWT missing 'amount' payload field → dependency returns 422."""
    private_key, _, _ = ed25519_key_pair
    token = _no_amount_token(private_key)
    _transport = ASGITransport(app=app)
    async with AsyncClient(transport=_transport, base_url="http://test") as client:
        response = await client.post("/api/complete", json={"payment_mandate": token})
    assert response.status_code == 422


# ── AC7: structured log assertions ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_mandate_dep_log_on_invalid_jwt_format(caplog) -> None:
    """Bad JWT format → structured error log with event/reason/ip fields (AC7)."""
    with caplog.at_level(logging.ERROR, logger="app.dependencies"):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            await client.post("/api/complete", json={"payment_mandate": "not-a-jwt"})
    assert caplog.records, "Expected at least one error log record"
    record = caplog.records[-1]
    assert getattr(record, "event", None) == "mandate_rejected"
    assert getattr(record, "reason", None) == "invalid_jwt_format"
    assert hasattr(record, "ip")


@pytest.mark.asyncio
async def test_mandate_dep_log_on_invalid_signature(caplog) -> None:
    """Wrong-key rejection → structured error log with event/reason/ip fields (AC7)."""
    token = _wrong_key_token()
    with caplog.at_level(logging.ERROR, logger="app.dependencies"):
        _transport = ASGITransport(app=app)
        async with AsyncClient(transport=_transport, base_url="http://test") as client:
            await client.post("/api/complete", json={"payment_mandate": token})
    assert caplog.records, "Expected at least one error log record"
    record = caplog.records[-1]
    assert getattr(record, "event", None) == "mandate_rejected"
    assert getattr(record, "reason", None) == "invalid_signature"
    assert hasattr(record, "ip")
