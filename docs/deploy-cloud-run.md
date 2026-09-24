# Deploying AKSHAR to a public link (Google Cloud Run)

One link anyone can open, at no cost, with **scanning working** — which is the
part every 512 MB free tier could not do.

Why this host and not the others we tried:

| | memory | verdict |
|---|---|---|
| Hugging Face Spaces | enough on ZeroGPU | refuses to start without a `@spaces.GPU` function; Docker and CPU Basic are paid on this account |
| Render / Heroku free | 512 MB | a scan peaks near 1.2 GB — scanning degrades, everything else works |
| Oracle Always Free | 24 GB | signup would not complete |
| **Cloud Run** | **up to 8 GB, you pick** | runs `docker/api.Dockerfile` unchanged; scales to zero so the free tier covers a demo |

Cloud Run's always-free allowance is 2M requests, 360,000 GiB-seconds and
180,000 vCPU-seconds per month. A demo that idles at zero instances stays inside
it. **A billing account with a card is still required to create the project** —
it will not be charged within those limits, but there is no way around adding it.

---

## What you need before starting

- A Google account, and a card to attach to the billing account.
- **Docker Desktop running locally.** The image is built on your machine, not by
  Google, and that is deliberate — see the next paragraph.
- The `gcloud` CLI.
- Roughly 25 GB of free disk and a quiet machine for the build.

### Why the image is built locally

The model weights are not in git. But `.dockerignore` does **not** exclude
`data/models`, so a build run on your machine copies the 166 MB of weights
straight into the image. Pushing that image means the deployed container already
has every model — no release artifact to publish, no fetch-at-boot step, nothing
to go wrong at startup.

A build run by Google from the repository would produce an image with no weights
in it at all, and the scan path would degrade exactly as it does on Render.

> Close the local `docker compose` stack before building. A previous build run
> alongside it exhausted this machine's memory and took the API down with it.

---

## 1. Install and sign in

```bash
# Windows (PowerShell), if gcloud is not installed:
#   https://cloud.google.com/sdk/docs/install  -> run the installer
gcloud version
gcloud auth login
```

## 2. Create the project and turn on the two APIs

Pick a globally unique project id — `akshar-` plus something.

```bash
gcloud projects create akshar-sih26034 --name="AKSHAR"
gcloud config set project akshar-sih26034
```

Now attach billing, which must be done in the browser:
<https://console.cloud.google.com/billing> → link the project.

Then:

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com
```

## 3. Make a place to put the image

`asia-south1` is Mumbai — closest region, lowest latency for Indian judges.

```bash
gcloud artifacts repositories create akshar \
  --repository-format=docker \
  --location=asia-south1 \
  --description="AKSHAR API images"

gcloud auth configure-docker asia-south1-docker.pkg.dev
```

## 4. Build the image and push it

Run from the repository root. Substitute your project id.

```bash
export PROJECT=akshar-sih26034
export IMAGE=asia-south1-docker.pkg.dev/$PROJECT/akshar/api:v1

docker build -f docker/api.Dockerfile -t $IMAGE .
docker push $IMAGE
```

The build fails deliberately if WeasyPrint cannot render a PDF — that check is
the last `RUN` in the Dockerfile and it exists so a broken report renderer is
found here rather than by an officer.

Confirm the weights actually made it in:

```bash
docker run --rm $IMAGE ls -la data/models
```

You should see eleven files — the three OCR recognisers and their `.yml`
companions, the text detector, the field classifier, the SKU embedder, the PCA
matrix and the retrieval model. If that directory is empty, a `.dockerignore`
rule is excluding it and the deployed API will run degraded.

**Eleven, not twelve.** `detector_rtmdet_ins_tiny_int8.onnx` — the package
detector — is not present on this machine and so will not be in the image. The
pipeline treats a missing model as a degradation tier rather than an error, and
falls back to a geometric package box, so the scan path still runs. Just do not
read the `11/12` in the next step as a failed deploy; it is the same number you
get locally.

## 5. Deploy

Two settings here are not arbitrary:

- **`--memory 2Gi`** — a scan peaks near 1.2 GB, measured on a 1.6 MP frame.
  1 GB is not enough and the container is killed mid-scan.
- **`--concurrency 1`** — one scan per instance. At ~1.2 GB each, two concurrent
  scans in one 2 GB instance is an out-of-memory kill. Cloud Run answers extra
  traffic by starting more instances instead, which is the behaviour you want.

```bash
gcloud run deploy akshar-api \
  --image $IMAGE \
  --region asia-south1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --concurrency 1 \
  --timeout 300 \
  --max-instances 3 \
  --set-env-vars "^@^AKSHAR_ENVIRONMENT=production@AKSHAR_STORAGE=sql@AKSHAR_JWT_SECRET=PASTE_A_LONG_RANDOM_STRING@AKSHAR_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/neondb?sslmode=require@AKSHAR_MINIO_ENDPOINT="
