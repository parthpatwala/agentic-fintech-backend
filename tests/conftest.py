import os
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.models.db import Base


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests requiring TEST_DATABASE_URL and live PostgreSQL",
    )


@pytest.fixture
def ed25519_key_pair():
    """Generate a real in-memory Ed25519 key pair — no disk I/O."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_pem = public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return private_key, public_key, pub_pem


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set — integration tests skipped")
    db_name = urlparse(url).path.lstrip("/").split("/")[0]
    if db_name == "fintech_db":
        pytest.fail(
            "TEST_DATABASE_URL must point to a dedicated test database "
            "(e.g. fintech_test_db), not the development fintech_db"
        )
    return url


@pytest_asyncio.fixture
async def db_engine(test_database_url) -> AsyncEngine:
    """Test-scoped async engine with schema ensured."""
    engine = create_async_engine(test_database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_engine_truncated(db_engine) -> AsyncEngine:
    """Truncate all tables before each integration test."""
    async with db_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(
                text(f"TRUNCATE {table.name} RESTART IDENTITY CASCADE")
            )
    return db_engine
