# AKSHAR — Technical Plan

### AKSHAR · *letter, character*

**Software system to check compliance of packaged commodities under the Legal Metrology (Packaged Commodities) Rules, 2011**
SIH26034 · Ministry of Consumer Affairs, Food & Public Distribution

The name is the claim. Rule 7(2) governs the **height of letters and numerals** on a package, and measuring them from a photograph is the one thing no existing tool does. Every commercial product reads a label as text; the law regulates it as geometry. *Akshar* also carries a second sense — imperishable — which suits a system whose records are hash-chained and whose findings must be reproducible years later.

This is the document we build from. It explains what we are making, why each decision was taken, and what "done" means for every piece of it.

---

## Contents

1. Where we fit, and what already exists
2. The nine things that make this ours
3. Four principles everything follows from
4. Making it fast
5. Making it work without internet
6. What we store, and what we deliberately don't
7. Languages — the requirement that catches everyone out
8. The pipeline
9. Contracts we freeze early
10. Database
11. The dashboard
12. API
13. The rulebook, as data
    · 13a. Source document register — what was read, and how completely
    · 13b. Complete coverage of the rules, and where we stop
    · 13c. Unit symbols — the checks nobody else will find
14. Models, training, and what we refuse to train
15. RAG — where it belongs and where it doesn't
16. Building the dataset
17. Module specs and acceptance criteria
18. Testing, privacy, and audit
19. Six-week schedule
20. Demo, questions, checklist, risks

---

# 1. Where we fit, and what already exists

Before designing anything we went and looked at what people already use. Three groups, and they matter for different reasons.

**Commercial tools.** LabelBlind's FoLSol 2.0 is the serious one — AI label validation against FSSAI and legal metrology rules, forty-plus customers including Tata Starbucks and ITC Hotels, and a 2.0 release in January 2026. Artwork Flow openly advertises font-size measurement against LMPC requirements. There are also production-line inspection systems from Cognex and OCTUM.

Here is the thing that unites all of them: **they work on the digital artwork file, before printing, for the brand.** Inside an artwork file the font size is a stored number. Reading "2 mm" out of a vector PDF is a lookup, not computer vision. None of them ever sees a photograph of a product on a shelf.

**Government.** eMaap, the National Legal Metrology Portal, launched in December 2024 and has been live since February 2025. NIC built it. It handles licences, LMPC registration, instrument verification and stamping, digital certificates, and a repository of rules and court judgments. Odisha is one of its linked states.

What it does not do is enforcement. The ministry's own press release says enforcement activities and compounding of offences are not online. That sentence is the most useful thing we found, because the sponsoring department has published exactly the gap we sit in.

**Open source.** We surveyed eight relevant GitHub repositories. Every one does the same thing: run OCR, get text, match it against a dictionary of banned ingredients or allergens. Six still use Tesseract, an engine from 2015.

Zero measure font height in millimetres. Zero check Legal Metrology rules. Zero check where a declaration sits on the pack. Zero are built for an enforcement officer.

**Why that matters.** The whole field, commercial and open source alike, treats a label as *text*. The law treats it as *geometry* — how tall the letters are, which panel they're on, whether they're grouped. That mismatch is our opening.

---

# 2. The nine things that make this ours

Any competent team will build OCR plus a rules engine plus a dashboard; that answer is sitting in the problem statement. What separates us is a set of things that each cost real effort, which is precisely why most teams skip them.

**1. Millimetre measurement from a photograph.** Nobody does this from an image. It needs perspective correction and scale recovery, and it is the hardest thing in the project.

**2. Two scale-free geometric rules.** `min_width_ratio` (Rule 7(3) proviso — character width must be at least one third of its height) and `clear_space` (Rule 8(1) proviso — the quantity declaration needs one numeral-height of clear space above and below, two to the left and right). Both compare **pixels against pixels**, so they run with no marker, no calibration and no scale recovery at all. They are our safety net, they come from the bare act rather than a blog, and nobody else will think to build a fallback tier.

**3. Panel geometry.** The law says declarations must appear on the Principal Display Panel, grouped together. Checking that needs panel segmentation. No existing project attempts it.

**4. Ground truth measured with an actual ruler.** Forty packets, physically measured. That gives us a real error figure in millimetres. Other teams will demo three photos and assert "high accuracy."

**5. Rules as data.** Every verdict cites a gazette clause. A new amendment means a new YAML entry, not a redeploy. Others will hardcode `if mrp is None`.

**6. Reproducible findings.** Every scan records which model versions and which rulepack produced it, so a measurement disputed six months later can be re-run exactly. Costs one database column, and nobody thinks of it.

**7. Three inputs, one engine.** Photo, bulk images, and listing *text* with no image at all. The PS names all three; most teams read only "images."

**8. Cache before compute.** A repeat SKU returns in about 60 ms because no model runs. Everyone else runs the full pipeline every time.

**9. Offline by default, not offline as a fallback.** Inference happens in the browser. The server is a sync target, not a dependency.

**The sentence to repeat until the team is sick of it:**

> **AKSHAR** measures the letters. Existing tools read font size out of artwork files before printing, for brands. We measure it in photographs after the product reaches the shelf, for enforcement — under a second, without a network.

**What other teams will build,** so we can consciously not look like it: Tesseract plus regex plus Flask plus Bootstrap; a consumer "scan your product" app; nutrition and ingredient analysis, which is FSSAI and the wrong law entirely; an LLM wrapper that reads the label and says whether it's compliant; blockchain for tamper-proofing; barcode lookup against Open Food Facts with no measurement at all.

---

# 3. Four principles everything follows from

**Extraction and decision stay separate.** The rules engine receives a dictionary of extracted facts and never sees an image. This isn't elegance for its own sake — the PS names three inputs and one is pure text from an e-commerce listing. If OCR is wired straight into the rules, that third channel becomes a rewrite instead of an afternoon's work.

**Rules decide, models never.** Neural networks extract facts. YAML rules issue verdicts. The reason is legal, not technical: a rule can be read aloud in court, and a confidence score cannot. Whenever you're tempted to let a model make a compliance call, remember the output may end up attached to a prosecution.

**The browser is the computer.** Not "we also work offline." The scan runs locally by default and syncs when it can. Officers work inside markets with no signal, and a tool that needs a network at the moment of inspection fails at the moment it matters.

**Never pay twice for the same label.** A violation is printed at design time, so it's identical on every packet of that SKU across the country. Photograph one and you've settled it for all of them. This single observation drives the cache, the repository, and most of our speed advantage.

---

# 4. Making it fast

Efficiency is a differentiator here, not a polish item. An officer standing in a shop with a queue behind them will not wait four seconds per packet, and a jury notices a sluggish demo.

### What everyone else will build

The obvious pipeline is: take the photo, OCR the whole image at full resolution, then detect, then apply rules. Measured, that's roughly 1660 ms — and OCR alone is 1400 ms of it. Eighty-four percent of the time, most of it spent carefully reading marketing copy we immediately throw away.

### What we build instead

Three exits, cheapest first.

**Exit zero — the cache.** Computing a perceptual hash costs about 12 ms. We do it *before* touching a model. If this SKU has been seen before, we replay the stored verdict and finish in roughly 60 ms. No detection, no OCR, nothing.

**Exit one — no product.** If the detector finds no package, stop and say "point the camera at a product." About 110 ms.

**Exit two — the full path,** only for a SKU we've genuinely never seen.

| Stage | ms |
|---|---|
| **B1 capture quality (blur, glare, exposure)** | **8** |
| pHash + cache lookup | 18 |
| Detection, INT8 @ 640 px | 110 |
| Rectify | 55 |
| Scale (ArUco corner detection) | 55 |
| **ROI-only OCR, 4 crops** | **290** |
| Classify | 20 |
| Rules | 5 |
| **Total, WebGPU** | **561** |
| Total, WASM fallback | 1036 |

### The four optimisations, and why each works

**Cache before compute.** On a real shelf most packets are repeats, so most scans never reach a model at all.

**ROI-only OCR.** We never OCR the photo. Detection hands us candidate text regions, and the expensive recognition head runs only on the four to eight crops that could plausibly be declarations. That alone is roughly 5× on the stage that dominates everything.

**Resolution ladder.** Detection runs at 640 px because it only needs to find boxes. Recognition runs at native resolution, but only on crops. A twelve-megapixel photo is never processed whole.

**INT8 quantisation.** Roughly 4× smaller and 2–3× faster, small enough to cache in the browser. Measure the accuracy cost — if INT8 loses more than 1% mAP, ship FP16 and explain why.

### What this looks like at a shelf

Forty packets, twelve unique SKUs among them:

| | Time |
|---|---|
| Naive full-image OCR | 102 s |
| Ours, WASM fallback | 14.1 s |
| Ours, WebGPU | 8.4 s |

The claim worth making isn't "we are fast." It's that **the system gets faster the more it is used**, because cache hit rate climbs with coverage. Manual inspection has no such property — the millionth packet costs exactly what the first did.

### Performance budget, enforced in CI

| Metric | Target | Build fails above |
|---|---|---|
| Cache hit, in browser | <100 ms | 200 ms |
| Cache miss, WebGPU | <700 ms | 1200 ms |
| Cache miss, WASM | <1300 ms | 2000 ms |
| Server bulk throughput | >8 img/s/worker | 4 img/s |
| Rules engine, 30 rules | <10 ms | 25 ms |
| Cached model bundle | <60 MB | 100 MB |

Add a `pytest-benchmark` job so a change that makes things slower breaks the build. Being able to say that in Q&A is worth more than the numbers themselves.

---

# 5. Making it work without internet

Web only — no native app, no app store, one codebase. An installable PWA gives us the camera through `getUserMedia`, offline through a service worker, and inference through `onnxruntime-web` with WebGPU where available and WASM SIMD everywhere else.

### What lives in the browser

| Cached asset | Size |
|---|---|
| Detector, INT8 ONNX | ~12 MB |
| OCR detection + recognition, INT8 | ~28 MB |
| Field classifier | ~4 MB |
| Rulepack YAML | ~40 KB |
| SKU cache (top 5,000: hashes and verdicts) | ~6 MB |
| **Total** | **~50 MB** |

Note the rulepack. **The entire legal logic of the system is 40 KB of text** — small enough to email. That's the payoff of rules-as-data, and it's worth one line in the presentation.

### Degradation ladder

The system must never simply fail. It degrades, and always reports which tier produced the answer.

| Tier | Situation | What still works |
|---|---|---|
| L0 | Online | Everything — full cache, rule explainer, live sync |
| L1 | No network | Full local scan, local cache, queued sync |
| L2 | No marker, unknown SKU | Ratio checks, presence, format, placement |
| L3 | OCR partly failed | Coverage % reported; verdicts on what was read |
| L4 | Nothing readable | Photo stored with geo and timestamp, queued for review |

L4 is the one people forget. Even in the worst case the officer walks away with a timestamped evidence record. **A tool that returns nothing when it can't read is worse than a notebook.**

### Sync, and why there are no conflicts

Scans queue in IndexedDB and replay when the network returns. Every scan gets a client-generated UUIDv7, which is time-ordered so it doubles as a sort key. Sync is idempotent, so replaying the outbox never duplicates a record. Hash-chain sequencing is assigned server-side on arrival, because offline clients cannot possibly agree on ordering among themselves. Verdicts sync before photos — a verdict is 2 KB and a photo is 3 MB, and the officer needs the record more urgently than the image.

**There is no conflict resolution, by design.** Scans are immutable facts. Corrections are append-only rows, never edits. Nothing is ever updated in place, so nothing can conflict. When asked about merge strategy, that's the answer, and it's stronger than describing a merge strategy.

### Cache warming

On wifi, pull the 5,000 most-scanned SKUs for the officer's district. Retail is heavily long-tailed, so a few megabytes covers close to 90% of what's actually on those shelves.

---

# 6. What we store, and what we deliberately don't

**Images never go in the database.** A Postgres row holding a 3 MB blob wrecks query performance, backup times and replication. Nothing here puts an image in a table.

But we do keep them, and not out of sentiment. The PS lists "attachment of photographs and supporting evidence" as a required feature, and there's a harder reason underneath: a Legal Metrology violation can lead to compounding or prosecution, and **a finding with no photograph is an allegation, not evidence.** An officer who can't produce the image that produced the verdict has nothing to attach to a notice.

Two further uses pay for themselves. When a manufacturer disputes a 1.8 mm measurement six months later, we need the original image plus the pinned model versions to re-run it — a hash chain over records with no images is half a chain. And officer corrections are only useful as training data if the image they corrected still exists.

### The policy — tiered, so it stays cheap

| Tier | What | Where | Kept for |
|---|---|---|---|
| Evidence original | Full resolution, only for FAIL or REVIEW scans | MinIO, write-once bucket | 7 years |
| Derived crops | The 4–8 declaration ROIs, ~40 KB | MinIO | 2 years |
| Compliant scans | Downscaled to 1024 px after 90 days | MinIO | 1 year, then hash only |
| Hash and metadata | sha256, dimensions, geo, timestamp | Postgres | Forever |
| Repeat SKU scans | **Nothing stored** — cache hits never upload | — | — |

That last row is where the cache-first design pays off twice. On a shelf of 40 packets with 12 unique SKUs, 28 scans upload nothing.

| Per 10,000 scans | Storage |
|---|---|
| Store everything at full resolution | ~30 GB |
| Ours | **~2.1 GB** |

Roughly 14× less, with every legally required photograph still present. That's the answer to "isn't this expensive to run," which a government jury genuinely asks.

Every image is hashed at upload and the hash lives inside the chain, so later alteration is detectable. The bucket is write-once with versioning, so deletion is detectable too.

---

# 7. Languages — the requirement that catches everyone out

LMPC permits mandatory declarations in **Hindi or English**. In practice a large share of Indian FMCG packaging carries declarations in Devanagari, often bilingually. A system that reads only English will report "MRP not found" on a perfectly compliant Hindi-only label — and reporting a violation that doesn't exist is the worst failure this project can have.

This changes four things, so it must be designed in rather than bolted on.

**OCR configuration.** PaddleOCR supports Devanagari; enable it and run both scripts. Detection is script-agnostic, so the cost is only in recognition.

**Field patterns.** The regex tier needs Devanagari variants — `अधिकतम खुदरा मूल्य` for MRP, `शुद्ध मात्रा` for net quantity. These live in the rulepack beside the English patterns, not in code.

**Corpus.** At least 25% of photographed packets must carry Hindi or bilingual declarations, or the classifier never learns them.

**Height measurement is unaffected**, and that's worth noticing — a bounding box is a bounding box regardless of script. Our core innovation is script-independent, which is a good thing to say out loud.

One wrinkle to handle deliberately: on a bilingual pack the same declaration appears twice, in two scripts, often at different sizes. The rule is satisfied if **either** instance meets the height requirement, so the engine groups by field and takes the maximum rather than flagging the smaller one.

---

# 8. The pipeline

```
INPUT              EXTRACTION                        DECISION
photo         →  pHash → cache? ──hit──────────→  replay verdicts    60 ms
listing image →  detect → rectify → scale
listing text  →  ROI OCR → classify → measure  →  rules engine      561 ms
                        ↓                              ↓
                  DeclarationSet                    Verdicts
                                                       ↓
                                        report · evidence · repository
```

The rules engine sits behind a wall. It receives a `DeclarationSet` and nothing else.

---

# 8b. Block decomposition — who owns what

The pipeline in section 8 is a data flow. This is the same thing cut into **eleven blocks that six people can own without hidden dependencies.** Each block takes a defined input, does one narrow job, and emits a defined output. **No block may assume the next block's job is already solved.**

