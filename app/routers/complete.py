import hashlib
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.dependencies import ap2_mandate
from app.models.schemas import CompleteResponse, PaymentMandatePayload
from app.services import invoice as invoice_service
from app.services import settlement as settlement_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/complete")
async def complete(
    mandate: Annotated[tuple[str, PaymentMandatePayload], Depends(ap2_mandate)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CompleteResponse:
    raw_jwt, payload = mandate

    invoice = await invoice_service.get_invoice(session, payload.session_id)
    if invoice is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "session_not_found"},
        )

    if invoice.status != "pending":
        raise HTTPException(
            status_code=409,
            detail={"reason": "session_already_settled"},
        )

    # Close the read transaction opened by get_invoice before Stripe + write path.
    await session.commit()

    amount_cents = int(invoice.total_amount * Decimal("100"))
    try:
        payment_intent = await settlement_service.create_payment_intent(
            amount=amount_cents,
            currency=invoice.currency.lower(),
        )
    except stripe.error.StripeError as exc:
        logger.error(
            "settlement_failed",
            extra={
                "event": "settlement_failed",
                "session_id": str(payload.session_id),
                "detail": str(exc),
            },
        )
        raise HTTPException(
            status_code=502,
            detail={"reason": "payment_failed"},
        ) from exc

    if payment_intent.status != "succeeded":
        logger.error(
            "settlement_failed",
            extra={
                "event": "settlement_failed",
                "session_id": str(payload.session_id),
                "detail": f"unexpected PaymentIntent status: {payment_intent.status}",
            },
        )
        raise HTTPException(
            status_code=502,
            detail={"reason": "payment_failed"},
        )

    settled_at = datetime.now(UTC)
    mandate_jwt_hash = hashlib.sha256(raw_jwt.encode()).hexdigest()

    async with session.begin():
        await invoice_service.settle_invoice(
            session=session,
            invoice=invoice,
            stripe_payment_intent_id=payment_intent.id,
            settled_at=settled_at,
        )
        await invoice_service.write_mandate_audit(
            session=session,
            session_id=invoice.session_id,
            agent_id=invoice.agent_id,
            mandate_jwt_hash=mandate_jwt_hash,
            settlement_timestamp=settled_at,
        )

    await session.commit()

    logger.info(
        "settlement_success",
        extra={
            "event": "settlement_success",
            "session_id": str(invoice.session_id),
            "stripe_payment_intent_id": payment_intent.id,
        },
    )

    return CompleteResponse(
        session_id=invoice.session_id,
        stripe_payment_intent_id=payment_intent.id,
        status="settled",
        settled_at=settled_at,
    )
