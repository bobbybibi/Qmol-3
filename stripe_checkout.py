"""Minimal serverless Stripe checkout — deploy to Vercel / Cloudflare Workers / AWS Lambda.

Environment variables:
  STRIPE_SECRET_KEY        sk_live_...
  STRIPE_PRICE_RESEARCH    price_xxx (created in Stripe dashboard)
  STRIPE_PRICE_COMMERCIAL  price_xxx
  STRIPE_PRICE_REDISTRIBUTION price_xxx
  SUCCESS_URL              https://yourdomain/success
  CANCEL_URL               https://yourdomain/checkout.html

Example Vercel handler (api/create-checkout.py):
    from stripe_checkout import handler as vercel_handler

To test locally:
    pip install stripe
    STRIPE_SECRET_KEY=sk_test_xxx python -c "from stripe_checkout import create_session; print(create_session('price_research'))"
"""
from __future__ import annotations
import json
import os

try:
    import stripe  # type: ignore
except ImportError:  # dev-only guard
    stripe = None

PRICE_LOOKUP = {
    "price_research": "STRIPE_PRICE_RESEARCH",
    "price_commercial": "STRIPE_PRICE_COMMERCIAL",
    "price_redistribution": "STRIPE_PRICE_REDISTRIBUTION",
}


def create_session(price_tag: str) -> dict:
    if stripe is None:
        raise RuntimeError("stripe package not installed")
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    env_var = PRICE_LOOKUP.get(price_tag)
    if not env_var:
        raise ValueError(f"unknown price: {price_tag}")
    price_id = os.environ[env_var]

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=os.environ.get(
            "SUCCESS_URL",
            "https://example.com/success?session_id={CHECKOUT_SESSION_ID}",
        ),
        cancel_url=os.environ.get("CANCEL_URL", "https://example.com/checkout.html"),
        automatic_tax={"enabled": True},
    )
    return {"sessionId": session.id, "url": session.url}


def handler(request):
    """Vercel/Next.js-style handler. Adapt for your FaaS."""
    try:
        body = request.json() if callable(getattr(request, "json", None)) else json.loads(request.body)
    except Exception:
        body = {}
    price_tag = body.get("price_id", "price_research")
    try:
        out = create_session(price_tag)
        return {"statusCode": 200, "body": json.dumps(out),
                "headers": {"content-type": "application/json",
                            "access-control-allow-origin": "*"}}
    except Exception as e:  # noqa: BLE001
        return {"statusCode": 400, "body": json.dumps({"error": str(e)}),
                "headers": {"content-type": "application/json",
                            "access-control-allow-origin": "*"}}
