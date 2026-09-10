# MAAPDAND → AKSHAR — what changed, and what it costs

**Date:** 7 September 2026
**Binding spec:** [`AKSHAR.md`](../AKSHAR.md). The previous plan is archived at
[`docs/superseded/MAAPDAND-superseded-2026-09-07.md`](superseded/MAAPDAND-superseded-2026-09-07.md)
and must not be built from.

This file exists so nobody re-derives the diff. It records **every** difference
between the two plans, whether it moves code, and what it invalidates. A change
that costs nothing is still listed, because "we checked and it costs nothing" is
a result and stops the question being asked twice.

At the point of the switch the repository held P0–P3 complete: 145 tests
passing, ruff clean, 38 vision modules, a 37-rule rulepack and the full engine.

---

## The one-paragraph summary

**The legal layer survives almost intact. The vision layer takes damage in
exactly two places.** `contracts/` needs no change at all. `rules/` needs one
rule reversed and its source register refreshed. In `vision/`, the reference
object changes from a ₹5 coin to a ChArUco marker and the detector changes from
YOLO11n-seg to RTMDet-Ins-tiny — the first for accuracy, the second for
licensing. One entirely new module appears ahead of everything else: a capture
quality gate. That is the whole cost.

---

## 1. Identity

| | Old | New |
|---|---|---|
| Name | MAAPDAND | **AKSHAR** — *letter, character*; also *imperishable* |
| Package root in §9 | `maapdand/` | `akshar/` |
| Spec file | `MAAPDAND.md` | `AKSHAR.md` |

The name is now load-bearing rather than decorative: Rule 7(2) governs the
height of **letters**, and measuring them is the differentiator. 23 files carry
the old name in a docstring or comment.

**Moves code:** cosmetic only, but it should be done in one sweep rather than
drifting. The repository directory itself stays `SIH_26034`.

---

## 2. Changes that invalidate working code

### 2.1 Scale reference: ₹5 coin → ChArUco marker  ⚠️ **rewrite**

> "A coin gives one dimension — an apparent diameter that foreshortens into an
> ellipse the moment the camera tilts, which is most of the time in a shop. An
> ArUco or ChArUco marker of known physical size gives **four detected corners
> with sub-pixel accuracy**, which yields the scale *and* the homography from
> the same detection." — §8b B3

This is the right call and it was the weakest link in the measurement chain. A
circle detector on shop lighting is a coin-flip; a marker is deterministic. It
also collapses two pipeline stages into one, because the four corners give the
homography that `vision/rectify/` currently recovers by contour search.

**Invalidated:**

| File | Fate |
|---|---|
| `vision/scale/tier_a.py` | **Replaced.** `HoughCircles`, `REFERENCE_DIAMETERS_MM`, `_disc_contrast`, `_MIN_RADIUS_FRAC`, `_MIN_EDGE_FIT` all go. New: `cv2.aruco.detectMarkers` / `CharucoDetector`, corner refinement, known marker edge length in mm |
| `vision/scale/resolve.py` | `reference="inr_5"` parameter → marker dictionary + physical size; `ScaleMethod` literal `"coin"` → `"aruco"` |
| `vision/types.py` | `ScaleMethod = Literal["coin", "scale_card", "known_sku", "none"]` → `["aruco", "known_sku", "none"]` |
| `vision/rectify/rectify.py` | The field-procedure docstring ("coin on the label face") is now wrong. Better: when a marker is detected, **prefer its homography** over the contour quad |
| `vision/pipeline.py` | `reference="inr_5"` kwarg |
| `tests/unit/synthetic.py` | `draw_coin()` → `draw_charuco()` — render a real marker so corner detection is exercised, not faked |
| `tests/unit/test_vision_geometry.py`, `test_vision_pipeline.py`, `bench/test_vision_latency.py` | Fixtures |
| `docs/spec-deltas.md` | The tier-A disc-contrast delta is now moot — keep it as a record, mark it superseded |

