import base64

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_public_key,
)


class MandateVerificationError(Exception):
    """Raised by verify_mandate on any JWT validation failure.

    Wraps jwt.exceptions.PyJWTError so callers never need to import PyJWT.
    """


def load_public_key(key_bytes: bytes) -> Ed25519PublicKey:
    """Load an Ed25519 public key from PEM bytes.

    Raises ValueError if the bytes are not a valid PEM-encoded key.
    Raises TypeError if the key is valid PEM but not an Ed25519 key.
    """
    key = load_pem_public_key(key_bytes)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError(f"Expected Ed25519PublicKey, got {type(key).__name__}")
    return key


def derive_jwk(public_key: Ed25519PublicKey) -> dict[str, str]:
    """Derive a JWK (RFC 8037) dict from an Ed25519 public key.

    The 'x' field is the raw 32-byte key material encoded as base64url without padding.
    """
    raw = public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return {"kty": "OKP", "crv": "Ed25519", "x": x}


def verify_mandate(token: str, public_key: Ed25519PublicKey) -> dict[str, object]:
    """Verify an AP2 Payment Mandate JWT using EdDSA.

    Returns the decoded payload dict if the signature is valid and exp is present.
    Raises MandateVerificationError for any JWT validation failure: invalid
    signature, algorithm confusion, missing or expired exp claim.
    """
    try:
        return jwt.decode(
            token,
            public_key,
            algorithms=["EdDSA"],
            options={"require": ["exp"]},
        )
    except jwt.exceptions.PyJWTError as exc:
        raise MandateVerificationError(str(exc)) from exc
