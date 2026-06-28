import contextlib
import json
import logging
from collections.abc import AsyncIterator

import stripe
from fastapi import FastAPI
from pydantic import ValidationError
from pythonjsonlogger.json import JsonFormatter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db import session as db_session
from app.models.schemas import ProductItem
from app.routers import checkout, complete, discovery
from app.services import crypto

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configure JSON structured logging via python-json-logger."""
    handler = logging.StreamHandler()
    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(event)s",
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
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(logger_name)
        uv_logger.handlers.clear()
        uv_logger.propagate = False
        uv_logger.addHandler(handler)
        uv_logger.setLevel(logging.WARNING)


_configure_logging()


async def check_db_connectivity(engine: AsyncEngine) -> None:
    """Ping the database with SELECT 1. Extracted for testability."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 1. Validate all configuration — ValidationError raised here exits the process
    settings = Settings()
    logger.info("Configuration validated", extra={"event": "startup"})

    # 2. Configure Stripe SDK with validated test key
    stripe.api_key = settings.stripe_api_key
    logger.info("Stripe API key configured", extra={"event": "startup"})

    # 3. Load public key file — explicit errors for missing, unreadable, or empty file
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

    # 4. Parse public key object + derive JWK (both cached in app.state)
    try:
        app.state.public_key = crypto.load_public_key(app.state.public_key_bytes)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"PUBLIC_KEY_PATH '{settings.public_key_path}' does not contain a valid "
            f"Ed25519 public key: {exc}"
        ) from exc
    app.state.jwk = crypto.derive_jwk(app.state.public_key)
    logger.info("JWK derived", extra={"event": "startup"})

    # 5. Load and validate product catalog
    try:
        with open(settings.catalog_path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"CATALOG_PATH '{settings.catalog_path}' does not exist."
        ) from exc
    except PermissionError as exc:
        raise PermissionError(
            f"CATALOG_PATH '{settings.catalog_path}' is not readable — "
            "check file permissions."
        ) from exc
    except json.JSONDecodeError as exc:
        raise json.JSONDecodeError(
            f"CATALOG_PATH '{settings.catalog_path}' contains invalid JSON: {exc.msg}",
            exc.doc,
            exc.pos,
        ) from exc

    if not isinstance(raw, list):
        raise TypeError(
            f"CATALOG_PATH '{settings.catalog_path}' must contain a JSON array, "
            f"got {type(raw).__name__}."
        )
    try:
        app.state.catalog = [ProductItem.model_validate(item) for item in raw]
    except (ValidationError, TypeError) as exc:
        raise ValueError(
            f"CATALOG_PATH '{settings.catalog_path}' contains invalid product "
            f"data: {exc}"
        ) from exc

    if not app.state.catalog:
        raise ValueError(
            f"CATALOG_PATH '{settings.catalog_path}' loaded an empty list — "
            "at least one product is required."
        )
    logger.info(
        "Catalog loaded",
        extra={"event": "startup", "count": len(app.state.catalog)},
    )

    # 6. Initialize DB engine and verify connectivity; dispose engine on failure
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

app.include_router(discovery.router)
app.include_router(checkout.router)
app.include_router(complete.router)


@app.get("/health")
async def health() -> dict[str, str]:
    logger.info("health_check", extra={"event": "health_check"})
    return {"status": "ok"}