**Kept, and worth keeping:** the disc-contrast bug (a printed `0` read as a
coin) stays in the record. It is evidence the geometry path was tested against
adversarial input, and the marker exists partly because that failure mode does.

**Latency:** §4 now budgets scale at **55 ms**, down from 70.

**Corpus impact:** §16 annotates "a box on the ChArUco marker card if present".
The officer shot list changes — the marker is **printed on the inspection card
an officer already carries**, so it is a sheet of paper rather than a prop.

### 2.2 Detector: YOLO11n-seg → RTMDet-Ins-tiny  ⚠️ **rewrite decoder**

> "The two are close on accuracy and speed; **the licence is not close at
> all.**" — §15b

Ultralytics YOLO11 is AGPL-3.0, and Ultralytics hold that the licence covers
the trained weights and that hosting behind an API triggers disclosure. A state
Legal Metrology department deploying this for its officers would be obliged to
publish its entire stack or buy a commercial licence — **for a tool we pitch as
free.** That is a procurement blocker and a fair question from a judge.
RTMDet-Ins is Apache-2.0 through MMDetection.

This is the strongest single argument in the new plan and it was not in the old
one at all.

**Invalidated:**

| File | Fate |
|---|---|
| `vision/detect/postprocess.py` | **`decode()` rewritten.** It currently unpacks YOLO11-seg's fused `(1, 4+nc+32, 8400)` tensor plus protos. RTMDet-Ins has a different head: separate classification, bbox and kernel outputs with a mask feature map. Class-wise NMS and the letterbox inverse survive |
| `vision/detect/preprocess.py` | Letterbox is reusable; RTMDet also trains at 640 px |
| `vision/detect/detector.py` | Output-name plumbing; thresholds re-derived after the first real evaluation |
| `vision/runtime.py` | Model registry name and expected SHA |
| `training/detector/` (not yet written) | `rtmdet-ins_tiny_8xb32-300e_coco` from COCO weights, MMDetection schedule cut to ~100 epochs, exported via mmdeploy `instance-seg_rtmdet-ins_onnxruntime_static-640x640.py` |
| `pyproject.toml` | `ultralytics` out; mmdet/mmdeploy are training-only and stay out of the runtime deps |

**Known risk, with a stated escape (§18b U4).** RTMDet-Ins ONNX export has
documented friction — mmdeploy issues #1967 and #1990, support merged in PR
#1662. **Rule: if export fights us for more than one day, take a pre-exported
ONNX.** Deeper fallback: ask whether B2 needs instance segmentation at all —
guided capture means the pack usually fills the frame and B3's quad recovery
already yields the PDP boundary on a flat label. Bounding-box detection plus
classical quad recovery loses very little.

The augmentation set is now explicit and the defaults are wrong for us:
**mosaic off** (fabricates impossible multi-pack scenes), **hflip off** (text
does not mirror), mild perspective, ±15° rotation, value-channel jitter.
**Never scale-augment the measurement test split.**

### 2.3 Text detection: PP-OCRv5 → PP-OCRv6 `small_det`  ⚙️ **retarget**

~9.5 MB, 2.48M params, LCNetV4 + RepLKFPN, released 11 June 2026 with
PaddleOCR 3.7. `small` over `tiny` (0.43M) **because our declarations are the
smallest print on the pack** — benchmark both, downgrade only if field recall
holds.

**Recognition stays PP-OCRv5 Devanagari mobile.** This is the subtle half and
worth stating: PP-OCRv6's 50 languages are Chinese, Japanese and 46
*Latin-script*. **Devanagari is not among them.** Taking v6 wholesale would
have silently dropped Hindi, which §7 calls the requirement that catches
everyone out.

`vision/ocr/detect_text.py` is DB-style postprocessing and should largely
survive; the model name, input size and `LIMIT_SIDE` need re-checking against
v6. Benchmark whether a second English-only recognition head earns its bundle
size — **do not assume it.**

