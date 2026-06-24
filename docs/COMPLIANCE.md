# Compliance & store-approval notes

Concrete steps to avoid the two most common Google Play rejections (and the
equivalents for the App Store / Stripe), based on real policy-status failures.

## 1. "Invalid Privacy policy" (User Data policy)

Every store listing **and** Stripe require a real, reachable privacy policy URL
whose contents match what the app actually does with data.

- **Done in this repo:** `landing/privacy.html` + `landing/terms.html`, served at
  stable URLs **`/privacy`** and **`/terms`** (and linked from the landing
  footer). Use `https://<your-domain>/privacy` as the Play/App-Store/Stripe
  privacy URL.
- The policy must stay **accurate**. It currently discloses: email, API key,
  usage metadata + IP, submitted structures (processed only to return results,
  not sold), webhook config, and payment-processor handling. If you change what
  you collect, update the policy.
- In Play Console, also complete the **Data safety** form to match the policy.
- ⚠️ This is the line from earlier: a privacy policy can't make a
  "collect users' molecules and resell them" model compliant — Play will reject
  it. The policy here reflects the legitimate "sell the tool, not the data"
  model, which is what passes review.

## 2. "App must use Google Play Billing Library 7.0.0+"

Google Play **requires its own billing system** for in-app purchases of digital
goods/subscriptions. **You may not use Stripe for the Android app's in-app
subscription.** (Stripe is fine for the web and desktop versions.)

Architecture for the subscription tool:

| Surface | Payment | Status |
|---|---|---|
| Web / Desktop | Stripe Checkout → `POST /billing/checkout` → webhook provisions key | ✅ built |
| Android (Play) | Google Play Billing Library **v7+** in the app → purchase token → `POST /billing/play/verify` provisions key | ⚙️ backend stub built; needs the Android app + creds |

Android steps when you build the app:
1. Integrate **Play Billing Library 7.0.0+**; define subscription products in
   Play Console (e.g. `qmol_research_monthly`, `qmol_commercial_monthly`).
2. On purchase, send the `purchaseToken` + `productId` to **`/billing/play/verify`**.
3. Configure the backend: `ANDROID_PACKAGE_NAME`, `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON`
   (a Play Developer API service account), and `PLAY_PRODUCT_*` ids. Until then
   the endpoint returns a clean `503`.
4. The endpoint verifies the token via the Play Developer API and provisions the
   key — the same key the web flow issues.

## 3. Other gotchas worth pre-empting

- **Account deletion**: Play requires an in-app/we b path to delete your account
  and data. The privacy policy points users to `privacy@qmol.app`; add a
  self-serve delete before launch for full compliance.
- **Foreground/permissions**: keep the Android app's requested permissions
  minimal (it's a thin API client — it needs network, nothing sensitive).
- **Stripe**: also needs the privacy + terms URLs and a clear product/refund
  description on the checkout.

## Env vars summary (set on the deploy)

```
# Web/desktop billing (Stripe)
STRIPE_SECRET_KEY=...
STRIPE_WEBHOOK_SECRET=...
STRIPE_PRICE_RESEARCH=price_...
STRIPE_PRICE_COMMERCIAL=price_...
STRIPE_PRICE_REDISTRIBUTION=price_...
QMOL_PUBLIC_URL=https://your-domain

# Android billing (Google Play)
ANDROID_PACKAGE_NAME=app.qmol.android
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON={...service account json...}
PLAY_PRODUCT_RESEARCH=qmol_research_monthly
PLAY_PRODUCT_COMMERCIAL=qmol_commercial_monthly

# Key delivery email
MAILGUN_API_KEY=...
MAILGUN_DOMAIN=...
```

> Templates here reflect the app's real behavior; have counsel review the
> privacy policy and terms before commercial launch.
