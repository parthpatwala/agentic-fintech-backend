"""Tests for app/services/settlement.py — Story 4.1.

All tests mock stripe.PaymentIntent.create so no real Stripe network calls are made.
stripe.api_key does NOT need to be set for mocked tests.
"""

import inspect
from unittest.mock import MagicMock, patch

import pytest
import stripe

from app.services.settlement import create_payment_intent


@pytest.mark.asyncio
async def test_create_payment_intent_success() -> None:
    """Happy path: mocked Stripe returns a succeeded PaymentIntent."""
    mock_intent = MagicMock(spec=stripe.PaymentIntent)
    mock_intent.id = "pi_3TestSuccess"
    mock_intent.status = "succeeded"

    with patch("stripe.PaymentIntent.create", return_value=mock_intent) as mock_create:
        result = await create_payment_intent(amount=7999, currency="usd")

    assert result.id == "pi_3TestSuccess"
    assert result.status == "succeeded"
    mock_create.assert_called_once_with(
        amount=7999,
        currency="usd",
        payment_method="pm_card_visa",
        confirm=True,
        payment_method_types=["card"],
    )


@pytest.mark.asyncio
async def test_create_payment_intent_stripe_error_propagates() -> None:
    """StripeError from SDK propagates unchanged — not caught in the service."""
    with patch(
        "stripe.PaymentIntent.create",
        side_effect=stripe.error.StripeError("Stripe test error"),
    ):
        with pytest.raises(stripe.error.StripeError, match="Stripe test error"):
            await create_payment_intent(amount=7999, currency="usd")


@pytest.mark.asyncio
async def test_create_payment_intent_amount_passed_as_cents() -> None:
    """Verify the exact amount integer is passed to Stripe SDK unchanged."""
    mock_intent = MagicMock(spec=stripe.PaymentIntent)
    mock_intent.id = "pi_test"
    mock_intent.status = "succeeded"

    with patch("stripe.PaymentIntent.create", return_value=mock_intent) as mock_create:
        await create_payment_intent(amount=12999, currency="usd")

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["amount"] == 12999


@pytest.mark.asyncio
async def test_create_payment_intent_card_error_propagates() -> None:
    """CardError (StripeError subclass) also propagates unchanged."""
    with patch(
        "stripe.PaymentIntent.create",
        side_effect=stripe.error.CardError(
            "Card declined", param=None, code="card_declined"
        ),
    ):
        with pytest.raises(stripe.error.CardError):
            await create_payment_intent(amount=4999, currency="usd")


@pytest.mark.asyncio
async def test_create_payment_intent_uses_pm_card_visa() -> None:
    """pm_card_visa test payment method is always used — never real card data."""
    mock_intent = MagicMock(spec=stripe.PaymentIntent)
    mock_intent.id = "pi_test"
    mock_intent.status = "succeeded"

    with patch("stripe.PaymentIntent.create", return_value=mock_intent) as mock_create:
        await create_payment_intent(amount=7999, currency="usd")

    assert mock_create.call_args.kwargs["payment_method"] == "pm_card_visa"


def test_create_payment_intent_no_db_writes() -> None:
    """Settlement service imports no SQLAlchemy — no DB access possible."""
    import app.services.settlement as settlement_module

    source = inspect.getsource(settlement_module)
    assert "sqlalchemy" not in source.lower()
    assert "AsyncSession" not in source
    assert "session" not in source.lower()