### 2.4 Rule direction reversed: country of origin → importer  ⚠️ **legal fix**

The current rulepack ships `LMPC.ORIGIN.IMPORTED`: *if an importer is declared,
require a country of origin.* The new §13b establishes that **nothing in the
2011 principal rules requires country of origin on the pack.** Rule 6(10A) —
inserted by GSR 128(E) of 13 Feb 2026 and already substituted by GSR 312(E) of
27 Apr 2026 — places an obligation on an *e-commerce platform* to provide a
searchable filter. It says nothing about what is printed on a package.

> "Our rulepack previously cited 6(10A) for a check that a photographed pack
> declares its country of origin. **Wrong law, confidently cited, on a legal
> document.**" — §13b

**This is a false-violation generator sitting in the rulepack right now.** It
must be replaced by `LMPC.IMPORTER.PRESENT`, which runs the other way:

```yaml
- id: LMPC.IMPORTER.PRESENT
  rule_ref: "Rule 6(1)(a)"        # exists in a document we hold
  severity: high
  check: conditional_present
  field: importer
  when: { field: country_of_origin, present: true }
  message: "Imported packages must declare the name and address of the importer."
```

**Touches:** `rules/packs/lmpc_2011.yaml`, `contracts/context.py:112`
(docstring), `tests/unit/test_engine.py:87,92`. The `conditional_present` check
type itself is unchanged — only the operands swap.

6(10A) also enters the out-of-scope table: verifying it means loading a
marketplace and testing whether its filter works. That is a platform audit, not
a package audit.

---

## 3. Genuinely new work

### 3.1 B1 — capture quality gate (M0)  🆕 **new module**

> "A blurry or glare-blown photo entering the pipeline produces a confident,
> wrong millimetre measurement. **That is the single worst failure this project
> can have**, and the fix costs nothing." — §8b

Variance-of-Laplacian for blur, histogram statistics for exposure, saturation
clipping for glare, minimum-resolution check. **No model.** ~8 ms.

```
CaptureQuality { usable: true, blur_score: 0.91, glare_ratio: 0.04 }
  → or → usable: false, reason: "Strong glare over label"
```

*Done when:* rejects the deliberately-bad corpus subset at **≥90% recall**
while passing **≥98%** of usable photos, in **under 15 ms**.

New module `vision/quality/`, and it sits ahead of everything — a fourth exit,
cheaper than the cache. It is also U5's first mitigation.

### 3.2 B5 — the evidence plan runs *before* OCR  🔄 **reordering**

> "**The law should tell perception what to look for.**" — §8b

Currently the applicability gate runs at rule time, inside `rules/engine.py`,
after everything has been extracted. The new ordering has it emit an
`EvidencePlan` from `PackageContext` alone, before any pixels are read:

```
EvidencePlan {
  need: [manufacturer, generic_name, net_quantity, mrp, packing_date, consumer_care]
  need_geometry: [mrp_height, quantity_height, placement, readability]
}
```

Two consequences. A **wholesale carton under Rule 24** asks for three
declarations instead of six, so we stop looking for the other three. A package
under a **Rule 26 exemption produces no evidence plan at all** — the scan ends
before OCR, in ~150 ms, with `NOT_APPLICABLE`.

**This does not breach the wall.** `vision/` may import `rules/`, and already
does — `vision/classify/regex_tier.py` reuses the rulepack's locate patterns.
The wall runs the other way and `tests/test_boundaries.py` enforces it.
`rules/applicability.py` needs a standalone entry point returning a plan.

### 3.3 B4 — version diffing, not a binary cache  🔄 **enhancement**

A known SKU can do better than hit/miss: align the current photo to the stored
reference and identify **which regions changed**.

```
unchanged: manufacturer · consumer care · generic name · layout
changed:   MRP · packing date
```

