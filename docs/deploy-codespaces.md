# Running the AKSHAR API on GitHub Codespaces

The web app is on Vercel. This guide runs the **API with real scanning** inside a
GitHub Codespace and points Vercel at it. No card needed, only your GitHub
account.

**Start here:** <https://codespaces.new/Jyoti0525/akshar>

---

## Know this before you start

A Codespace is a cloud computer that GitHub lends you. It has **8 GB of memory**
on the smallest size, which is plenty, because a scan needs about 1.2–1.8 GB.

The catch is that **it is not always on.**

- It **stops itself after a period of inactivity**. By default that's 30 minutes,
  and you can raise it to 4 hours (step 1).
- While it is stopped, the web app on Vercel still opens, but anything that needs
  the API (sign-in, scans, reports) will fail until you start the Codespace again.
- The free allowance is **60 hours a month** on the 2-core machine. That resets
  monthly.

So treat it like this: **start the Codespace before a demo or evaluation window,
and it gives you a working public link for as long as it's running.** The link
stays the same every time you restart the same Codespace, so you set Vercel up
once.

---

## 1. Change two settings first (one time)

Go to <https://github.com/settings/codespaces>.

| Setting | Set it to | Why |
|---|---|---|
| **Default idle timeout** | `240` minutes | the maximum, so it doesn't stop mid-demo |
| **Default retention period** | `30` days | so a stopped Codespace isn't deleted along with the models you uploaded |

These apply to Codespaces you create **after** changing them, so do this first.

## 2. Create the Codespace

Open <https://codespaces.new/Jyoti0525/akshar>.

- **Branch:** `main`
- **Machine type:** **2-core** (8 GB RAM). Don't pick a bigger one. It uses up
  the free hours two to four times as fast, and scanning doesn't need it.
- Click **Create codespace**.

A VS Code editor opens in your browser. The first start takes a few minutes,
partly because it downloads the repository's photographs (about 1.2 GB). Wait
until the file list on the left has loaded.

**Bookmark this page.** That's how you get back into this exact Codespace
later. You can also find it at <https://github.com/codespaces>.

## 3. Upload the model weights

The model weights aren't in git, so the Codespace doesn't have them yet.

1. On your laptop, open File Explorer at
   `C:\Users\jyoti\codefiles\SIH_26034\data\`.
2. In the Codespace, expand the `data` folder in the file list on the left.
3. **Drag the `models` folder** from File Explorer onto the `data` folder in the
   Codespace.

It is about 170 MB. Wait for the upload to finish, then in the Codespace
terminal (**Terminal → New Terminal** if one isn't open):

```bash
ls data/models
```

You should see **15 files**: `bge-small-en-v1.5.onnx` and its tokenizer, three
`ppocrv5_rec_*.onnx` with their `.yml` files, three dictionary `.txt` files,
`ppocrv6_small_det.onnx`, `field_classifier_int8.onnx`,
`mobilenetv3_small_embed.onnx` and `sku_pca_512.npz`.

`data/models` is ignored by git, so these can't be committed by accident.

## 4. Build the API image

In the Codespace terminal:

```bash
docker build -f docker/api.Dockerfile -t akshar-api .
```

About 10 to 15 minutes the first time. The last step deliberately fails the
build if PDF rendering is broken, so a successful build means reports work.

Check the models made it into the image:

```bash
docker run --rm akshar-api ls data/models
```

Same 15 files. If the list is empty, go back to step 3.

## 5. Write the settings file

Make a signing secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Create the settings file **in your home folder, outside the project**, so it can
never end up in a commit:

```bash
code ~/akshar.env
```

Paste this and fill in the three values:

```
AKSHAR_ENVIRONMENT=production
AKSHAR_STORAGE=sql
AKSHAR_JWT_SECRET=PASTE_THE_SECRET_FROM_ABOVE
AKSHAR_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/neondb?sslmode=require
AKSHAR_CORS_ORIGINS=https://YOUR-APP.vercel.app
AKSHAR_MINIO_ENDPOINT=
```

Save with `Ctrl+S`.

Things that will bite you if they're wrong:

- **No quotes** around any value. Docker would keep them as part of the value.
- **The database URL must start with `postgresql+psycopg://`**, not
  `postgresql://`.
- **Rotate the Neon password first**, because the old one was pasted into a chat.
  Use the new one here, and on Render too if Render is still running.
- `AKSHAR_CORS_ORIGINS` is your Vercel URL with `https://` and no slash at the end.
- **Keep `AKSHAR_MINIO_ENDPOINT=` with nothing after the `=`.** It says there is
  no evidence-photo storage on this host. Leave the line out and the API
  refuses to start in production: it sees the local MinIO address it defaults
  to, finds that storage's development password, and stops. The container then
  restarts over and over, and `curl` reports `Connection reset by peer`.

