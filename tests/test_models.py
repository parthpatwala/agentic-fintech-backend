"""Tests for ORM model definitions (Story 1.3)."""

import uuid

from sqlalchemy import inspect

from app.models.db import Base, Invoice, MandateAudit


def test_invoice_table_name() -> None:
    assert Invoice.__tablename__ == "invoices"


def test_mandate_audit_table_name() -> None:
    assert MandateAudit.__tablename__ == "mandate_audit"


def test_invoice_columns_exist() -> None:
    mapper = inspect(Invoice)
    column_names = {col.key for col in mapper.columns}
    expected = {
        "session_id",
        "agent_id",
        "items",
        "total_amount",
        "currency",
        "status",
        "stripe_payment_intent_id",
        "created_at",
        "settled_at",
    }
    assert expected == column_names


def test_mandate_audit_columns_exist() -> None:
    mapper = inspect(MandateAudit)
    column_names = {col.key for col in mapper.columns}
    expected = {
        "id",
        "session_id",
        "agent_id",
        "mandate_jwt_hash",
        "settlement_timestamp",
    }
    assert expected == column_names


def test_invoice_primary_key_is_session_id() -> None:
    mapper = inspect(Invoice)
    pk_cols = [col.key for col in mapper.primary_key]
    assert pk_cols == ["session_id"]


def test_mandate_audit_primary_key_is_id() -> None:
    mapper = inspect(MandateAudit)
    pk_cols = [col.key for col in mapper.primary_key]
    assert pk_cols == ["id"]


def test_base_metadata_has_both_tables() -> None:
    table_names = set(Base.metadata.tables.keys())
    assert "invoices" in table_names
    assert "mandate_audit" in table_names


def test_invoice_session_id_is_uuid_type() -> None:
    col = Invoice.__table__.c["session_id"]
    assert col.type.__class__.__name__ == "UUID"


def test_invoice_items_is_jsonb() -> None:
    col = Invoice.__table__.c["items"]
    assert col.type.__class__.__name__ == "JSONB"


def test_invoice_status_default() -> None:
    col = Invoice.__table__.c["status"]
    assert col.default is not None or col.server_default is not None


def test_mandate_audit_fk_references_invoices() -> None:
    fk_cols = list(MandateAudit.__table__.c["session_id"].foreign_keys)
    assert len(fk_cols) == 1
    fk = fk_cols[0]
    assert fk.column.table.name == "invoices"
    assert fk.name == "fk_mandate_audit_session_id"


def test_invoice_relationship_to_mandate_audits() -> None:
    assert hasattr(Invoice, "mandate_audits")


def test_mandate_audit_relationship_to_invoice() -> None:
    assert hasattr(MandateAudit, "invoice")


def test_invoice_can_be_instantiated() -> None:
    from decimal import Decimal

    inv = Invoice(
        session_id=uuid.uuid4(),
        agent_id="agent-001",
        items=[{"name": "Widget", "quantity": 1, "unit_price": 9.99}],
        total_amount=Decimal("9.99"),
        currency="USD",
        status="pending",
    )
    assert inv.status == "pending"
    assert inv.stripe_payment_intent_id is None
    assert inv.settled_at is None
