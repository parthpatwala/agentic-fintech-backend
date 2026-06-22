---
baseline_commit: 9873622
---

# Story 2.2: UCP Discovery Profile Endpoint

Status: done

## Story

As a UCP-compliant AI Agent,
I want to call `GET /.well-known/ucp` without any authentication and receive a complete machine-readable profile,
So that I can autonomously determine what this server supports and how to interact with it before initiating any commerce flow.

## Acceptance Criteria

**Given** the app is running with a valid catalog and public key loaded in `app.state`
**When** `GET /.well-known/ucp` is called without any authentication headers
**Then** the response is HTTP 200 with `Content-Type: application/json`
**And** `response.json()["ucp"]["version"] == "2026-04-08"`
**And** `response.json()["ucp"]["capabilities"]` contains both `"dev.ucp.shopping.checkout"` and `"dev.ucp.shopping.ap2_mandate"`
**And** `response.json()["ucp"]["routes"]["checkout"] == "/api/checkout"`
**And** `response.json()["ucp"]["routes"]["complete"] == "/api/complete"`
**And** `response.json()["ucp"]["signing_keys"]` is a non-empty list where `signing_keys[0]["kty"] == "OKP"` and `signing_keys[0]["crv"] == "Ed25519"` and `signing_keys[0]["x"]` is a non-empty string
**And** `response.json()["ucp"]["catalog"]` is a list of length 5 where each item has `id`, `name`, `price`, and `currency` fields

## Tasks / Subtasks

- [x] Task 1: Create `app/routers/discovery.py` — the UCP endpoint (AC: all)
  - [x] Define `UCP_VERSION = "2026-04-08"` and `SUPPORTED_CAPABILITIES` constants at module level
  - [x] Implement `GET /.well-known/ucp` handler reading `request.app.state.catalog` and `request.app.state.jwk`
  - [x] Construct and return `UCPDiscoveryProfile` using all imported Pydantic models from `app.models.schemas`
  - [x] Call `JWK.model_validate(request.app.state.jwk)` to coerce the dict to a typed model

- [x] Task 2: Register the router in `app/main.py` (AC: all)
  - [x] Import `from app.routers import discovery` at the top of `app/main.py`
  - [x] Call `app.include_router(discovery.router)` immediately after the `app = FastAPI(...)` line

- [x] Task 3: Write `tests/test_discovery.py` — UCP endpoint tests (AC: all ACs)
  - [x] Create `_FAKE_CATALOG` with 5 items mirroring `catalog/products.json` so catalog-count assertion passes
  - [x] Create `setup_app_state` autouse fixture that directly sets `app.state.jwk` and `app.state.catalog` (ASGITransport in httpx 0.28+ does not run the lifespan, so state must be injected manually)
  - [x] `test_ucp_returns_200` — GET `/.well-known/ucp` → status 200
  - [x] `test_ucp_version` — `ucp.version == "2026-04-08"`
  - [x] `test_ucp_capabilities_contains_checkout` — `"dev.ucp.shopping.checkout"` in capabilities
  - [x] `test_ucp_capabilities_contains_ap2_mandate` — `"dev.ucp.shopping.ap2_mandate"` in capabilities
  - [x] `test_ucp_route_checkout` — `ucp.routes.checkout == "/api/checkout"`
  - [x] `test_ucp_route_complete` — `ucp.routes.complete == "/api/complete"`
  - [x] `test_ucp_signing_keys_shape` — `signing_keys[0].kty == "OKP"`, `crv == "Ed25519"`, `x` is non-empty string
  - [x] `test_ucp_catalog_count` — `len(ucp.catalog) == 5`
  - [x] `test_ucp_catalog_item_fields` — first item has `id`, `name`, `price`, `currency` attributes
  - [x] `test_ucp_no_auth_required` — calling without `Authorization` header still returns 200

### Review Findings (2026-06-22)

- [x] [Review][Patch] `SUPPORTED_CAPABILITIES` defined as mutable list — should be tuple [discovery.py:8-11]
- [x] [Review][Patch] `test_ucp_no_auth_required` duplicates `test_ucp_returns_200` — test should send an auth header and assert 200 is still returned [test_discovery.py:123-130]
- [x] [Review][Patch] Magic number `5` hardcoded in `test_ucp_catalog_count` — use `len(_FAKE_CATALOG)` [test_discovery.py:112]
- [x] [Review][Patch] Fixture accesses private Starlette internal `app.state._state` — use `del app.state.jwk; del app.state.catalog` instead [test_discovery.py:28-35]
- [x] [Review][Defer] Unguarded `app.state.jwk`/`catalog` at request time — startup invariant; app cannot serve requests if lifespan failed [discovery.py:26-27]
- [x] [Review][Defer] `exc.doc` in JSONDecodeError re-raise exposes full file content — catalog not sensitive; pre-existing Story 2.1 pattern [main.py:101-106]
- [x] [Review][Defer] `IsADirectoryError`/`UnicodeDecodeError` not caught for catalog path — pre-existing Story 2.1 deferred item [main.py:91]
- [x] [Review][Defer] No Cache-Control headers on discovery response — out of Story 2.2 scope
- [x] [Review][Defer] `crypto.derive_jwk()` can raise unexpected exception type — pre-existing Story 2.1 deferred pattern [main.py:86]
- [x] [Review][Defer] `_FAKE_JWK.x = "fake_x"` not valid base64url 32-byte key — isolation test; crypto correctness tested in test_state_init.py [test_discovery.py:22]
- [x] [Review][Defer] No test for missing-state path — startup invariant; lifespan guarantees state is set if app serves requests [test_discovery.py]

