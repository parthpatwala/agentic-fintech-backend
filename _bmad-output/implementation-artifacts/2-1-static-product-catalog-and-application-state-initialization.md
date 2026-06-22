---
baseline_commit: 987362200ee58449e87d3720b346afe8dcb21fdf
---

# Story 2.1: Static Product Catalog & Application State Initialization

Status: done

## Story

As a UCP-compliant AI Agent,
I want the server to load its product catalog and cryptographic identity at startup,
So that both are available instantly on every discovery request without per-request disk I/O.

## Acceptance Criteria

**Given** `catalog/products.json` contains at least one product with `id`, `name`, `price` (float), and `currency` (ISO 4217) fields
**And** `PUBLIC_KEY_PATH` points to a valid Ed25519 public key PEM file
**When** the app starts via its lifespan handler
**Then** `app.state.catalog` is a non-empty list of validated `ProductItem` objects
**And** `app.state.jwk` is a dict with keys `kty: "OKP"`, `crv: "Ed25519"`, and `x` (base64url-encoded string)
**And** `app.state.public_key` holds the loaded `Ed25519PublicKey` object ready for JWT verification

**Given** `catalog/products.json` contains exactly 5 items
**When** the lifespan handler completes
**Then** `len(app.state.catalog) == 5`

**Given** `catalog/products.json` is malformed JSON
**When** the app attempts to start
**Then** a JSON parse error is raised and the process exits with a non-zero code

**And** the initial `catalog/products.json` committed to the repo includes these 5 items:
- `prod_001`: Wireless Headphones, $79.99 USD
- `prod_002`: Mechanical Keyboard, $129.99 USD
- `prod_003`: USB-C Hub, $49.99 USD
- `prod_004`: HD Webcam, $89.99 USD
- `prod_005`: Desk Lamp LED, $34.99 USD

## Tasks / Subtasks

- [x] Task 1: Create `catalog/products.json` (AC: all)
  - [x] Remove `.gitkeep` from `catalog/`; create `catalog/products.json` with the 5 canonical products
  - [x] Validate manually that `python3 -c "import json; json.load(open('catalog/products.json'))"` succeeds

- [x] Task 2: Create `app/models/schemas.py` — Pydantic request/response models (AC: all)
  - [x] `ProductItem(BaseModel)`: `id: str`, `name: str`, `price: float`, `currency: str`
  - [x] `JWK(BaseModel)`: `kty: Literal["OKP"]`, `crv: Literal["Ed25519"]`, `x: str`
  - [x] `UCPRoutes(BaseModel)`: `checkout: str`, `complete: str`
  - [x] `UCPProfile(BaseModel)`: `version: Literal["2026-04-08"]`, `capabilities: list[str]`, `routes: UCPRoutes`, `signing_keys: list[JWK]`, `catalog: list[ProductItem]`
  - [x] `UCPDiscoveryProfile(BaseModel)`: `ucp: UCPProfile`

- [x] Task 3: Create `app/services/crypto.py` — Ed25519 key utilities (AC: JWK)
  - [x] `load_public_key(key_bytes: bytes) -> Ed25519PublicKey` — calls `load_pem_public_key`; raises `TypeError` if key is not Ed25519
  - [x] `derive_jwk(public_key: Ed25519PublicKey) -> dict[str, str]` — exports raw 32-byte public key material; base64url-encodes without padding; returns `{"kty": "OKP", "crv": "Ed25519", "x": <str>}`
  - [x] Add placeholder stub `verify_mandate` (Story 3.1 will implement): `def verify_mandate(...): raise NotImplementedError`
  - [x] No PyJWT import yet — Story 3.1 adds that

- [x] Task 4: Update `app/config.py` — add `catalog_path` setting (AC: all)
  - [x] Add `catalog_path: str = "catalog/products.json"` field to `Settings`

- [x] Task 5: Extend `app/main.py` lifespan — catalog load + JWK derivation (AC: all)
  - [x] Import `json`, `app.services.crypto as crypto`, and update existing imports
  - [x] After storing `app.state.public_key_bytes`: call `app.state.public_key = crypto.load_public_key(app.state.public_key_bytes)`
  - [x] Call `app.state.jwk = crypto.derive_jwk(app.state.public_key)` immediately after
  - [x] Load catalog: open `settings.catalog_path`, call `json.load(f)`, validate each item via `ProductItem.model_validate(item)` → store `app.state.catalog`
  - [x] Wrap catalog load in `try/except (json.JSONDecodeError, FileNotFoundError, PermissionError)` with clear error messages including the path
  - [x] Raise `ValueError` if `app.state.catalog` is empty (0-length list after load)
  - [x] Log `"Catalog loaded"` at INFO with `event: "startup"`, `count: len(app.state.catalog)`
  - [x] Log `"JWK derived"` at INFO with `event: "startup"`
  - [x] Insert catalog + JWK steps BEFORE the DB engine initialization (items 2–3 in lifespan, after key bytes load)

