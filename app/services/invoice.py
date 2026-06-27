import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Invoice


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
