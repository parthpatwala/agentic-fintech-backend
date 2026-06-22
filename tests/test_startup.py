"""Tests for startup validation — Settings validators and lifespan failure modes (Story 1.4)."""  # noqa: E501

from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from pydantic import ValidationError

from app.config import Settings

_FAKE_CATALOG = [{"id": "p1", "name": "Test Product", "price": 9.99, "currency": "USD"}]

# ── Settings unit tests (no running app needed) ──────────────────────────────


def test_settings_valid_stripe_key() -> None:
    s = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        stripe_api_key="sk_test_valid_key_12345",
        public_key_path="keys/public_key.pem",
    )
    assert s.stripe_api_key.startswith("sk_test_")


def test_settings_invalid_stripe_key_raises() -> None:
    with pytest.raises(ValidationError, match="sk_test_"):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/db",
            stripe_api_key="pk_live_this_is_wrong",
            public_key_path="keys/public_key.pem",
        )


def test_settings_invalid_stripe_key_error_message() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/db",
            stripe_api_key="sk_live_wrong",
            public_key_path="keys/public_key.pem",
        )
    assert "sk_test_" in str(exc_info.value)


def test_settings_bare_prefix_stripe_key_raises() -> None:
    """Verify that the bare 'sk_test_' prefix alone is rejected."""
    with pytest.raises(ValidationError, match="sk_test_"):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/db",
            stripe_api_key="sk_test_",
            public_key_path="keys/public_key.pem",
        )


def test_settings_custom_public_key_path() -> None:
    """Verify that public_key_path can be set to any value (overrides env/default)."""
    s = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        stripe_api_key="sk_test_abc",
        public_key_path="/custom/path/key.pem",
    )
    assert s.public_key_path == "/custom/path/key.pem"


def test_settings_catalog_path_default() -> None:
    """Verify catalog_path defaults to catalog/products.json."""
    s = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        stripe_api_key="sk_test_abc",
        public_key_path="keys/public_key.pem",
    )
    assert s.catalog_path == "catalog/products.json"


# ── Lifespan failure mode tests (direct context manager invocation) ───────────
# Tests call lifespan(app) directly rather than going through the ASGI transport,
# which swallows startup exceptions internally.


@pytest.mark.asyncio
async def test_startup_missing_public_key_raises_file_not_found() -> None:
    from app.main import app, lifespan

    with (
        patch("app.main.Settings") as MockSettings,
        patch("app.main.check_db_connectivity", new_callable=AsyncMock),
        patch("app.db.session.init_engine"),
    ):
        instance = MockSettings.return_value
        instance.database_url = "postgresql+asyncpg://user:pass@localhost/db"
        instance.stripe_api_key = "sk_test_fake"
        instance.public_key_path = "/nonexistent/path/public_key.pem"
        instance.catalog_path = "/fake/products.json"

        with pytest.raises(FileNotFoundError, match="/nonexistent/path/public_key.pem"):
            async with lifespan(app):
                pass


@pytest.mark.asyncio
async def test_startup_db_unreachable_raises() -> None:
    from sqlalchemy.exc import OperationalError

    from app.main import app, lifespan

    with (
        patch("app.main.Settings") as MockSettings,
        patch("app.db.session.init_engine"),
        patch("builtins.open", mock_open(read_data=b"fake-pem-bytes")),
        patch("app.main.crypto.load_public_key", return_value=MagicMock()),
        patch(
            "app.main.crypto.derive_jwk",
            return_value={"kty": "OKP", "crv": "Ed25519", "x": "fake_x"},
        ),
        patch("app.main.json.load", return_value=_FAKE_CATALOG),
        patch(
            "app.main.check_db_connectivity",
            new_callable=AsyncMock,
            side_effect=OperationalError("connect failed", None, None),
        ),
    ):
        instance = MockSettings.return_value
        instance.database_url = "postgresql+asyncpg://bad:bad@bad:5432/bad"
        instance.stripe_api_key = "sk_test_fake"
        instance.public_key_path = "/fake/public_key.pem"
        instance.catalog_path = "/fake/products.json"

        with pytest.raises(OperationalError):
            async with lifespan(app):
                pass