| Block | Question it answers | Technology | ML? | Owner |
|---|---|---|---|---|
| **B1** | Is this image usable at all? | OpenCV, gradient + histogram | No | R1 |
| **B2** | Where is the package? | Guided capture first; detector only if needed | Yes | R1 |
| **B3** | What is its usable geometry, and the scale? | OpenCV homography + ArUco | No | R1 |
| **B4** | Have we seen this SKU before? | Barcode → pHash → embedding (ORB keypoint matching as fallback for re-print variants) | No | R3 |
| **B5** | Which checks apply, and what evidence is needed? | Rulepack applicability gate | No | R3 |
| **B6** | Where is the text? | PP-OCRv6 detection | Yes | R2 |
| **B7** | What does it say? | PP-OCRv5 Devanagari recognition | Yes | R2 |
| **B8** | Which declaration is each region? | Regex + layout anchors | No initially | R2 |
| **B9** | How tall, where, how legible? | OpenCV, arithmetic | No | R1 |
| **B10** | **Is it legal?** | YAML rulepack + evaluator | **Never** | R3 |
| **B11** | Show and preserve the evidence | Application code | No | R4/R5 |

**Three ML components on the critical path.** Not fifty. Package isolation, text detection, text recognition. Everything else is deterministic engineering, and that is the answer when a judge asks how many models we trained.

**Measurement is evidence, never verdict.** B9 emits `height_mm: 1.77, error: ±0.08`. It does not emit `FAIL`. Only B10, reading the rulepack, decides that 1.77 mm against a 2.0 mm requirement is a failure — and that a 1.96 ± 0.10 result is a `REVIEW` instead. Keeping those two jobs in different blocks is what lets us change a threshold by editing YAML without touching a line of vision code.

**The boundary that matters is between B9 and B10.** Everything before B10 establishes *facts*. B10 alone turns facts into a *compliance decision*. If those ever mix, we lose explainability and the output stops being defensible.

### B1 — the pre-gate we were missing

A blurry or glare-blown photo entering the pipeline produces a confident, wrong millimetre measurement. That is the single worst failure this project can have, and the fix costs nothing: variance-of-Laplacian for blur, histogram statistics for exposure, saturation clipping for glare, plus a minimum-resolution check.

```
CaptureQuality { usable: true, blur_score: 0.91, glare_ratio: 0.04 }
  → or → usable: false, reason: "Strong glare over label"
```

No model. Ordinary mathematics answers "is this blurry" deterministically and in about 8 ms. **Rejecting a bad photo before spending 500 ms on it is both faster and more honest than measuring it badly.**

### B3 — ArUco marker, not a coin

Section 17 previously proposed a ₹5 coin as the reference object. **The marker is better and we are switching.**

A coin gives one dimension — an apparent diameter that foreshortens into an ellipse the moment the camera tilts, which is most of the time in a shop. An ArUco or ChArUco marker of known physical size gives **four detected corners with sub-pixel accuracy**, which yields the scale *and* the homography from the same detection.

Print the marker on the inspection card an officer already carries. It costs a sheet of paper and removes the weakest link in the measurement chain.

**Curved and crumpled packaging — the honest limit.** Homography is valid for *planar* surfaces. A flat box or a printed carton rectifies correctly. A bottle or pouch has a locally readable region that we crop and use as-is. A badly crumpled pouch has no recoverable planar geometry at all, and there the answer is **`NO_DATA` on every geometry-dependent rule** — not a guessed measurement.

We do not attempt cylindrical unwrapping or any learned surface-flattening. Claiming to measure millimetres on a crushed foil pouch would be the fastest way to lose credibility with a judge who has handled one. The presence, format, unit and placement rules still run; only the three `min_height_mm` rules return `NO_DATA`, and the report says which and why.

The transform matrix from B3 is **retained in the ScanContext**, because every OCR box must be mappable back onto the original photograph for the annotated evidence image. Without it the evidence is a crop nobody can locate on the pack.

### B5 — applicability runs *before* OCR, not after

Our earlier ordering evaluated the applicability gate at rule time, after everything had been extracted. That is wasteful and slightly backwards. **The law should tell perception what to look for.**

Given `retail package, 200 ml, not imported, bottle`, B5 emits an evidence plan:

```
EvidencePlan {
  need: [manufacturer, generic_name, net_quantity, mrp, packing_date, consumer_care]
  need_geometry: [mrp_height, quantity_height, placement, readability]
}
```

Two consequences. A wholesale carton under Rule 24 asks for three declarations instead of six, so we stop looking for the other three. And a package under Rule 26 exemption produces **no evidence plan at all** — the scan ends before OCR, in about 150 ms, with `NOT_APPLICABLE`.

### B7 — two-pass recognition

First pass batches every detected crop at working resolution. Regions returning low confidence — `"MRP Rs. 1?9"` at 0.67 — are **re-cropped from the original full-resolution pixels and re-read**.

This matters more here than in general OCR, because the declarations we care about are deliberately the smallest print on the pack. Cheap recognition first, expensive verification only where it is earned.

### B4 — version diffing, not a binary cache

Section 4 treated the cache as hit or miss. A known SKU can do better: align the current photo to the stored reference and identify **which regions changed**.

```
unchanged: manufacturer · consumer care · generic name · layout
changed:   MRP · packing date
```

B5 then plans to re-read only the changed regions. **We shorten the OCR work; we never shorten the legal evaluation.** Every rule still runs against the full DeclarationSet — reused evidence is still evidence.

A barcode match means *probably the same SKU*. It does not mean the same printing, the same MRP, or the same batch. B4 never outputs a compliance verdict.

### The ScanContext

One object grows through the pipeline and **nothing silently overwrites anything**:

```
ScanContext { scan_id, original_image }
  +B1 quality        +B2 package_region   +B3 geometry, transforms, scale
  +B4 product_match  +B5 evidence_plan    +B6/B7 recognised_regions
  +B8 DeclarationSet +B9 measurements     +B10 verdicts
```

Additive-only is what makes a finding reproducible six months later. If B9 could overwrite B7's output, we could not show what the system actually read.

---

# 8c. What runs after the verdict — and what must never delay it

When B11 finishes, **the officer already has the answer.** Everything below is supporting work and none of it may sit on the critical path.

```
                    B11 VERDICT  ──→ shown to officer immediately
                          │
        ┌─────────────────┼──────────────────┬────────────────┐
        ▼                 ▼                  ▼                ▼
   EVIDENCE STORE   REPORT WORKER      DASHBOARD        REVIEW QUEUE
   Postgres+MinIO   PDF / DOCX         aggregates       REVIEW verdicts
```

**Report generation is a background job.** A PDF takes 300–800 ms to render and an officer standing in a shop must not wait for it. The verdict renders; the report link appears when it is ready. Getting this wrong silently doubles our measured latency and it is the most common way a fast pipeline ends up feeling slow.

Same for the dashboard counters, the SKU `scan_count` increment, and the evidence upload. **Verdicts sync before photos** for the same reason.

### Queue priority

One worker pool, two priorities. A bulk job of 10,000 e-commerce listing images must never delay a field officer's single scan.

- **High:** interactive scans, officer report requests
- **Low:** bulk ingestion, retraining exports, dashboard rebuilds

Dramatiq supports separate queues consumed by the same workers; declare `scan` and `bulk` and weight them. Without this, one overnight bulk job makes the tool unusable the next morning.

### The review queue is a worklist, not a log

Every `REVIEW` verdict lands here — the near-threshold measurements where we deliberately refuse to convict. An officer resolves it in one click, and the resolution is stored as a labelled example for retraining.

**This closes the loop that makes `REVIEW` honest.** A status that nobody ever resolves is just a way of avoiding a decision.

### Bulk path reuses the same blocks

Ten thousand listing images do not travel through a browser one at a time. They enter the queue, workers run **the identical B1–B10 sequence** server-side, and results land in the repository. Batch multiple OCR crops per inference call for throughput.

**Same blocks, same rulepack, same verdict semantics.** If the bulk path ever diverges from the interactive path, two products exist and only one is tested.

---

# 9. Contracts we freeze early

Freeze these on day four. Once frozen, six people work in parallel without blocking each other, which is the only way six weeks is enough.

```python
# contracts/declarations.py
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime

FieldName = Literal[
    "mrp","net_quantity","mfg_date","expiry_date","manufacturer",
    "packer","importer","consumer_care","country_of_origin","generic_name",
    "batch","marketing_text","other",
]

class Box(BaseModel):
    x: float; y: float; w: float; h: float     # rectified label space, px
    panel_id: Optional[str] = None             # "pdp" | "side" | "back"

class Declaration(BaseModel):
    field: FieldName
    text: str
    script: Literal["latin","devanagari","other"]
    box: Box
    height_px: float
    height_mm: Optional[float] = None
    height_mm_tolerance: Optional[float] = None
    scale_tier: Optional[Literal["A","B","C"]] = None
    ocr_confidence: float
    field_confidence: float
    contrast_ratio: Optional[float] = None

class LabelGeometry(BaseModel):
    label_area_cm2: Optional[float] = None
    pdp_polygon: Optional[list[tuple[float,float]]] = None
    mm_per_px: Optional[float] = None
    rectified: bool

class DeclarationSet(BaseModel):
    source: Literal["photo","bulk_image","listing_text"]
    declarations: list[Declaration]
    geometry: LabelGeometry
    coverage: float
    degradation_tier: Literal["L0","L1","L2","L3","L4"]
    captured_at: datetime
    model_versions: dict[str, str]

class Verdict(BaseModel):
    rule_id: str          # "LMPC.MRP.HEIGHT"
    rule_ref: str         # "Rule 9"
    status: Literal["PASS","FAIL","NOT_APPLICABLE","REVIEW","NO_DATA"]
    severity: Literal["high","medium","low"]
    field: Optional[FieldName]
    found: Optional[str]
    expected: str
    message: str
```

Three details are load-bearing.

**`height_mm` is Optional and `source` includes `listing_text`.** A text listing has no pixels, and the same engine must handle it by skipping geometric checks and running the rest.

**`REVIEW` is what makes this deployable.** At 1.9 mm ± 0.2 against a 2.0 mm threshold we don't assert a violation — we flag it for the officer. Convicting on a 0.1 mm margin would be dismantled in court, and a sharp judge will ask about exactly this.

**`script` travels with each declaration**, so bilingual grouping works and reports show which script was read.

### Repository layout

```
akshar/
├─ contracts/          # Pydantic models — must NOT import cv2
├─ vision/             # detect · rectify · scale · ocr · classify
├─ rules/
│  ├─ engine.py        # ~200 lines, no I/O
│  ├─ checks/          # one file per check type
│  └─ packs/lmpc_2011.yaml
├─ api/  workers/  reports/  evidence/
├─ web/                # Next.js 15 + PWA
├─ data/
│  ├─ corpus/
│  ├─ test_split/      # RULER GROUND TRUTH — DO NOT TRAIN ON
│  └─ manifest.json
├─ training/  bench/  tests/
├─ RESULTS.md          # every measured number, dated
└─ docker-compose.yml
```

`rules/engine.py` must not import OpenCV, PaddleOCR or the database. If it does, the boundary has leaked and the text channel breaks later.

---

# 10. Database

```sql
CREATE TABLE skus (
  id           UUID PRIMARY KEY,
  brand        TEXT NOT NULL,
  brand_group  TEXT,                  -- parent company, for the dashboard
  variant      TEXT,
  pack_size    TEXT NOT NULL,         -- part of identity, not metadata
  category     TEXT NOT NULL,         -- food | cosmetic | cement | electronics
  barcode      TEXT,
  phash        BIT(64),
  embedding    VECTOR(512),
  label_w_mm   NUMERIC,
  label_h_mm   NUMERIC,
  scan_count   INT DEFAULT 0,
  first_seen   TIMESTAMPTZ,
  UNIQUE (brand, variant, pack_size)
);

CREATE TABLE scans (
  id               UUID PRIMARY KEY,     -- client-generated UUIDv7
  sku_id           UUID REFERENCES skus(id),
  officer_id       UUID REFERENCES users(id),
  district         TEXT,
  source           TEXT NOT NULL,
  degradation_tier TEXT NOT NULL,
  image_key        TEXT,                 -- MinIO object, never the image
  image_sha256     CHAR(64),
  declaration_set  JSONB NOT NULL,
  coverage         NUMERIC,
  latency_ms       INT,
  cache_hit        BOOLEAN,
  geo              POINT,
  captured_at      TIMESTAMPTZ NOT NULL,
  synced_at        TIMESTAMPTZ,
  model_versions   JSONB NOT NULL,
  rulepack_version TEXT NOT NULL,
  record_sha256    CHAR(64) NOT NULL,
  prev_sha256      CHAR(64),
  chain_seq        BIGINT                -- assigned server-side
);

CREATE TABLE verdicts (
  id BIGSERIAL PRIMARY KEY,
  scan_id UUID REFERENCES scans(id),
  rule_id TEXT NOT NULL, rule_ref TEXT NOT NULL,
  status TEXT NOT NULL, severity TEXT NOT NULL,
  field TEXT, found TEXT, expected TEXT
);

CREATE TABLE corrections (          -- append-only, cannot conflict
  id BIGSERIAL PRIMARY KEY,
  scan_id UUID REFERENCES scans(id),
  box_index INT, from_field TEXT, to_field TEXT,
  officer_id UUID, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE access_log (           -- who looked at what
  id BIGSERIAL PRIMARY KEY,
  user_id UUID, action TEXT, entity TEXT, entity_id TEXT,
  ip INET, at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON skus USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON skus (phash);
CREATE INDEX ON skus (brand_group, category);
CREATE INDEX ON verdicts (rule_id, status);
CREATE INDEX ON scans (district, captured_at DESC);
```

Two columns are easy to overlook and both matter.

**`pack_size` sits inside the unique constraint** because 30 g and 100 g of the same product have *different height thresholds*. Treat them as one SKU and violations vanish silently, with no error to tell you.

**`brand_group`** turns the dashboard from a list into an investigation tool. Lay's and Kurkure are separate brands but the same parent company, and a legal notice is addressed to the parent.

`latency_ms` and `cache_hit` are stored so our performance claims come from production data rather than a benchmark we ran once.

---

# 11. The dashboard

This is where a real enforcement department either uses the system or ignores it, and it's the part most teams treat as an afterthought — four cards and a pie chart.

### Start from the questions, not the charts

A dashboard isn't a collection of visualisations. It's an answer to a fixed set of questions a specific person has on a specific morning. Ours answers eight.

1. Is non-compliance getting better or worse?
2. **Which rule is broken most often?** — tells the department what to publicise
3. **Which brands are repeat offenders?** — tells them where to open cases
4. Which product categories are worst — food, cosmetics, cement, electronics?
5. Which districts are actually being covered, and which are dark?
6. What needs a human decision right now?
7. Is a specific brand improving after being notified?
8. Is the tool itself healthy — latency, coverage, cache rate, sync backlog?

Everything below exists to answer one of those. **If a chart doesn't map to a numbered question, cut it.**

### Information architecture

The core insight is that a department isn't browsing — it's drilling. Every view is an entry point into the same scan data, sliced by a different dimension, and every view must lead downward to an individual scan and its evidence photo.

```
                    ┌─────────────┐
                    │   OVERVIEW  │   Q1, Q6, Q8
                    └──────┬──────┘
        ┌──────────┬───────┼────────┬──────────┐
        ▼          ▼       ▼        ▼          ▼
     BRANDS      RULES  CATEGORIES DISTRICTS  REVIEW
      (Q3)       (Q2)     (Q4)      (Q5)     QUEUE (Q6)
        │          │       │          │          │
        ▼          ▼       ▼          ▼          │
   brand detail  rule   category   district      │
      (Q7)      detail   detail     detail       │
        │          │       │          │          │
        └──────────┴───────┴──────────┴──────────┘
                           ▼
                 SKU DETAIL → SCAN DETAIL → evidence photo
```

Four global filters sit above every view and persist across navigation: **date range, district, category, severity.** Each is a URL parameter, so any view can be shared as a link — which matters more than it sounds, because that's how a finding gets escalated to a controller.

### The overview

Five tiles across the top, each a number someone is accountable for:

`Scans this period` · `Unique SKUs covered` · `Non-compliance rate` · `High-severity open` · `Awaiting review`

Each shows the value, the change against the previous period, and clicks through to the filtered list. A number you can't click is a number you can't act on.

Below them, three things and nothing more.