```

Three things that will bite you:

1. **`^@^` at the front is required.** It tells gcloud to split on `@` instead of
   the default comma, and the database URL contains characters that break the
   comma parser.
2. **The database URL must say `postgresql+psycopg://`**, not `postgresql://`.
   SQLAlchemy picks its driver from that prefix and will not load psycopg 3
   without it.
3. **`--timeout 300`.** A cold scan takes about 25 seconds while ONNX loads the
   weights; the 60-second default is survivable but leaves no margin on a cold
   start plus a large photograph.

Generate the JWT secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The command prints a URL like `https://akshar-api-xxxxxxxx.a.run.app`. Check it:

```bash
curl https://akshar-api-xxxxxxxx.a.run.app/healthz
```

Expect `"models_present": 11, "models_expected": 12` — the RTMDet gap explained
above. If it reports **0 present**, the image has no weights and step 4's `ls`
check was skipped. If it reports `0 expected` as well, `scripts/` did not make
it into the image and healthz cannot see the manifest to count against.

## 6. The web app, on Vercel

Vercel's free tier is better for Next.js than Cloud Run — it does not sleep, and
it is built for exactly this. Put the frontend there and point it at the API.

1. <https://vercel.com/new> → import `Jyoti0525/akshar`.
2. Set **Root Directory** to `web`.
3. Add one environment variable:

   | Name | Value |
   |---|---|
   | `AKSHAR_API_ORIGIN` | `https://akshar-api-xxxxxxxx.a.run.app` |

   The full origin including `https://`, with no trailing slash — `serverFetch`
   concatenates it with the request path.
4. Deploy.

A browser never talks to Cloud Run directly. `web/src/app/api/v1/[...path]`
reads the httpOnly session cookie and attaches the bearer token server-side,
which is what keeps the token out of page JavaScript.

## 7. Let the API accept the web app's origin

Once Vercel gives you a URL:

```bash
gcloud run services update akshar-api --region asia-south1 \
  --update-env-vars "AKSHAR_CORS_ORIGINS=https://your-app.vercel.app"
```

## 8. Check it end to end

- Open the Vercel URL.
- Sign in with a seeded account.
- Upload a photograph, set a pack height, scan.
- Export a PDF — that exercises the native libraries the build check protected.

---

## Costs, honestly

Scale-to-zero means an idle demo costs nothing. What consumes the free
allowance is scanning: 2 GiB × ~25 s is about 50 GiB-seconds per cold scan,
against 360,000 free per month. That is thousands of scans before anything is
billable. **Set a budget alert anyway** at
<https://console.cloud.google.com/billing/budgets> — not because this will
overrun, but because an unattended cloud project with a card attached should
always have one.

## Redeploying after a change

```bash
docker build -f docker/api.Dockerfile -t $IMAGE .
docker push $IMAGE
gcloud run deploy akshar-api --image $IMAGE --region asia-south1
```

Vercel redeploys itself on every push to `main`.

## Before you deploy: rotate the database password

The Neon connection string was pasted into a chat transcript. Rotate it in the
Neon console and use the new one in step 5.
