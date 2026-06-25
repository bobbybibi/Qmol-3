# Q-Mol microsite

Static marketing microsite for the Q-Mol app + API. Plain HTML/CSS (no build
step) so it drops onto any host and uses **relative links** — it works whether
it's served at a domain root, a `/qmol` subfolder, or a subdomain.

```
microsite/
  index.html        home (hero, features, app, pricing, ad slots)
  privacy.html      privacy policy (covers cookies + AdSense)
  terms.html        terms of service
  assets/
    styles.css      modern responsive dark theme
    shot-dashboard.png
    ads.txt         AdSense ads.txt — move to the DOMAIN ROOT when you enable ads
```

## Deploy — automatic (recommended)

`.github/workflows/deploy-microsite.yml` uploads this folder to the FTP `/qmol`
directory. It runs on **push to `main`** (i.e. after this PR merges) or **on
demand** (Actions → deploy-microsite → Run workflow) from any branch. One-time
setup:

1. Repo → **Settings → Secrets and variables → Actions → New repository secret**
   - name: `FTP_PASSWORD`  · value: *(your FTP password)*
2. (Optional) repo **variables**: `FTP_SERVER` / `FTP_USERNAME` to override the
   defaults (`ftp.photon-bounce.com` / `photonb`), and `FTP_PROTOCOL` (`ftps`
   default; set `ftp` if your host only supports plain FTP).
3. Merge to `main`, or trigger the workflow manually.

If `FTP_PASSWORD` isn't set, the job **skips** (stays green) instead of failing.
The password lives only in the GitHub secret — never in the repo.

## Deploy — manual

Upload the **contents** of `microsite/` into the server's `/qmol` folder with any
FTP client (FileZilla, Cyberduck) or:

```bash
lftp -u photonb ftp.photon-bounce.com -e "mirror -R microsite /qmol; bye"
```

## Enable ads later

1. Get a Google AdSense publisher id (`ca-pub-…`).
2. In `index.html`, replace both `ca-pub-XXXXXXXXXXXXXXXX` placeholders.
3. Put `assets/ads.txt` (with your id) at your **domain root**, e.g.
   `https://photon-bounce.com/ads.txt`.
4. Ads load only after a visitor accepts the cookie banner (already wired).

## Security note

The FTP password was shared in chat — consider **rotating it** and relying on the
GitHub secret for deploys going forward.
