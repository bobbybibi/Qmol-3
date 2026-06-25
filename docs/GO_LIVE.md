# Go-live runbook — from "code complete" to "accepting payments"

Everything below is configuration, not code. Order matters.

## 0. Deploy the API + worker

The repo ships a `render.yaml` (a Render worker + web service) and a
`Dockerfile`. Push to GitHub → Render → "New > Blueprint" → pick the repo, or use
any host that runs the Docker image. Set the web service's start command to
`uvicorn api:app --host 0.0.0.0 --port $PORT` (already in `render.yaml`).

Set at minimum:
```
QMOL_ADMIN_TOKEN=<long-random>      # protects /admin/*
QMOL_PUBLIC_URL=https://your-domain # used in checkout redirect URLs + emails
```
Smoke test: `GET https://your-domain/health` → `{"status":"ok"}`.

## 1. Email delivery (so buyers receive their key)

Create a Mailgun (or similar) account and set:
```
MAILGUN_API_KEY=...
MAILGUN_DOMAIN=mg.your-domain
MAILGUN_FROM=Q-Mol <hi@your-domain>
```
Without this, payments still work but the key isn't emailed (the buyer can still
fetch it via `/auth/magic-link`).

## 2. Web / desktop billing — Stripe

1. Stripe Dashboard → create 3 **recurring** Products/Prices: Research,
   Commercial, Redistribution. Copy each `price_...` id.
2. Set on the deploy:
   ```
   STRIPE_SECRET_KEY=sk_live_...
   STRIPE_PRICE_RESEARCH=price_...
   STRIPE_PRICE_COMMERCIAL=price_...
   STRIPE_PRICE_REDISTRIBUTION=price_...
   ```
3. Stripe → Developers → Webhooks → add endpoint pointing at your
   `stripe_webhook` handler, subscribe to `checkout.session.completed`,
   `invoice.paid`, `customer.subscription.deleted`, `invoice.payment_failed`.
   Copy the signing secret → `STRIPE_WEBHOOK_SECRET=whsec_...`.
4. Test: open `/checkout.html`, pick a tier, complete a Stripe **test-mode**
   payment → confirm the webhook fires and a key is provisioned (`/admin/top-users`).

That's the full loop: checkout → pay → webhook provisions + emails the key →
customer uses the API. **The web/desktop product can take money at this point.**

## 3. Android billing — Google Play (only if you ship the Android app)

Google **requires Play Billing** for in-app digital subscriptions; Stripe is not
allowed there. See `docs/COMPLIANCE.md`. Backend side:
```
ANDROID_PACKAGE_NAME=app.qmol.android
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON={...}     # Play Developer API service account
PLAY_PRODUCT_RESEARCH=qmol_research_monthly
PLAY_PRODUCT_COMMERCIAL=qmol_commercial_monthly
```
The Android app buys via Play Billing v7+ and posts the token to
`/billing/play/verify`, which provisions the same key. The Flutter app lives in
`mobile/` — see `mobile/README.md` for the build + publish steps.

## 4. Store / legal prerequisites (do before any public listing)

- Privacy policy URL: `https://your-domain/privacy` · Terms: `/terms` (built in).
- Google Play **Data safety** form must match the privacy policy.
- Account deletion path: `DELETE /account` (in-app via the portal's "Delete
  account" button) + the web portal URL — Play requires both.
- Have counsel review the privacy/terms templates.

## 5. Launch checklist

- [ ] `/health` green on the live domain
- [ ] Stripe live keys + webhook verified with a real test payment
- [ ] Buyer receives key email (or magic-link works)
- [ ] Privacy/Terms reachable; Data-safety form submitted
- [ ] `DELETE /account` works from the portal
- [ ] Pricing page numbers match the Stripe prices
- [ ] Pick a real `QMOL_ADMIN_TOKEN`, rotate any dev keys

## Reality check on revenue

The sellable product is the **tool/subscription** (people paying to run compute
on their own molecules), and a cheap **commodity dataset** (descriptors of public
PubChem molecules) on Kaggle/Gumroad. There is no market for reselling either
public-domain descriptors or users' submitted structures to pharma — so the
go-to-market is normal SaaS: get users, convert a fraction to paid. The
engineering is done; growth is a sales/marketing effort.
