# Launch checklist — ship today

Do these in order. Don't skip.

## 0. (Recommended) Run the worker in the cloud, not on your PC

Push this folder to a GitHub repo, then go to https://render.com/select-repo
and pick it. Render reads `render.yaml` and creates a 24/7 worker with a
persistent disk for `data/`. Set `HF_TOKEN` and `HF_REPO_ID` in the Render
dashboard. ($7/mo on the starter plan.)

Alternative free options:
- **fly.io** — `fly launch` from this folder, uses the Dockerfile
- **Local Docker** — `docker build -t qmol . && docker run -v $PWD/data:/app/data --env-file .env qmol`

If you skip cloud for now, do step 1 below to run on your PC.

## 1. Start the worker (continuous ingestion)
```powershell
cd c:\qua\qua
.\run_worker.bat
```
Leave it running. It will keep computing and writing to `data/qmol.sqlite`.
Every N molecules (default 500) it auto-publishes to Hugging Face (if `HF_TOKEN` is set in `.env`).

## 2. Create Hugging Face account + dataset
1. Sign up: https://huggingface.co/join (free)
2. Settings → Access Tokens → **New token** → "write" scope
3. Copy `.env.example` to `.env`, set:
   - `HF_TOKEN=hf_xxx...`
   - `HF_REPO_ID=your-username/qmol`
   - `HF_PRIVATE=false`
4. First publish happens automatically after 500 molecules, or run:
   ```powershell
   .\.venv\Scripts\python.exe -c "from src.publish import publish_to_hf; from pathlib import Path; publish_to_hf(Path('data/qmol.parquet'))"
   ```

## 3. Build first release bundle
```powershell
.\.venv\Scripts\python.exe build_release.py
```
Outputs `release/qmol_full.parquet`, `release/qmol_full.csv`, `release/qmol_sample_100.csv`.

## 4. Create Gumroad product (free)
1. Sign up at gumroad.com (free)
2. **Products → New product → Digital**
3. Name: "Q-Mol — Molecular Descriptor Dataset"
4. Upload `release/qmol_full.parquet` + `release/qmol_full.csv` + `release/LICENSE.txt`
5. Price: $29 (Research) — create a second product at $299 with `LICENSE_COMMERCIAL.txt` for the commercial tier
6. Description: copy from `release/STATS.md`
7. Get product URL → paste into `landing/index.html` (replace `YOUR-PRODUCT`)

### 4b. (Optional) Auto-update the Gumroad product on every snapshot
1. Settings → Advanced → generate **Access Token** with `edit_products` scope
2. Copy the **Product ID** from the product URL (the part after `/l/`)
3. Add to `.env`:
   ```
   GUMROAD_ACCESS_TOKEN=...
   GUMROAD_PRODUCT_ID=...
   ```
4. Worker will now re-upload the latest Parquet/CSV every snapshot.
5. Manual run: `python -m src.gumroad_publish`

### 4c. (Optional) Auto-publish to Kaggle Datasets
1. kaggle.com → Account → **Create API Token** → downloads `kaggle.json`
2. Add to `.env`:
   ```
   KAGGLE_USERNAME=...
   KAGGLE_KEY=...
   KAGGLE_DATASET_SLUG=qmol-molecular-descriptors
   ```
3. Worker auto-publishes a new dataset version every snapshot.
4. Manual run: `python -m src.kaggle_publish`

## 5. Publish landing page (free)
Fastest option: GitHub Pages
```powershell
cd c:\qua\qua
git init
git add .
git commit -m "initial"
# Create repo on github.com, then:
git remote add origin https://github.com/YOUR-USER/qmol.git
git push -u origin main
```
Settings → Pages → source = main branch, /landing folder → gives you `https://YOUR-USER.github.io/qmol/`.

Alternative: drag `landing/index.html` to https://app.netlify.com/drop (instant, free URL).

## 6. Email capture
Replace `YOUR-FORM-ID` in `landing/index.html` with a free Formspree form (https://formspree.io — 50 submissions/month free).

## 7. Start outreach
Open `docs/OUTREACH.md`. Send 20 emails today to:
- Cheminformatics PIs (google "cheminformatics lab site:edu")
- Pharma ML engineers (LinkedIn "ML engineer drug discovery")
- Kaggle users who've entered comp-chem competitions

## 8. Also publish free tier to:
- **Kaggle Datasets** — upload same Parquet, link back to Gumroad for the paid tier
- **Zenodo** — gives it a DOI, boosts academic credibility
- **Reddit**: r/MachineLearning (Saturday self-promo thread), r/chemistry, r/comp_chem

## Revenue math (conservative)
- 1 Gumroad sale/week @ $29 = $116/mo
- 1 commercial sale/month @ $299 = $299/mo
- 1 custom-compute gig/month @ $500 = $500/mo
- **Target month 1: $500. Month 3: $2000.**

Run the worker. Send the emails. Ship.
