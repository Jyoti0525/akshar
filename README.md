# AKSHAR

**अक्षर** — *letter, character.* And, in its second sense, *imperishable.*

Rule 7(2) governs the **height of the letters** on a package. Measuring them
from a photograph is the one thing no existing tool does — which is why the
name is the claim.

Compliance checking for packaged commodities under the **Legal Metrology
(Packaged Commodities) Rules, 2011**.

> Existing tools measure font size in artwork files before printing, for brands.
> AKSHAR measures it in photographs after the product reaches the shelf, for
> enforcement — under a second, without a network.

Smart India Hackathon 2026 · problem statement **SIH26034** · Ministry of
Consumer Affairs, Food & Public Distribution.

---

## What it does

An enforcement officer photographs a packet in a shop. In about half a second,
in the browser, with no internet:

1. the pack and its principal display panel are detected and the image is
   perspective-corrected;
2. scale is recovered from a printed ChArUco marker card in frame, so printed
   characters can be measured **in millimetres**;
3. the declarations are read in **English and Hindi** and classified;
4. a YAML rulepack issues a verdict against each rule, citing its gazette clause.

The output is a report shaped like the form the officer is required to file,
with the evidence photograph attached.

**What it does not do:** anything needing a physical balance — net quantity
accuracy, sampling, tare and gross determination. A camera cannot weigh a
packet, and claiming otherwise is how projects get marked down. See §13b of the
plan.

---

## Documents

| File | What it is |
|---|---|
| [AKSHAR.md](AKSHAR.md) | **The plan.** 20 sections, binding. Read the section before implementing against it |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Task checklist mapped to plan sections; what is done, what is blocked |
| [docs/plan-migration.md](docs/plan-migration.md) | **MAAPDAND → AKSHAR, 7 Sep 2026.** Every difference between the plan and the one it replaced, and what each invalidated |
| [docs/spec-deltas.md](docs/spec-deltas.md) | Every place the code departs from the plan, and why |
| [docs/legal-decisions.md](docs/legal-decisions.md) | Rules we found, traced, and deliberately did **not** ship |
| [RESULTS.md](RESULTS.md) | Every measured number, dated |
| [docs/submission-checklist.md](docs/submission-checklist.md) | §20's checklist, walked — what is actually true, including the four rows that are not |
| [docs/annotation-guide.md](docs/annotation-guide.md) | For anyone drawing boxes: seven rules, each written around the specific way of getting it wrong |
| [docs/corpus.md](docs/corpus.md) | What arrived, what it can be used for, and what the messaging transcode cost |
| [docs/superseded/](docs/superseded/) | The previous plan. Kept for traceability; **do not build from it** |

---

## Layout

Extraction and decision are separated by a wall, and the wall is load-bearing.
The problem statement names three inputs and one of them is pure text from an
e-commerce listing with no image at all.

```
contracts/   Pydantic models — the only shared vocabulary. No cv2.
rules/       The decision layer. Pure. No cv2, no database, no network.
  engine.py    (DeclarationSet, PackageContext, Rulepack) -> [Verdict]
  checks/      thirteen check types, one file each
  packs/       the rulepack — 33 KB of YAML that is the entire legal logic
vision/      Extraction. detect · rectify · scale · ocr · classify · measure
evidence/    Hash chain and object storage
api/         FastAPI. workers/ Dramatiq. reports/ PDF + DOCX
retrieval/   Rule explainer — citation lookup, then hybrid search
web/         Next.js 15 PWA. Inference runs in the browser by default
data/        corpus · originals · test_split (RULER GROUND TRUTH — DO NOT TRAIN ON)
             manifest.json — every frame, its provenance, and §16's targets
training/    detector (RTMDet-Ins + Label Studio→COCO) · classifier · ocr
bench/       tests/ (unit · golden · e2e)    docs/
```

`tests/test_boundaries.py` fails the build if `rules/` or `contracts/` imports
anything from the extraction or persistence layers.

---

## Running it

### The whole thing, in one command, with no Docker

```bash
python -m pip install -e ".[dev]"
cd web && npm ci && cd ..

python scripts/run_demo.py
```

| | |
|---|---|
| Web app | <http://localhost:3000> |
| API docs | <http://localhost:8000/docs> |
| Sign in | `officer@akshar.demo` · `supervisor@akshar.demo` · `admin@akshar.demo` |
| Password | `akshar-demo` |

It starts the API against the in-memory stores and the web app pointed at it —
no Postgres, no Redis, no MinIO, no Docker daemon. That works because the stores
are Protocols and `AKSHAR_STORAGE=auto` falls back when no driver is importable;
it is the architecture being used, not a special mode.

**The instance starts empty.** That is what a real deployment looks like on its
first morning, and it is the only state in which nothing on screen can be
mistaken for a finding. The three sign-ins above exist regardless — the in-memory
backend has no migration and no registration route, so without them there would
be no way in at all, and `/healthz` says `DEMONSTRATION ACCOUNTS` so nobody
mistakes a published password for a real one.

