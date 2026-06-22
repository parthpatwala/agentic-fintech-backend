"""Tests for GET /.well-known/ucp — UCP discovery profile endpoint (Story 2.2).

ASGITransport (httpx) does not invoke the FastAPI lifespan, so app.state is never
populated by the startup handler. These tests set app.state directly in a fixture
and restore it after each test, keeping all tests fully isolated.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.schemas import ProductItem

_FAKE_CATALOG = [
    {"id": "prod_001", "name": "Wireless Headphones", "price": 79.99, "currency": "USD"},  # noqa: E501
    {"id": "prod_002", "name": "Mechanical Keyboard", "price": 129.99, "currency": "USD"},  # noqa: E501
    {"id": "prod_003", "name": "USB-C Hub", "price": 49.99, "currency": "USD"},
    {"id": "prod_004", "name": "HD Webcam", "price": 89.99, "currency": "USD"},
    {"id": "prod_005", "name": "Desk Lamp LED", "price": 34.99, "currency": "USD"},
]

_FAKE_JWK = {"kty": "OKP", "crv": "Ed25519", "x": "fake_x"}


@pytest.fixture(autouse=True)
def setup_app_state():
    """Populate app.state directly; restore after each test.

    ASGITransport does not run the lifespan, so state must be injected manually.
    """
    app.state.jwk = _FAKE_JWK
    app.state.catalog = [ProductItem.model_validate(item) for item in _FAKE_CATALOG]
    yield
    del app.state.jwk
    del app.state.catalog


@pytest.mark.asyncio
async def test_ucp_returns_200() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/ucp")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ucp_version() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/ucp")
    assert response.json()["ucp"]["version"] == "2026-04-08"


@pytest.mark.asyncio
async def test_ucp_capabilities_contains_checkout() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/ucp")
    assert "dev.ucp.shopping.checkout" in response.json()["ucp"]["capabilities"]


@pytest.mark.asyncio
async def test_ucp_capabilities_contains_ap2_mandate() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/ucp")
    assert "dev.ucp.shopping.ap2_mandate" in response.json()["ucp"]["capabilities"]


@pytest.mark.asyncio
async def test_ucp_route_checkout() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/ucp")
    assert response.json()["ucp"]["routes"]["checkout"] == "/api/checkout"


@pytest.mark.asyncio
async def test_ucp_route_complete() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/ucp")
    assert response.json()["ucp"]["routes"]["complete"] == "/api/complete"


@pytest.mark.asyncio
async def test_ucp_signing_keys_shape() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/ucp")
    keys = response.json()["ucp"]["signing_keys"]
    assert len(keys) >= 1
    assert keys[0]["kty"] == "OKP"
    assert keys[0]["crv"] == "Ed25519"
    assert isinstance(keys[0]["x"], str) and keys[0]["x"]


@pytest.mark.asyncio
async def test_ucp_catalog_count() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/ucp")
    assert len(response.json()["ucp"]["catalog"]) == len(_FAKE_CATALOG)


@pytest.mark.asyncio
async def test_ucp_catalog_item_fields() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/ucp")
    item = response.json()["ucp"]["catalog"][0]
    assert "id" in item
    assert "name" in item
    assert "price" in item
    assert "currency" in item


@pytest.mark.asyncio
async def test_ucp_no_auth_required() -> None:
    """An Authorization header must be silently ignored — endpoint is public."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/.well-known/ucp",
            headers={"Authorization": "Bearer fake-token"},
        )
    assert response.status_code == 200