B5 then plans to re-read only the changed regions. **"We shorten the OCR work;
we never shorten the legal evaluation."** Every rule still runs against the full
DeclarationSet — reused evidence is still evidence.

Identity order is now explicit: **barcode → pHash → embedding**, with **ORB
keypoint matching as a fallback for re-print variants**. ORB is new;
`vision/identify/` has the other three.

A barcode match means *probably the same SKU*. It does not mean the same
printing, the same MRP, or the same batch. **B4 never outputs a verdict.**

### 3.4 B7 — two-pass recognition  🔄 **enhancement**

First pass batches every crop at working resolution. Regions returning low
confidence — `"MRP Rs. 1?9"` at 0.67 — are **re-cropped from the original
full-resolution pixels and re-read.**

> "This matters more here than in general OCR, because the declarations we care
> about are deliberately the smallest print on the pack."

`vision/ocr/crosscheck.py` already computes the confidence signal; it currently
only withholds. It gains a re-read path.

### 3.5 ScanContext — additive-only  🔄 **restructure**

```
ScanContext { scan_id, original_image }
  +B1 quality        +B2 package_region   +B3 geometry, transforms, scale
  +B4 product_match  +B5 evidence_plan    +B6/B7 recognised_regions
  +B8 DeclarationSet +B9 measurements     +B10 verdicts
```

> "**Nothing silently overwrites anything.** If B9 could overwrite B7's output,
> we could not show what the system actually read."

`vision/pipeline.py` returns a flat `ScanOutcome`. It becomes a context that
accumulates one named slot per block. Same information, but the provenance
becomes structural rather than conventional — which is what makes a finding
reproducible six months later.

**The transform matrix from B3 must be retained in the context**, because every
OCR box has to be mappable back onto the original photograph for the annotated
evidence image. Without it the evidence is a crop nobody can locate on the pack.

### 3.6 §8c — nothing may delay the verdict  🆕 **P5/P6 constraint**

> "When B11 finishes, **the officer already has the answer.**"

Report generation (300–800 ms), dashboard counters, the `scan_count`
increment and evidence upload all move off the critical path. **Verdicts sync
before photos.**

> "Getting this wrong silently doubles our measured latency and it is the most
> common way a fast pipeline ends up feeling slow."

**Queue priority — one worker pool, two priorities.** Declare `scan` (high:
interactive scans, officer report requests) and `bulk` (low: bulk ingestion,
retraining exports, dashboard rebuilds) as separate Dramatiq queues consumed by
the same workers, and weight them. Without this, one overnight bulk job makes
the tool unusable the next morning.

**The review queue is a worklist, not a log.** Every `REVIEW` verdict lands
there; an officer resolves it in one click and the resolution is stored as a
labelled example for retraining. This closes the loop that makes `REVIEW`
honest — a status nobody ever resolves is just a way of avoiding a decision.

### 3.7 COOP/COEP headers  🆕 **deployment, easy to miss**

Multithreaded WASM only runs when the page is cross-origin isolated:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

Without them ONNX Runtime pins `numThreads` to 1 and **the WASM fallback path
roughly doubles in latency** — so the L1 offline path is quietly half speed on
every device without WebGPU. Two lines of server config that decide a headline
number. Belongs in `docs/deployment.md` and `next.config`.

### 3.8 Browser OCR is a shipped path, not a conversion project  ✅ **de-risked**

> "**Solved.** MIT packages ship PP-OCRv5 through ONNX Runtime Web today, with
> WebGPU and INT8."

`ppu-paddle-ocr` (MIT) first — WebGPU, INT8, 40+ languages, and **99.22%
character accuracy on a receipt benchmark**, which is the closest public
analogue to packaging: small, dense, low-contrast print. Keep
`@paddleocr/paddleocr-js` as the fallback if we hit an op-support wall;
`client-ocr` is a third option with explicit Hindi support.

The old plan treated in-browser Paddle as an open risk. It is now settled, and
that removes the largest question mark from M11.