## Dev Notes

### What this story does and does NOT do

**Story 2.2 scope (do now):**
- Create `app/routers/discovery.py` with the single `GET /.well-known/ucp` route
- Register the router in `app/main.py`
- Write `tests/test_discovery.py` covering all FR-1 + FR-2 ACs

**Story 2.2 does NOT do:**
- Any authentication or authorization logic (endpoint is public by spec)
- Any DB access or Stripe calls
- Any cryptographic operations — key was already loaded in Story 2.1; just read `app.state.jwk`
- `POST /api/checkout` or `POST /api/complete` — those are Epics 3 and 4
- No runtime catalog writes — `app.state.catalog` is read-only here

### Critical: app.state values available from Story 2.1

The following are guaranteed to be set by the lifespan after Story 2.1:

| `app.state` attribute | Type | Source |
|---|---|---|
| `app.state.catalog` | `list[ProductItem]` | Loaded from `catalog/products.json` |
| `app.state.jwk` | `dict[str, str]` | Derived by `crypto.derive_jwk()` — keys: `kty`, `crv`, `x` |
| `app.state.public_key` | `Ed25519PublicKey` | Loaded by `crypto.load_public_key()` — NOT used in this story |

### Exact implementation pattern for `app/routers/discovery.py`

```python
from fastapi import APIRouter, Request

from app.models.schemas import JWK, UCPDiscoveryProfile, UCPProfile, UCPRoutes

router = APIRouter()

UCP_VERSION = "2026-04-08"
SUPPORTED_CAPABILITIES = [
    "dev.ucp.shopping.checkout",
    "dev.ucp.shopping.ap2_mandate",
]


@router.get("/.well-known/ucp", response_model=UCPDiscoveryProfile)
def get_ucp_profile(request: Request) -> UCPDiscoveryProfile:
    return UCPDiscoveryProfile(
        ucp=UCPProfile(
            version=UCP_VERSION,
            capabilities=SUPPORTED_CAPABILITIES,
            routes=UCPRoutes(checkout="/api/checkout", complete="/api/complete"),
            signing_keys=[JWK.model_validate(request.app.state.jwk)],
            catalog=request.app.state.catalog,
        )
    )
```

- Endpoint is **synchronous** — no I/O, all in-memory from `app.state`; FastAPI handles sync routes fine
- `JWK.model_validate(request.app.state.jwk)` coerces the raw dict to the typed `JWK` model; this will raise `ValidationError` at runtime only if `derive_jwk()` produced bad output (impossible by construction, but validates the shape)
- Do NOT import `cryptography` or `PyJWT` in this file — that violates the architecture boundary
- Do NOT access `request.app.state.public_key` — not needed here
- Routes `/api/checkout` and `/api/complete` are hardcoded strings — they match the architecture's canonical endpoint paths

### Router registration in `app/main.py`

Add these two lines to `app/main.py` after the existing imports and before the `app` definition:

```python
from app.routers import discovery        # ADD this import

# ...existing lifespan + app factory...

app = FastAPI(title="Agentic Fintech Backend", lifespan=lifespan)

app.include_router(discovery.router)     # ADD this line, immediately after app = FastAPI(...)
```

Do NOT add a `prefix` to `include_router` — the route path `/.well-known/ucp` is already absolute.

### Test isolation pattern for `tests/test_discovery.py`

Use the **identical pattern** to `tests/test_health.py`. The `mock_startup_dependencies` fixture mocks the lifespan so tests never need a real key file, catalog, or DB. Use a 5-item fake catalog so `test_ucp_catalog_count` asserts `len == 5`:

