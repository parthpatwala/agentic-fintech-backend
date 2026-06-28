# Open Standard Reference Guide

Verified external references for the protocols this prototype implements.

## Mandatory Links

| Resource | URL | Relevance to this repo |
|---|---|---|
| AP2 Repository | https://github.com/google-agentic-commerce/AP2 | Open-source AP2 schemas, Python SDK models, and reference client structures — defines Payment Mandate and Checkout Mandate concepts this prototype simplifies |
| UCP Spec Hub | https://ucp.dev/ | Industry-neutral UCP rules (Google, Shopify, Stripe, Walmart co-authors) — governs `/.well-known/ucp` discovery and capability negotiation |
| Secure Agent Commerce Codelab | https://codelabs.developers.google.com/next26/adk-agent-commerce | End-to-end UCP discovery + AP2 mandate walkthrough — closest published guide to the flow `scripts/agent_client.py` demonstrates |

## Related Specifications (optional but useful)

| Resource | URL | Notes |
|---|---|---|
| UCP AP2 Mandates Extension | https://ucp.dev/latest/specification/ap2-mandates/ | How UCP negotiates `dev.ucp.shopping.ap2_mandate` capability |
| AP2 Specification (markdown) | https://github.com/google-agentic-commerce/AP2/blob/main/docs/ap2/specification.md | Payment vs Checkout Mandate definitions |
| Google UCP Merchant Guide | https://developers.google.com/merchant/ucp | Merchant adoption context |

## How This Prototype Maps

This backend implements a **REST-only merchant/verifier prototype**, not a full AP2 reference implementation:

- **Discovery:** `GET /.well-known/ucp` returns capabilities (`dev.ucp.shopping.checkout`, `dev.ucp.shopping.ap2_mandate`), API routes, Ed25519 signing key (JWK), and product catalog
- **Checkout:** `POST /api/checkout` returns `CheckoutResponse` with `checkout_context` — no merchant-signed Cart Mandate JWT
- **Settlement:** `POST /api/complete` accepts a simplified Payment Mandate JWT in the `payment_mandate` body field, verified with EdDSA before Stripe Sandbox settlement
- **Transport:** HTTP/REST via FastAPI and `httpx` — not MCP or A2A

For the full SD-JWT+kb mandate stack and Google ADK agent patterns, follow the Secure Agent Commerce Codelab above.