---

## 4. The legal register, rewritten (§13a)

The register went from a partly-aspirational list to an evidenced one. This is
the largest text change in the plan and it moves rulepack **metadata**, not
rules.

| | Old | New |
|---|---|---|
| Documents | ~14 claimed, 8 registered | **11, all registered.** "The family is eleven" |
| Pages | — | 834 uploaded + 43-page LMPC; **451 OCR'd this session** |
| Doc 2, National Standards | "needs OCR" | **40/79** — full English section OCR'd |
| Doc 7, General Rules | "655 pp, scanned" | **356/655** — every English page OCR'd and keyword-scanned |
| Doc 9, Approval of Models | assumed no impact | **26/26 OCR'd — verified, not assumed** |
| Docs 8, 9b, 10 | absent | Corrigendum GSR 317(E); S.O. 824(E); IILM Rules GSR 76(E) — all no-impact |

**The keyword scan is now a presentable artefact.** Across 443 pages outside
LMPC: `packaged commodity` 0, `pre-packed` 0, `retail sale price`/`MRP` 0,
`net quantity` 0, `principal display panel` 0, `consumer care` 0, `font size` 0.
`label` appears 16 times, **all** referring to marks on instruments — a metal
disc stamped on a weight, or a ticket from a shop price-labelling scale.

**The Hindi halves were tested, not assumed.** Numerals survive OCR regardless
of script, so eight Hindi pages were OCR'd and every numeric value cross-checked
against the English half. The two dense specification tables — 59 and 69 values
— reproduce at **100%**. The weak rows are prose pages where Devanagari OCRs
into spurious digits. Conclusion: translations, no independent content.

**Amendment tracking changes shape:**

| Old field | New field |
|---|---|
| `amendments_known_missing` (3 entries, all unknown) | `amendments_checked` (4, each with a confirmed effect) + `amendments_unverified` (1) |

- GSR 128(E) 13-02-2026 — inserts r.6(10A) — **no effect**, platform obligation
- GSR 312(E) 27-04-2026 — substitutes it — **no effect**, in force 01-07-2027
- GSR 734(E) 30-09-2011 — packaging transition — **expired**
- GSR 748(E) 24-10-2011 — withdraws provisos — **already reflected**
- "2025-10-23 medical devices" — **unverified**, stays out of the pack

> "**So no confirmed amendment changes any rule we encode.**"

This converts obtaining the LMPC amendment PDFs from a **blocker** into a
**verification task**, which materially changes what is blocked on the user.

**One discrepancy to resolve, not paper over.** The new §13a meta shows
`amendments_included: []` and files GSR 748(E) under `amendments_checked` as
"already reflected in the principal text we read". Our shipped rulepack lists
748(E) under `amendments_included`, citing a footnote printed on p. 34 of
GSR 202(E) that moves Fourth Schedule item 15 (ice cream) from volume to weight,
w.e.f. 1 July 2012 — and that value **is encoded** in
`tables.unit_by_commodity.ice_cream`. The evidence is real and stays. The entry
should be reclassified to match the new register's vocabulary while keeping the
footnote citation, rather than dropping a sourced value to match a template.

**Rule 18 of the National Standards Rules** was chased and rejected. It looked
like it would catch imperial units on a label; the Seventh Schedule is actually
CGS units (erg, dyne, poise, gauss) and the Eighth is fermi, torr, micron.
Imperial is already caught by `LMPC.NETQTY.SI_UNITS`. **The trap inside it:**
the *calorie* sits in the Eighth Schedule, so a naive reading makes every
nutrition panel printing `kcal` a violation. It is not — nutrition labelling is
FSSAI's domain. **Do not encode it.** Third "we checked and declined to ship
it", after the comma and the litre symbol.

