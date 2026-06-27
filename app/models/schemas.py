from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_VALID_ISO_4217 = frozenset({
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY",
    "INR", "SGD", "MXN", "BRL", "KRW", "ZAR", "HKD", "SEK",
    "NOK", "DKK", "NZD", "PLN",
})


class ProductItem(BaseModel):
    id: str
    name: str
    price: float
    currency: str


class JWK(BaseModel):
    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: str


class UCPRoutes(BaseModel):
    checkout: str
    complete: str


class UCPProfile(BaseModel):
    version: Literal["2026-04-08"]
    capabilities: list[str]
    routes: UCPRoutes
    signing_keys: list[JWK]
    catalog: list[ProductItem]


class UCPDiscoveryProfile(BaseModel):
    ucp: UCPProfile


class LineItem(BaseModel):
    name: str
    quantity: int = Field(..., ge=1)
    unit_price: float = Field(..., gt=0)


class CheckoutRequest(BaseModel):
    session_id: UUID
    agent_id: str = Field(..., min_length=1)
    currency: str
    items: list[LineItem] = Field(..., min_length=1)

    @field_validator("currency")
    @classmethod
    def currency_must_be_iso4217(cls, v: str) -> str:
        if v not in _VALID_ISO_4217:
            raise ValueError(f"currency '{v}' is not a supported ISO 4217 code")
        return v


class CheckoutContext(BaseModel):
    session_id: UUID
    total_amount: float
    currency: str
    server_timestamp: datetime


class CheckoutResponse(BaseModel):
    session_token: str
    checkout_context: CheckoutContext


class CompleteRequest(BaseModel):
    payment_mandate: str = Field(..., max_length=8192)  # JWT string (EdDSA-signed)


class PaymentMandatePayload(BaseModel):
    session_id: UUID
    amount: float = Field(..., gt=0)
    currency: str = Field(..., min_length=1)
    agent_id: str