**Non-compliance rate over time.** Weekly buckets, line chart, optional lines per category. The only trend senior officials actually ask about.

**Violations by rule.** Horizontal bars, descending, top eight. The most useful chart in the system — if 60% of failures are MRP font height, the department's next move is a public advisory to manufacturers, not more inspections.

**The review queue.** A short list of REVIEW-status scans needing a human call, with one-click resolve. It's a worklist, not a chart, and it belongs on the front page because it's the only thing there representing work owed by the person looking at it.

### Brands view — the one that does real work

A sortable table, columns chosen deliberately:

| Brand | Parent | SKUs checked | Fail rate | High-sev | Worst rule | Trend | Last scanned |
|---|---|---|---|---|---|---|---|

Sortable on any column, but it **defaults to high-severity count, not fail rate.** That's deliberate. A small brand with two SKUs and a 100% fail rate is noise; a national brand at 30% across forty SKUs is a case worth opening. Sorting by absolute severity count surfaces the second one.

The `Parent` column groups Lay's, Kurkure and Uncle Chipps under one company, because that's the entity a legal notice is addressed to.

**Brand detail** is where an investigation actually happens: every SKU of that brand, which rules each fails, a timeline of scans, and — the important part — **a marker for when the brand was notified**, so the department can see whether behaviour changed afterwards. That before-and-after view is the most persuasive artefact this system can produce, because it shows enforcement working.

### Rules view

Every rule in the active pack, with how often it's checked, how often it fails, and which brands fail it most. Clicking through gives the gazette clause and the full list of failing SKUs.

This view has a second, quieter purpose: **it audits our own rules.** A rule failing on 95% of products is more likely a bug in our regex than a national conspiracy.

### Categories view

Food, cosmetics, cement, electronics, footwear, medical devices — non-compliance rate per category with the worst rule for each.

This view makes a point as much as it informs. Competing tools are food-first because they come from FSSAI. **A category chart showing cement and phone chargers alongside biscuits is proof we're implementing the right law**, and it belongs on a slide.

### Districts view

Scans, unique SKUs, active officers, fail rate, and **coverage against an estimated SKU population** — that last column identifies districts that are dark rather than compliant. A choropleth map is optional and should be the first thing cut; the table carries all the information.

### System health

Median latency (hit and miss), cache hit rate, mean coverage, scans awaiting sync, current model and rulepack versions.

Unusual on an enforcement dashboard, and worth keeping. **It shows the department the tool is working, not just that products are failing** — and it's where you'd notice OCR quietly degrading after a model update.

### Build rules for the dashboard

Every table paginates server-side and exports to CSV. Every chart has a matching table view, because officials copy numbers into reports. Everything respects the four global filters. Nothing auto-refreshes — a moving dashboard is unusable when someone is reading a figure aloud.

Server Components for all of it except the review queue, which needs interactivity. Recharts for the two charts. **No global state library** — server state plus URL parameters is enough, and reaching for Redux here reads as inexperience to anyone who knows Next.js.

### Interface elsewhere

| Route | Role | Purpose |
|---|---|---|
| `/login` | all | Auth |
| `/scan` | officer | Capture or upload, live verdict |
| `/scan/[id]` | officer | Verdict, evidence overlay, corrections |
| `/scan/bulk` | officer | Multi-file upload with job progress |
| `/scan/listing` | officer | Text listing check, no image |
| `/products`, `/products/[id]` | all | SKU repository and history |
| `/search` | officer, supervisor | Faceted search |
| `/dashboard/*` | supervisor | The above |
| `/summary` | supervisor | Violation summary builder and export |
| `/rules` | all | Active rulepack, readable |
| `/admin` | admin | Users, roles, rulepack versions |
| `/queue` | officer | Offline outbox status |

**The scan screen deserves specific attention** because an officer uses it fifty times a day. Everything above the fold is the verdict. The annotated image shows the MRP box in red with its measured height and the PDP outlined dashed. Below, one row per rule.

Three details there are non-negotiable. The **latency figure is displayed on every scan** — we make a speed claim, and showing it makes the claim verifiable. The **scale tier badge and coverage percentage are always visible**, because an officer must know how much the system understood before trusting a verdict. And **REVIEW rows render amber, never red**, distinguishable at a glance from a definite failure.

Minimum 16 px text, 4.5:1 contrast, 44 px touch targets, full keyboard navigation, and a **high-contrast daylight mode** — officers work outdoors and the default palette will be unreadable at noon.

---

# 12. API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/scans` | Single image → DeclarationSet + verdicts |
| `POST` | `/api/v1/scans/bulk` | Multi-image, returns job id |
| `POST` | `/api/v1/scans/listing` | Text listing, no image |
| `POST` | `/api/v1/scans/sync` | Outbox batch, idempotent |
| `GET` | `/api/v1/scans/{id}` | Full record |
| `GET` | `/api/v1/scans/{id}/report.pdf` `.docx` | Report, both formats |
| `POST` | `/api/v1/scans/{id}/corrections` | Officer override → training data |
| `GET` | `/api/v1/skus/lookup?phash=&barcode=` | Cache check before processing |
| `GET` | `/api/v1/skus/cache?district=&n=5000` | Offline cache warming |
| `GET` | `/api/v1/search` | brand, barcode, date, district, rule, status |
| `GET` | `/api/v1/dashboard/{overview\|brands\|rules\|categories\|districts\|health}` | Dashboard views |
| `GET` | `/api/v1/summary` `+/export.pdf` `.docx` | Violation summary |
| `POST` | `/api/v1/auth/login` `/refresh` | JWT |
| `GET` | `/api/v1/rules` | Active rulepack |
| `GET` | `/healthz` `/metrics` | Ops |

Roles: `officer` · `supervisor` · `admin`. A public consumer submission channel is a plausible extension, but the PS never asks for it — build it only if everything else is done.

**Barcode deserves a note.** The lookup endpoint accepts a barcode as well as a pHash, because if the pack has a readable EAN-13 then identifying the SKU is a single indexed lookup — faster and more reliable than image matching. Decoding happens in the browser with `BarcodeDetector` where supported and a small WASM fallback elsewhere. It costs almost nothing and it's the fastest path to a cache hit we have.

---

# 13. The rulebook, as data

