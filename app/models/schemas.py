from typing import Literal

from pydantic import BaseModel


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
