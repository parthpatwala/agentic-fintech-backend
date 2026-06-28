import asyncio

import stripe


async def create_payment_intent(amount: int, currency: str) -> stripe.PaymentIntent:
    """Create a Stripe Sandbox PaymentIntent using the pm_card_visa test method.

    Args:
        amount: Amount in minor currency units (cents). E.g. $79.99 → 7999.
        currency: Lowercase ISO 4217 currency code (e.g. "usd").

    Returns:
        stripe.PaymentIntent with status="succeeded" and a non-empty id.

    Raises:
        stripe.error.StripeError: Any Stripe SDK exception — propagates unchanged.
            The caller (route handler in Story 4.2) maps this to HTTP 502.
    """
    return await asyncio.to_thread(
        stripe.PaymentIntent.create,
        amount=amount,
        currency=currency,
        payment_method="pm_card_visa",
        confirm=True,
        payment_method_types=["card"],
    )
