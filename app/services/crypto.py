import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_public_key,
)


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


def verify_mandate(*args: object, **kwargs: object) -> None:
    """Verify an AP2 Payment Mandate JWT. Implemented in Story 3.1."""
    raise NotImplementedError("verify_mandate is implemented in Story 3.1")
