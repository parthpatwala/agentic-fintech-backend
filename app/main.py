import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from pythonjsonlogger.json import JsonFormatter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db import session as db_session

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configure JSON structured logging via python-json-logger."""
    handler = logging.StreamHandler()
    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
        },
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


async def check_db_connectivity(engine: AsyncEngine) -> None:
    """Ping the database with SELECT 1. Extracted for testability."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _configure_logging()

    # 1. Validate all configuration — ValidationError raised here exits the process
    settings = Settings()
    logger.info("Configuration validated", extra={"event": "startup"})

    # 2. Load public key file — explicit errors for missing, unreadable, or empty file
    try:
        with open(settings.public_key_path, "rb") as f:
            app.state.public_key_bytes = f.read()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"PUBLIC_KEY_PATH '{settings.public_key_path}' does not exist. "
            "Generate keys with: "
            "openssl genpkey -algorithm ed25519 -out keys/private_key.pem"
        ) from exc
    except PermissionError as exc:
        raise PermissionError(
            f"PUBLIC_KEY_PATH '{settings.public_key_path}' is not readable — "
            "check file permissions."
        ) from exc
    if not app.state.public_key_bytes:
        raise ValueError(
            f"PUBLIC_KEY_PATH '{settings.public_key_path}' is empty — "
            "the file must contain a valid Ed25519 public key."
        )
    logger.info(
        "Public key loaded",
        extra={"event": "startup", "path": settings.public_key_path},
    )

    # 3. Initialize DB engine and verify connectivity; dispose engine on failure
    engine = db_session.init_engine(settings.database_url)
    try:
        await check_db_connectivity(engine)
    except Exception:
        await db_session.dispose_engine()
        raise
    logger.info("Database connected", extra={"event": "startup"})

    logger.info(
        "Startup complete — configuration validated and database connected",
        extra={"event": "startup_complete"},
    )

    yield  # app is live from here

    # Teardown
    await db_session.dispose_engine()
    logger.info("Engine disposed", extra={"event": "shutdown"})


app = FastAPI(title="Agentic Fintech Backend", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
