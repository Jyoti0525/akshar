# Architecture

Two pages. The long version is [AKSHAR.md](../AKSHAR.md); this is the map.

---

## The one sentence

> AKSHAR measures the letters. Existing tools read font size out of artwork files
> before printing, for brands. We measure it in photographs after the product
> reaches the shelf, for enforcement.

Everything below follows from that being a **geometry** problem rather than a
text problem.

---

## Four principles, and what each one buys

**Extraction and decision stay separate.** `rules/` receives a `DeclarationSet`
and never sees an image. That is why the third input channel — an e-commerce
listing with no photograph — was an afternoon's work rather than a rewrite.

**Rules decide, models never.** Neural networks extract facts; YAML issues
verdicts. The reason is legal: a rule can be read aloud in court and a confidence
score cannot.

**The browser is the computer.** The scan is designed to run locally and sync
when it can. The server is a sync target, not a dependency.

**Never pay twice for the same label.** A violation is printed at design time, so
it is identical on every packet of that SKU nationally. This drives the cache,
the repository, and most of the speed.

---

## The shape

```
                        ┌────────────────────────────────┐
   photograph ─────────►│                                │
   bulk images ────────►│   vision/   B1 … B8            │──► DeclarationSet
   listing text ───┐    │   (never decides compliance)   │      (contracts/)
                   │    └────────────────────────────────┘            │
                   │                                                  ▼
                   │                                   ┌──────────────────────────┐
                   └──────────────────────────────────►│  rules/  (pure)          │
                                                       │  YAML pack → Verdicts    │
                                                       └──────────────────────────┘
                                                                      │
              ┌───────────────────────────────────────────────────────┤
              ▼                        ▼                              ▼
      evidence/ (hash chain,    api/ + workers/              reports/ (PDF, DOCX)
      redaction, storage)       (FastAPI, Dramatiq)
                                       │
                                       ▼
                                 web/ (Next.js PWA)
```

**The walls are real and enforced by imports.** `rules/` and `contracts/` never
import `vision/`. `vision/` never imports `rules/`. The frontend never reaches
past `api/`. Anywhere the same idea has to exist on both sides of a wall — the
rotation axis swap, for instance — it is written twice rather than imported
across, and each copy says so.

---

## Directory map

| Path | What lives there |
|---|---|
| `contracts/` | Frozen dataclasses: `Declaration`, `DeclarationSet`, `Verdict`, `Box`. mypy strict. |
| `vision/` | B1 quality gate · B2 detector · B3 rectify + scale · B6 OCR · B8 field classification · `measure/` (cap height, characters, orientation) |
| `rules/` | The rulepack loader and the check implementations. Pure. mypy strict. |
| `rules/packs/` | `lmpc_2011.yaml` — the entire legal logic, ~40 KB |
| `retrieval/` | RAG over the gazettes, for the "why" behind a citation |
| `api/` | FastAPI: routers, analytics, SQL stores, auth |
| `workers/` | Dramatiq actors: evidence upload, bulk ingest, report rendering |
| `evidence/` | Hash chain, face redaction, object storage, annotation |
| `reports/` | The statutory forms, PDF and DOCX |
| `web/` | Next.js 15 App Router PWA — the officer's and supervisor's screens |
| `bench/` | Latency and accuracy benchmarks against section 4's budgets |
| `data/` | Corpus, rulebook text, `test_split/` (sealed) |

---

## The web app, specifically

- **Server Components** for the whole dashboard; the review queue, the scanner
  and the offline panel are the client components, because they are the only
  interactive things.
- **No global state library.** Server state plus URL parameters. The four global
  filters are URL parameters by design, so any view is a shareable link — which
  is how a finding gets escalated.
- **Types are generated** from the FastAPI OpenAPI schema (`npm run gen:api`), and
  CI fails if the committed file is stale. The dashboard payloads are the
  exception and are hand-declared in `web/src/lib/api/types.ts`, each naming the
  function in `api/analytics.py` it must match.
- **Credentials live in httpOnly cookies.** Page JavaScript never sees a token:
  the browser calls same-origin `/api/v1/*`, and a route handler attaches the
  bearer header and refreshes the pair when it expires.
- **Offline** is IndexedDB (`idb` 8) plus Workbox 7. The outbox is a queue, not a
  cache: scans are immutable facts with client-generated UUIDv7s, sync is
  idempotent, and there is no conflict resolution because nothing is ever updated
  in place.

---

## The degradation ladder

The system never simply fails, and it always reports which tier produced the
answer.

| Tier | Situation | What still works |
|---|---|---|
| L0 | Online | Everything |
| L1 | No network | Local scan, local cache, queued sync |
| L2 | No marker | Ratio, presence, format and placement checks — 28 of 31 rules need no scale |
| L3 | OCR partly failed | Coverage reported; verdicts on what was read |
| L4 | Nothing readable | Photograph stored with time and location, queued for review |

L4 is the one people forget: *a tool that returns nothing when it can't read is
worse than a notebook.*

---

## Where the honest gaps are

Recorded here so nobody has to find them by surprise. Each is also stated in the
interface where it would otherwise mislead.

- **On-device inference is not wired.** The bundle manifest, the WebGPU/WASM
  probe and the cache strategy exist; the vision blocks still run server-side, so
  an offline scan is an L4 record that gets its verdict on sync.
- **Offline photographs are held on the device**, because the API has no route
  that attaches an image to a sealed scan record and section 6 hashes that record
  with its image fields inside.
- **User and role administration has no API.** The three roles are enforced on
  every request; there is no endpoint to list or change a user.
- **The brand-notification marker** on the brand timeline is not drawn: no notice
  date is stored anywhere, and drawing a plausible one would fabricate the exact
  before-and-after the view exists to prove.
- **MRP coverage is below the 0.90 bar** on the sealed forty-frame ruler set —
  14/40 declarations found, 9/40 measured. `RESULTS.md` has every number and the
  decomposition of the misses.