```yaml
meta:
  pack_id: lmpc_2011
  version: "2026.03"
  authority: "Legal Metrology (Packaged Commodities) Rules, 2011 (GSR 202(E), 7 March 2011)"
  sources:                       # see section 13a register — every value traces here
    - { id: 1, ref: "GSR 202(E) 07-03-2011", scope: "principal rules, 43 pp, read in full" }
    - { id: 2, ref: "SO 211(E) 31-01-2011", scope: "National Standards Rules; Third+Fourth Schedules" }
    - { id: 3, ref: "GSR 474(E) 05-07-2019", scope: "SI base units; authority for r.13(5)(i)" }
    - { id: 4, ref: "GSR 13(E) 07-01-2011", scope: "Numeration Rules; digit form r.2(3)" }
    - { id: 5, ref: "GSR 109(E) 23-02-2011", scope: "Numeration commencement -> 1 Apr 2011" }
  amendments_included: []        # no CONFIRMED amendment changes a rule we encode
  amendments_checked:            # confirmed via legal databases; gazette PDFs not held
    - { ref: "GSR 128(E) 13-02-2026", action: "inserts r.6(10A)",
        effect: "none — platform filter obligation, not a labelling rule" }
    - { ref: "GSR 312(E) 27-04-2026", action: "substitutes r.6(10A)",
        effect: "none — supersedes the above, in force 01-07-2027" }
    - { ref: "GSR 734(E) 30-09-2011", action: "extends packaging transition",
        effect: "none — expired" }
    - { ref: "GSR 748(E) 24-10-2011", action: "withdraws provisos",
        effect: "none — already reflected in the principal text we read" }
  amendments_unverified:         # claimed by a secondary source, never confirmed
    - "2025-10-23 medical devices"
  family_2011_status: closed            # all 10 instruments registered, see 13a

# ---------------- APPLICABILITY GATE (Rules 3 and 26) ----------------
# Runs BEFORE any rule. If out of scope, every rule returns NOT_APPLICABLE.
applicability:
  exclude_if:
    - net_quantity_gt: { value: 25, unit: kg }      # Rule 3(a)
      except_categories: [cement, fertiliser]        # ...to 50 kg
    - net_quantity_gt: { value: 25, unit: L }
    - net_quantity_lte: { value: 10, unit: g }      # Rule 26(a)
    - net_quantity_lte: { value: 10, unit: ml }
    - category_in: [restaurant_fastfood, dpco_drug] # Rule 26(b),(c)
    - consumer_type_in: [industrial, institutional] # Rule 3(b)
  package_type_rules:                              # Rule 24
    wholesale_requires_only: [manufacturer, generic_name, net_quantity]
  commodity_carveouts:
    no_date_required: [bidi, incense_sticks, lpg_domestic]   # Rule 6(1) prov A
    no_mrp_required:  [bidi, lpg_administered_price]         # Rule 6(1) prov C

# ---------------- HEIGHT TABLES (Rule 7(2)) ----------------
# NOTE: Table I is driven by NET QUANTITY, not label area.
# Table II (PDP area) applies only when quantity is by length/area/number.
tables:
  numeral_height_by_net_quantity:        # Rule 7(2)(i), Table I
    - { max_g_ml: 200,  normal_mm: 1, embossed_mm: 2 }
    - { max_g_ml: 500,  normal_mm: 2, embossed_mm: 4 }
    - { max_g_ml: null, normal_mm: 4, embossed_mm: 6 }
  numeral_height_by_pdp_area:            # Rule 7(2)(ii), Table II
    - { max_area_cm2: 100,  normal_mm: 1, embossed_mm: 2 }
    - { max_area_cm2: 500,  normal_mm: 2, embossed_mm: 4 }
    - { max_area_cm2: 2500, normal_mm: 4, embossed_mm: 6 }
    - { max_area_cm2: null, normal_mm: 6, embossed_mm: 6 }
  standard_pack_sizes:                   # Rule 5, Second Schedule (extract)
    biscuits: [25,50,75,100,150,200,250,300, "+100 to 1000"]
    tea:      [25,50,100,125,250,500,1000, "+1000"]
    cement:   [1000,2000,5000,10000,20000,25000,50000]
    toilet_soap: [25,50,75,100,125,150, "+50"]

patterns:
  # TWO patterns per field, never one. See "Locate, then validate" below.
  mrp_locate:                            # permissive — only job is to FIND the MRP
    latin: '(?i)\b(max(imum)?\.?\s*retail\s*price|m\.?r\.?p\.?)\b'
    devanagari: '(अधिकतम\s*खुदरा\s*मूल्य|एम\.?आर\.?पी\.?)'
  mrp_format:                            # Rule 2(m) — BOTH forms are legal
    latin: '(?i)\b(max(imum)?\.?\s*retail\s*price|m\.?r\.?p\.?)\s*(rs\.?|₹)\s*\d{1,3}([,\s]?\d{2,3})*(\.\d{1,2})?\s*.{0,6}(incl)'
    devanagari: 'अधिकतम\s*खुदरा\s*मूल्य'
  net_quantity_locate:                   # permissive — only job is to FIND it
    latin: '(?i)\b(net\s*(wt|weight|qty|quantity)|net\s*cont(ent)?s?|qty\.?|contents)\b'
    devanagari: '(शुद्ध|कुल)\s*(मात्रा|वजन|तौल)'
  net_quantity:                          # strict — value + lawful SI symbol
    latin: '(?i)\b(net\s*(wt|weight|qty|quantity)|net\s*content)\b\D{0,12}\d+(\.\d+)?\s?(mg|g|kg|ml|l|cm|mm|m|t|N|U)\b'
    devanagari: 'शुद्ध\s*(मात्रा|वजन)'
  mfg_date_locate:
    latin: '(?i)\b(mfg|manufactur\w*|packed|pkd|date\s*of\s*(mfg|packing)|month\s*(and|&)\s*year)\b'
    devanagari: '(निर्माण|पैकिंग)\s*(की\s*)?(तिथि|माह)'
  mfg_date:                              # Rule 6(1)(d) — month AND year
    latin: '(?i)(0?[1-9]|1[0-2])[\/\-\.\s](20\d{2})|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*[\s\/\-\.]*20\d{2}\b'
  consumer_care_locate:
    latin: '(?i)\b(consumer\s*care|customer\s*care|for\s*(any\s*)?(complaint|query|grievance)|helpline|toll[\s\-]?free)\b'
    devanagari: 'उपभोक्ता\s*(सेवा|शिकायत)'
  consumer_care_phone:                   # Rule 6(2) — telephone is mandatory
    latin: '(?i)(\+?91[\s\-]?)?(1800[\s\-]?\d{3}[\s\-]?\d{4}|[6-9]\d{9}|0\d{2,4}[\s\-]?\d{6,8})'
  manufacturer_locate:
    latin: '(?i)\b(manufactur\w*\s*(by|:)|mktd\.?\s*by|marketed\s*by|packed\s*by|imported\s*by|name\s*(and|&)\s*address)\b'
    devanagari: '(निर्माता|पैकर|आयातकर्ता)'
  amount:                                # digits only, both grouping conventions
    latin: '\d{1,3}(?:[,\s]?\d{2,3})*(?:\.\d{1,2})?'
  pluralised_symbol:                     # NS Third Schedule 7(1)(b)
    latin: '(?i)\b\d+\s*(g|kg|mg|ml|l|cm|mm|m|t)s\b|\b\d+\s*(ltrs?|gms|kgs|nos)\b'
  symbol_full_stop:                      # NS Third Schedule 7(1)(c)
    latin: '\b\d+\s*(g|kg|mg|ml|l|cm|mm|m|t)\.(?!\d)'
  missing_unit_space:                    # NS Third Schedule 7(1)(d)
    latin: '(?i)\d(?:kg|mg|ml|cm|mm|g|l|t)\b'
  capital_litre:                         # NS Fourth Schedule 3 - DISPUTED
    latin: '\b\d+\s*L\b'
  non_international_digits:              # Numeration r.2(3)
    latin: '[\u0966-\u096F\u0AE6-\u0AEF\u0B66-\u0B6F\u0BE6-\u0BEF]'
  when_packed:                           # Rule 11(4), Third Schedule
    latin: '(?i)\bwhen\s+packed\b'
    devanagari: 'पैक\s*किए\s*जाने\s*पर'
  banned_quantity_words:                 # Rule 12(6)
    latin: '(?i)\b(minimum|not\s+less\s+than|average|about|approximately)\b'
  banned_number_units:                   # Rule 13(4)
    latin: '(?i)\b(dozen|score|great\s+gross|gross)\b'

rules:
  # ---- presence, Rule 6(1) ----
  - id: LMPC.MFR.PRESENT
    rule_ref: "Rule 6(1)(a)"
    severity: high
    check: present
    field: manufacturer
    locate_ref: manufacturer_locate
    message: "Name and address of manufacturer, packer or importer not declared."

  - id: LMPC.GENERIC.PRESENT
    rule_ref: "Rule 6(1)(b)"
    severity: medium
    check: present
    field: generic_name
    message: "Common or generic name of the commodity not declared."

  - id: LMPC.NETQTY.PRESENT
    rule_ref: "Rule 6(1)(c)"
    severity: high
    check: present
    field: net_quantity
    locate_ref: net_quantity_locate
    message: "Net quantity not declared."

  - id: LMPC.DATE.PRESENT
    rule_ref: "Rule 6(1)(d)"
    severity: medium
    check: present
    field: mfg_date
    locate_ref: mfg_date_locate
    message: "Month and year of manufacture, packing or import not declared."

  - id: LMPC.MRP.PRESENT
    rule_ref: "Rule 6(1)(e)"
    severity: high
    check: present
    field: mrp
    message: "Retail sale price not declared."

  - id: LMPC.CARE.PRESENT
    rule_ref: "Rule 6(2)"
    severity: medium
    check: present
    field: consumer_care
    locate_ref: consumer_care_locate
    phone_ref: consumer_care_phone
    requires_subfields: [name, address, telephone]   # e-mail only if available
    message: "Consumer care must declare name, address and telephone number."

  # ---- format ----
  - id: LMPC.MRP.FORMAT
    rule_ref: "Rule 2(m)"
    severity: medium
    check: regex
    field: mrp
    locate_ref: mrp_locate               # extraction — permissive
    pattern_ref: mrp_format              # validation — strict
    on_locate_fail: LMPC.MRP.PRESENT     # only a missing LABEL yields NOT_FOUND
    message: "MRP must read 'Maximum retail price Rs ... inclusive of all taxes' or 'MRP Rs ... incl., of all taxes'."

  - id: LMPC.NETQTY.SI_UNITS
    rule_ref: "Rule 13(5)"
    severity: medium
    check: regex
    field: net_quantity
    locate_ref: net_quantity_locate      # permissive
    pattern_ref: net_quantity            # strict
    on_locate_fail: LMPC.NETQTY.PRESENT
    also_ref: "LM (National Standards) Rules 2011 (SO 211(E)) as amended by GSR 474(E) 2019"
    si_base: [m, kg, s, A, K, cd, mol]           # rr. 4-10, as substituted 2019
    si_prefixes:                                  # Third Schedule, Table 1
      { E: 1e18, P: 1e15, T: 1e12, G: 1e9, M: 1e6, k: 1e3,
        h: 1e2, da: 1e1, d: 1e-1, c: 1e-2, m: 1e-3, "\u00b5": 1e-6,
        n: 1e-9, p: 1e-12, f: 1e-15, a: 1e-18 }
    permitted_units:                              # Fourth Schedule
      l:   { name: litre, equals: "1 dm3",  note: "gazette symbol is lower-case l" }
      t:   { name: tonne, equals: "1000 kg", prefixes_allowed: [k, M, G, T] }
      min: { name: minute }
      h:   { name: hour }
      d:   { name: day }
    message: "Net quantity must use International System units."

  # ---- geometry: heights, Rule 7 ----
  - id: LMPC.MRP.NUMERAL_HEIGHT
    rule_ref: "Rule 7(2), Table I"
    severity: high
    check: min_height_mm
    field: mrp
    table: numeral_height_by_net_quantity
    variant_key: embossed          # picks normal_mm or embossed_mm
    bilingual: max                 # Rule 9(4): either script may satisfy
    requires: [geometry.mm_per_px, declarations.net_quantity]
    message: "MRP numerals below the minimum height for this net quantity."

  - id: LMPC.NETQTY.NUMERAL_HEIGHT
    rule_ref: "Rule 7(2), Table I"
    severity: high
    check: min_height_mm
    field: net_quantity
    table: numeral_height_by_net_quantity
    variant_key: embossed
    requires: [geometry.mm_per_px, declarations.net_quantity]
    message: "Net quantity numerals below the minimum height."

  - id: LMPC.LETTER.MIN_HEIGHT
    rule_ref: "Rule 7(3)"
    severity: medium
    check: min_height_mm
    fields: [manufacturer, consumer_care, generic_name, mfg_date]
    fixed_mm: { normal: 1.0, embossed: 2.0 }
    requires: [geometry.mm_per_px]
    message: "Declaration letters are below the 1 mm minimum height."

  - id: LMPC.CHAR.WIDTH_RATIO
    rule_ref: "Rule 7(3) proviso"
    severity: medium
    check: min_width_ratio
    fields: [mrp, net_quantity]
    ratio: 0.3333
    exclude_chars: ["1", "i", "I", "l"]
    scale_free: true               # width_px / height_px — no mm_per_px needed
    requires: []                   # runs at scale tier C
    message: "Character width is less than one third of its height."

  # ---- geometry: placement, Rule 8 ----
  - id: LMPC.PDP.ON_PANEL
    rule_ref: "Rule 8(1)"
    severity: medium
    check: same_panel
    fields: [mrp, net_quantity, manufacturer, mfg_date]
    allow_split: pre_printed_vs_online     # Rule 2(h)(ii)
    message: "Mandatory declarations must appear on the principal display panel."

  - id: LMPC.NETQTY.EXCLUSION_ZONE
    rule_ref: "Rule 8(1) proviso"
    severity: medium
    check: clear_space
    field: net_quantity
    vertical_multiple: 1.0        # >= 1x numeral height above and below
    horizontal_multiple: 2.0      # >= 2x numeral height left and right
    scale_free: true              # gap_px / numeral_height_px — no mm needed
    requires: []                  # runs at scale tier C
    message: "Area around the net quantity declaration must be free of printed information."

  # ---- readability, Rule 9 ----
  - id: LMPC.CONTRAST.NUMERALS
    rule_ref: "Rule 9(1)(b)"
    severity: medium
    check: min_contrast
    fields: [mrp, net_quantity]           # numerals of these two only
    min_ratio: 3.0
    skip_if: { surface_in: [blown, molded, glass, plastic_formed] }
    message: "Retail sale price and net quantity numerals must contrast conspicuously with the background."

  # ---- misleading, Rules 6(3), 12(6), 13(4) ----
  - id: LMPC.MRP.OVERSTICKER
    rule_ref: "Rule 6(3)"
    severity: high
    check: no_duplicate_field
    field: mrp
    lawful_if: { sticker_value_lower: true, original_visible: true }
    message: "A revised MRP sticker may only reduce the price and must not cover the original declaration."

  - id: LMPC.QTY.BANNED_WORDS
    rule_ref: "Rule 12(6)"
    severity: medium
    check: regex_absent
    field: net_quantity
    pattern_ref: banned_quantity_words
    message: "Quantity declaration must not use 'minimum', 'average', 'about' or similar qualifiers."

  - id: LMPC.QTY.BANNED_UNITS
    rule_ref: "Rule 13(4)"
    severity: low
    check: regex_absent
    field: net_quantity
    pattern_ref: banned_number_units
    message: "Dozen, score or gross must not be used."

  # ---- standard pack size, Rule 5 ----
  - id: LMPC.PACK.STANDARD_SIZE
    rule_ref: "Rule 5, Second Schedule"
    severity: medium
    check: in_table
    field: net_quantity
    table: standard_pack_sizes
    keyed_by: category
    message: "Commodity is not packed in a standard quantity prescribed by the Second Schedule."

  # ---- unit correctness, Rules 12(2) and 13 ----
  - id: LMPC.QTY.UNIT_BY_COMMODITY
    rule_ref: "Rule 12(2), Fourth Schedule"
    severity: medium
    check: in_table
    field: net_quantity
    table: unit_by_commodity          # curd=weight, garments=number, tyres=number
    keyed_by: category
    message: "Quantity must be declared in the unit prescribed for this commodity."

  - id: LMPC.QTY.UNIT_MAGNITUDE
    rule_ref: "Rule 13(2)-(3)"
    also_ref: "NS Rules Third Schedule item 10 - value must fall in [0.1, 1000)"
    severity: low
    check: value_in_range                 # not regex: needs the parsed number
    field: net_quantity
    parse_ref: amount                     # how the numeral is extracted
    min_value: 0.1
    max_value: 1000                       # exclusive - "1500 g" must be "1.5 kg"
    message: "The unit must be chosen so the declared value falls between 0.1 and 1000."

  - id: LMPC.QTY.WHEN_PACKED
    rule_ref: "Rule 11(4), Third Schedule"
    severity: medium
    check: regex_absent
    field: net_quantity
    pattern_ref: when_packed
    unless_category_in: [soap, lotion, cream]
    message: "'When packed' may only qualify quantity on soaps, lotions and cream."

  # ---- dealer offences, Rule 18 ----
  - id: LMPC.MRP.DEFACED
    rule_ref: "Rule 18(5)"
    severity: high
    check: min_contrast
    field: mrp
    min_ratio: 2.0
    respondent: dealer                # NOT the manufacturer
    suppresses: LMPC.CONTRAST.NUMERALS   # one measurement -> one verdict
    only_if: { sticker_or_overprint_detected: true }
    message: "Retail sale price appears obliterated, smudged or altered."

  - id: LMPC.DATE.FORMAT
    rule_ref: "Rule 6(1)(d)"
    severity: medium
    check: regex
    field: mfg_date
    locate_ref: mfg_date_locate          # permissive
    pattern_ref: mfg_date                # strict: month AND year both present
    on_locate_fail: LMPC.DATE.PRESENT
    message: "Date must declare both the month and the year of manufacture, packing or import."

  # ---- unit symbol printing, National Standards Rules Third Schedule ----
  # All severity LOW: formatting defects, reported in the advisory block.
  - id: LMPC.UNIT.SYMBOL_CASE
    rule_ref: "LMPC r.13(5)(i) read with NS Rules Third Schedule item 7(2)"
    severity: low
    check: symbol_case
    field: net_quantity
    lowercase_required: true
    proper_name_exceptions: [N, Pa, A, K, W, J, V, Hz, C, T, Wb, S, F, Bq, Gy, Sv, Ohm]
    message: "Unit symbols must be printed in lower case unless named after a person (e.g. 'ml', not 'ML')."

  - id: LMPC.UNIT.SYMBOL_PLURAL
    rule_ref: "NS Rules Third Schedule item 7(1)(b)"
    severity: low
    check: regex_absent
    field: net_quantity
    pattern_ref: pluralised_symbol
    message: "Unit symbols do not take a plural form ('500 g', not '500 gs')."

  - id: LMPC.UNIT.SYMBOL_STOP
    rule_ref: "NS Rules Third Schedule item 7(1)(c)"
    severity: low
    check: regex_absent
    field: net_quantity
    pattern_ref: symbol_full_stop
    message: "Unit symbols are written without a final full stop."

  - id: LMPC.UNIT.SYMBOL_SPACE
    rule_ref: "NS Rules Third Schedule item 7(1)(d)"
    severity: low
    check: regex_absent
    field: net_quantity
    pattern_ref: missing_unit_space
    message: "A space is required between the numerical value and the unit symbol."

  - id: LMPC.UNIT.LITRE_SYMBOL
    rule_ref: "NS Rules Fourth Schedule item 3"
    severity: low
    enabled: false                     # DISPUTED - see 13c. BIPM accepts 'L'
    check: regex_absent
    field: net_quantity
    pattern_ref: capital_litre
    message: "The gazette gives the litre symbol as lower-case 'l'. Advisory only."

  - id: LMPC.NUM.DIGIT_FORM
    rule_ref: "LM (Numeration) Rules 2011, r.2(3)"
    severity: low
    check: regex_absent
    field: [mrp, net_quantity, mfg_date]   # every field carrying a numeral
    pattern_ref: non_international_digits
    message: "Numbers must use the international form of Indian numerals (0-9)."

  # ---- imports ----
  - id: LMPC.IMPORTER.PRESENT
    rule_ref: "Rule 6(1)(a)"          # principal rules, verified in our source PDF
    severity: high
    check: conditional_present
    field: importer
    when: { field: country_of_origin, present: true }
    message: "Imported packages must declare the name and address of the importer."

  # NOTE: there is deliberately NO package-level country-of-origin rule.
  # Rule 6(10A) does not require it on the pack — see section 13b.
```

**Thirteen check types. Build these and no more:**
`present` · `regex` · `regex_absent` · `min_height_mm` · `min_width_ratio` · `same_panel` · `clear_space` · `min_contrast` · `no_duplicate_field` · `conditional_present` · `in_table` · `symbol_case` · `value_in_range`

`ratio_min` was dropped, and with it the `usp` field name. Both existed only for a "Unit Sale Price must be half the MRP height" rule that came from a vendor blog and **is not in the 2011 Rules.** Nothing in the bare act needs it. Its removal is what forced the Tier C correction below.

Three of these — `min_height_mm`, `min_width_ratio` and `clear_space` — are pure geometry and **cannot be implemented without bounding boxes.** Two of the three need no millimetres either: width-against-height and gap-against-height are ratios of pixels, so they survive total failure of scale recovery. They are the rules that only our architecture can check, and they come straight from the bare act rather than from our imagination.

When a `requires` key is missing from the DeclarationSet, return **`NO_DATA`, never `FAIL`.** Absence of evidence is not evidence of a violation — say that sentence in Q&A, because it's the difference between a tool an officer can rely on and one that generates false accusations.

Four reasons this design earns its place, all four presentable. The law changes — the Numeration Rules were amended six weeks after publication, and LMPC has been amended repeatedly since 2011 (we hold none of those notifications, see the register). Every verdict cites a clause, so it's explainable. Rules are data, so they're unit-testable against fixtures. And FSSAI can later become a second rulepack over the same extracted fields with no new extraction work.

---

### Locate, then validate — two patterns per field, never one

The single most dangerous failure this system can produce is reporting **"MRP not declared"** on a pack where the MRP is printed clearly. That is a false accusation against a manufacturer, and one instance of it in front of a judge ends the demo.

It nearly happened here. The MRP pattern originally required `\d+(\.\d{1,2})?` for the amount — digits with no separator. Tested against realistic label strings:

| Label text | Old pattern |
|---|---|
| `MRP Rs. 45.00 (inclusive of all taxes)` | matched |
| `MRP Rs. 1,250.00 (inclusive of all taxes)` | **no match** |
| `M.R.P. ₹ 1,199.00 (incl. of all taxes)` | **no match** |
| `MRP ₹ 2,50,000.00 (inclusive of all taxes)` | **no match** |

**Every product priced at ₹1,000 or above would have been reported as having no MRP** — cosmetics, footwear, electronics, cement, appliances. The rule that fires is `LMPC.MRP.PRESENT`, severity `high`, and it would fire on a perfectly compliant pack. The `incl` tail was also too tight for `(incl. of all taxes)`, where the gap runs to six characters, not four.

The bug is not the regex. **The bug is using one pattern for two jobs.**

- **Locating** asks *is there an MRP declaration on this pack at all?* It must be as permissive as possible. Miss here and you generate a false `NOT_FOUND`.
- **Validating** asks *is it written in the form Rule 2(m) prescribes?* It must be strict. Fail here and you generate a `FORMAT` violation, which is a real and much milder finding.

So every field carries `locate_ref` and `pattern_ref`. `on_locate_fail` names the only rule permitted to return `NOT_FOUND`. A formatting question can never escalate into a missing-declaration verdict.

**This is done for every field, not just MRP.** `net_quantity`, `mfg_date`, `consumer_care` and `manufacturer` each carry a `*_locate` pattern alongside their strict one, and `on_locate_fail` names the single rule allowed to return `NOT_FOUND`. The consumer-care rule additionally carries `phone_ref`, because Rule 6(2) makes the telephone number mandatory and a name-and-address-only check would pass packs that fail.

The presentable version: *"a strict pattern that fails to match tells you the label is wrong. A strict pattern used to find the label tells you the label is absent. Those are different verdicts with different legal consequences, so we use different patterns."*

---

### Misleading declarations — the third category

The PS asks for detection of "missing, **misleading** or non-standard declarations." Misleading is its own thing: the declaration is present and correctly formatted, and still deceives. It's easy to skim past that word, and most teams will.

Scope it tightly, because full deception detection is a research problem and overclaiming is how projects get marked down.

**Build dual MRP.** A sticker pasted over a lower printed price. Genuinely common in Indian retail, visually obvious in a demo, and instantly recognisable to any Indian judge. Detection is geometric, which suits our pipeline — two MRP-pattern matches on the same panel, or an MRP box overlapping a detected sticker edge. That's `LMPC.MRP.OVERSTICKER` above.

**Two more come almost free**, because we already have the data:

- **Contradicting quantities** — two different net-quantity values extracted from one pack. Same `no_duplicate_field` check, different field.
- **Illegible declarations** — present but below the contrast threshold. The law treats an ambiguous or illegible declaration as a violation, so `LMPC.CONTRAST.NUMERALS` is a misleading check as much as a readability one.

Everything beyond this — false marketing claims, deceptive imagery, misleading pack shapes — is out of scope and we say so. Marking it as future work is stronger than pretending we handle it.

### Reports and summaries are two different documents

The PS asks for "compliance reports **and violation summaries**", and they serve different readers.