```python
_FAKE_CATALOG = [
    {"id": "prod_001", "name": "Wireless Headphones", "price": 79.99, "currency": "USD"},
    {"id": "prod_002", "name": "Mechanical Keyboard", "price": 129.99, "currency": "USD"},
    {"id": "prod_003", "name": "USB-C Hub", "price": 49.99, "currency": "USD"},
    {"id": "prod_004", "name": "HD Webcam", "price": 89.99, "currency": "USD"},
    {"id": "prod_005", "name": "Desk Lamp LED", "price": 34.99, "currency": "USD"},
]

@pytest.fixture(autouse=True)
def mock_startup_dependencies():
    mock_settings = MagicMock()
    mock_settings.database_url = "postgresql+asyncpg://user:pass@localhost/db"
    mock_settings.stripe_api_key = "sk_test_fake_key"
    mock_settings.public_key_path = "/fake/public_key.pem"
    mock_settings.catalog_path = "/fake/products.json"

    with (
        patch("app.main.Settings", return_value=mock_settings),
        patch("builtins.open", mock_open(read_data=b"fake-pem-bytes")),
        patch("app.main.crypto.load_public_key", return_value=MagicMock()),
        patch(
            "app.main.crypto.derive_jwk",
            return_value={"kty": "OKP", "crv": "Ed25519", "x": "fake_x"},
        ),
        patch("app.main.json.load", return_value=_FAKE_CATALOG),
        patch("app.db.session.init_engine"),
        patch("app.main.check_db_connectivity", new_callable=AsyncMock),
    ):
        yield
```

After this fixture runs, `app.state.catalog` will be a list of 5 `ProductItem` objects (because the lifespan code still calls `ProductItem.model_validate(item)` on the mocked data) and `app.state.jwk` will be `{"kty": "OKP", "crv": "Ed25519", "x": "fake_x"}`.

### Key files in this story

| File | Action | Notes |
|---|---|---|
| `app/routers/discovery.py` | CREATE | Single route; no DB, no crypto, no Stripe |
| `app/main.py` | UPDATE | Add `from app.routers import discovery` import + `app.include_router(discovery.router)` |
| `tests/test_discovery.py` | CREATE | 10 tests covering all FR-1 + FR-2 ACs |

`app/routers/__init__.py` already exists — no changes needed.

### Architecture compliance reminders

- **No PyJWT import** in `discovery.py` — architecture.md §Component Boundaries: "Crypto operations are centralized in `app/services/crypto.py`"
- **No DB access** in `discovery.py` — architecture.md §Component Boundaries: "All DB access goes through `app/services/invoice.py`"
- **Read-only access to `app.state`** — catalog was loaded once at startup by the lifespan; this router only reads it
- **`response_model=UCPDiscoveryProfile`** on the route decorator triggers automatic JSON serialization and OpenAPI schema generation
- **Sync handler** is correct — FastAPI runs sync route functions in a thread pool automatically; no async overhead needed for pure in-memory operations

### References

- [Source: epics.md#Story 2.2] — acceptance criteria (FR-1, FR-2)
- [Source: architecture.md#Component Boundaries] — `app/routers/discovery.py` owns UCP response; reads `app.state.catalog` + `app.state.jwk`; no DB, no Stripe, no crypto calls
- [Source: architecture.md#Naming Conventions] — `UCP_VERSION`, `SUPPORTED_CAPABILITIES` as module-level constants; endpoint `GET /.well-known/ucp` (no trailing slash)
- [Source: architecture.md#Updated Pydantic Models] — canonical schema definitions already in `app/models/schemas.py`
- [Source: architecture.md#API & Communication Patterns] — `response_model` on decorator for direct Pydantic serialization; no envelope wrapper
- [Story 2.1 dev notes] — `app.state.jwk` is a `dict[str, str]`; use `JWK.model_validate()` to convert; `app.state.catalog` is already `list[ProductItem]`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-5

### Debug Log References

**Issue: `app.state.jwk` not set at request time** — `ASGITransport` (httpx 0.28.1) does not invoke the FastAPI lifespan protocol, so `app.state` values set during startup are never populated. Health tests were unaffected because `/health` doesn't read `app.state`. Fixed by injecting `app.state.jwk` and `app.state.catalog` directly in a `setup_app_state` autouse fixture and restoring `app.state._state` after each test.

### Completion Notes List

- Created `app/routers/discovery.py`: synchronous `GET /.well-known/ucp` handler; reads `app.state.jwk` + `app.state.catalog` (set at startup); wraps in `UCPDiscoveryProfile`; two module-level constants `UCP_VERSION` and `SUPPORTED_CAPABILITIES`
- Updated `app/main.py`: added `from app.routers import discovery` import; registered `app.include_router(discovery.router)` immediately after app creation
- Created `tests/test_discovery.py`: 10 tests covering all FR-1 + FR-2 ACs; `setup_app_state` autouse fixture injects `app.state` directly (ASGITransport limitation discovered and documented); state is restored after every test
- 46/46 tests pass; ruff clean

### File List

- `app/routers/discovery.py` (created)
- `app/main.py` (updated — import + include_router)
- `tests/test_discovery.py` (created)

### Change Log

- Story 2.2 implemented: `GET /.well-known/ucp` UCP discovery profile endpoint (2026-06-22)