**Rule 21(1)(iii)** is the new headline: quantity tests are ordinarily *not*
carried out at a retail dealer's premises — **except** where a package does not
bear the required declarations. Weighing a pack in a shop is restricted;
**checking its declarations in a shop is expressly permitted.** That is the
statutory basis for a field inspection tool, written by the sponsoring ministry.
One line in the presentation.

---

## 5. Numbers that moved

| | Old | New |
|---|---|---|
| Capture quality (B1) | — | **8 ms** |
| Scale | 70 ms (coin) | **55 ms** (ArUco) |
| ROI OCR | ~300 ms, 8 crops | **290 ms, 4 crops** |
| Cache-miss total, WebGPU | 570 ms | **561 ms** |
| Cache-miss total, WASM | — | **1036 ms** |
| Budget row: WASM cache miss | absent | **<1300 ms, build fails above 2000 ms** |
| Shelf of 40 / 12 unique | — | naive 102 s · WASM 14.1 s · **WebGPU 8.4 s** |
| Tier A accuracy pass | MAE ≤ 0.15 mm | MAE ≤ 0.15 mm **and p95 ≤ 0.25 mm** |
| Tier A marginal band | — | **0.15–0.35 mm → widen REVIEW to ±2× MAE** |
| Tier A fail | — | **> 0.5 mm → scale-free tier leads** |
| Retrieval corpus | unsized | **1,700 chunks, 498 English pages, 2.7 MB f32** |
| Retrieval embedder | unnamed | **`bge-small-en-v1.5`**, 33M, 384-d, Apache-2.0 |
| SKU index | pgvector | **HNSW `m=16`, `ef_construction=64`** — justified because SKU count grows without bound |
| Rule-corpus index | — | **none. Sequential scan over 1,700 vectors is ~1.3 ms** and beats building an index |

The p95 requirement is the sharpest addition: **the tail matters more than the
mean** for a measurement that may be attached to a prosecution.

---

## 6. Unchanged — verified, so nobody re-checks

These were compared line by line and are identical in substance:

- **All 13 check types.** `present` · `regex` · `regex_absent` · `min_height_mm` ·
  `min_width_ratio` · `same_panel` · `clear_space` · `min_contrast` ·
  `no_duplicate_field` · `conditional_present` · `in_table` · `symbol_case` ·
  `value_in_range`. No fourteenth.
- **`contracts/declarations.py` §9** — byte-for-byte the same models. **Zero change.**
- Locate-then-validate, `on_locate_fail`, and the ₹1,000-MRP false-negative story
- `NO_DATA` never `FAIL` when `requires` is absent
- The `REVIEW` band and why convicting on 0.1 mm loses in court
- Three inputs, one engine; `listing_text` has no pixels
- Degradation ladder L0–L4, and L4 still storing a timestamped record
- §6 storage tiers, ~2.1 GB per 10,000 scans vs ~30 GB, repeat SKUs uploading nothing
- §10 database schema — every table, column and index, including `pack_size`
  inside the unique constraint and `brand_group`
- §12 API surface — every endpoint and all three roles
- §11 dashboard — the same eight questions, the same drill-down, brands still
  defaulting to high-severity count rather than fail rate
- pHash 64-bit DCT, Hamming ≤ 8
- MobileNetV3-Small 576-d → PCA 512-d
- Field classifier: MiniLM-L6 384-d frozen, 2-layer encoder, `d_model=128`, ~2M
  params, focal γ=2, AdamW 3e-4 — and LayoutLMv3-base still rejected at 125M
- §16 corpus targets — 100 SKUs, ~400 photos, 15% negatives, ≥25% curved,
  ≥15% foil, **≥25% Hindi**, ≥30% non-food, 40-photo ruler split
- All six §14 hard negatives
- The VLM rejection, the comma decision, the disputed litre symbol
- Backend stack: FastAPI 0.115, Pydantic v2, Dramatiq 1.17, Postgres 17,
  pgvector 0.8, MinIO, WeasyPrint 62, python-docx 1.1, Alembic