- [x] Task 6: Update test isolation fixtures (AC: none — test infrastructure)
  - [x] Update `tests/test_health.py` `mock_startup_dependencies` fixture: add mocks for `app.main.crypto.load_public_key` and `app.main.crypto.derive_jwk`; extend `mock_open` OR mock `json.load` to also handle the catalog file read
  - [x] Update `tests/test_startup.py`: add `crypto.load_public_key` and `crypto.derive_jwk` mocks to any test that exercises the lifespan past the key-bytes step
  - [x] Ensure `uv run ruff check .` and `uv run pytest -v` both pass with zero failures after changes

### Review Findings (2026-06-22)

- [x] [Review][Patch] Uncaught `pydantic.ValidationError` and non-list JSON root crash startup without path context [main.py:85-90]
- [x] [Review][Patch] `crypto.load_public_key()` call in lifespan has no try/except — `ValueError`/`TypeError` propagates without startup message [main.py:77]
- [x] [Review][Patch] Catalog file opened without `encoding="utf-8"` — `UnicodeDecodeError` on non-UTF-8 systems [main.py:83]
- [x] [Review][Patch] `load_public_key` docstring claims "Raises `TypeError`" only — `ValueError` also propagated [crypto.py:12-14]
- [x] [Review][Patch] No test for non-Ed25519 PEM (RSA/ECDSA) triggering the `isinstance` guard [test_state_init.py]
- [x] [Review][Defer] `price: float` vs `Decimal` — architecture explicitly defines float; prototype scope
- [x] [Review][Defer] ISO 4217 currency not validated on `ProductItem` — hardcoded catalog has valid currencies; prototype scope
- [x] [Review][Defer] Empty `signing_keys: list[JWK]` allowed — Story 2.2 concern
- [x] [Review][Defer] Duplicate product `id` values load without error — hardcoded catalog; prototype scope
- [x] [Review][Defer] `app.state.catalog` is a mutable list — prototype scope
- [x] [Review][Defer] `IsADirectoryError` / other `OSError` not caught — rare edge; prototype scope
- [x] [Review][Defer] Malformed-JSON test doesn't verify process exit code — same as Story 1.4 deferred pattern
- [x] [Review][Defer] Relative `catalog_path` depends on process CWD — same pattern as `public_key_path`

- [x] Task 7: Write `tests/test_state_init.py` — startup state unit tests (AC: all ACs)
  - [x] Generate a real in-memory Ed25519 key pair in a pytest fixture (use `cryptography` — no file I/O)
  - [x] `test_load_public_key_returns_ed25519_key` — passes real PEM bytes; asserts return is `Ed25519PublicKey`
  - [x] `test_load_public_key_raises_on_invalid_bytes` — passes garbage bytes; asserts `ValueError` is raised
  - [x] `test_derive_jwk_has_correct_shape` — calls `derive_jwk` on a real key; asserts `kty == "OKP"`, `crv == "Ed25519"`, `x` is non-empty string
  - [x] `test_derive_jwk_x_is_base64url` — verifies `x` contains no `+` or `/` characters and no `=` padding (urlsafe, unpadded)
  - [x] `test_catalog_loaded_into_app_state` — exercises lifespan with real `catalog/products.json` bytes via `mock_open`; asserts `app.state.catalog` is a list of 5 `ProductItem` objects
  - [x] `test_catalog_item_fields` — asserts first catalog item has `id`, `name`, `price`, `currency` attributes
  - [x] `test_startup_malformed_catalog_raises` — passes `b"not-json"` for catalog file; asserts `json.JSONDecodeError` propagates from lifespan

## Dev Notes

### What this story does and does NOT do

**Story 2.1 scope (do now):**
- Create `catalog/products.json` with the 5 canonical products
- Create `app/models/schemas.py` with all Pydantic models defined (not just catalog ones — include `UCPDiscoveryProfile` too, even though the endpoint is Story 2.2, so the schema is ready)
- Create `app/services/crypto.py` with `load_public_key` and `derive_jwk` only
- Extend `app/main.py` lifespan to populate `app.state.public_key`, `app.state.jwk`, `app.state.catalog`

**Story 2.1 does NOT do:**
- `GET /.well-known/ucp` endpoint — that is Story 2.2
- `app/routers/discovery.py` — Story 2.2
- `verify_mandate()` implementation in `crypto.py` — Story 3.1 (add stub only)
- Any checkout or settlement routes

### Critical: lifespan order

The new steps slot in between key-bytes loading and DB init. Final lifespan order after this story:

```
1. _configure_logging()
2. settings = Settings()  [config validation]
3. Load public_key_bytes from settings.public_key_path → app.state.public_key_bytes
4. [NEW] crypto.load_public_key(app.state.public_key_bytes) → app.state.public_key
5. [NEW] crypto.derive_jwk(app.state.public_key) → app.state.jwk
6. [NEW] Load catalog/products.json → app.state.catalog (list of ProductItem)
7. db_session.init_engine(settings.database_url) + check_db_connectivity()
8. yield  [app live]
9. await db_session.dispose_engine()
```

### crypto.py implementation pattern

```python
# app/services/crypto.py
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key

def load_public_key(key_bytes: bytes) -> Ed25519PublicKey:
    key = load_pem_public_key(key_bytes)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError(f"Expected Ed25519PublicKey, got {type(key).__name__}")
    return key

def derive_jwk(public_key: Ed25519PublicKey) -> dict[str, str]:
    raw = public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return {"kty": "OKP", "crv": "Ed25519", "x": x}
```

### Key files updated in this story

| File | Action | Notes |
|---|---|---|
| `catalog/products.json` | CREATE | 5 canonical products; replaces `.gitkeep` |
| `app/models/schemas.py` | CREATE | All Pydantic models: `ProductItem`, `JWK`, `UCPRoutes`, `UCPProfile`, `UCPDiscoveryProfile` |
| `app/services/crypto.py` | CREATE | `load_public_key`, `derive_jwk`; stub for `verify_mandate` |
| `app/config.py` | UPDATE | Add `catalog_path: str = "catalog/products.json"` |
| `app/main.py` | UPDATE | Extend lifespan with steps 4–6 (key object, JWK, catalog) |
| `tests/test_health.py` | UPDATE | Extend `mock_startup_dependencies` fixture |
| `tests/test_startup.py` | UPDATE | Extend `test_startup_db_unreachable_raises` fixture; add `test_settings_catalog_path_default` |
| `tests/test_state_init.py` | CREATE | 11 unit tests for `crypto.py` and lifespan catalog loading |

### References

- [Source: architecture.md#Component Boundaries] — `app/services/crypto.py` owns all `cryptography` and PyJWT calls
- [Source: architecture.md#Updated Pydantic Models] — canonical Pydantic model definitions for `ProductItem`, `JWK`, `UCPProfile`, `UCPDiscoveryProfile`
- [Source: architecture.md#Data Flow] — catalog loaded once at startup, served inline in discovery
- [Source: architecture.md#Authentication & Security] — key loaded at startup, never re-read per request
- [Source: epics.md#Story 2.1] — full ACs and the 5 canonical product items with exact prices
- [Source: epics.md#Story 2.2] — dependency: `app.state.catalog` and `app.state.jwk` populated here so Story 2.2 can read them directly from `app.state`
- [RFC 8037] — JWK representation of Ed25519 keys: `kty: "OKP"`, `crv: "Ed25519"`, `x`: base64url-encoded raw public key bytes without padding

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-5

### Debug Log References

None — implementation completed cleanly in one pass.

### Completion Notes List

- Created `catalog/products.json` with 5 canonical products; removed `catalog/.gitkeep`
- Created `app/models/schemas.py` with `ProductItem`, `JWK`, `UCPRoutes`, `UCPProfile`, `UCPDiscoveryProfile` — all Pydantic v2 models using `Literal` types
- Created `app/services/crypto.py` with `load_public_key` (PEM→Ed25519PublicKey), `derive_jwk` (RFC 8037 base64url JWK), and `verify_mandate` stub
- Added `catalog_path: str = "catalog/products.json"` to `Settings` in `app/config.py`
- Extended `app/main.py` lifespan: steps 3→4 (load_public_key), 3→5 (derive_jwk), 3→6 (catalog load with FileNotFoundError, PermissionError, JSONDecodeError, and empty-list guards)
- Updated `tests/test_health.py` and `tests/test_startup.py` fixtures to mock `crypto.load_public_key`, `crypto.derive_jwk`, and `json.load` — all tests now fully isolated from disk/DB/crypto
- Created `tests/test_state_init.py` with 11 tests: 5 for `crypto.py` (real Ed25519 keys, RFC 8037 compliance) and 4 for lifespan state population + 2 for error paths
- 35/35 tests pass; ruff clean

### File List

- `catalog/products.json` (created)
- `app/models/schemas.py` (created)
- `app/services/crypto.py` (created)
- `app/config.py` (updated)
- `app/main.py` (updated)
- `tests/test_health.py` (updated)
- `tests/test_startup.py` (updated)
- `tests/test_state_init.py` (created)

### Change Log

- Story 2.1 implemented: product catalog + Ed25519/JWK application state initialization (2026-06-22)
