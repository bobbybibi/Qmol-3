"""Stripe webhook: auto-deliver the dataset + API key on successful payment.

Deploy as serverless (Vercel/Cloudflare/Lambda) or run as a tiny server.

Env vars:
  STRIPE_SECRET_KEY
  STRIPE_WEBHOOK_SECRET
  QMOL_API_KEY_SECRET       - any random string; used to derive per-buyer API keys
  DELIVERY_BASE_URL         - e.g. https://your-host/release (presigned S3 or HF)
  MAILGUN_API_KEY           - optional; if set, an email is sent automatically
  MAILGUN_DOMAIN
  MAILGUN_FROM              - "Q-Mol <hi@yourdomain.com>"

Local test:
  pip install stripe requests
  python -c "from stripe_webhook import deliver; deliver('buyer@example.com', 'price_commercial')"
"""
from __future__ import annotations
import json
import os

try:
    import stripe  # type: ignore
except ImportError:
    stripe = None
import requests

from api import make_api_key
from src import keys as keysdb

TIER_FROM_PRICE = {
    os.getenv("STRIPE_PRICE_RESEARCH", "price_research"): "research",
    os.getenv("STRIPE_PRICE_COMMERCIAL", "price_commercial"): "commercial",
    os.getenv("STRIPE_PRICE_REDISTRIBUTION", "price_redistribution"): "redistribution",
}


def _send_mailgun(to: str, subject: str, text: str) -> bool:
    api_key = os.getenv("MAILGUN_API_KEY")
    domain = os.getenv("MAILGUN_DOMAIN")
    sender = os.getenv("MAILGUN_FROM", f"Q-Mol <hi@{domain}>")
    if not api_key or not domain:
        print("[mail] Mailgun not configured, skipping send")
        return False
    r = requests.post(
        f"https://api.mailgun.net/v3/{domain}/messages",
        auth=("api", api_key),
        data={"from": sender, "to": to, "subject": subject, "text": text},
        timeout=30,
    )
    if not r.ok:
        print(f"[mail] send failed: {r.status_code} {r.text[:200]}")
    return r.ok


def deliver(email: str, tier_price_id: str) -> dict:
    tier = TIER_FROM_PRICE.get(tier_price_id, "research")
    base = os.getenv("DELIVERY_BASE_URL", "https://huggingface.co/datasets/YOUR/qmol/resolve/main")
    info = keysdb.provision(email, tier)
    api_key = info.key

    api_base = os.getenv("QMOL_API_BASE", "https://qua-22p1.onrender.com").rstrip("/")
    body = (
        f"Thanks for buying Q-Mol ({tier} tier)!\n\n"
        f"Downloads:\n"
        f"  Parquet: {base}/qmol_full.parquet\n"
        f"  CSV:     {base}/qmol_full.csv\n"
        f"  SDF:     {base}/qmol_full.sdf\n"
        f"  JSONL:   {base}/qmol_full.jsonl\n\n"
        f"API key (monthly quota: {info.monthly_quota:,} SMILES):\n"
        f"  {api_key}\n\n"
        f"Usage:\n"
        f'  curl -X POST {api_base}/compute/premium \\\n'
        f'    -H "x-api-key: {api_key}" \\\n'
        f'    -H "content-type: application/json" \\\n'
        f'    -d \'{{"smiles": ["CCO","c1ccccc1"]}}\'\n\n'
        f"Check remaining quota: GET {api_base}/usage  (with same header)\n"
        f"Customer portal: {api_base}/portal.html\n\n"
        f"Questions? Reply to this email.\n"
    )
    _send_mailgun(email, f"Your Q-Mol {tier} license + API key", body)
    return {"email": email, "tier": tier, "api_key": api_key}


def handler(request):
    if stripe is None:
        return {"statusCode": 500, "body": "stripe not installed"}
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    sig = request.headers.get("stripe-signature") if hasattr(request, "headers") else None
    payload = request.body if hasattr(request, "body") else b""
    try:
        event = stripe.Webhook.construct_event(
            payload, sig, os.environ["STRIPE_WEBHOOK_SECRET"]
        )
    except Exception as e:  # noqa: BLE001
        return {"statusCode": 400, "body": f"bad signature: {e}"}

    if event["type"] == "checkout.session.completed":
        sess = event["data"]["object"]
        email = sess.get("customer_details", {}).get("email") or sess.get("customer_email")
        items = stripe.checkout.Session.list_line_items(sess["id"], limit=1)
        price_id = items["data"][0]["price"]["id"] if items["data"] else ""
        if email:
            info = deliver(email, price_id)
            print(f"[deliver] {info}")

    elif event["type"] == "invoice.paid":
        # Recurring subscription renewal — extend quota by re-provisioning.
        inv = event["data"]["object"]
        email = inv.get("customer_email")
        price_id = ""
        try:
            price_id = inv["lines"]["data"][0]["price"]["id"]
        except Exception:
            pass
        if email:
            tier = TIER_FROM_PRICE.get(price_id, "research")
            info = keysdb.provision(email, tier)
            _send_mailgun(email, "Q-Mol subscription renewed",
                          f"Your {tier} subscription was renewed. "
                          f"API key (unchanged): {info.key}\n"
                          f"Quota reset: {info.monthly_quota:,} SMILES/month.")
            print(f"[renew] {email} tier={tier}")

    elif event["type"] in ("customer.subscription.deleted",
                           "invoice.payment_failed"):
        # Customer churned / payment failed — deactivate their key.
        obj = event["data"]["object"]
        email = obj.get("customer_email")
        if email:
            c = keysdb._connect()
            c.execute("UPDATE api_keys SET active=0 WHERE email=?", (email,))
            c.commit()
            c.close()
            print(f"[churn] deactivated keys for {email}")

    return {"statusCode": 200, "body": json.dumps({"received": True})}