| | Report | Summary |
|---|---|---|
| Scope | One product | One drive, district or period |
| Reader | Officer, and eventually a court | Department, controller |
| Contains | Rule-by-rule verdicts, evidence photo, measured heights, remediation | Counts, top violation types, repeat offenders, coverage, officer activity |
| Format | PDF + editable | PDF + editable |

The summary is a straight aggregation over scan records, so it's cheap once the repository exists — and it's what makes the dashboard exportable rather than merely decorative. The dashboard is the live view; the summary is its printable form.

---

# 13a. Source document register

**Every value in the rulepack must trace to a document in this table.** No blog summaries, no recalled figures, no "this is probably right." One entry in the plan had wrong height thresholds taken from a vendor blog, and it would have made every verdict incorrect while looking confident. That is why this register exists.

All entries below are read from **gazette PDFs**, not mirrors. The register records what each one governs, **how much of it was actually read**, and what it changed — including when it changed nothing, because a "no impact" finding is a result and stops the document being re-read.

The coverage column is deliberate. An earlier version of this register said "read" against a document that had been *sampled*, and that is the same overclaiming that sank DISHA and PARAKH. **A sampled document is marked sampled.**

| # | Document | Gazette ref | Coverage | Effect on our build |
|---|---|---|---|---|
| 1 | **LM (Packaged Commodities) Rules, 2011** | GSR 202(E), 7 Mar 2011 | 43/43 read | **Primary source.** All 60 provisions catalogued in 13b. Corrected the Rule 7 height tables, added 30 provisions |
| 2 | **LM (National Standards) Rules, 2011** | S.O. 211(E), 31 Jan 2011 | **40/79** — full English section, OCR'd; Hindi half (1–39) is the same text | **Second most important document.** Third Schedule gives the SI prefix table and the symbol-printing rules — five new checks, see 13c. Rule 18 checked and rejected, see below |
| 3 | **LM (National Standards) (Amdt) Rules, 2019** | GSR 474(E), 5 Jul 2019 | 2/2 read | Substitutes rr. 4–10 with constant-based SI definitions. **No rulepack value changes.** Authority behind LMPC r.13(5)(i) |
| 4 | **LM (Numeration) Rules, 2011** | GSR 13(E), 7 Jan 2011 | 6/6 read | One encodable check (digit form, r.2(3)). Rule 4 grouping resolved as not applicable — see "The comma question". Schedule gives the numeration-in-words table |
| 5 | **LM (Numeration) (Amdt) Rules, 2011** | GSR 109(E), 23 Feb 2011 | 2/2 OCR'd | Commencement moves 1 Mar → **1 Apr 2011.** No substantive effect, but see "the lesson" below |
| 6 | **LM Act 2009 commencement** | S.O. 1(E), 31 Dec 2010 | 1/1 read | Appoints 1 Mar 2011 as the date the Act came into force. Context only |
| 7 | **LM (General) Rules, 2011** | GSR 71(E), 7 Feb 2011 | **356/655** — every English page OCR'd and keyword-scanned | **No impact, and now evidenced.** See the scan result below |
| 8 | **Corrigendum to GSR 71(E)** | GSR 317(E), 13 Apr 2011 | 1/1 read | Corrects three fee figures in the Twelfth Schedule. **No impact** |
| 9 | **LM (Approval of Models) Rules, 2011** | GSR 183(E), 1 Mar 2011 | **26/26 OCR'd** | **No impact — verified, not assumed.** Two "mandatory declaration" hits refer to markings on the *instrument being type-approved*, not on a package |
| 9a | **LM (Approval of Models) (Amdt) Rules, 2019** | GSR 823(E), 6 Nov 2019 | 2/2 read | Amends r.11, substitutes r.19 (test fees ₹10,000 mechanical / ₹25,000 digital). **No impact** |
| 9b | **Notification under Approval of Models rr. 3–5** | S.O. 824(E), 19 Mar 2014 | **7/7 OCR'd** | Authorises labs to receive model-test applications directly; two application forms. **No impact** |
| 10 | **Indian Institute of Legal Metrology Rules, 2011** | GSR 76(E), 8 Feb 2011 | **12/12 OCR'd** | Training institute, courses, advisory committee. **No impact** |

**Eleven documents, 834 pages of uploaded gazettes plus the 43-page LMPC Rules. 451 pages OCR'd to text this session.** Ten are read cover to cover; two are complete in English with the Hindi halves verified as duplicates below. Two documents changed the build. Nine are recorded as no-impact with evidence behind the finding.

**A note on the number.** An earlier version of this register said "fourteen documents in the 2011 family are being reviewed." That figure was never counted — it came from an expectation of how many files would arrive, and it sat here unchallenged. The family is eleven. If a number in this plan cannot be traced to something someone actually counted, it does not belong in the plan.

### How the no-impact findings were actually established

These gazettes are scanned images with no text layer, so reading them page by page visually is not feasible at this scale. They were converted to text with OCR at 120–200 DPI and then keyword-scanned for every term that could indicate label content.

Result across all 443 pages:

| Term | Occurrences outside LMPC |
|---|---|
| `packaged commodity` | **0** |
| `pre-packed` / `pre-packaged` | **0** |
| `retail sale price` / `MRP` | **0** |
| `net quantity` | **0** |
| `principal display panel` | **0** |
| `consumer care` | **0** |
| `font size` | **0** |
| `declaration` | 3, all instrument-related |
| `label` | 16, **all** referring to marks on instruments |

Every `label` hit in the General Rules is a metal disc stamped on a weight, a mark on a measuring instrument, or a ticket printed by a *price-labelling instrument* — the shop scale that prints a sticker for loose goods. None concerns a packaged commodity.

**This is a presentable artefact, not just diligence.** If a judge asks whether you read the whole legal family: *"834 pages across ten instruments. We OCR'd 443 of them and keyword-scanned every English page. 'Packaged commodity', 'net quantity' and 'MRP' appear zero times outside the Packaged Commodities Rules. Two documents govern labels; the other eight govern instruments, and we can show the scan."*

### Rule 18 — a promising lead that turned out to be nothing

National Standards Rule 18 says units in the **Seventh and Eighth Schedules** shall not be used in any field except scientific and technological research. That sounded like it would catch imperial units on a label — `1 lb`, `16 oz`, `5 inches`.

**It does not.** The Seventh Schedule is CGS units with special names — erg, dyne, poise, stokes, gauss, oersted, maxwell, stilb, phot. The Eighth is fermi, torr, kilogram-force, calorie, micron, X unit, gamma, lambda. Obscure scientific units, no imperial anywhere. Imperial on a label is already caught by the existing `LMPC.NETQTY.SI_UNITS` rule under LMPC r.13(5), not by rule 18.

**One trap inside it.** The *calorie* sits in the Eighth Schedule. A naive reading makes every nutrition panel printing `kcal` a violation. It is not — nutrition labelling is FSSAI's domain and mandates kcal, and LMPC does not govern nutritional declarations at all. **Do not encode it.** This is the third "we checked and declined to ship it" in this project, after the comma and the litre symbol, and the three of them together are a better answer to "how do you know your rules are right" than any accuracy number.

### Why skipping the Hindi halves loses nothing — verified, not assumed

Documents 2 and 7 are marked at partial coverage because only their English sections were OCR'd. Indian gazettes print the same instrument twice, Hindi first then English, so the Hindi pages should be a translation carrying no independent content. **That was an assumption, so it was tested.**

Numerals survive OCR regardless of script. Eight pages spread across the Hindi half of the General Rules were OCR'd and every numeric value extracted, then checked against the numbers found in the English half:

| Hindi page | Numeric values | Also present in English | Match |
|---|---|---|---|
| 60 | 1 | 1 | 100% |
| 180 | 7 | 7 | 100% |
| 290 | 3 | 3 | 100% |
| **310** | **59** | **59** | **100%** |
| **312** | **69** | **69** | **100%** |
| 120 | 6 | 3 | 50% |
| 240 | 10 | 7 | 70% |

The two dense specification tables — 59 and 69 values — reproduce exactly. The two weak rows are prose pages carrying six to ten numbers, where Devanagari characters OCR into spurious digits; the misses are artefacts, not missing data.

**Conclusion: the Hindi sections are translations and carry no value absent from the English.** For the Numeration Rules this is directly confirmed rather than inferred, because all six pages were read and pages 1–3 mirror pages 4–6.

Direct proof for one document, strong numeric evidence for the largest one. Good enough to stop, and stated so nobody has to re-litigate it in week four.

### The lesson buried in document 5