- Frontend stack: Next.js 15.1, React 19, TS 5.7 strict, Tailwind 4, shadcn/ui,
  Recharts 2.15, TanStack Query v5, Workbox 7, `idb` 8, **no Redux/Zustand**

---

## 7. What this does to the test suite

145 tests pass today. The switch touches:

| Suite | Effect |
|---|---|
| `tests/unit/test_engine.py` (61) | 2 assertions flip with `LMPC.IMPORTER.PRESENT` |
| `tests/unit/test_vision_geometry.py` (29) | Tier-A tests rewritten for marker detection |
| `tests/unit/test_vision_pipeline.py` (47) | Coin fixtures → marker fixtures; detector decode tests rewritten |
| `tests/test_boundaries.py` (8) | **Unaffected.** The wall does not move |
| `bench/` (6) | Coin fixture; scale budget 70 → 55 ms; new B1 benchmark under 15 ms |

**The boundary tests being unaffected is the point.** Two of the three ML
components on the critical path were just swapped for different vendors under a
different licence, and the architecture absorbed it without the decision layer
noticing. That is what the wall was for.

---

## 8. Ordering implied by §18b

The new plan attaches a test, a threshold and a fallback to every open question,
and one of them is a gate:

- **U1 · millimetre accuracy — day 5–7, go/no-go.** 40 packets, ChArUco card,
  steel rule to 0.1 mm. Pass MAE ≤ 0.15 / p95 ≤ 0.25. Fail > 0.5 mm ⇒ absolute
  height becomes a stretch goal and the scale-free tier leads. **Fallback holds:
  28 of 31 rules never needed a scale.**
- **U2 · Devanagari on stylised packaging** — week 2. CER ≤ 0.15 flat printed;
  > 0.25 ⇒ fine-tune the recognition head only.
- **U3 · in-browser latency** — week 2, then CI. Watch the COOP/COEP headers.
- **U4 · RTMDet-Ins ONNX export** — week 2. One day, then take a pre-export.
- **U5 · foil, glare, crumple** — week 2. B1 rejects the worst frames first.

Consequence for build order: **B1 and the marker-based tier A come before
anything else**, because U1 is a day-7 decision and B1 is what keeps a bad frame
from poisoning it.

---

## 9. Numbers the plan does not reconcile

Found while transcribing §13a into the rulepack meta. **None of these changes a
rule or a line of code** — they are all in prose and in counts, and every one is
in a sentence intended to be said out loud to a judge. Recording rather than
resolving them, because §13a's own rule is:

> "If a number in this plan cannot be traced to something someone actually
> counted, it does not belong in the plan."

Picking one silently would be exactly what that warns against.

| Where | Says | But |
|---|---|---|
| §13a register table | **12 rows** (1–10, plus 9a and 9b) | — |
| §13a summary, line 1254 | "**Eleven** documents, 834 pages" | the table has 12 rows |
| §13a Q&A line, 1278 | "834 pages across **ten** instruments" | and "the other **eight** govern instruments" |
| §13 rulepack meta, line 768 | `# all **10** instruments registered` | — |
| §13a, line 1254 | "**451** pages OCR'd to text this session" | line 1262 scans "all **443** pages", and 1278 says "we OCR'd **443**" |
| §13a "How to use this register", 1332 | "everything the **eleven** check types need" | §13 states, in bold, **"Thirteen check types. Build these and no more"** — and lists 13 |
| §13a, 1332 | "The remaining **twelve** are verification" | if the family is 11 and 2 changed the build, the remainder is 9 |

**The check-type one is the only one worth fixing before it is spoken.** "Eleven
check types" contradicts the plan's own bolded list a few pages earlier, and the
implementation has thirteen modules with a test asserting there is no
fourteenth. Anyone quoting §13a's line in a viva would be contradicted by our
own repository.

The document counts are lower-stakes but appear in a scripted Q&A answer, so
they should agree before the demo. Our register records what is countable — 12
rows — and says so.
