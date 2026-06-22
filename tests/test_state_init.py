"""Tests for startup state initialization — crypto utilities and catalog loading (Story 2.1)."""  # noqa: E501

import base64
import json
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services.crypto import derive_jwk, load_public_key

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ed25519_key_pair():
    """Generate a real in-memory Ed25519 key pair — no disk I/O."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_pem = public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return private_key, public_key, pub_pem


# ── load_public_key tests ─────────────────────────────────────────────────────


def test_load_public_key_returns_ed25519_key(ed25519_key_pair) -> None:
    _, _, pub_pem = ed25519_key_pair
    result = load_public_key(pub_pem)
    assert isinstance(result, Ed25519PublicKey)


def test_load_public_key_raises_on_invalid_bytes() -> None:
    with pytest.raises(ValueError):
        load_public_key(b"this is not a valid PEM key")


def test_load_public_key_raises_on_empty_bytes() -> None:
    with pytest.raises(ValueError):
        load_public_key(b"")


def test_load_public_key_raises_on_non_ed25519_key() -> None:
    """RSA public key PEM must be rejected with TypeError (isinstance guard)."""
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    rsa_pub_pem = (
        generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    with pytest.raises(TypeError):
        load_public_key(rsa_pub_pem)


# ── derive_jwk tests ──────────────────────────────────────────────────────────


def test_derive_jwk_has_correct_shape(ed25519_key_pair) -> None:
    _, public_key, _ = ed25519_key_pair
    jwk = derive_jwk(public_key)
    assert jwk["kty"] == "OKP"
    assert jwk["crv"] == "Ed25519"
    assert isinstance(jwk["x"], str)
    assert len(jwk["x"]) > 0


def test_derive_jwk_x_is_base64url(ed25519_key_pair) -> None:
    """x must be base64url-encoded without padding (RFC 8037)."""
    _, public_key, _ = ed25519_key_pair
    jwk = derive_jwk(public_key)
    x = jwk["x"]
    assert "+" not in x, "base64url must not contain '+'"
    assert "/" not in x, "base64url must not contain '/'"
    assert "=" not in x, "base64url must not contain padding '='"


def test_derive_jwk_x_is_32_bytes_encoded(ed25519_key_pair) -> None:
    """Ed25519 raw public key is 32 bytes → 43 base64url chars (no padding)."""
    _, public_key, _ = ed25519_key_pair
    jwk = derive_jwk(public_key)
    padded = jwk["x"] + "=" * (-len(jwk["x"]) % 4)
    raw = base64.urlsafe_b64decode(padded)
    assert len(raw) == 32


def test_derive_jwk_is_deterministic(ed25519_key_pair) -> None:
    """Same key always produces identical JWK."""
    _, public_key, _ = ed25519_key_pair
    assert derive_jwk(public_key) == derive_jwk(public_key)


# ── lifespan catalog + state loading tests ────────────────────────────────────

_FAKE_CATALOG_RAW = [
    {"id": "prod_001", "name": "Wireless Headphones", "price": 79.99, "currency": "USD"},  # noqa: E501
    {"id": "prod_002", "name": "Mechanical Keyboard", "price": 129.99, "currency": "USD"},  # noqa: E501
    {"id": "prod_003", "name": "USB-C Hub", "price": 49.99, "currency": "USD"},
    {"id": "prod_004", "name": "HD Webcam", "price": 89.99, "currency": "USD"},
    {"id": "prod_005", "name": "Desk Lamp LED", "price": 34.99, "currency": "USD"},
]


def _patched_lifespan():
    """Return a stack of patches that fully isolates the lifespan for state tests."""
    mock_settings = MagicMock()
    mock_settings.database_url = "postgresql+asyncpg://user:pass@localhost/db"
    mock_settings.stripe_api_key = "sk_test_fake"
    mock_settings.public_key_path = "/fake/public_key.pem"
    mock_settings.catalog_path = "/fake/products.json"
    return mock_settings


@pytest.mark.asyncio
async def test_catalog_loaded_into_app_state() -> None:
    from app.main import app, lifespan
    from app.models.schemas import ProductItem

    mock_settings = _patched_lifespan()

    with (
        patch("app.main.Settings", return_value=mock_settings),
        patch("builtins.open", mock_open(read_data=b"fake-pem-bytes")),
        patch("app.main.crypto.load_public_key", return_value=MagicMock()),
        patch(
            "app.main.crypto.derive_jwk",
            return_value={"kty": "OKP", "crv": "Ed25519", "x": "fake_x"},
        ),
        patch("app.main.json.load", return_value=_FAKE_CATALOG_RAW),
        patch("app.db.session.init_engine"),
        patch("app.main.check_db_connectivity", new_callable=AsyncMock),
    ):
        async with lifespan(app):
            assert isinstance(app.state.catalog, list)
            assert len(app.state.catalog) == 5
            assert all(isinstance(item, ProductItem) for item in app.state.catalog)


@pytest.mark.asyncio
async def test_catalog_item_fields() -> None:
    from app.main import app, lifespan

    mock_settings = _patched_lifespan()

    with (
        patch("app.main.Settings", return_value=mock_settings),
        patch("builtins.open", mock_open(read_data=b"fake-pem-bytes")),
        patch("app.main.crypto.load_public_key", return_value=MagicMock()),
        patch(
            "app.main.crypto.derive_jwk",
            return_value={"kty": "OKP", "crv": "Ed25519", "x": "fake_x"},
        ),
        patch("app.main.json.load", return_value=_FAKE_CATALOG_RAW),
        patch("app.db.session.init_engine"),
        patch("app.main.check_db_connectivity", new_callable=AsyncMock),
    ):
        async with lifespan(app):
            first = app.state.catalog[0]
            assert first.id == "prod_001"
            assert first.name == "Wireless Headphones"
            assert first.price == pytest.approx(79.99)
            assert first.currency == "USD"


@pytest.mark.asyncio
async def test_jwk_stored_in_app_state() -> None:
    from app.main import app, lifespan

    mock_settings = _patched_lifespan()
    fake_jwk = {"kty": "OKP", "crv": "Ed25519", "x": "abc123"}

    with (
        patch("app.main.Settings", return_value=mock_settings),
        patch("builtins.open", mock_open(read_data=b"fake-pem-bytes")),
        patch("app.main.crypto.load_public_key", return_value=MagicMock()),
        patch("app.main.crypto.derive_jwk", return_value=fake_jwk),
        patch("app.main.json.load", return_value=_FAKE_CATALOG_RAW),
        patch("app.db.session.init_engine"),
        patch("app.main.check_db_connectivity", new_callable=AsyncMock),
    ):
        async with lifespan(app):
            assert app.state.jwk["kty"] == "OKP"
            assert app.state.jwk["crv"] == "Ed25519"
            assert isinstance(app.state.jwk["x"], str)


@pytest.mark.asyncio
async def test_startup_malformed_catalog_raises() -> None:
    from app.main import app, lifespan

    mock_settings = _patched_lifespan()

    with (
        patch("app.main.Settings", return_value=mock_settings),
        patch("builtins.open", mock_open(read_data=b"fake-pem-bytes")),
        patch("app.main.crypto.load_public_key", return_value=MagicMock()),
        patch(
            "app.main.crypto.derive_jwk",
            return_value={"kty": "OKP", "crv": "Ed25519", "x": "fake_x"},
        ),
        patch(
            "app.main.json.load",
            side_effect=json.JSONDecodeError("Expecting value", "not-json", 0),
        ),
        patch("app.db.session.init_engine"),
        patch("app.main.check_db_connectivity", new_callable=AsyncMock),
    ):
        with pytest.raises(json.JSONDecodeError):
            async with lifespan(app):
                pass
