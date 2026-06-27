import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.schemas import CheckoutContext, CheckoutRequest, CheckoutResponse
from app.services import invoice as invoice_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/checkout", status_code=201)
async def checkout(
    body: CheckoutRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CheckoutResponse:
    total = sum(
        Decimal(str(item.unit_price)) * item.quantity for item in body.items
    )
    session_token = str(uuid.uuid4())
    items_data = [item.model_dump() for item in body.items]

    try:
        async with session.begin():
            await invoice_service.create_invoice(
                session=session,
                session_id=body.session_id,
                agent_id=body.agent_id,
                items=items_data,
                total_amount=total,
                currency=body.currency,
            )
    except IntegrityError as exc:
        # Only map unique/PK violations (pg 23505) to 409.
        # FK, CHECK, and NOT NULL violations are unexpected here and should 500.
        orig = getattr(exc, "orig", None)
        sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
        if sqlstate == "23505":
            raise HTTPException(
                status_code=409,
                detail={"reason": "session_id_already_exists"},
            ) from exc
        raise
    except DataError as exc:
        raise HTTPException(
            status_code=422,
            detail={"reason": "total_amount_out_of_range"},
        ) from exc

    logger.info(
        "checkout_created",
        extra={
            "event": "checkout_created",
            "session_id": str(body.session_id),
        },
    )

    return CheckoutResponse(
        session_token=session_token,
        checkout_context=CheckoutContext(
            session_id=body.session_id,
            total_amount=float(total),
            currency=body.currency,
            server_timestamp=datetime.now(UTC),
        ),
    )