```bash
python scripts/run_demo.py --seed
```

fills it: 16 SKUs, 10 brands, 6 districts, 260 scans over 75 days. **The packets
are invented; the verdicts are not.** `api/demo.py` builds each one as a real
`DeclarationSet` — cap heights in millimetres, character boxes, panel geometry —
and runs it through `rules.engine.evaluate` against the real rulepack, so nothing
on the dashboard is a stored answer. It refuses to run in production or against a
database, and `/healthz` says `DEMONSTRATION DATA` while it is on.

| Flag | |
|---|---|
| `--seed` | fill the instance with the synthetic shelf |
| `--https` | serve over https with a self-signed certificate, so the **camera works from a phone on the same network** — browsers only expose `getUserMedia` in a secure context, and `http://192.168.x.x` is not one. Implies `--dev` |
| `--dev` | `next dev` instead of a production build: faster to start, but no service worker, so the offline demonstration will not work |
| `--api-only` | skip the web app |

### The rules engine alone — no models, no database, no Docker

The legal layer is testable on its own, which is the point of the split:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
# .venv/bin/python -m pip install -e ".[dev]"     # Linux/macOS

.venv/Scripts/python -m pytest tests/ -q          # unit + boundary tests
.venv/Scripts/python -m pytest bench/ -q          # latency budget (section 4)
```

### The web app on its own

The PWA needs the API for verdicts, but it builds, lints and tests without one:

```bash
cd web
npm ci
npm run gen:api      # regenerate types from the OpenAPI schema
npm run typecheck && npm run lint
npm run build        # next build, then the Workbox service worker
npm run e2e          # 12 Playwright tests, incl. the aeroplane-mode and camera runs
npm run dev          # http://localhost:3000
```

Set `AKSHAR_API_ORIGIN` if the API is not on `http://localhost:8000`. The
browser never talks to it directly — every call goes to `/api/v1/*` on the web
origin, where a route handler attaches the session token, so no access token is
reachable from page JavaScript.

**If you put anything in front of this app, read
[`docs/deployment.md`](docs/deployment.md) first.** It has to pass the COOP and
COEP headers through untouched; a proxy that drops them halves the WASM path
silently, with nothing in the console to say so.

### The full stack, with real persistence

```bash
cp .env.example .env
docker compose up
```

| Service | URL |
|---|---|
| Web (PWA) | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |

---

## Principles

Four, and everything else follows from them.

**Extraction and decision stay separate.** The rules engine receives a
dictionary of extracted facts and never sees an image.

**Rules decide, models never.** A neural network may extract a fact; only YAML
issues a verdict — because a rule can be read aloud in court and a confidence
score cannot.

**The browser is the computer.** Not "we also work offline". Officers work
inside markets with no signal, and a tool that needs a network at the moment of
inspection fails at the moment it matters.

**Never pay twice for the same label.** A violation is printed at design time,
so it is identical on every packet of that SKU in the country. Photograph one
and you have settled it for all of them.

---

## Status

Under construction. [IMPLEMENTATION.md](IMPLEMENTATION.md) is the live view and
[RESULTS.md](RESULTS.md) carries every measured number with the date it was
taken.

Three things are **blocked on physical work** and cannot be produced by writing
code. `data/manifest.json` tracks the first against §16's targets, and reports
`null` rather than a guess for anything it cannot count.

- **The corpus is 479 frames, 231 of them millimetre-grade.** 469 arrived
  through WhatsApp (1600 px, EXIF stripped); 231 camera originals then arrived
  and supersede 221 of them. The other 248 still have no original behind them.
- **The 40-photo ruler test split needs re-measuring.** The frames exist and are
  sealed. The recorded heights are whole and half millimetres, which reads like a
  rule read to 0.5 mm rather than the 0.1 mm §16 asks for — and U1 cannot be more
  accurate than its own ground truth.
- **20–30 deliberately non-compliant photographs.** §17's capture-gate criterion
  is recall on a deliberately-bad subset, and there is no deliberately-bad subset,
  so that half of it cannot be claimed at all.

Nothing may ever be trained on the test split, tuned against it, or used to pick
a threshold from it; `training/detector/convert.py` raises rather than skips if
one of its frames appears in an annotation export.

Three gaps are worth knowing before reading the code, because each is stated in
the interface rather than hidden:

- **On-device inference is not wired.** The model bundle, the WebGPU/WASM probe
  and the cache strategy are in place; the vision blocks still run server-side,
  so a scan taken with no signal is recorded at tier L4 — photograph, time and
  location — and gets its verdict when it syncs.
- **Photographs taken offline stay on the device.** Verdicts sync; images cannot
  follow, because the scan record is hashed into the evidence chain with its
  image fields inside and there is no route that fills them afterwards.
- **MRP coverage is below the 0.90 bar** on the sealed ruler set. `RESULTS.md`
  has the numbers and the decomposition of the misses.
