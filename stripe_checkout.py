"""Stripe checkout — creates a hosted subscription session.

Environment variables (set these in cPanel / .env):
  STRIPE_SECRET_KEY           sk_live_...  (required)
  STRIPE_PUBLISHABLE_KEY      pk_live_...  (required; served to frontend via /public-config)
  STRIPE_PRICE_RESEARCH       price_xxx    (monthly $49 Research plan)
  STRIPE_PRICE_COMMERCIAL     price_xxx    (monthly $299 Commercial plan)
  STRIPE_PRICE_REDISTRIBUTION price_xxx    (monthly $999 Redistribution plan)
  STRIPE_WEBHOOK_SECRET       whsec_xxx    (for /stripe-webhook signature verification)
  QMOL_API_BASE               https://www.photon-bounce.com/qmol
  SUCCESS_URL                 https://www.photon-bounce.com/qmol/checkout.html?success=1
  CANCEL_URL                  https://www.photon-bounce.com/qmol/checkout.html

To test locally:
    pip install stripe
    STRIPE_SECRET_KEY=sk_test_xxx STRIPE_PRICE_RESEARCH=price_xxx \\
        python -c "from stripe_checkout import create_session; print(create_session('price_research'))"
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

_API_BASE = os.getenv("QMOL_API_BASE", "https://www.photon-bounce.com/qmol").rstrip("/")


def create_session(price_tag: str, coupon_code: str | None = None) -> dict:
    """Create a Stripe Checkout session in subscription mode and return {url}."""
    if stripe is None:
        raise RuntimeError("stripe package not installed — run: pip install stripe")
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    env_var = PRICE_LOOKUP.get(price_tag)
    if not env_var:
        raise ValueError(f"unknown price tag: {price_tag!r}. "
                         f"Expected one of: {list(PRICE_LOOKUP)}")
    price_id = os.environ[env_var]

    kwargs: dict = dict(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=os.environ.get(
            "SUCCESS_URL",
            f"{_API_BASE}/checkout.html?success=1&session_id={{CHECKOUT_SESSION_ID}}",
        ),
        cancel_url=os.environ.get("CANCEL_URL", f"{_API_BASE}/checkout.html"),
        automatic_tax={"enabled": True},
        billing_address_collection="auto",
    )
    if coupon_code:
        kwargs["discounts"] = [{"coupon": coupon_code}]

    session = stripe.checkout.Session.create(**kwargs)
    return {"sessionId": session.id, "url": session.url}
