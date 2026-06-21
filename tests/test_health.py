"""Tests for the /health endpoint (Stories 1.2 + 1.4)."""

from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture(autouse=True)
def mock_startup_dependencies():
    """Fully isolate health tests from env vars, key file, and DB connectivity."""
    mock_settings = MagicMock()
    mock_settings.database_url = "postgresql+asyncpg://user:pass@localhost/db"
    mock_settings.stripe_api_key = "sk_test_fake_key"
    mock_settings.public_key_path = "/fake/public_key.pem"

    with (
        patch("app.main.Settings", return_value=mock_settings),
        patch("builtins.open", mock_open(read_data=b"fake-pem-bytes")),
        patch("app.db.session.init_engine"),
        patch("app.main.check_db_connectivity", new_callable=AsyncMock),
    ):
        yield


@pytest.mark.asyncio
async def test_health_returns_200() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_returns_status_ok() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.json() == {"status": "ok"}
