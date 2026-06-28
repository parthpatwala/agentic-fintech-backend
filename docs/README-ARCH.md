# Backend Architecture Runbook

Developer integration guide for reviewers and incoming maintainers. Covers typing strategy, cryptographic design, and how tests simulate agent interactions without Google's reference SDK.

For onboarding and the execution playbook, see the root [README.md](../README.md). For protocol diagrams, see [architecture/diagrams.md](architecture/diagrams.md).

---

## Type Strategy Rationale

This codebase uses a **dual typing pattern** — strict Pydantic models for domain data, plain dicts for cryptographic primitives at the state layer.

### 1. `list[ProductItem]` for catalog

**Where:** `app/models/schemas.py`, loaded in `app/main.py` lifespan

- Catalog JSON from `catalog/products.json` is validated at startup via `ProductItem.model_validate()`
- Strict fields: `id`, `name`, `price`, `currency` — malformed catalog fails before serving traffic
- Served inline in UCP discovery response as a typed catalog array
- **Why strict:** catalog is business data consumed by agents; validation errors must fail fast at boot

### 2. `dict[str, str]` for JWK in `app.state.jwk`

**Where:** `crypto.derive_jwk()` return type, stored in lifespan at `app/main.py:98`

- JWK is a **cryptographic primitive map** (`kty`, `crv`, `x`) per RFC 8037
- Stored as plain dict in `app.state` after derivation — no nested Pydantic object in state
- Discovery handler wraps with `JWK.model_validate(request.app.state.jwk)` only at the response boundary (`app/routers/discovery.py:30`)
- **Why dict at state layer:** avoids coupling lifespan/crypto layer to FastAPI/Pydantic response models; `derive_jwk()` is a pure crypto utility returning RFC-shaped data
- **Contrast:** `ProductItem` is domain catalog data; JWK dict is encoding output from `cryptography` key material

**Code references:**

- `app/services/crypto.py:31-38` — `derive_jwk()`
- `app/main.py:98` — `app.state.jwk = crypto.derive_jwk(...)`
- `app/routers/discovery.py:30` — `JWK.model_validate(request.app.state.jwk)`

---

## Cryptographic Blueprint

### JWK derivation (`derive_jwk`)

Ed25519 public key material is encoded as RFC 8037 JWK:

```python
raw = public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
return {"kty": "OKP", "crv": "Ed25519", "x": x}
```

**Rules:**

- Ed25519 raw public key is **32 bytes**
- RFC 8037 JWK `x` uses **base64url encoding without padding** (`rstrip(b"=")`)
- Tests enforce: no `+`, `/`, or `=` in `x` (`tests/test_state_init.py::test_derive_jwk_x_is_base64url`)
- 32 bytes → 43 base64url characters (no padding)

### Mandate signing (agent client)

```python
payload = {
    "session_id": session_id,
    "amount": amount,
    "currency": currency,
    "agent_id": agent_id,
    "exp": int(time.time()) + 300,
}
jwt.encode(payload, private_key, algorithm="EdDSA")
```

Private key loaded via `cryptography.hazmat.primitives.serialization.load_pem_private_key`.

### Mandate verification (server)

```python
jwt.decode(
    token,
    public_key,
    algorithms=["EdDSA"],
    options={"require": ["exp"]},
)
```

Called from `crypto.verify_mandate()` — routers never import PyJWT directly. The `ap2_mandate` FastAPI Dependency (`app/dependencies.py`) orchestrates format check → verify → `PaymentMandatePayload` validation.

### Key separation

- Server reads `public_key.pem` only — never `private_key.pem`
- `scripts/agent_client.py` reads `private_key.pem` only — never server verification logic
- Unit tests use ephemeral keys from `tests/conftest.py` — no dependency on `keys/` directory

---

## Testing Mechanics

### Isolated cryptographic test loop

**1. `tests/conftest.py::ed25519_key_pair` fixture**

- Generates ephemeral Ed25519 key pair **per test function** (default pytest fixture scope)
- No dependency on `keys/` directory for unit tests
- Returns `(private_key, public_key, public_pem_bytes)`

**2. `tests/test_state_init.py`**

- Unit tests for `load_public_key()` and `derive_jwk()` against fixture keys
- Lifespan catalog loading tests with mocked file I/O and patched `derive_jwk`
- Validates JWK shape matches what discovery serves
- Proves base64url compliance independent of live server

**3. `scripts/agent_client.py`**

- Standalone script — **never imports `app/`**
- Loads `keys/private_key.pem` from disk at signing step (local dev/demo)
- Signs mandate with same EdDSA algorithm as tests
- Full HTTP loop against running server simulates Google-compliant agent behavior
- `AGENT_ID = "agent-client-demo"` — constant agent identifier in mandates

**4. Integration vs unit split**

- Router tests: ASGITransport + mocked DB/Stripe (`test_complete.py`, `test_crypto.py`)
- DB integration: real Postgres via `TEST_DATABASE_URL` (`test_db_integration.py`)
- Crypto path coverage: FR-16 cases in `test_crypto.py` including mandate rejection logs

### Narrative

Tests and the agent client together demonstrate the full handshake → sign → verify → settle loop without requiring Google's reference SDK — aligned with AP2 intent but prototype-scoped.

---

## Prototype Limitations

Deferred features include full CartMandate, MCP transport, and production hardening. This runbook documents **as-built** prototype behavior only.
