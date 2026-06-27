# Deploying Q-Mol on cPanel (HostUpon Shared Hosting)

This guide deploys the full Q-Mol API at `www.photon-bounce.com/qmol`.

## Prerequisites

- cPanel with **"Setup Python App"** feature
- MySQL database (from cPanel → MySQL Databases)
- Your Stripe keys (from previous setup steps)

---

## Step 1: Create the Python App in cPanel

1. Log into cPanel
2. Go to **"Setup Python App"** (under Software section)
3. Click **"Create Application"**
4. Configure:
   - **Python version**: 3.10 or 3.11 or 3.12 (pick highest available)
   - **Application root**: `qmol_app` (this is the folder name under your home dir)
   - **Application URL**: `/qmol` (so it's at `photon-bounce.com/qmol`)
   - **Application startup file**: `passenger_wsgi.py`
   - **Application entry point**: `application`
5. Click **Create**

> After creation, note the **virtual environment path** shown (e.g., `/home/yourusername/virtualenv/qmol_app/3.12/bin/python`).

---

## Step 2: Upload the Code

**Option A: Via cPanel File Manager**
1. Go to **File Manager** → navigate to `/home/yourusername/qmol_app/`
2. Upload a ZIP of this entire repository
3. Extract it so files are directly in `qmol_app/` (not in a subfolder)

**Option B: Via SSH (if available)**
```bash
cd ~/qmol_app
git clone https://github.com/bobbybibi/Qmol-3.git .
```

**Option C: Via FTP**
- Connect your FTP client to the server
- Upload all files to `/home/yourusername/qmol_app/`

---

## Step 3: Install Dependencies

In cPanel → **"Setup Python App"** → click your app → use the **"Run pip install"** button:

```
pip install -r requirements.txt
pip install a2wsgi stripe pymysql
```

Or if you have SSH access:
```bash
source ~/virtualenv/qmol_app/3.12/bin/activate
cd ~/qmol_app
pip install -r requirements.txt
pip install a2wsgi stripe pymysql
```

---

## Step 4: Create the Data Directory

The app stores SQLite databases in a `data/` folder. Via File Manager or SSH:

```bash
mkdir -p ~/qmol_app/data
chmod 755 ~/qmol_app/data
```

---

## Step 5: Create the `.env` File

In your `qmol_app/` directory, create a file named `.env`:

```env
# App base URL (your hosted URL)
QMOL_API_BASE=https://www.photon-bounce.com/qmol

# Stripe (from your Stripe dashboard)
STRIPE_SECRET_KEY=sk_test_YOUR_KEY_HERE
STRIPE_PUBLISHABLE_KEY=pk_test_YOUR_KEY_HERE
STRIPE_PRICE_RESEARCH=price_YOUR_RESEARCH_PRICE_ID
STRIPE_PRICE_COMMERCIAL=price_YOUR_COMMERCIAL_PRICE_ID
STRIPE_PRICE_REDISTRIBUTION=price_YOUR_REDISTRIBUTION_PRICE_ID
STRIPE_WEBHOOK_SECRET=whsec_YOUR_WEBHOOK_SECRET

# Checkout URLs
SUCCESS_URL=https://www.photon-bounce.com/qmol/checkout.html?success=1
CANCEL_URL=https://www.photon-bounce.com/qmol/checkout.html

# Admin token (make up a random string)
QMOL_ADMIN_TOKEN=pick_a_random_secret_string_here

# Email delivery (optional)
MAILGUN_API_KEY=
MAILGUN_DOMAIN=
MAILGUN_FROM=Q-Mol <hi@photon-bounce.com>

# HuggingFace (for dataset publishing)
HF_TOKEN=hf_xxx
HF_REPO_ID=bobbybibi/q-mol-dataset
```

---

## Step 6: Update Stripe Webhook URL

In your Stripe Dashboard:
1. Go to **Developers** → **Webhooks**
2. Edit your endpoint (or create a new one)
3. Set the URL to: `https://www.photon-bounce.com/qmol/stripe-webhook`
4. Events: `checkout.session.completed`, `invoice.paid`, `customer.subscription.deleted`, `invoice.payment_failed`
5. Save and copy the new **Signing Secret** → update `STRIPE_WEBHOOK_SECRET` in your `.env`

---

## Step 7: Restart the App

In cPanel → **"Setup Python App"** → click the **"Restart"** button on your app.

---

## Step 8: Test It

1. Visit: `https://www.photon-bounce.com/qmol/` — should show the landing page
2. Visit: `https://www.photon-bounce.com/qmol/health` — should return `{"status":"ok",...}`
3. Visit: `https://www.photon-bounce.com/qmol/docs` — should show API docs page
4. Try Stripe test checkout: `https://www.photon-bounce.com/qmol/checkout.html`

---

## Troubleshooting

### "502 Bad Gateway" or "Application Error"
- Check cPanel → **Error Log** (under Metrics section)
- Make sure `passenger_wsgi.py` is in the app root
- Make sure `a2wsgi` is installed: run `pip install a2wsgi` via the Python App interface

### "Module not found" errors
- Re-run: `pip install -r requirements.txt` via the Python App interface
- Check that the Python version matches (3.10+)

### Static pages (HTML) not loading
- The HTML files in `landing/` are served by FastAPI, no separate static hosting needed
- They're available at `/qmol/checkout.html`, `/qmol/docs.html`, etc.

### Database permission errors
- Make sure `data/` directory exists and is writable: `chmod 755 ~/qmol_app/data`

### Stripe webhooks failing
- Check that your webhook URL is exactly: `https://www.photon-bounce.com/qmol/stripe-webhook`
- Check that `STRIPE_WEBHOOK_SECRET` matches the signing secret shown in Stripe

---

## Optional: Set Up Cron for the Worker

If you want the molecule computation worker to run:

1. cPanel → **Cron Jobs**
2. Add a new cron (e.g., every 6 hours):
   ```
   0 */6 * * * cd ~/qmol_app && ~/virtualenv/qmol_app/3.12/bin/python worker.py --max-molecules 500
   ```

---

## File Structure on Server

```
~/qmol_app/
├── .env                    ← your secrets (Step 5)
├── passenger_wsgi.py       ← Passenger entry point
├── api.py                  ← FastAPI app
├── stripe_checkout.py
├── stripe_webhook.py
├── worker.py
├── config.py
├── requirements.txt
├── src/                    ← all source modules
├── landing/                ← HTML pages
├── data/                   ← SQLite databases (auto-created)
│   ├── keys.sqlite
│   ├── jobs.sqlite
│   └── metrics.sqlite
└── ...
```

---

## Migrating from Render

If you were previously running on Render:
1. Your data (SQLite DBs) won't transfer automatically
2. If you had existing customers, copy `data/keys.sqlite` from Render to `~/qmol_app/data/`
3. Update DNS/Stripe webhooks to point to the new URL

---

That's it! Your full Q-Mol API is now running on your HostUpon shared hosting at no extra cost.
