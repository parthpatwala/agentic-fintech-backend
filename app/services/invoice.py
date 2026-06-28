import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Invoice, MandateAudit


async def create_invoice(
    session: AsyncSession,
    session_id: uuid.UUID,
    agent_id: str,
    items: list[dict],
    total_amount: Decimal,
    currency: str,
) -> Invoice:
    """Insert a new invoice with status='pending'. Caller owns the transaction.

    Raises sqlalchemy.exc.IntegrityError if session_id already exists (PK violation).
    """
    invoice = Invoice(
        session_id=session_id,
        agent_id=agent_id,
        items=items,
        total_amount=total_amount,
        currency=currency,
        status="pending",
    )
    session.add(invoice)
    await session.flush()
    return invoice


async def get_invoice(
    session: AsyncSession,
    session_id: uuid.UUID,
) -> Invoice | None:
    """Fetch an invoice by session_id. Returns None if not found."""
    result = await session.execute(
        select(Invoice).where(Invoice.session_id == session_id)
    )
    return result.scalar_one_or_none()


async def settle_invoice(
    session: AsyncSession,
    invoice: Invoice,
    stripe_payment_intent_id: str,
    settled_at: datetime,
) -> Invoice:
    """Mark invoice settled. Caller owns the transaction."""
    invoice.status = "settled"
    invoice.stripe_payment_intent_id = stripe_payment_intent_id
    invoice.settled_at = settled_at
    await session.flush()
    return invoice


async def write_mandate_audit(
    session: AsyncSession,
    session_id: uuid.UUID,
    agent_id: str,
    mandate_jwt_hash: str,
    settlement_timestamp: datetime,
) -> MandateAudit:
    """Insert mandate_audit row. Caller owns the transaction."""
    audit = MandateAudit(
        session_id=session_id,
        agent_id=agent_id,
        mandate_jwt_hash=mandate_jwt_hash,
        settlement_timestamp=settlement_timestamp,
    )
    session.add(audit)
    await session.flush()
    return audit
