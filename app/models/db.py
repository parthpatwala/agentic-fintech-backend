import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    UUID,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    items: Mapped[dict] = mapped_column(JSONB, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    mandate_audits: Mapped[list["MandateAudit"]] = relationship(
        back_populates="invoice"
    )

    __table_args__ = (Index("ix_invoices_status", "status"),)


class MandateAudit(Base):
    __tablename__ = "mandate_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.session_id", name="fk_mandate_audit_session_id"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    mandate_jwt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    settlement_timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    invoice: Mapped["Invoice"] = relationship(back_populates="mandate_audits")

    __table_args__ = (Index("ix_mandate_audit_session_id", "session_id"),)