The principal Numeration Rules gazette (#4) states commencement as **1 March 2011**. That is wrong today, because #5 amended it to **1 April 2011** six weeks later. Reading only the principal rules gives you a date that has not been correct since February 2011.

This is the register's whole argument in one example, and it runs in both directions: **a bare act is not authoritative on its own, and neither is a mirror site.** You need the principal document *and* every amendment to it. Which is exactly why row #1 still carries a warning — the LMPC principal rules are in hand, but the amendments after 2011 are not.

### What the General Rules do not contain

Document 7 is 655 pages and it is tempting to treat that bulk as important. It is not, for us — and that is now a scan result rather than an impression formed from the first page.

It specifies the physical construction of weights and measures: reference, secondary and working standards, permissible errors on metre bars and capacity measures, materials, sealing points, verification periods, importer registration, and the fee schedules. **`packaged commodity`, `net quantity`, `MRP` and `principal display panel` appear zero times in all 356 English pages.** A label cannot violate the General Rules.

One adjacency worth knowing about, though it creates no rule: the General Rules regulate **price-labelling instruments** — the shop scale that weighs loose goods and prints a price ticket. That ticket is a common carrier of the pasted-over-MRP problem our `LMPC.MRP.OVERSTICKER` check targets. The instrument is governed there; the sticker it produces is governed by LMPC r.18(5), which we already encode. Useful context for a question about where shop-printed labels fit, not a sixth rule.

### How to use this register

**Every rule in the pack carries a `rule_ref` and the pack carries a `source`.** When a document arrives, one person reads it and adds a row — the finding, or an explicit "no impact." Documents 6, 7 and 8 almost certainly touch nothing we build, but the row still gets written so nobody reads them twice.

Two entries deserve attention when they arrive. **Document 5, the Numeration Rules**, is the one most likely to change a check, because how a numeral may lawfully be written bears directly on our MRP and quantity patterns. **Document 3** completes the unit symbol list that document 2 amends.

### What this register is *not*

It is not a reading list to complete before building. Documents 1 and 2 already cover the declaration rules, the height tables, the placement geometry and the unit authority — which is everything the eleven check types need. **The remaining twelve are verification, not blockers.** If a document arrives late, the rulepack version bumps and the YAML changes; no code moves.

Say that if asked how the system handles legal change: *"our legal logic is 40 KB of YAML with a version string and a source register. A new notification is a data edit, not a release."*

### The comma question — resolved, and the answer is "don't build it"

Both the Numeration Rules and the National Standards Rules prohibit comma separators, and the second one does it in terms that point straight at us.

**Numeration Rules 2011, rule 4** — writing a number exceeding three digits, the decimal point is the starting point; under Indian terminology the first three digits group together and subsequent digits divide into groups of two, under English terminology into groups of three, and in both cases *neither dots nor commas shall be inserted in the intervening spaces.* The gazette's own examples are `23 14 345.732 23 50` and `123 345.732 456`.

**National Standards Rules, Third Schedule, item 11** is the sharper one, because it is expressly about *numbers in connection with units of weights and measures*: the dot separates the integral part from the decimal part, numbers divide into groups of three from the decimal point, and neither dots nor commas go in the gaps. Its illustration is explicit — write `3211 468.022 82`, **not** `3,211,468.022.82`.

So on the face of it, `Net Wt. 1,500 g` is unlawful and `Net Wt. 1 500 g` is correct.

**We are still not building this check.** Three reasons, and the third is the one that settles it.

- **It does not reach the MRP.** Item 11 governs numbers used with units of weight or measure. A retail sale price is a monetary amount, not a measurement. `MRP Rs. 1,250.00` is outside the clause entirely, and the MRP is where the commas actually appear on real labels.
- **The magnitude rule makes it almost unreachable on net quantity.** Third Schedule item 10 requires the multiple to be chosen so the numerical value falls between 0.1 and 1000. A compliant net quantity is therefore `1.5 kg`, never `1500 g` — so a four-digit quantity that would need grouping is *already* a violation of item 10, which is a cleaner and better-founded finding. Flagging the comma would be flagging a symptom.
- **A rule that fires on every product in India is a rule being read wrong.** Enforcement has never treated the comma as an offence. Shipping it would generate mass false violations and destroy the tool's credibility with the one user who matters.

**What we build instead:** `LMPC.QTY.UNIT_MAGNITUDE` (already in the pack) now cites Third Schedule item 10 alongside LMPC r.13(2)–(3), and gains an upper bound it was missing — the old regex only caught `0.5 kg`, not `1500 g`. Commas are accepted everywhere in extraction via the `amount` pattern.

The presentable version: *"we found a clause that would make every label in India non-compliant, traced why it does not apply, and built the rule underneath it instead."* A team that can explain why it declined to ship a finding reads better than one that ships it.

### Still missing, and flagged honestly

**The 2011 family is closed.** All ten instruments in it are accounted for. What is missing is a different year.

The LMPC text we hold is the **2011 principal version**, and the gazette PDFs of later amendments are not in the register. Their status has been checked individually rather than left open:

| Amendment | Status | Moves the rulepack? |
|---|---|---|
| GSR 128(E), 13 Feb 2026 — inserts r.6(10A) | Confirmed via legal databases | **No.** Platform filter obligation, not a labelling rule |
| GSR 312(E), 27 Apr 2026 — substitutes r.6(10A) | Confirmed via legal databases | **No.** Supersedes the above, same subject |
| 30 Sep 2011 (GSR 734(E)) | Referenced inside our own PDF | Extends a packaging-material transition date, long expired |
| 24 Oct 2011 (GSR 748(E)) | Referenced inside our own PDF | Withdrew provisos; already reflected in the text we read |
| "23 Oct 2025, medical devices" | **Unverified.** Came from a secondary source and never confirmed | Unknown — treat as not held |

**So no confirmed amendment changes any rule we encode.** The one outstanding claim is the medical-devices notification, and until someone produces that gazette it stays out of the rulepack rather than being cited on trust. Obtaining the LMPC amendment PDFs is still worth doing — but it is now a verification task, not a blocker.

`amendments_included` stays empty, `amendments_checked` records the four whose effect we have confirmed, and `amendments_unverified` isolates the one claim nobody has evidenced. **The version string never claims an amendment the register cannot support.** The country-of-origin rule was not kept on trust — it was investigated, found to be a platform obligation rather than a labelling requirement, and removed.

---

# 13b. Complete coverage of the rules, and where we stop

We catalogued all 60 substantive provisions of LMPC 2011, including the seven schedules. This section is the completeness proof and, more importantly, **the scope boundary** — the thing that stops this project sprawling into elimination.

### The legal authority for the whole project

**Rule 21(1)** says quantity tests are ordinarily *not* carried out at a retail dealer's premises — **except** in three cases, of which **21(1)(iii)** is that any package does not bear all or any of the declarations required under these rules.

Read that carefully. Weighing a pack in a shop is restricted. **Checking its declarations in a shop is expressly permitted.** Our tool operates entirely inside 21(1)(iii). That is the statutory basis for a field inspection tool, written by the sponsoring ministry, and it should be one line in the presentation.

### What we deliberately do not do

| Out of scope | Why |
|---|---|
| Net quantity accuracy (Schedule I, maximum permissible error) | Requires physically weighing the pack. A camera cannot do it |
| Sampling procedure (Schedule V: lot <4000 → 32 samples) | Physical process at a factory |
| Tare and gross determination (Schedule VI) | Requires a balance |
| Rules 19–20, inspection at manufacturer premises | Factory-floor procedure, not field |
| Rule 18(2), sale above MRP | Needs the price actually charged; officer input, not the label |
| Rule 18(7), retailer's weighing machine | Premises check, not a package check |
| **Rule 6(10A), e-commerce country-of-origin filter** | **A platform-architecture obligation. Verifying it means testing a website's filter, not reading a label** |

**Say this out loud.** A team that names what its tool cannot do reads as competent. Every one of these needs a physical balance, and claiming otherwise is exactly the overclaiming that sinks projects.

### Rule 6(10A) — confirmed, and confirmed to be out of scope

This one is worth setting out, because we had it wrong and the error was the kind that survives review.

The amendment is real. **G.S.R. 128(E) of 13 February 2026** inserted sub-rule 6(10A) after 6(10), in force 1 July 2026:

> *Every e-commerce entity selling imported products shall provide the product listings of such imported products in a searchable and sortable filter specifying the country of origin.*

**That is not a labelling rule.** It places an architecture obligation on an *e-commerce platform* — build a working filter on your website. It says nothing about what is printed on a package. Our rulepack previously cited 6(10A) for a check that a photographed pack declares its country of origin. Wrong law, confidently cited, on a legal document.

It had also already been superseded. **G.S.R. 312(E) of 27 April 2026**, the Second Amendment Rules, substitutes 6(10A) entirely with effect from 1 July 2027. **The rule was amended twice in ten weeks**, which is a better argument for keeping rules as versioned data than anything we could invent.

Two consequences:

**No package-level country-of-origin rule.** Nothing in the 2011 principal rules requires it on the pack. Rule 6(1)(a) requires the **name and address of the importer** for an imported package, and that is what `LMPC.IMPORTER.PRESENT` now checks, citing a provision that exists in a document we hold.

**6(10A) compliance is not checkable by this tool, at all.** Verifying it means loading a marketplace and testing whether its filter works — a platform audit, not a package audit. It belongs in the out-of-scope table beside net-quantity weighing.

*(Both amendments were confirmed through legal-database and law-firm sources. The gazette PDFs are not in our register, so neither is listed as `amendments_included` — nothing in either changes a rule we encode.)*

### Gates that must run before any rule

Applying a rule to a package the rule does not govern produces a false violation, which is worse than missing a real one. Six gates:

| Gate | Rule | Effect |
|---|---|---|
| Size | 3(a) | >25 kg or 25 L out of scope; cement and fertiliser up to 50 kg stay in |
| Buyer | 3(b) | Industrial or institutional consumer out of scope |
| Small pack | 26(a) | ≤10 g or 10 ml fully exempt |
| Category | 26(b)(c)(d) | Restaurant fast food, DPCO drugs, farm produce >50 kg exempt |
| **Package type** | **24** | **Wholesale packages need only three declarations, not six** |
| Other law | 7(4) | Height rules disapply where another statute mandates the same information |

Plus per-commodity carve-outs worth encoding because they are demo-visible: bidis and incense sticks need no date; bidis and administered-price LPG need no MRP; returnable soft-drink bottles may carry `MRP Rs...` on the crown cap.

**The wholesale gate is the one most teams will miss.** A wholesale carton under Rule 24 needs only the manufacturer, the identity of the commodity, and the count or net quantity. Run retail rules against it and every scan produces four false violations.

### Checkable provisions we had not planned for

Thirty provisions came out of the schedules and later chapters. The ones worth building:

**Rule 12(2) with the Fourth Schedule** — the unit of declaration is fixed per commodity. Curd by weight. Ready-made garments by number. Tyres and tubes by number. Cosmetics by weight or measure. Ice cream by weight. Twenty-six entries, a pure table lookup, and a violation that no human inspector remembers to check.

**Rule 13(2)–(3)** — unit selection by magnitude. Under one kilogram must be expressed in grams; under one litre in millilitres. A pack declaring "0.5 kg" instead of "500 g" is non-compliant. Trivial to check, invisible to the eye.

**Rule 6(2)** — consumer care requires name, address **and telephone number**, with e-mail if available. We had only name and address, so we would have passed packs that fail.

**Rule 18(5)** — a dealer must not obliterate, smudge or alter the MRP. This is photo-detectable and it is **the retailer's offence, not the manufacturer's** — a different respondent on the notice, which matters for the report.

**Rules 14, 16, 17** — category-specific extras: sarees and bed-sheets need finished dimensions per piece; foil and tissue need the count of usable sheets and sheet dimensions; bags and cups need count plus linear dimensions.

**Rule 9(2)–(3)** — a declaration must not be readable only through the liquid contents, and an outer wrapper must repeat the declarations unless it is transparent.

**Rule 11(4) with the Third Schedule** — "when packed" is permitted only on soaps, lotions and cream. Anywhere else it is a violation.

**Rule 31(1)–(2)** — an advertisement quoting MRP must state net quantity, at the same font size. This applies directly to our listing-text channel and is checkable without any image.

### The report must match the statutory form

**Rule 19(2) and the Seventh Schedule** prescribe Form A (weight checking) and Form B (volume and length). Both have a fixed structure: particulars of package, commodity classification, lot and sample size, checking data, results, general comments on compliance with the Act, and signature blocks for the authorised person and the manufacturer's representative or a competent witness.

Our per-product report should **mirror Part A, Part E and Part F of that form** — package particulars, general compliance comments, signature block — while leaving the weight-checking sections (Parts B, C, D) marked *not applicable, declaration check only*.

That single decision is worth more than any feature. An officer receives a document already shaped like the one they are required to file, and it makes the omission of weight checking explicit rather than hidden.

---

# 13c. Unit symbols — the checks nobody else will find

LMPC rule 13(5)(i) says net quantity must be declared in SI units and no other system. It does not say *how the symbol must be written*. That is in the **National Standards Rules 2011, Third Schedule** — a 79-page scanned gazette about national measurement standards, which looks entirely irrelevant to package labels and is where the most checkable rules in this project are hiding.

They are worth building because they are pure string checks on text OCR already gives us: no geometry, no model, no ambiguity, and near-zero false-positive risk.

### Third Schedule, item 7 — printing of unit symbols

| Requirement | Compliant | Violation |
|---|---|---|
| 7(1)(b) symbols unaltered in the plural | `500 g` | `500 gs`, `2 kgs`, `5 ltrs` |
| 7(1)(c) no final full stop unless context requires | `500 g` | `500 g.`, `1 kg.` |
| 7(1)(d) symbol placed after the complete numerical value, **with a space** | `500 g` | `500g`, `1kg` |
| 7(2) lower case, **unless the unit is named after a person** | `g`, `kg`, `ml`, `cm` | `500 G`, `250 ML`, `1 KG` |

That last row is the valuable one. `250 ML` is printed on an enormous number of Indian packs and it is not the prescribed symbol — `ml` is. The proper-name carve-out is why `N` (newton), `Pa` (pascal), `A` (ampere) and `K` (kelvin) keep their capital, and it must be encoded as an exception list rather than a blanket lower-case rule.

Two more from the same schedule: prefix symbols attach to the unit **with no space or dot** between them (item 2), and multiples of mass are formed on the *gram*, so `mg` is right and `µkg` is wrong (item 6).

### Third Schedule, item 10 — expression of results

The multiple or sub-multiple must be chosen so the numerical value falls **between 0.1 and 1000**. This is the firmer source for the magnitude check we already had from LMPC r.13(2)–(3), and it supplies the upper bound that rule was missing: `1500 g` should be `1.5 kg`, just as `0.5 kg` should be `500 g`.

### Fourth Schedule — permitted units

Litre is a **permitted** unit rather than an SI unit, with the symbol given in the gazette as lower-case **`l`**, equal to one thousandth of a cubic metre. Tonne is permitted for mass with symbol **`t`**, equal to 1000 kg, and only the prefixes kilo, mega, giga and tera may be used with it.

**Handle the litre carefully.** The gazette says `l`; international practice and BIPM accept `L` as well, and virtually every Indian beverage label uses `L` or `Ltr`. Encode `LMPC.UNIT.LITRE_SYMBOL` at severity `low`, **defaulted off**, and say in the report that it is disputed. `Ltr` and `LTR` are separately caught by the plural and case rules anyway, which rest on firmer ground.

### Numeration Rules, rule 2(3) — digit form

Numbers must be represented using the **international form of Indian numerals, `0`–`9`**. A label printing net quantity or MRP in Devanagari digits (`५००`) is non-compliant. Rare, cheap to check, and a genuine finding when it appears.

### What this adds to the pack

Five checks, all string-level, all traceable to a gazette page:

`LMPC.UNIT.SYMBOL_CASE` · `LMPC.UNIT.SYMBOL_PLURAL` · `LMPC.UNIT.SYMBOL_STOP` · `LMPC.UNIT.SYMBOL_SPACE` · `LMPC.NUM.DIGIT_FORM`

**Severity should be `low` for all five.** They are formatting defects, not consumer deception, and a tool that reports `250 ML` at the same severity as a missing MRP is a tool an officer stops trusting. Report them in a separate "minor / advisory" block in the PDF.

The Q&A line: *"most teams will read the Packaged Commodities Rules. The rules that say how a unit symbol must actually be printed are in the National Standards Rules, Third Schedule, and that is where five of our checks come from."*

---

# 14. Models, training, and what we refuse to train

Most of this system is not machine learning, and that's deliberate.

| Component | Trained? |
|---|---|
| Package and panel detection (B2) | Yes — RTMDet-Ins-tiny, fine-tuned. Apache-2.0 |
| Field classification | Yes — small layout-aware head |
| OCR recognition | Only if measured to be necessary |
| Dual-MRP detection | Small head sharing the detector backbone |
| Rectification, scale, measurement | No — deterministic geometry |
| Readability and contrast | No — pixel statistics |
| **Compliance decision** | **Never** |

### Why not a vision-language model

The 2026 instinct is to reach for Surya 2, olmOCR, dots.ocr or PaddleOCR-VL. We reject them as a source of truth for two reasons.

First, published comparisons flag that VLM OCR fabricates values on exactly the numeric fields a pipeline cares about — and ours are MRP and net quantity. A tool that invents an MRP and attaches it to a legal notice is worse than no tool.

Second, they emit markdown, not pixel geometry. **Box height is our measurement.** Detection-based OCR gives us coordinates natively; VLMs largely don't.

Worth knowing too: on clean printed text the best traditional engine essentially ties the best VLM on character accuracy, and packaging is clean printed text. So we use a VLM in exactly one place — suggesting a field mapping when an unfamiliar layout appears — and never for numbers or measurement. **Saying why we rejected the fashionable option is stronger than having used it.**

### The detector

RTMDet-Ins-tiny, COCO-pretrained, fine-tuned on our corpus, exported INT8 ONNX via mmdeploy. Losses are framework defaults; tuning them isn't where our marks are. Licence rationale in section 15b.

*Done when:* package mAP@50 ≥ 0.85, PDP mask IoU ≥ 0.85, **zero false packages across the 60 negative photos**, under 120 ms in-browser on WebGPU.

### The field classifier

Regex handles MRP, dates, net quantity, batch and country of origin in both scripts — these have strong lexical shape, and a pattern is more explainable than a model.

A trained head handles what regex genuinely cannot: **manufacturer versus packer versus importer versus consumer care.** All four are just addresses. The distinguishing signal is position and context, not vocabulary.

Features: text embedding, normalised box coordinates, relative font size, panel id, script. About 2M parameters — LayoutLMv3's 125M would overfit 400 photos badly. Focal loss, γ=2.

*Done when:* per-field F1 ≥ 0.85, and ≥ 0.90 on MRP specifically since everything depends on it. Report per class, never averaged.

### OCR fine-tuning

Don't start here. Run the PP-OCRv5 baseline and record CER by surface type. Fine-tune only if it fails, only on what fails, recognition head only, CTC loss. Likely failures: foil glare, stylised brand fonts, curved bottles, low-contrast kraft paper.

"CER dropped from 0.19 to 0.07 on foil packaging after fine-tuning" is a far better slide than "we used AI."

### Negatives, which matter more than positives

**Detector negatives:** about 15% of training photos should contain no package at all — bare shelves, hands, price rails, floor. Without them the detector confidently boxes a shelf edge.

**Hard negatives for classification** are where accuracy actually comes from:

| Hard negative | Why it fools a model |
|---|---|
| `Rs. 20 OFF` | Price-shaped, but marketing |
| `Net wt. 500g` beside `Drained wt. 350g` | Two quantity-shaped strings, one is legal |
| Batch code `24MRP07` | Contains the literal string MRP |
| `Best before 9 months from mfg` | Date-shaped, not a date |
| Manufacturer vs consumer care address | Identical shape, different legal role |
| Barcode digits | Long numeric string |

Hunt these deliberately. **A model that has never seen `24MRP07` will label it an MRP the first time it appears — possibly on stage.**

**Class imbalance:** violations run maybe 10–15% of shelf products, so a model that always predicts "compliant" scores 87% and is useless. Three defences, the first strongest: **the verdict comes from rules, not a model**, so imbalance barely reaches the decision. Then focal loss where models are used, and report per-class recall on the violation class rather than overall accuracy. Missing a violation is the expensive error; a false flag costs an officer a minute.

**Augmentation:** perspective warps, ±15° rotation, barrel distortion, brightness and colour temperature, motion blur, JPEG artefacts, glare. No random scaling on the measurement test set — it destroys the ground truth. No horizontal flips; text doesn't mirror.

### Learning from use

Officer corrections are stored as labelled examples and feed periodic retraining. The system improves through use, and the labelling is done by people already doing the job — that's a deployment story, not a demo trick.

### Reproducibility

Every scan stores detector hash, OCR version, classifier version and rulepack version. A finding you cannot reproduce is a finding you cannot defend.

---

# 15. Retrieval — what kind, and why not the fancy kind

**Never in the decision path.** If a language model reads a retrieved clause and rules on it, the same photo can yield different verdicts on different days and nobody can explain why. Verdicts are deterministic YAML. Retrieval exists to *show an officer the law behind a verdict*, nothing more.

That single constraint decides the architecture, so state it before naming any technology.

### Size the corpus first

Twelve gazette documents, 498 English pages, roughly **1,700 clause-level chunks.** At 384 dimensions that is 2.7 MB as float32, or 0.67 MB quantised to int8.

This number kills most of the options:

- **Exact cosine over 1,700 vectors takes about 1.3 ms on CPU.** An HNSW or IVF index would take longer to build than brute force takes to run. We use `pgvector` with **no index** — a sequential scan is correct here, and saying so demonstrates you sized the problem rather than reached for the default.
- The whole corpus fits in browser memory, so the explainer can work offline at tier L1.

### The tier that isn't retrieval at all

Every `Verdict` already carries `rule_ref` — `"Rule 7(2), Table I"`, `"Rule 8(1) proviso"`. **The citation is the retrieval key.** We do not need to search for Rule 7(2); we know it is Rule 7(2).

| Tier | Trigger | Mechanism | Latency |
|---|---|---|---|
| **1. Citation lookup** | Officer taps "why" on a verdict | Dict lookup by `rule_ref` → verbatim clause text | <1 ms, deterministic, **always correct** |
| **2. Hybrid search** | Officer types a free-text question | BM25 + dense, fused | ~40 ms |
| **3. Grounded answer** | Only after tier 2 | Extractive, see below | ~1 s |

**Tier 1 covers the overwhelming majority of use.** It is a JSON file keyed by clause reference, and it is not RAG in any meaningful sense. Build it first; it is an afternoon's work and it is the feature officers will actually use.

### Tier 2, specified precisely

**Hybrid, not pure dense.** Legal text is full of exact terms of art — *principal display panel*, *pre-packaged commodity*, *maximum permissible error*. Dense embeddings blur these; BM25 nails them. Pure semantic search is the wrong tool for statute.

- **Lexical:** Postgres native `tsvector` with `english` config. No new dependency
- **Dense:** `bge-small-en-v1.5` — 33M parameters, 384 dimensions, ~130 MB, Apache-2.0, exports cleanly to ONNX so the identical model runs server-side and in the browser. Chosen over `bge-base` because at 1,700 chunks the accuracy difference is invisible and the size difference is 4×
- **Fusion:** Reciprocal Rank Fusion, `k=60`. No tuning, no learned weights, one line of SQL
- **Reranking:** none. A cross-encoder over 1,700 chunks buys nothing measurable and costs 300 ms

**Chunking is the decision that actually matters.** Statutes have natural boundaries — rule, sub-rule, clause, proviso, explanation. Fixed 512-token windows would cut Rule 8(1) away from its proviso, and the proviso *is* the exclusion-zone rule. So: **structure-aware chunking on the numbering hierarchy**, one chunk per sub-rule, provisos and explanations attached to their parent, each chunk carrying `{doc_id, rule_ref, parent_ref, text}`.

### Tier 3 — and why generation is mostly switched off

**Default: extractive, not generative.** Display the verbatim gazette text with the matched span highlighted. No model writes anything.

For a legal enforcement tool this is the stronger position, not the lazy one. A generated paraphrase of a statute is an unattributed restatement of law that nobody signed off. The verbatim clause is the actual authority.

Where a plain-language summary genuinely helps, it runs under three constraints: **strictly extractive-grounded** (every sentence traceable to retrieved text), **always displayed beside the verbatim clause and never instead of it**, and **clearly labelled as a summary.** Model: `Qwen2.5-3B-Instruct` or `Llama-3.2-3B-Instruct`, int4, self-hosted — small enough to run on the same box as the API and open-weight so there is no per-call cost or data-residency objection.

### What we deliberately did not build

| Rejected | Why |
|---|---|
| **Agentic / multi-hop RAG** | Built for questions needing several retrieval rounds. Ours need one clause |
| **GraphRAG** | Entity-graph construction over 1,700 chunks costs more than it returns |
| **HNSW / IVF indexing** | Slower than brute force at this corpus size |
| **Cross-encoder reranking** | 300 ms for no measurable gain over 1,700 chunks |
| **Fine-tuned embeddings** | No labelled query set exists, and building one is not this project |
| **Generative-first answers** | Paraphrasing statute in an enforcement tool is a liability, not a feature |

**The presentable line:** *"We sized the corpus before choosing an architecture. It is 1,700 clauses, every verdict already carries its own citation, so retrieval is a dictionary lookup in the common case and a hybrid BM25-plus-dense search in the rare one. We index nothing, rerank nothing, and generate nothing by default — because at this scale those would all be slower and less accurate."*

**Scope:** tier 1 is a week-5 feature and worth building. Tiers 2 and 3 are week 7. **Cut them first if time runs short** — but have this reasoning ready for "why didn't you use an LLM for the rules?"

---

# 15b. Technology decisions, stated precisely

A product name is not a decision. "We used PaddleOCR" invites *which models, which version, what size, why not the other one* — and having no answer reads worse than having chosen differently. Every choice below is pinned to a variant, with the alternative that was rejected.

### The B2 model decision — settled on licence, not mAP

**RTMDet-Ins-tiny. Not YOLO11n-seg.** The two are close on accuracy and speed; the licence is not close at all.

Ultralytics YOLO11 is **AGPL-3.0**, and the terms are stricter than most teams realise. Ultralytics state that the licence covers the training code *and the models produced by it*, that custom-trained versions remain AGPL-3.0, and that compliance means publicly releasing the complete source of the entire derivative work — application, configs, scripts and weights. AGPL also closes the SaaS loophole: **hosting the model behind an API counts as distribution and triggers disclosure.** Anything else needs a paid Enterprise Licence.

Now apply that to what we are actually building. A Legal Metrology department deploying this behind an API for officers across a state would be distributing under AGPL — obliging them to publish their entire stack, or buy a commercial licence for a tool we are pitching as free. **That is a procurement blocker, and it is a fair question for a judge to ask.**

RTMDet is Apache-2.0 through MMDetection, which OpenMMLab describes as usable freely without restriction by industrial users. No obligation attaches to the department, ever.

**Known friction, and the mitigation.** RTMDet-Ins ONNX export has a documented history of trouble — mmdeploy issues #1967 and #1990 — although support was merged in PR #1662 with a dedicated `instance-seg_rtmdet-ins_onnxruntime_static-640x640.py` config. Pre-exported artefacts also exist publicly, including OpenVINO IR builds and repackaged checkpoints. **If the export fights us for more than a day, take a pre-exported ONNX rather than debugging mmdeploy.**

**And question whether B2 needs segmentation at all.** Guided capture means the pack usually fills the frame, and B3's contour-and-quadrilateral step already recovers the label boundary for rectification — which is the PDP polygon in most flat-label cases. If instance-segmentation export proves painful, fall back to bounding-box detection plus classical quad recovery and lose very little. **Benchmark this in week 2 before investing in the harder path.**

### Vision

| Role | Exact choice | Size | Why this variant |
|---|---|---|---|
| Text detection | **PP-OCRv6 `small_det`**, ONNX INT8 | ~9.5 MB (2.48M params) | v6 released 11 Jun 2026 with PaddleOCR 3.7; LCNetV4 + RepLKFPN. `small` over `tiny` (0.43M) because our declarations are the smallest print on the pack — benchmark both, downgrade only if field recall holds. Detection is script-agnostic, so v6 serves Hindi and English alike |
| Text recognition | **PP-OCRv5 Devanagari mobile `rec`**, ONNX INT8 | ~7.5 MB | **Not v6 here.** PP-OCRv6's 50 languages are Chinese, Japanese and 46 *Latin-script* — Devanagari is not among them. v5's Devanagari recogniser covers Hindi and Marathi and handles English too. Benchmark whether a second English-only head earns its bundle size; do not assume it |
| Cross-check | **docTR `db_resnet50` + `crnn_vgg16_bn`** | server only | Second opinion on low-confidence crops. Disagreement between engines is a confidence signal, and it never runs in the browser |
| Package isolation (B2) | **RTMDet-Ins-tiny** (OpenMMLab), ONNX INT8 | 5.6M params | **Apache-2.0 — this is the deciding factor, not accuracy.** See the licensing note below |
| Geometry | **OpenCV 4.10** — `findContours` → `approxPolyDP` → `getPerspectiveTransform` → `warpPerspective` | — | Deterministic. No model involved in any measurement |
| Scale reference | **`cv2.aruco` ChArUco marker**, known physical size, printed on the inspection card | — | Four sub-pixel corners give scale *and* homography from one detection. A coin gives one foreshortening diameter — it reads as an ellipse the moment the camera tilts, and `HoughCircles` is unreliable on shop lighting. Marker replaces coin throughout |
| Perceptual hash | **pHash (DCT-based), 64-bit**, Hamming ≤ 8 | — | dHash and aHash are faster but break under the lighting variation of shop photography, which is exactly our condition |
| SKU near-duplicate | **MobileNetV3-Small** penultimate layer, 576-d → PCA to 512-d | ~4 MB | Reuses a model already in the bundle. A dedicated embedding model for label matching is not worth 90 MB |

**Browser execution — a shipped path, not a conversion project.** We do not convert Paddle graphs ourselves. Maintained MIT packages already run PP-OCRv5 through ONNX Runtime Web:

| Package | What it gives us |
|---|---|
| **`ppu-paddle-ocr`** (MIT) | PP-OCRv5 graphs, WebGPU acceleration, INT8 quantisation, 40+ languages. Runs in browser, web worker and React Native from one API. Reports **99.22% character accuracy on a receipt benchmark** — the closest public analogue to packaging: small, dense, low-contrast print |
| `@paddleocr/paddleocr-js` | The more official route — PP-OCRv5 via ONNX Runtime Web plus OpenCV.js, worker mode built in |
| `client-ocr` | RapidOCR + PaddleOCR, explicit Hindi support, PWA offline caching |

Start with `ppu-paddle-ocr`; it is the fastest to stand up and the INT8 + WebGPU story matches our budget. Keep `@paddleocr/paddleocr-js` as the fallback if we hit an op-support wall.

**Deployment requirement — do not miss this.** Multithreaded WASM only runs when the page is **cross-origin isolated**. That needs two response headers:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

Without them ONNX Runtime pins `numThreads` to 1 and **the WASM fallback path roughly doubles in latency**. This is a server config line, but it belongs in the deployment document — otherwise the L1 offline path is quietly half speed on every device without WebGPU.

**Execution provider:** WebGPU first, WASM SIMD + threads as fallback. Detect at load and record which path ran in `scans.model_versions`, so every latency figure is attributable to a backend.

### Field classification

Regex tier first, and **measure before building the model.** If patterns separate the fields adequately on the corpus, ship without a classifier — fewer parts, more explainable, nothing to overfit.

If a model is needed, it handles only manufacturer vs packer vs importer vs consumer_care:

- **Architecture:** 2-layer transformer encoder, 4 heads, `d_model=128`. **~2M parameters**
- **Input:** `MiniLM-L6` sentence embedding (384-d, frozen) ‖ normalised box `[x,y,w,h]` ‖ relative font size ‖ panel one-hot ‖ script one-hot
- **Rejected:** LayoutLMv3-base at 125M parameters. On ~400 photos it memorises the training set. Being able to say *"we chose 2M over 125M because our corpus is 400 images"* is a better answer than the bigger number

**Loss:** focal, γ=2, α balanced by inverse class frequency. **Optimiser:** AdamW, lr 3e-4, cosine schedule, 30 epochs, early stop on validation macro-F1.

### Detector training

**RTMDet-Ins-tiny** from COCO weights, `rtmdet-ins_tiny_8xb32-300e_coco`. 640 px, batch 16, AdamW lr 1e-3 (MMDetection default schedule, cut to ~100 epochs on our corpus size), early stop on val mask mAP. Augmentation is set explicitly because the defaults are wrong for us: **mosaic off** (it fabricates impossible multi-pack scenes), **horizontal flip off** (text does not mirror), mild perspective and ±15° rotation, and value-channel jitter for shop lighting. **Never scale-augment the measurement test split.**

### Backend

| Layer | Exact choice | Why this and not the neighbour |
|---|---|---|
| API | **FastAPI 0.115 + Pydantic v2**, async, `uvloop` | Pydantic v2 is Rust-backed; v1 validation would show at bulk-upload volume |
| Queue | **Dramatiq 1.17 + Redis 7** | Rejected Celery: heavier, worse defaults, more configuration for the same job |
| DB | **PostgreSQL 17 + pgvector 0.8** | One store. `vector(512)` for SKUs. **No index on the 1,700-row rule corpus** — sequential scan is faster |
| SKU index | **HNSW**, `m=16`, `ef_construction=64` | Here an index *is* justified: SKU count grows without bound, unlike the rule corpus |
| Objects | **MinIO**, versioned write-once bucket for evidence | S3-compatible, self-hosted, no cloud dependency |
| PDF | **WeasyPrint 62** | Rejected ReportLab: we would write the report layout twice. One HTML template renders both formats |
| Editable | **python-docx 1.1** | Explicitly required by the PS |
| Migrations | **Alembic** | — |

### Frontend

**Next.js 15.1 App Router · React 19 · TypeScript 5.7 strict · Tailwind 4 · shadcn/ui · Recharts 2.15.**

- **Types:** generated from the FastAPI OpenAPI schema via `openapi-typescript`, so frontend types cannot drift from `contracts/`
- **Client state:** TanStack Query v5 for server cache and optimistic corrections. **No Redux, no Zustand** — server state plus URL params covers every screen, and adding a store here reads as inexperience
- **PWA:** Workbox 7. Models cached `CacheFirst` with explicit versioning; API `NetworkFirst`; app shell precached
- **Offline store:** IndexedDB via `idb` 8 — outbox, SKU cache, rulepack

### Testing and CI

**pytest + pytest-benchmark + Playwright + GitHub Actions.** Ruff for lint, mypy strict on `contracts/` and `rules/`. Benchmark job fails the build on latency regression against section 4's budget.

### The rule for the whole table

If a judge asks "why this and not X", there must be a sentence. Where there isn't one yet — and there are a few — **make the choice from a measurement in week 2, not from a preference.**

---

# 16. Building the dataset

Nobody supplies one. We make it, and that's an advantage rather than a burden because we control what's in it.

**Tool:** Label Studio, self-hosted.

**Per photo:** a box per package, a polygon for the PDP, polygons for other visible panels, one box per declaration labelled with its field name and script, and a box on the ChArUco marker card if present.

**Test split only:** ruler-measured height in millimetres per declaration to 0.1 mm, plus physical label width and height.

**Rules that stop annotators disagreeing.** Measure cap height — top of a capital letter to the baseline, excluding descenders — and write that on the wall. The MRP box covers the full declaration including "(inclusive of all taxes)", but the height measurement uses the numerals only. Text spanning a fold gets the largest flat readable run. Anything a human can't read is labelled `other`, never guessed. Promotional price graphics are `marketing_text`, never `mrp`. A second annotator signs off every photo's field labels.

**Corpus targets:**

| Property | Target |
|---|---|
| Distinct SKUs | 100 |
| Photos | ~400 |
| No package present (detector negatives) | ~60 (15%) |
| Curved surfaces | ≥25% |
| Foil or reflective | ≥15% |
| **Hindi or bilingual declarations** | **≥25%** |
| Contains a hard negative | ≥30 photos |
| **Non-food** (soap, cement, electronics, footwear) | **≥30%** |
| Test split, ruler-measured | 40 photos, 20 SKUs |

Two of those are strategic rather than technical. **Non-food at 30%** because competitors are food-first, and a demo checking a cement bag can't be mistaken for a nutrition app. **Bilingual at 25%** because without it we will confidently report violations that don't exist.

---

# 17. Module specs and acceptance criteria

A module isn't done because the code exists. It's done when the criterion is measurably met and the number is written into `RESULTS.md`.

**M0 Capture quality (B1).** Variance-of-Laplacian for blur, histogram statistics for exposure, saturation clipping for glare, minimum-resolution check. No model. *Done when:* rejects the deliberately-bad subset of the corpus (motion blur, foil glare, underexposed) at ≥90% recall while passing ≥98% of usable photos, in under 15 ms.

**M1 Rectify.** Edge detection, largest quadrilateral, perspective transform, warp; falls back to the detector box when no clean quad is found. *Done when:* printed lines deviate under 2° from horizontal after warping, across the 40 test photos.

**M2 Scale, three tiers.** Tier A detects a printed ChArUco marker of known size. Tier B uses known SKU dimensions from the repository. Tier C returns no `mm_per_px` at all — and the two `scale_free: true` rules still run, along with every presence, format, placement and unit-symbol check. **Only the three `min_height_mm` rules go dark at Tier C.** *Done when:* tier A mean absolute error ≤ 0.15 mm against ruler ground truth. **Build C first** — no props needed and it validates the whole geometry path. Then A, the demo moment. B falls out free once the repository fills, and it's the elegant one: the more the system has seen, the less it needs the marker.

**M3 Detect.** As section 14. *Done when:* mAP ≥ 0.85, PDP IoU ≥ 0.85, zero false positives on negatives, under 120 ms.

**M4 OCR, ROI only.** Never OCR the full image; detection supplies the crops. Devanagari and Latin both enabled. *Done when:* baseline CER recorded per surface type before any fine-tuning decision, and the ROI path at least 5× faster than full-image on the same photos.

**M5 Classify.** Regex tier plus trained head. *Done when:* per-field F1 ≥ 0.85, MRP ≥ 0.90.

**M6 Rules.** A pure function from DeclarationSet and rulepack to a list of verdicts. No I/O. *Done when:* unit tests cover all eight check types against synthetic fixtures, it runs identically on `listing_text` with geometric rules returning NO_DATA, and 30 rules evaluate in under 10 ms.

**M7 Evidence.** Canonical JSON, SHA-256, chained to the previous record; photo hashed at upload into MinIO. *Done when:* `verify_chain()` detects any tampered historical record.

**M8 Reports.** One HTML template rendered by WeasyPrint to PDF and python-docx to editable. Contains product identity, per-rule verdicts with gazette references, annotated photo, measured heights with tolerances, degradation tier, remediation text. *Done when:* both formats generate from one scan and the DOCX opens and edits in Word.

**M9 Repository, cache and search.** Barcode lookup first, then pHash exact match, then pgvector cosine for near-duplicates. Search across brand, barcode, date, district, officer, rule and status. *Done when:* a repeat SKU returns a cached verdict in under 100 ms without running OCR.

**M10 Dashboard and summary.** Section 11, plus the exportable violation summary. *Done when:* summary exports to PDF and DOCX with counts, top violations, repeat offenders and coverage.

**M11 PWA.** Service worker for asset and model caching, `getUserMedia` camera, `onnxruntime-web` with WebGPU and WASM fallback, IndexedDB outbox, UUIDv7, resumable upload. *Done when:* a full scan completes in aeroplane mode, syncs without duplicates, cached bundle under 60 MB.

---

# 18. Testing, privacy, and audit

Three things that are invisible until someone asks, and then decisive.

### Testing

**Unit tests** cover the rules engine exhaustively — every check type, every status including NO_DATA and REVIEW, boundary values either side of each threshold. Fast, deterministic, and they're what lets us change the rulepack without fear.

**Golden-file tests** run the full pipeline over ten fixed photos and assert the DeclarationSet matches a committed JSON snapshot. This is how we catch a model update silently changing behaviour.

**Contract tests** validate API responses against the OpenAPI schema, and the frontend's Zod types are generated from that same schema, so frontend and backend cannot drift apart.

**Benchmark tests** enforce the section 4 latency budget and fail the build on regression.

**Manual:** the aeroplane-mode run, executed before every demo rehearsal.

### Privacy

Shop photographs can capture bystanders, and officer geolocation is personal data under the DPDP Act 2023. Neither is hard to handle, but both need a stated position.

Capture guidance frames the pack, not the shop. Faces detected in an evidence photo are blurred on upload, with the original retained only in the write-once bucket. Geolocation is stored at reduced precision — enough to identify a market, not a doorway. Retention follows section 6 and is documented.

None of this is asked for in the PS. All of it is the kind of question a government jury asks.

### Audit

Role-based access says who *can* see something. An audit log records who *did*. The `access_log` table captures user, action, entity and timestamp for every record view and export.

The distinction matters because the hash chain protects records from alteration but says nothing about who read them — and in an enforcement context, who looked at a pending case is exactly the question that eventually gets asked.

---

# 18b. What is proven, what is not, and how we settle it

A plan that claims everything will work is a plan nobody checked. This section separates the three, and gives each unknown a test, a threshold and a fallback. **Nothing here is a leap of faith — every open question is answered by a measurement in the first two weeks.**

## Settled — build on it without worrying

| Component | Why it is not a risk |
|---|---|
| Perspective correction, ChArUco scale | OpenCV, deterministic, decades old. No model, no variance |
| Rules engine over YAML | ~200 lines. The only risk is encoding a rule wrongly, which is a review problem |
| PaddleOCR in the browser | **Solved.** MIT packages ship PP-OCRv5 through ONNX Runtime Web today, with WebGPU and INT8. 99.22% character accuracy on a receipt benchmark |
| FastAPI · Postgres · MinIO · Docker | Boring infrastructure. Thousands of deployments |
| OCR on flat printed English | A solved problem since well before this project |

## Open — and how each one closes

### U1 · Millimetre accuracy from a photograph
**The one genuine unknown.** Nobody has published this for retail packaging, so any number we state before measuring is a guess.

*The physics is encouraging.* At 12 MP with the pack filling the frame you get ~24 pixels per millimetre, so a 2-pixel bounding-box error is 0.08 mm — comfortably inside a 1 mm threshold. Even a 1080p frame gives ~10 px/mm and 0.20 mm. **Pixel density is not the limit.** Box tightness, perspective residual and print bleed are.

| | |
|---|---|
| **Test** | 40 packets, ChArUco card in frame, cap heights measured with a steel rule to 0.1 mm |
| **Metric** | Mean absolute error, and the 95th percentile — the tail matters more than the mean |
| **Pass** | MAE ≤ 0.15 mm, p95 ≤ 0.25 mm |
| **Marginal** | MAE 0.15–0.35 mm → keep absolute measurement but widen the `REVIEW` band to ±2× MAE |
| **Fail** | MAE > 0.5 mm → drop absolute height to a stretch goal, lead with the scale-free tier |
| **Fallback** | 28 of 31 rules never needed a scale. The system still works, and still contains two checks nobody else has |
| **When** | Day 5–7. **This is the day-7 go/no-go.** |

### U2 · Devanagari on stylised packaging type
Recognisers exist and Hindi is supported by the browser packages. What is unknown is accuracy on decorative Hindi set on foil or over a photograph.

| | |
|---|---|
| **Test** | Baseline CER on the ≥25% bilingual slice of the corpus, split by surface |
| **Pass** | CER ≤ 0.15 on flat printed Devanagari |
| **Fail** | CER > 0.25 → fine-tune the recognition head on Devanagari crops (CTC, head only) |
| **Last resort** | Scope to English-only declarations **and say so on the slide.** A stated limit beats a silent failure |
| **When** | Week 2, alongside the English baseline |

### U3 · In-browser latency
561 ms is assembled from published per-stage figures, not measured on a device.

| | |
|---|---|
| **Test** | `pytest-benchmark` plus a real mid-range Android phone, both WebGPU and WASM paths |
| **Pass** | <700 ms WebGPU, <1300 ms WASM cache-miss |
| **Fail** | Detector input 640 → 512 px; ROI count capped at the top 4 by confidence; INT8 everywhere |
| **Watch** | Confirm COOP/COEP headers are set. Without them WASM is single-threaded and roughly twice as slow |
| **When** | Week 2, then continuously in CI |

### U4 · RTMDet-Ins ONNX export
Documented friction — mmdeploy issues #1967 and #1990 — although support was merged in PR #1662 with a dedicated onnxruntime config.

| | |
|---|---|
| **Rule** | If the export fights us for more than one day, take a pre-exported ONNX (OpenVINO IR builds and repackaged checkpoints exist publicly) |
| **Deeper fallback** | Ask whether B2 needs segmentation at all. Guided capture means the pack usually fills the frame, and B3's quadrilateral recovery already gives the PDP boundary on a flat label. Bounding-box detection plus classical quad recovery loses very little |
| **When** | Week 2 |

### U5 · OCR on foil, glare and crumpled surfaces
Expected to degrade. The question is how far.

| | |
|---|---|
| **Test** | CER split by surface class — flat card, curved bottle, foil pouch, kraft paper |
| **Mitigation** | B1 capture gate rejects the worst frames before they cost anything; two-pass re-read on low confidence; dual-engine cross-check with docTR; coverage % printed on every scan |
| **Honest limit** | A badly crumpled pouch returns `NO_DATA` on geometry rules. We do not guess |
| **When** | Week 2 |

## After the build — how it gets to "accurate", not just "working"

Passing the week-2 gates makes it *work*. These four make it *accurate*, and they run from week 3 onward.

**Measure per class, never in aggregate.** A single accuracy number hides the failure that matters. Report CER by surface, F1 by declaration field, and mm error by scale tier. The MRP field carries a higher bar than the rest — ≥0.90 F1 — because every other verdict depends on it.

**Hunt the errors, do not wait for them.** After each measurement, pull the twenty worst cases and look at them. Errors cluster: one bad lighting condition, one font, one pack shape. Twenty images tell you more than a summary statistic.

**Let corrections feed back.** Every officer override is a labelled example. Retrain the field classifier on accumulated corrections at the end of week 4 and again in week 6, and report the delta. *The system gets more accurate through use, and the labelling is done by people already doing the job.*

**Guard against silent regression.** Golden-file tests over ten fixed photos catch a model update quietly changing behaviour. The benchmark job fails the build on a latency regression. Both exist so that "it worked last week" is a fact rather than a memory.

**And keep the test split sealed until day 36.** If it leaks into tuning, the headline number is fiction — and you will find that out while you are saying it aloud.

---

# 19. Six-week schedule

| Role | Owns |
|---|---|
| R1 Vision | Rectify, scale, detection — the differentiator |
| R2 OCR/ML | OCR, classification, training |
| R3 Backend | Rules, evidence, API, database, sync |
| R4 Frontend | Dashboard, scan UI, corrections |
| R5 PWA/Reports | Reports, service worker, offline |
| R6 Data/Docs | Corpus, annotation, RESULTS.md, deck |

**Week 1 — corpus and the geometry gamble.** Repo, Docker Compose, contracts drafted and a benchmark harness on day one. Days 1–3 the whole team shoots 400 photos across 100 SKUs, including negatives, hard negatives, bilingual packs and non-food. R1 builds rectification then scale tiers C and A. **Contracts freeze on day 4.** Days 5–7, ruler-measure the 40 test photos and begin annotation.

*Day 7 is a decision point.* If tier A error exceeds 0.5 mm, drop absolute measurement to a stretch goal and lead with the scale-free tier: `min_width_ratio`, `clear_space`, and the 26 non-geometric rules. That is still a working enforcement tool and still contains two checks nobody else has. Decide on day 7, not day 30.

**Week 2 — detection, OCR baseline, latency. This is the week the uncertainties in 18b close.** Finish annotation. R1 fine-tunes the detector, exports INT8 ONNX, records the accuracy delta. R2 runs the OCR baseline in both scripts and measures ROI versus full-image timing, then decides on fine-tuning from data rather than instinct. R3 builds database, migrations, auth and MinIO. R4 scaffolds Next.js and the upload page.

**Week 3 — classification, rules, cache.** R2 builds the regex tier then the trained head. R3 builds the rules engine and **all thirteen check types**, the listing-text path, and the barcode-plus-pHash cache — that's the 60 ms exit. Two of the thirteen are new and cheap: `symbol_case` for the lower-case rule with its proper-name exception list, and `value_in_range` for the 0.1–1000 magnitude bound. **Every field is implemented as locate-then-validate** — a permissive pattern to find the declaration, a strict one to judge it, and only `on_locate_fail` may return `NOT_FOUND`. R4 builds the scan result UI with the annotated overlay, and the report needs a **separate advisory block** for the five severity-`low` symbol checks, so a `250 ML` never appears next to a missing MRP. **Days 15–17, two people independently cross-check the Rule 7 tables, the Second Schedule pack sizes, the applicability gate and the Third Schedule prefix table against the gazette PDFs.**

**Week 4 — evidence, reports, placement.** Hash chain and model version pinning. Reports in both formats. Scale tier B. The placement check end to end. The correction UI writing to the corrections table. Dual-MRP detection.

**Week 5 — repository, dashboard, offline.** pgvector deduplication and the cache-warming endpoint. The dashboard views from section 11. The PWA: service worker, onnxruntime-web, IndexedDB outbox, degradation ladder L0 to L4, install prompt, daylight mode. Faceted search. Bulk upload through Dramatiq.

**Week 6 — measure, harden, present.** Day 36: the final run on the untouched test split, and the latency benchmark on a real device. RESULTS.md with dated numbers, **including a false-positive count for the five advisory checks** — they fire often by design, and an unmeasured advisory block is how a tool loses an officer's trust. Offline sync end to end. README and the two-page architecture document. The two-minute demo video. Five slides. Then rehearse five times and drill hostile questions.

**Nobody touches the test split before day 36.** If it leaks into tuning, the headline number is fiction — and you'll know that while you're saying it out loud.

---

# 20. Demo, questions, checklist, risks

### Two minutes

| Time | What | Line |
|---|---|---|
| 0:00 | Photo of a real packet, marker card beside it | "This is AKSHAR. One photograph, in a shop." |
| 0:15 | **1.6 mm measured, 2.0 mm required**, boxed red | "No existing tool does this. We measure the print, not just read it." |
| 0:25 | Timer on screen: **0.56 s** | "Under a second, in the browser." |
| 0:35 | Report downloads, PDF then DOCX | "Gazette reference, evidence photo, ready to attach to a notice." |
| 0:50 | Second pack fails placement | "Declarations must sit together on the front panel. These don't." |
| 1:00 | A Hindi-only label passes | "The law allows Hindi. So do we." |
| 1:10 | Paste an e-commerce listing — no image | "Three inputs, one rules engine." |
| 1:25 | Rescan the first packet: **60 ms** | "Checked once in Bhubaneswar. Known everywhere." |
| 1:35 | Dashboard, brands sorted by high-severity | "Fourteen non-compliant SKUs. Here's the parent company." |
| 1:45 | **Aeroplane mode. Scan again. Works.** | "Markets have no signal. Neither does this need one." |
| 1:55 | Accuracy table | "Akshar means letter. We measure the letters — 0.13 mm mean error, on 40 packets we checked with a ruler." |

Open on measurement, close on measurement.

### Hostile questions

**"LabelBlind already does this."** Pre-print, artwork file, food, paid, brand-side. We're post-shelf, photograph, all commodities, free, enforcement-side.

**"Why not a vision-language model?"** They fabricate numeric values — ours are MRP and net quantity — and emit markdown rather than pixel geometry. Box height *is* our measurement. We use one only to suggest field mappings.

**"How accurate is the measurement?"** 0.13 mm mean absolute error on 40 ruler-measured packets. Table, corpus and script are in the repository.

**"What if the officer has no marker card?"** Twenty-eight of the thirty-one rules still run. Character width ratio and the clear-space zone are pixel-against-pixel comparisons and need no scale at all; only the three absolute-height rules require it. Tier B also recovers scale from any SKU we have seen before.

**"Isn't this just OCR?"** OCR is one of eleven modules, and we run it on crops only. Reading is the easy part; measuring and locating are the problem.

**"What about Hindi labels?"** Both scripts are read. A bilingual pack satisfies a height rule if either instance meets it.

**"Why is it fast?"** Cache before compute, ROI-only OCR, INT8 in-browser. 561 ms first sight, 60 ms repeat. A regression breaks our build.

**"No internet?"** Installable PWA, 50 MB cached including the entire rulebook. Five degradation tiers; it never returns nothing.

**"Why not blockchain?"** A hash chain gives identical tamper-evidence. Blockchain solves trust between mutually distrusting parties; the department is sole authority over its own records.

**"eMaap is being built for this."** eMaap covers licensing and verification. Its own press release says enforcement is not online. We're the field layer that feeds it.

**"What if it flags a compliant product?"** REVIEW, not FAIL, near thresholds, with tolerances shown. No conviction on a 0.1 mm margin.

**"Can it handle a new rule?"** One YAML entry. The February 2026 country-of-origin amendment took eleven lines and no redeploy.

### Submission checklist

GitHub public with a README that works · `docker compose up` from a clean clone · architecture document, two pages maximum · demo video, two minutes maximum · presentation, five slides maximum · RESULTS.md with dated accuracy *and* latency numbers · reports exporting both PDF and editable · search across all facets · role-based access demonstrable · deployment framework documented · offline demo rehearsed in aeroplane mode · **Rule 7 tables and Second Schedule cross-checked against the bare act PDF by two people.**

Teams lose marks on the boring items — the editable format, the search facility, the deployment document. Check these the night before, not the morning of.

### Risks

| Risk | Trigger | Action |
|---|---|---|
| Tier A error > 0.5 mm | Day 7 | Lead with the scale-free rules (28 of 31 still run); absolute height becomes a stretch goal |
| Annotation behind | Day 10 | Cut to 60 SKUs; keep the 40-photo test split intact |
| Classifier F1 < 0.80 | Day 21 | Regex-only for demo fields; state the limitation |
| Devanagari OCR poor | Day 14 | Fine-tune on Devanagari crops; if it fails, scope to English and *say so* |
| Browser latency > 1.3 s on WASM | Day 30 | Detector input to 512 px; ROI count to top 4 by confidence |
| WebGPU unavailable | Day 30 | WASM fallback, already built |
| Rulepack drifts from the act | Day 17 | Re-check Rule 7 tables + Second Schedule against the PDF. Values were wrong once already — from a vendor blog |
| Test split contaminated | Any time | Re-shoot 40 fresh packets. The number is worthless otherwise |

### Numbers to have ready

Font-height mean absolute error at tier A · count of rules evaluable at each scale tier · per-field F1 · coverage percentage · cache hit rate · in-browser latency, hit and miss, WebGPU and WASM · cached bundle size · storage per 10,000 scans · cost per scan, ₹0 in API fees — and say what a paid vision API would have cost instead.