## 6. Start the API

```bash
docker run -d \
  --name akshar-api \
  --restart unless-stopped \
  --env-file ~/akshar.env \
  -p 8000:8000 \
  akshar-api
```

Give it 20 seconds, then:

```bash
curl http://localhost:8000/healthz
```

Look for `"models_present": 11, "models_expected": 12`. **Eleven is correct.**
The package detector (RTMDet) isn't trained yet, and the scan uses a simpler
package outline without it. `0 present` means step 3 or 4 went wrong.

If `curl` hangs, the database URL is wrong or Neon isn't reachable:

```bash
docker logs akshar-api --tail 50
```

## 7. Make port 8000 public

By default, only you can reach a Codespace's ports. Vercel needs to reach this
one.

1. Open the **Ports** tab (next to Terminal at the bottom).
2. Port **8000** should be listed. If it isn't, click **Add Port** and type
   `8000`.
3. **Right-click** the row → **Port Visibility** → **Public**.
4. Copy the **Forwarded Address**. It looks like:

```
https://your-codespace-name-8000.app.github.dev
```

**Test it from your laptop, not from the Codespace.** In PowerShell:

```powershell
curl.exe https://your-codespace-name-8000.app.github.dev/healthz
```

You should get the same JSON as step 6. If you get an HTML page or a GitHub
sign-in page instead, the port is still private. Redo step 7.3.

## 8. Make sure the database has tables and accounts

**If Render was already working with this same Neon database, skip this step.**
The tables and sign-ins are already there.

For a fresh Neon database, create the tables. `psql` wants the URL **without**
`+psycopg`:

```bash
docker run --rm -i postgres:16 psql "postgresql://USER:PASSWORD@HOST/neondb?sslmode=require" < db/schema.sql
```

Then create the three demo sign-ins:

```bash
docker exec akshar-api python -c "
from api.sql.engine import get_engine
from api.sql.stores import SqlUserStore
from api.demo import seed_accounts
print([u.email for u in seed_accounts(SqlUserStore(get_engine()))])
"
```

That prints `officer@akshar.demo`, `supervisor@akshar.demo` and
`admin@akshar.demo`. The password for all three is `akshar-demo`.

## 9. Point Vercel at it

Vercel → your project → **Settings** → **Environment Variables**:

| Name | Value |
|---|---|
| `AKSHAR_API_ORIGIN` | `https://your-codespace-name-8000.app.github.dev` |
| `AKSHAR_DEMO_CREDENTIALS` | `1` |

`https://` included, no slash at the end.

The second one puts the three demo accounts and their password on the login
page, so a reviewer can sign in without being told them. A production build
hides that panel unless this is set, so a real deployment never advertises
working credentials.

**Then redeploy.** A changed variable only applies to a new deployment:
**Deployments** → latest → **⋯** → **Redeploy**.

## 10. Test the whole thing

1. Open your Vercel URL.
2. Sign in as `officer@akshar.demo` / `akshar-demo`.
3. Upload a label photograph, enter the pack height, and run the scan.
4. The result should show text read from the label. That's the part Render
   couldn't do.
5. Export the PDF report.

If anything fails, run `docker logs akshar-api --tail 50` in the Codespace first.

---

## Every time after this

**Starting it up before a demo:**

1. Open <https://github.com/codespaces> → click your Codespace. It resumes where
   it left off, with the models, the image and the settings file still there.
2. In the terminal:

   ```bash
   docker start akshar-api
   curl http://localhost:8000/healthz
   ```

   (If it says the container is already running, that's fine.)
3. In the **Ports** tab, check port 8000 still says **Public**. If not, set it
   again (step 7.3).

The address stays the same, so Vercel needs no change.

**Stopping it** when you're done, to save free hours:
<https://github.com/codespaces> → **⋯** next to it → **Stop codespace**. Don't
**delete** it, or you'll have to redo steps 3 to 7.

**Updating after a code change** (in the Codespace terminal):

```bash
git pull
docker build -f docker/api.Dockerfile -t akshar-api .
docker rm -f akshar-api
docker run -d --name akshar-api --restart unless-stopped --env-file ~/akshar.env -p 8000:8000 akshar-api
```

**Checking your free hours:** <https://github.com/settings/billing>, under
Codespaces. If you're a verified student with the GitHub Student Developer
Pack, your allowance is higher (GitHub Pro includes 90 hours a month on the
2-core machine instead of 60).
