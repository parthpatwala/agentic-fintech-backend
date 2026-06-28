#!/usr/bin/env python3
"""Standalone agent client — simulates UJ-1 purchase via HTTP (Story 5.2)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import typer
from cryptography.hazmat.primitives.serialization import load_pem_private_key

AGENT_ID = "agent-client-demo"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRIVATE_KEY_PATH = PROJECT_ROOT / "keys" / "private_key.pem"
HTTP_TIMEOUT = 30.0

_BUDGET_PATTERNS = [
    re.compile(r"under\s*\$(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"if\s*.*<\s*\$(\d+(?:\.\d+)?)", re.IGNORECASE),
]

app = typer.Typer(add_completion=False)


def parse_budget(prompt: str) -> float | None:
    for pattern in _BUDGET_PATTERNS:
        match = pattern.search(prompt)
        if match:
            return float(match.group(1))
    return None


def select_product(catalog: list[dict], prompt: str, budget: float) -> dict | None:
    prompt_lower = prompt.lower()
    for item in catalog:
        if item["name"].lower() in prompt_lower and item["price"] <= budget:
            return item
    return None


def find_over_budget_match(
    catalog: list[dict], prompt: str, budget: float
) -> dict | None:
    prompt_lower = prompt.lower()
    for item in catalog:
        if item["name"].lower() in prompt_lower and item["price"] > budget:
            return item
    return None


def print_catalog(catalog: list[dict]) -> None:
    print("Catalog:")
    for item in catalog:
        print(f"  - {item['name']}: ${item['price']:.2f} {item['currency']}")


def parse_discovery_body(data: object) -> tuple[list[dict], dict[str, str]]:
    if not isinstance(data, dict):
        print("Invalid discovery response: expected JSON object")
        raise typer.Exit(code=1)
    try:
        ucp = data["ucp"]
        catalog = ucp["catalog"]
        routes = ucp["routes"]
        routes["checkout"]
        routes["complete"]
    except (KeyError, TypeError) as exc:
        print(f"Invalid discovery response: missing expected field ({exc})")
        raise typer.Exit(code=1) from exc
    return catalog, routes


def load_private_key(private_key_path: Path):
    try:
        pem_bytes = private_key_path.read_bytes()
    except OSError as exc:
        print(f"Private key not found at {private_key_path}: {exc}")
        print("Generate keys per REQUIREMENT.md (openssl genpkey -algorithm ed25519)")
        raise typer.Exit(code=1) from exc
    try:
        return load_pem_private_key(pem_bytes, password=None)
    except ValueError as exc:
        print(f"Invalid private key at {private_key_path}: {exc}")
        print("Regenerate keys per REQUIREMENT.md (openssl genpkey -algorithm ed25519)")
        raise typer.Exit(code=1) from exc


def sign_mandate(
    private_key,
    session_id: str,
    amount: float,
    currency: str,
    agent_id: str,
) -> str:
    payload = {
        "session_id": session_id,
        "amount": amount,
        "currency": currency,
        "agent_id": agent_id,
        "exp": int(time.time()) + 300,
    }
    return jwt.encode(payload, private_key, algorithm="EdDSA")


def run_purchase(
    base_url: str,
    prompt: str,
    private_key_path: Path = DEFAULT_PRIVATE_KEY_PATH,
) -> None:
    budget = parse_budget(prompt)
    if budget is None:
        print("Could not parse budget from prompt (expected e.g. 'under $100')")
        raise typer.Exit(code=1)

    discovery_url = f"{base_url.rstrip('/')}/.well-known/ucp"
    print(f"Fetching UCP discovery profile from {discovery_url} ...")
    print()

    try:
        client_kwargs = {"base_url": base_url.rstrip("/"), "timeout": HTTP_TIMEOUT}
        with httpx.Client(**client_kwargs) as client:
            discovery_resp = client.get("/.well-known/ucp")
            if discovery_resp.status_code != 200:
                print(
                    f"Discovery failed: HTTP {discovery_resp.status_code} "
                    f"{discovery_resp.text}"
                )
                raise typer.Exit(code=1)

            catalog, routes = parse_discovery_body(discovery_resp.json())

            print_catalog(catalog)
            print()

            selected = select_product(catalog, prompt, budget)
            if selected is None:
                over = find_over_budget_match(catalog, prompt, budget)
                if over is not None:
                    print(
                        f"{over['name']} (${over['price']:.2f}) exceeds "
                        f"${budget:.2f} budget"
                    )
                print("No items found within the stated budget")
                raise typer.Exit(code=0)

            print(
                f"Selected: {selected['name']} (${selected['price']:.2f}) "
                f"— within ${budget:.2f} budget"
            )
            print()

            checkout_body = {
                "session_id": str(uuid4()),
                "agent_id": AGENT_ID,
                "currency": selected["currency"],
                "items": [
                    {
                        "name": selected["name"],
                        "quantity": 1,
                        "unit_price": selected["price"],
                    }
                ],
            }

            print("Creating checkout session...")
            checkout_resp = client.post(routes["checkout"], json=checkout_body)
            if checkout_resp.status_code != 201:
                print(
                    f"Checkout failed: HTTP {checkout_resp.status_code} "
                    f"{checkout_resp.text}"
                )
                raise typer.Exit(code=1)

            checkout_data = checkout_resp.json()
            session_token = checkout_data["session_token"]
            ctx = checkout_data["checkout_context"]
            print(f"  session_token: {session_token}")
            print()

            print("Signing payment mandate...")
            private_key = load_private_key(private_key_path)
            signed_jwt = sign_mandate(
                private_key,
                session_id=ctx["session_id"],
                amount=ctx["total_amount"],
                currency=ctx["currency"],
                agent_id=AGENT_ID,
            )

            print("Submitting settlement...")
            complete_resp = client.post(
                routes["complete"], json={"payment_mandate": signed_jwt}
            )
            if complete_resp.status_code != 200:
                print(
                    f"Settlement failed: HTTP {complete_resp.status_code} "
                    f"{complete_resp.text}"
                )
                raise typer.Exit(code=1)

            result = complete_resp.json()
            print()
            print("Settlement complete!")
            print(f"  session_id: {result['session_id']}")
            print(f"  stripe_payment_intent_id: {result['stripe_payment_intent_id']}")
            print(f"  status: {result['status']}")
            print(f"  settled_at: {result['settled_at']}")

    except typer.Exit:
        raise
    except (httpx.ConnectError, httpx.TimeoutException):
        print(f"Connection error: could not reach {base_url}")
        raise typer.Exit(code=1) from None


@app.command()
def main(
    prompt: str,
    base_url: str = typer.Option(
        "http://localhost:8000",
        "--base-url",
        help="Backend base URL",
    ),
) -> None:
    run_purchase(base_url=base_url, prompt=prompt)


if __name__ == "__main__":
    app()
