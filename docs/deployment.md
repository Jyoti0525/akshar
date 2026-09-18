# Deployment

Everything an operator has to get right, in the order it bites.

---

## 1. The two headers, and why they are not optional

```
Cross-Origin-Opener-Policy:   same-origin
Cross-Origin-Embedder-Policy: require-corp
```

They are set in [`web/next.config.ts`](../web/next.config.ts) and served by `next start`. **If
anything in front of the app drops them, the app still works and is roughly half
as fast, silently.**

The chain is: those two headers make the document *cross-origin isolated* →
isolation makes `SharedArrayBuffer` available → `SharedArrayBuffer` is what lets
`onnxruntime-web` use more than one WASM thread. Without it ONNX Runtime pins
`numThreads` to 1 and the WASM path roughly doubles in latency. Nothing throws.
No request fails. The only visible symptom is a slower scan, which will be
blamed on the phone.

**How to check, in one line, against the real deployment:**

```bash
curl -sI https://<host>/scan | grep -i 'cross-origin'
```

Both must come back. There is also a Playwright test that asserts it —
`web/e2e/shell.spec.ts`, *"cross-origin isolation is on, or the WASM path is
silently halved"* — and it checks `crossOriginIsolated` in the page as well as
the headers, because a header that arrives but is overridden by a
`<meta http-equiv>` somewhere is still a broken deployment. `/queue` shows the
same fact to the officer, under **This device**.

**Nginx**, if you terminate TLS with one:

```nginx
location / {
    proxy_pass http://web:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Pass the app's headers through untouched. Do NOT use `add_header` for
    # these — `add_header` in a location block silently discards every
    # inherited header, which is how they get lost.
    proxy_pass_header Cross-Origin-Opener-Policy;
    proxy_pass_header Cross-Origin-Embedder-Policy;
}
```

**Cloudflare and similar**: check that "Rocket Loader", HTML post-processing and
any header-rewriting rule are off for this hostname. They rewrite responses and
they are the usual reason isolation disappears between staging and production.

### What `require-corp` costs

Every cross-origin subresource must opt in with CORP or CORS, or it is blocked.
The app is therefore built to load **nothing** cross-origin:

- models are served from `/models/…` on the same origin;
- the API is reached at `/api/v1/…` on the same origin, proxied by the route
  handler at `web/src/app/api/v1/[...path]/route.ts`;
- fonts are system fonts; there is no font CDN and no analytics script.

If you add a third-party script or an image host later, it must send
`Cross-Origin-Resource-Policy: cross-origin` or the page will simply not load it.

---

## 2. Origins and the request path

```
browser ──► web (Next, :3000) ──► api (FastAPI, :8000) ──► postgres / redis / minio
             │
             └── /api/v1/* is a route handler, not a rewrite: it reads the
                 httpOnly session cookie and adds `Authorization: Bearer`
```

The browser only ever talks to the web origin. That is what makes `require-corp`
workable, and it is also why **no access token is reachable from page
JavaScript** — see `web/src/lib/api/session.ts`.

Set `AKSHAR_API_ORIGIN` on the web container to where the API actually is
(`http://api:8000` inside Compose). It is server-side only and is never sent to
the browser.

---

## 3. Environment

| Variable | Where | Notes |
|---|---|---|
| `AKSHAR_JWT_SECRET` | api | **Required.** The API refuses to start without it. |
| `AKSHAR_DATABASE_URL` | api, worker | Postgres 17 with pgvector 0.8. |
| `AKSHAR_REDIS_URL` | api, worker | Dramatiq broker and the evidence spool. |
| `AKSHAR_S3_*` | api, worker | MinIO or S3 for the evidence buckets. |
| `AKSHAR_API_ORIGIN` | web | Server-side only. |
| `AKSHAR_ANCHOR_LOG` | api, cron | The evidence anchor log. See §8 — the default is the weakest possible placement. |
| `NODE_ENV=production` | web | The service worker only registers in production. |

`.env` is gitignored and must never be committed. `.env.example` lists the full
set with safe placeholders.

---

## 4. Order of operations

```bash
docker compose up -d postgres redis minio
alembic upgrade head              # schema
python scripts/fetch_models.py    # ~44 MB of weights, pinned by digest
docker compose up -d api worker web
```

Then check:

```bash
curl -s http://localhost:8000/healthz | jq          # rules loaded, models present
curl -sI http://localhost:3000/scan | grep -i cross-origin
```

`/healthz` reports `models_present` against `models_expected` and the rulepack
version. A deployment that starts with models missing will serve, degrade to the
scale-free rule tier, and say so — it will not pretend.

