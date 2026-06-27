# Q-Mol — Flutter app (Android / Play, + iOS/desktop later)

A thin client for the Q-Mol API: compute descriptors, manage your subscription
via **Google Play Billing**, and manage/delete your account. One codebase that
also targets iOS and desktop later.

> ⚠️ **This is source, not a built app.** It was written and reviewed but **not
> compiled** in the backend CI environment (no Android SDK there). Build and run
> it once on a machine with the Flutter + Android toolchain before release, and
> run `flutter analyze`. The one spot to double-check against your plugin
> version is the purchase-token extraction in `lib/billing.dart`.

## What's here

```
mobile/
  pubspec.yaml                 deps (http, in_app_purchase, shared_preferences, url_launcher)
  analysis_options.yaml        lints
  lib/
    main.dart                  app + bottom-nav (Compute / Subscribe / Account)
    api.dart                   Q-Mol API client
    store.dart                 local API-key storage
    billing.dart               Google Play Billing + server verification
    screens/compute_screen.dart
    screens/subscribe_screen.dart
    screens/account_screen.dart
  android/AndroidManifest.additions.xml   manifest edits to apply
```

## 1. Generate the platform scaffolding

`flutter create` writes the `android/`, `ios/`, gradle wrappers, etc. Generate
them, then drop this kit's `lib/` + `pubspec.yaml` on top:

```bash
flutter create --org app.qmol --project-name qmol qmol_app
cp -r mobile/lib mobile/pubspec.yaml mobile/analysis_options.yaml qmol_app/
cd qmol_app
flutter pub get
```

## 2. Android config

- **Application id**: in `android/app/build.gradle(.kts)` set
  `applicationId = "app.qmol.android"` and `minSdkVersion 21` (in_app_purchase
  needs 21+). Set `targetSdkVersion`/`compileSdkVersion` to the current value
  (35 at time of writing).
- **Manifest**: apply `mobile/android/AndroidManifest.additions.xml` to
  `android/app/src/main/AndroidManifest.xml` (INTERNET permission, `<queries>`,
  `android:label="Q-Mol"`).
- **Billing Library**: `in_app_purchase 3.2+` bundles **Billing Library 7**,
  which satisfies Play's "Billing Library 7.0.0+" requirement. Keep it current.

## 3. Play Console — subscription products

Create two **subscription** products with these ids (they must match
`lib/billing.dart` and the backend `PLAY_PRODUCT_*` env vars):

- `qmol_research_monthly`
- `qmol_commercial_monthly`

## 4. Build

Point the app at your API and build the bundle:

```bash
flutter build appbundle --dart-define=QMOL_API=https://your-domain
# -> build/app/outputs/bundle/release/app-release.aab
```

## 5. Backend wiring (so purchases provision a key)

Set on your API deployment (see `../docs/COMPLIANCE.md`):

```
ANDROID_PACKAGE_NAME=app.qmol.android
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON={...play developer api service account...}
PLAY_PRODUCT_RESEARCH=qmol_research_monthly
PLAY_PRODUCT_COMMERCIAL=qmol_commercial_monthly
```

Flow: app buys via Play Billing → `PurchaseDetails` token → `POST
/billing/play/verify` → backend verifies with the Play Developer API → returns
the API key → app stores it.

## 6. Store listing requirements (avoid the common rejections)

- **Privacy policy URL**: `https://your-domain/privacy` (served by the API).
- **Data safety form**: must match the privacy policy.
- **Account deletion**: present in-app (Account → "Delete account & data", which
  calls `DELETE /account`) and provide the same as a web URL.
- **Permissions**: INTERNET only — keep it minimal.
- Use **Play Billing** for the subscription (this app does); never Stripe on
  Android.

## 7. QA checklist before submitting

- [ ] `flutter analyze` clean
- [ ] Runs on a device/emulator; free-key signup works against your API
- [ ] Descriptors return for a SMILES
- [ ] License-tester account can complete a **test** subscription; the key is
      provisioned and saved
- [ ] Account → Delete works and signs you out
- [ ] Privacy/Terms links open