---

## 5. Serving the models

The browser fetches weights from `/models/<versioned filename>`. They are cached
`CacheFirst` by the service worker, which is only safe because the version is in
the filename: a new model is a new URL. **Never overwrite a model file in place.**
Publish a new filename and update `web/src/lib/ocr/models.ts`.

`next.config.ts` already sets `Cache-Control: public, max-age=31536000, immutable`
on that path for the same reason.

---

## 6. Updating the app

The service worker does not activate a new build under a running tab. It fires
`waiting`, the app raises `akshar:update-ready`, and `/queue` shows a banner. An
officer mid-inspection keeps the code they started with.

If you ship a rulepack change, remember the point of section 13: it is data. A
new YAML entry and an API restart, not a web redeploy — and every scan records
which rulepack version produced it, so verdicts stay reproducible across the
change.

---

## 7. Known deployment-blocking gaps

Stated here rather than discovered later.

- ~~`next@15.5.25` carries CVE-2025-66478.~~ **Closed.** The app runs on
  `next@16.3.4`; `npm audit` reports nothing against Next or anything that
  reaches the browser. The plan pins "Next.js 15.1" and this is a deliberate
  departure from it, recorded here and in `RESULTS.md`: the pinned line had a
  critical advisory with no fix inside it.
- **Two `npm audit` findings remain and both are build-time only.**
  `openapi-typescript` pulls `@redocly/openapi-core`, which pins a `js-yaml`
  below the fix for a YAML-parser CPU-exhaustion advisory. It runs in
  `npm run gen:api` and in CI's `contract` job, over `web_openapi.json` — a file
  this repository generates from its own FastAPI app. Nothing untrusted reaches
  it and none of it is shipped. The override to `js-yaml@5` is not taken because
  4 to 5 is a major and redocly is not tested against it; a codegen tool reading
  our own file is not worth a build that breaks on the morning of a deployment.
- **Photographs taken offline stay on the device.** The API has no route that
  attaches an image to a sealed scan record, and section 6 hashes that record
  with its image fields inside — so filling them in afterwards would break the
  evidence chain. Verdicts sync; images are held and `/queue` says so.
- **On-device inference is not wired.** The bundle, the execution-path probe and
  the cache strategy are in place; the vision blocks still run on the server, so
  an offline scan is recorded at tier L4 and gets its verdict on sync.

---

## 8. The evidence anchor

Section 6 gives every scan a hash chain, and `evidence/verify.py` is honest at
the top about what a chain does not do: **it is tamper-evident, not
tamper-proof.** Someone with write access to Postgres can rewrite a record,
recompute every digest after it, and leave a chain that verifies cleanly.
`tests/unit/test_evidence_chain.py` asserts exactly that, so nobody overclaims
it in a hearing.

What closes it is a copy the rewriter does not control.

```bash
# Publish the current head. Safe to run often; it writes nothing if the head
# has not moved.
python -m evidence.anchor

# Check every published anchor against the chain as it stands now.
python -m evidence.anchor --verify
```

`GET /api/v1/chain/status` reports the same check, and returns
`anchor_status: "unanchored"` — never `ok` — until the log holds something.

**Two operational decisions this repository cannot make for you, and the anchor
is worth nothing without both.**

1. **Put the log somewhere the API cannot quietly rewrite.** Set
   `AKSHAR_ANCHOR_LOG` to a path on a different volume, an append-only mount, or
   a share the API container holds write-but-not-truncate rights to. The default
   (`data/evidence/anchors.jsonl`) sits beside everything else and is the
   weakest arrangement there is; it is the default so the feature works out of
   the box, not because it is adequate.
2. **Send the line onward.** The plan's phrasing is *"an append-only log, a
   daily line to the controller"*, and the second half is the half that
   survives a compromised server. A nightly mail carrying the day's anchor to a
   mailbox in a different administrative domain costs nothing and means a
   wholesale rewrite must also reach the controller's inbox.

Anchor **after each scan** if you can afford it, and nightly at worst. The
anchor log localises damage: the earliest anchor that disagrees names the record
that was altered, and every anchor before it still agreeing is what lets the
department state in writing that the rest of the chain is intact. Anchoring once
a week means a week of records can only be vouched for collectively.

It is deliberately **not** written from the scan request path. An anchor volume
that is full, unmounted or read-only would then fail the scan itself, and
section 5's whole argument is that an officer walks away with a record even when
everything else has gone wrong. A cron entry that fails loudly is the right
place for it.
