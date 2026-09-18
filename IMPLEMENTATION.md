# AKSHAR — implementation checklist

Every deliverable in [AKSHAR.md](AKSHAR.md), mapped to the plan section that specifies it.
Nothing is marked done until its **acceptance criterion** (§17) is met and, where the plan asks for a
number, that number is written into `RESULTS.md` with a date.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (reason stated)

> **Plan switched 7 September 2026.** MAAPDAND → AKSHAR. The old plan is archived at
> `docs/superseded/`; every difference and what it invalidates is in
> [`docs/plan-migration.md`](docs/plan-migration.md). Items marked **⚠️ REDO** were
> complete under the old plan and must be rebuilt against the new one.

---

## P0 — Scaffold and foundations

- [x] Repository tree per §9 (`contracts/ vision/ rules/ api/ workers/ reports/ evidence/ web/ data/ training/ bench/ tests/`)
- [x] `git init`
- [x] `pyproject.toml` — pinned deps per §15b (FastAPI 0.115, Pydantic v2, Dramatiq 1.17, WeasyPrint 62, python-docx 1.1, Alembic)
- [x] `.gitignore`, `.env.example`, `README.md` that works from a clean clone
- [x] `docker-compose.yml` — Postgres 17 + pgvector 0.8, Redis 7, MinIO, api, worker, web
- [x] `ruff` + `mypy strict` config (strict on `contracts/` and `rules/` only)
- [x] `RESULTS.md` skeleton — every measured number, dated
- [x] ⚠️ **REDO** Rename MAAPDAND → AKSHAR across 23 files (docstrings, headers, README, rulepack comment, env prefix `AKSHAR_*`, compose project/DB/bucket names)
- [x] ⚠️ **REDO** Drop `ultralytics` from `pyproject.toml` (AGPL — §15b licence decision); the reason is recorded in the file so it is not added back for convenience

## P1 — Contracts (§9) — FROZEN, and unchanged by the plan switch

- [x] `contracts/declarations.py` — `FieldName`, `Box`, `Declaration`, `LabelGeometry`, `DeclarationSet`, `Verdict` verbatim from §9
- [x] `height_mm` Optional; `source` includes `listing_text`; `script` on every declaration
- [x] `REVIEW` and `NO_DATA` statuses present and meaningful
- [x] `contracts/` must NOT import cv2 — enforced by `tests/test_boundaries.py`
- [x] Version stamp types: `model_versions`, `rulepack_version`
- [~] `contracts/` gains `CaptureQuality`, `EvidencePlan`, `ScanContext` (§8b) — the three new block outputs. **`CaptureQuality` done** (`contracts/quality.py`, frozen, with `QualityFault` and the officer-facing `ADVICE` table), and **`Framing` added 2026-09-10** beside it with `FramingFault` and `FRAMING_ADVICE`; **`ScanContext` done 2026-09-10** (`vision/context.py`, with the union in `vision/multiframe.py` and `frame_id` on `Declaration` and `LabelGeometry`); `EvidencePlan` still open

## P2 — Rules engine (§13) — the legal core

- [x] `rules/packs/lmpc_2011.yaml` — full rulepack (meta, sources, applicability, tables, patterns, rules)
- [x] `tables.unit_by_commodity` — 26 entries, Fourth Schedule
- [x] `rules/engine.py` — pure function, ~200 lines, **no I/O, no cv2, no DB**
- [x] Applicability gate runs BEFORE any rule; out of scope ⇒ every rule `NOT_APPLICABLE` (§13b six gates)
- [x] Gate: size 3(a) · buyer 3(b) · small pack 26(a) · category 26(b)(c)(d) · **wholesale 24** · other-law 7(4)
- [x] Commodity carve-outs: bidi/incense no date, bidi/LPG no MRP, crown-cap MRP
- [x] **Locate-then-validate** for every field: `locate_ref` + `pattern_ref` + `on_locate_fail`
- [x] `NO_DATA` when `requires` absent — never `FAIL`
- [x] Bilingual grouping: `bilingual: max` — either script may satisfy a height rule
- [x] Rule suppression (`suppresses:`) — one measurement yields one verdict
- [x] REVIEW band near thresholds using `height_mm_tolerance`

### 13 check types — build these and no more (§13). Unchanged by the switch.
- [x] `present` · `regex` · `regex_absent` · `min_height_mm` · `min_width_ratio` (scale-free)
- [x] `same_panel` · `clear_space` (scale-free) · `min_contrast` · `no_duplicate_field`
- [x] `conditional_present` · `in_table` · `symbol_case` · `value_in_range`

### Rulepack correctness
- [x] Rule 7(2) Table I keyed on **net quantity** (not label area); Table II only for length/area/number
- [x] Second Schedule standard pack sizes
- [x] Third Schedule SI prefix table + permitted units (Fourth Schedule)
- [x] `LMPC.UNIT.LITRE_SYMBOL` present but `enabled: false` (disputed, §13c)
- [x] Comma/grouping check deliberately NOT built (§13a) — documented in `docs/legal-decisions.md`
- [x] NS Rule 18 (Seventh/Eighth Schedule units) deliberately NOT built; `kcal` trap documented
- [x] Rule 7 tables + Second Schedule cross-checked vs gazette PDF (2026-09-03) — §19 days 15–17 done early
- [x] ⚠️ **REDO** `LMPC.ORIGIN.IMPORTED` → **`LMPC.IMPORTER.PRESENT`** — direction reverses. Old rule cited Rule 6(10A) for a package-level country-of-origin requirement **that does not exist** (§13b). New: country of origin present ⇒ require *importer*, citing Rule 6(1)(a). Touches `contracts/context.py:112`, `tests/unit/test_engine.py:87,92`
- [x] ⚠️ **REDO** `meta.sources` refreshed to the §13a register: **11 documents**, coverage per document (doc 2 = 40/79, doc 7 = 356/655, doc 9 = 26/26), plus docs 8, 9b, 10
- [x] ⚠️ **REDO** `amendments_known_missing` → **`amendments_checked`** (GSR 128(E), 312(E), 734(E), 748(E), each with a confirmed effect) + **`amendments_unverified`** (medical devices only)
- [ ] Reconcile GSR 748(E): the new §13a meta shows `amendments_included: []`, but our pack cites the footnote on p. 34 of GSR 202(E) for the ice-cream volume→weight change, which **is encoded**. Keep the sourced value, reclassify the entry
- [x] **No package-level country-of-origin rule** — asserted in `tests/test_boundaries.py::test_no_package_level_country_of_origin_rule`, which also fails if any rule ever makes `country_of_origin` a required field
- [x] ⚠️ **Found and fixed 2026-09-09: `regex_absent` searched the whole label.**
      It fell back to `ds.raw_text` when the classifier had not identified the
      field the rule names, so all eight rules using it could report a violation
      from text that was not in the declaration they were about. Found by
      `scripts/advisory_false_positives.py`: 13 advisory findings over 40 frames,
      **11 of them with no classified net quantity at all** — a bare `G`, three
      bare `M`s, `16g` from a nutrition panel's serving size, Devanagari numerals
      from lawful Hindi body text. The advisories are how it surfaced; the damage
      was on the three non-advisory rules, and `LMPC.QTY.WHEN_PACKED` (Rule
      11(4)) would have alleged that a packet declares its quantity at the time
      of packing because those words appeared *somewhere* on the label. Now
      returns NO_DATA when the field was not read — §8b, applied where it was
      being violated. `scope: label` is the opt-in and no shipped rule sets it;
      a test fails if one ever does.

- [x] ⚠️ **Found and fixed 2026-09-09 (night): a presence check could allege an
      absence from a label it had not read.** A real scan of an ITC Dark Fantasy
      pack returned **six high-severity FAILs** — no MRP, no net quantity, no
      manufacturer, no generic name, no date, no consumer care — against a pack
      carrying all six. The recogniser had returned `'METAWEIHT: 2429'` for
      `NET WEIGHT: 242 g`. The scan reached the engine as L2 because `coverage`
      is the share of proposed regions the recogniser was *run on*, not a measure
      of whether anything came back. Three signals were measured before choosing:
      `coverage` scored **1.00** on a frame of pure noise, median CTC confidence
      scored **0.995** on the same frame, word-shape did not separate either. The
      test that does is how many of Rule 6(1)'s six declarations were identified —
      read out of the rulepack, not listed in the check. Below half, and at L3/L4
      regardless (§5 confines L3 to *"verdicts on what was read"*), a presence
      miss is NO_DATA. **The demo pack went 6 non-advisory FAILs → 1**, and
      `bodywash_bottle_300ml` stayed at 6 because it identified four of the six —
      the gate withholds accusations, it does not switch the rules off

## P3 — Vision (§8b, §14, §15b)

### Built and still correct
- [x] `vision/rectify/` — findContours → approxPolyDP → getPerspectiveTransform → warpPerspective, detector-box fallback (M1) — **0.00° residual skew on synthetic photos, was −4.97°**
- [x] `vision/scale/tier_c.py` — no mm_per_px; scale-free rules still run (**built first**)
- [x] `vision/scale/tier_b.py` — known SKU dimensions via a caller-supplied lookup (no DB import)
- [x] `vision/ocr/` — ROI crops only, ≤ 8 regions, both scripts *(weights pending)*
- [x] `vision/ocr/crosscheck.py` — docTR second opinion; withholds, never overrules
- [x] `vision/classify/regex_tier.py` — reuses the rulepack's locate patterns (D13); all 6 hard negatives separated, both scripts
- [x] `vision/classify/model_tier.py` — 2M-param head, 4 address classes only, abstains below 0.55 *(weights pending)*
- [x] `vision/measure/` — cap height (descender-excluded), char boxes, numeral box, WCAG contrast, tolerance propagation
- [x] `vision/identify/phash.py` — 64-bit DCT pHash, Hamming ≤ 8, pre-normalised (D11): 6 vs 26 bits
- [x] `vision/identify/embed.py` — MobileNetV3-Small 576-d → PCA 512-d *(weights pending)*
- [x] `vision/identify/barcode.py` — EAN-13/8, UPC-A via `cv2.barcode`, GS1 checksum verified
- [x] Degradation tiers L0–L4 assigned and reported on every scan (§5) — worst condition wins
- [x] Coverage % computed per scan and carried onto the DeclarationSet

### ⚠️ Invalidated by the plan switch — rebuild
- [x] ⚠️ **REDO** `vision/scale/tier_a.py` — **ArUco marker, not a ₹5 coin** (§8b B3). `cv2.aruco` gives four sub-pixel corners → scale *and* homography from one detection. Delete `HoughCircles`, `REFERENCE_DIAMETERS_MM`, `_disc_contrast`
- [x] ⚠️ **REDO** `vision/scale/resolve.py` + `vision/types.py` — `ScaleMethod` `"coin"` → `"aruco"`; `reference="inr_5"` → marker dictionary + physical edge length
- [x] ⚠️ **REDO** `vision/rectify/rectify.py` — **prefer the marker homography** when a marker is present; field-procedure docstring no longer mentions a coin
- [x] ⚠️ **REDO** `vision/detect/postprocess.py` — **RTMDet-Ins-tiny, not YOLO11n-seg** (§15b, Apache-2.0 vs AGPL-3.0). Separate cls/bbox/kernel heads + mask features, not YOLO's fused `(1, 4+nc+32, 8400)`. Letterbox inverse survives. Our own `nms()` is **gone**: mmdeploy's end-to-end export bakes class-aware NMS into the graph, so ~70 lines of hand-written tensor surgery went with it
- [x] ⚠️ **REDO** `vision/ocr/detect_text.py` — **PP-OCRv6 `small_det`** (~9.5 MB, 2.48M params, LCNetV4+RepLKFPN). `small` over `tiny`: our declarations are the smallest print on the pack
- [x] Recognition **stays PP-OCRv5 Devanagari mobile** — v6's 50 languages are Chinese, Japanese and 46 *Latin-script*; **Devanagari is not among them**. Benchmark whether a second English-only head earns its bundle size
- [x] ⚠️ **REDO** `tests/unit/synthetic.py` — `draw_coin()` → `draw_marker()`, generating a real marker from the same OpenCV dictionary the detector decodes against, so the fixture cannot be charitable to the code under test

### Done in the 2026-09-07 migration pass

The invalidated list above is complete. Two things came out of doing it that
were not on it:

- [x] **`vision/rectify/warp_to_marker()`** — the other half of §8b's claim that
      one detection yields "the scale *and* the homography". The marker's four
      corners fit a warp for the whole plane, which is stronger than a contour
      quad because **a square is square by construction** whereas a label
      outline is only assumed to be a rectangle. New `RectifyMethod` value
      `"marker"`, preferred over `"quad"`.
- [x] **`tests/unit/test_vision_detect.py`** — 19 tests. This file previously
      claimed the decoder was *"verified against synthetic tensors"*. **It was
      not**: there was no test for it anywhere, and the claim survived a plan
      switch unchallenged. A decoder with no weights fails silently, so nothing
      caught it. Now covered: letterbox roundtrip across five aspect ratios,
      box placement, label handling, mask→polygon, the U4 bbox-only fallback,
      and four contract violations that must raise rather than guess.
- [x] **`map_length()` deleted** — it existed only to average a circle's two
      axes under perspective. With corners there are no circles.

### 🆕 New blocks (§8b) — NOT STARTED, discuss first
- [~] **B1 `vision/quality/` (M0)** — built 2026-09-09. Blur, exposure, glare and min-resolution, no model, wired as the first step of `vision.pipeline.scan` with a new `unusable` exit path that still produces the L4 record. 14 unit tests. **Measured at 7.5–8.5 ms** on a 2 MP frame and unchanged on a 8 MP one (fixed-size working copy), against §4's 15 ms budget.
  - **Deviation, stated:** blur is the variance of the *second derivative along each axis, minimum of the two*, not variance-of-Laplacian. The Laplacian sums both second derivatives, so directional camera shake — the commonest bad frame in a shop — leaves enough edge energy on the unblurred axis to score sharp. A 35 px horizontal smear scored 0.32 against a 0.18 threshold and passed; per-axis it scores 0.06 and is rejected.
  - **Exposure is measured by clipping, not by mean luminance.** A near-white pack — salt, sugar, flour, most pharmaceutical cartons — has a mean around 245 and is the easiest label in the country to read; a mean-based test rejects all of them. A test asserts this specific false positive stays fixed.
  - **The done-criterion is NOT met and cannot be yet.** ≥90% recall on the bad subset and ≥98% pass on usable both need the deliberately-bad subset of the field corpus, which is part of the 400 photographs that must come from the user. Every threshold is provisional, the module docstring says so, and `RESULTS.md` reports no recall figure for B1 because there is nothing honest to report one against

  - **Half the criterion is now measured, and it fails.** The 38-photograph
    declaration-block set (2026-09-10) is 38 *usable* photographs of statutory
    panels by construction, so it answers the "≥ 98% pass on usable" half
    directly: **M0 passes 17 of 38, 0.447.** Of the 21 it rejects, 20 pass the
    framing gate — the two halves of B1 disagree with each other. The faults are
    `resolution` 15, `glare` 11, `overexposed` 10, firing on small crops, on
    white-sweep e-commerce renders and on flash against glossy film. The other
    half of the criterion still has nothing to measure against: **no
    deliberately-bad frames have been delivered**, and both halves have to move
    together, so no threshold has been touched. `RESULTS.md`, "38 labelled
    declaration panels"

- [ ] **B5 evidence plan before OCR** — `rules/applicability.py` gains a standalone entry point emitting `EvidencePlan { need, need_geometry }` from `PackageContext` alone. Rule 24 wholesale asks for 3 declarations not 6; a Rule 26 exemption ends the scan **before OCR**, ~150 ms, `NOT_APPLICABLE`
- [ ] **B4 version diffing** — align to the stored reference, re-read only changed regions. **Shorten the OCR work, never the legal evaluation** — every rule still runs against the full DeclarationSet
- [ ] **B4 ORB keypoint matching** — fallback for re-print variants, after barcode → pHash → embedding
- [ ] **B7 two-pass recognition** — low-confidence crops re-cropped from **original full-resolution pixels** and re-read
- [x] **`ScanContext`** — additive-only, one named slot per block. **Nothing
      silently overwrites anything**. Built 2026-09-10 as `vision/context.py`,
      and it is the multi-frame union: one pack, two or three photographs,
      evidence unioned, **rules evaluated once on the union**. That is the
      answer to the objection that shaped the whole day — *"an officer will not
      take care of these things"* — because it replaces "aim at the declaration
      panel" with "walk round the pack".
  - **Deviation, stated:** the per-block additivity was already structural and
    is not re-implemented. `ScanOutcome` is a frozen dataclass with one named
    field per block, constructed once at the end of `scan()`; there is no
    assignment that could overwrite a slot, which is stronger than a `set()`
    that raises. `test_scan_context.py` asserts the frozen-ness rather than
    trusting it. What the context adds is the dimension that was missing —
    frames.
  - **Second deviation:** no `verdicts` slot. This module lives in `vision/`,
    and a slot for verdicts there would put the decision inside the extractor.
    `api/scanning.py` pairs a context with its verdict list; neither owns the
    other.
  - **Not a vote over per-frame verdicts, and that is the load-bearing
    choice.** Best-status-wins acquits a pack whose second photograph shows the
    violation; worst-status-wins convicts every pack whose second photograph
    merely failed to repeat a declaration. Neither is right, because the
    verdicts were computed against different evidence and the law is about the
    package. Union the evidence and evaluate once and both cases come out right
- [x] ⚠️ **The three ways a union could fabricate a violation, closed with a
      test each.** Each photograph has its OWN rectified coordinate space, so
      `Declaration.frame_id` travels with every declaration and: `clear_space`
      ignores intruders from another frame (it is 40% of the blocking FAILs on
      the corpus — multiplying its chances by the number of shots taken would
      have been the most expensive mistake available here); `same_panel`
      returns **NO_DATA** when the declarations span frames, because grouping
      is a fact about one surface; and `no_duplicate_field` returns **REVIEW**
      rather than FAIL when two frames disagree, because one price read twice
      with a digit misread is indistinguishable from two printed prices — a
      naive union would fabricate the exact Rule 6(3) offence it exists to
      catch, on a lawful pack, out of our own OCR error
- [x] ⚠️ **`measured_for` — a measurement is taken from ONE photograph per
      field.** Every measurement check in `rules/checks` iterates and keeps the
      worst outcome, which is right on one photograph and wrong across several:
      three shots give three chances for one soft crop to produce a FAIL, so an
      officer taking more care would make the pack look worse. The best
      calibrated frame wins, then the most confidently classified, then the
      earliest. What this gives up is stated in the docstring: a duplicate
      declaration on a second panel is judged once
- [x] **Every frame is evidence.** `scans.frames` (migration `0003`, nullable
      JSONB) carries one entry per photograph with its own `image_sha256`, so
      section 6's "the digest lives inside the chain" holds for all of them.
      **NULL rather than `[]` on a single-frame scan** — the chain hashes the
      keys a payload carries, so a `frames: null` on every existing row would
      fail `verify_chain` on records nobody touched. `_payload_from_row` omits
      the key when the column is NULL and a test asserts it
- [ ] B3 transform matrix **retained in the context** so every OCR box maps back onto the original photograph for the annotated evidence image

### Model weights — ours to do, not the user's
- [x] `scripts/fetch_models.py` — 10 artifacts declared with purpose, licence and size; `--check` reports what is missing *and what still works without it*. **URLs not yet pinned** (see below). A boundary test asserts every filename a loader wants is one the script can supply
- [ ] **U4 escape hatch:** if RTMDet-Ins ONNX export fights us for **more than one day**, take a pre-exported ONNX. Deeper fallback: bbox detection + classical quad recovery, which loses very little under guided capture

- [x] ⚠️ **Found and fixed 2026-09-10: the detector threw the frame away at
      tier C.** `detect_text.input_side` returned its 640 px floor whenever no
      scale had been recovered, so a 4032 px photograph was detected at a **6.3×
      downscale** and the 1 mm print Rule 7(2) exists to measure fell below a
      pixel — never proposed, never read, never classified. Now sized to the
      frame, clamped into `[640, 2048]`. Measured over fifteen corpus frames:
      **15 → 23 declarations identified (+53%)**, 326 → 562 lines read, for
      21.7 → 225 ms of detection. §4 budgets 110 ms and this breaks it
      *affordably*: tier C is exactly where the three `min_height_mm` rules
      already return NO_DATA, so the budget is protecting a measurement that is
      not being taken, and what is scarce there is recall. The one golden
      snapshot that moved was `no_marker_tier_c` — the only tier-C scene — and
      the diff was 1–3 px of box and 0.02 of confidence, no text or field change
- [x] ⚠️ **Found and fixed 2026-09-10: `MFG BY <company>` classified as a DATE.**
      `mfg` matched `mfg_date_locate` before `manufacturer_locate` was ever
      consulted, so a company name was handed to a date-format check at 0.88
      confidence. `MFG BY` names a manufacturer; `MFG:` introduces a date; a
      negative lookahead now lets the following word decide
- [x] ⚠️ **Locate patterns could not match the statute's own words.**
      `retail sale price` is Rule 2(m)'s term and `mrp_locate` read
      `max(imum)? retail price` — the printed phrase has `sale` in the middle, so
      a pack declaring its MRP in the exact words of the rule was reported as
      declaring none. Also added from real packaging: `MFD./MFG. BY`, `UBD:`,
      `MADEININDIA` (OCR eats the spaces), and the "for feedback/complaints"
      family. **16 → 24 of 25** hand-checked phrasings; §14's hard negatives
      (`Rs. 20 OFF`, `24MRP07`, drained weight) all still behave. Two of the
      widenings had to be made twice — a trailing `` or `(?!...)` after a
      widened alternation lands *inside* the word it just matched, which broke
      `MADE IN INDIA` and `Complaints`; both are now `\w*`-terminated

- [x] ⚠️ **Found and fixed 2026-09-10: format checks judged our OCR, not the
      printer.** 25 of 75 corpus FAILs, the largest single source. Two faults:
      `locate` searched the whole label while `strict_text` searched one
      classified fragment, so a declaration split across two regions was
      located on the label and failed on the fragment (`'MFD*'` judged against
      the date format while `06/2026` sat in the text we had read); and the
      rest were claims about *print* — case, spacing, separators — decided from
      a recogniser that returns `'Servingsize'` for `Serving size`. OCR
      confidence does not separate format FAILs from PASSes (median 0.84 vs
      0.96, ranges overlapping), so there is nothing to threshold on. Validate
      now retries on the same evidence locate matched, and on the image channel
      a mismatch is REVIEW; `listing_text` still FAILs, because nothing stands
      between us and those characters. See `rules/checks/regex.py`
- [x] ⚠️ **Found and fixed 2026-09-10: the contrast estimator understated by up
      to 35%.** It averaged luminance over the binarised ink and over the
      background ring, and at the pixel sizes a 1 mm character occupies both
      samples are dominated by the shared anti-aliased edge, so the two
      estimates walk toward each other. Black on white, published ratio 21.0,
      measured 13.66. Across 1178 corpus declarations it never exceeded 10.35
      and put 68% below the 3.0 threshold — two thirds of legible retail
      packaging reported illegible under Rule 9(1)(b). Sampling the ink and
      paper *colours* (20th/80th percentiles) returns the published value
      exactly on seven known pairs; `LMPC.CONTRAST.NUMERALS` 10 → 6
- [x] ⚠️ **Found and fixed 2026-09-10: the rulepack contradicted itself about
      the litre.** `LMPC.UNIT.LITRE_SYMBOL` ships `enabled: false` because BIPM
      accepts `L`, and `LMPC.UNIT.SYMBOL_CASE` reached the same symbol by
      another route and failed `Net Content: 1L (905 g)` anyway — every litre
      pack in the country. The decision now lives in one table,
      `unit_case_disputed`, read by the check rather than duplicated in it
- [x] ⚠️ **Found and fixed 2026-09-10: advisory findings carried the red
      headline.** `api/analytics.py` excludes `advisory: true` from every
      published violation count; `rules.engine.is_compliant` and the web's
      `overallStatus` did not, so one scan could read "Non-compliant" on screen
      and sit outside the violation tables on the dashboard. An advisory
      failure is now amber, still listed, and does not decide the verdict
- [x] ⚠️ **Found and fixed 2026-09-10: nine phrasings printed on real packs
      matched no locate pattern**, and a phrasing we cannot match is a
      declaration reported *absent*. The worst was `Date of Packaging` —
      `mfg_date_locate` read `date\s*of\s*(mfg|packing)` and *packaging* is not
      *packing*, so Rule 6(1)(d) was reported undeclared against a very large
      share of Indian food packs. Also `Name of Commodity` (Rule 6(1)(b)),
      `In case of any complaint` and `Reach us` (Rule 6(2)), `Date of Import`,
      `Month & Year of Manufacture` (which was going to `manufacturer`),
      a bare `B.NO.:` whose value the detector put in another region, and
      `Manufactured & Packed by`. Hand-checked sweep **41/51 → 50/51**.
      `Product Name` is deliberately still `other`: it introduces the brand and
      Rule 6(1)(b) requires the generic name, and a locate pattern may be too
      narrow but never too wide
- [x] ⚠️ **Found and fixed 2026-09-10: `generic_name` had two definitions that
      had diverged.** `vision/classify/regex_tier.py` kept a local copy reading
      `(common|generic) name` while the rulepack had grown `Name of Commodity`,
      so the engine reported the declaration present and the extractor
      classified the line `other` — the exact divergence that module's docstring
      forbids. The local copy is gone and the field reads `generic_name_locate`
      from the pack like the other six
- [x] ⚠️ **Found and fixed 2026-09-10: the exclusion zone counted noise and a
      declaration's own label as intrusions.** Rule 8(1)'s proviso was reporting
      `13 intrusion(s): 14; s; a`. B2 has no trained weights, so a number of its
      proposals are one character of nothing; and the label joined to a figure
      by `vision.classify.associate` is demoted to `other` and then sat inside
      the subject's own box. An intruder must now look like a word or a number
      and must not be part of the declaration it is said to be crowding
- [x] ⚠️ **Found and fixed 2026-09-10: the evidence exhibit captioned every
      recognised line.** 50 coloured boxes on an Amul ghee tin, 48 of them
      reading "Unclassified text" over the nutrition table and over single
      characters the recogniser invented, burying the two that carried the
      verdict. `evidence/annotate.py` now draws unnamed text as a thin grey
      outline and never captions it — which is what its own docstring already
      said, that an unlabelled rectangle beats a mislabelled one. Same frame:
      2 captioned, 48 outlined
- [x] ⚠️ **Asserted 2026-09-10: Rule 7(2)'s tables are floors, not targets.**
      The behaviour was already correct and is now guarded, because it is the
      question the whole project turns on: a 5 g pack requires 1 mm, and 3 mm
      or 12 mm on that pack is PASS, 0.9 mm is REVIEW (inside our own 0.15 mm
      error) and 0.4 mm is FAIL. The band follows the *declared quantity* —
      the same 3 mm numeral is lawful at 5 g and at 300 g and unlawful at 900 g
- [x] ⚠️ **Found and fixed 2026-09-10: the scan screen mislabelled coverage.**
      It read "share of the declarations we expected that were read" and showed
      74.5% on a frame carrying two named declarations. `coverage` is the share
      of *detected text regions the recogniser returned text for* — it says
      nothing about declarations — so the caption now says that, under the
      label "Text read"

## P4 — Evidence and database (§6, §10) — unchanged by the switch

- [x] `db/schema.sql` — skus, scans, verdicts, corrections, access_log, users + all 5 indexes
- [x] `pack_size` inside the SKU unique constraint; `brand_group` column — both asserted in `tests/unit/test_schema.py`
- [x] SKU vector index: **HNSW `m=16`, `ef_construction=64`** (§15b); a test asserts the rule corpus gets **no** vector index, so the asymmetry cannot be lost
- [x] Alembic migrations — `0001_initial_schema` applies `schema.sql` verbatim rather than restating it, so `pack_size` has one definition; no connection string committed
- [x] `evidence/chain.py` — canonical JSON, SHA-256, `prev_sha256`, server-assigned `chain_seq`
- [x] **`evidence/verify.py` — M7 MET.** `verify_chain()` names four distinct failures (`CONTENT_ALTERED`, `BROKEN_LINK`, `SEQUENCE_GAP`, `BAD_GENESIS`) and keeps checking after the first
- [x] `evidence/storage.py` — tiered retention as data, `ObjectStore` Protocol so policy is testable with no MinIO running
- [x] Repeat-SKU scans upload nothing — the 40-packet/12-SKU shelf arithmetic is a test
- [x] Face blur on upload; geo stored at reduced precision (§18 privacy) — `evidence/redact.py`. **Redaction is synchronous and the hash chain is why**: the row carries `image_sha256` and cannot be edited afterwards, so the digest must be over the bytes that will actually exist. A face **printed on the package** (the Amul girl, a baby on a formula tin) is detected and deliberately left alone — blurring it would remove label content, which is the evidence. Blur alone is invertible in principle, so the region is mosaicked first. If the cascade cannot load, **no image is stored at all** and the scan record still is

### What P4 still needs

- [~] **Pin the model source URLs and digests** in `scripts/fetch_models.py`.
      **Three of the eight are pinned** — `ppocrv6_small_det.onnx`,
      `ppocrv5_rec_devanagari.onnx` and its `.yml` all carry a URL and a
      verified SHA-256. The remaining five cannot be pinned by downloading,
      and the reason differs: four are **produced here, not fetched** (the
      RTMDet export, the SKU PCA, the field classifier that
      `training/classifier/train.py` now writes, and the embedder that reuses a
      model already in the bundle), and `bge-small-en-v1.5.onnx` is on disk but
      its provenance has never been verified against an upstream URL. Pinning
      the hash of a file we merely happen to hold is the security theatre this
      row was written to avoid — it looks like provenance while meaning
      "whatever we downloaded first". **What is left is one verified download**,
      after which a changed upstream artifact fails loudly instead of silently
      altering every measurement, which matters because `scans.model_versions`
      writes that digest into a legal record.
- [ ] **Publish the chain head digest somewhere outside the database.** A chain
      is tamper-*evident*, not tamper-*proof*: an actor with full write access
      can rewrite a record and re-chain everything after it, and the result
      verifies cleanly. `head_digest()` exists and there is a test asserting
      exactly this limit. Anchoring it externally — an append-only log, a daily
      line to the controller — is what closes it, and it costs one row.
- [x] Schema executed against a live Postgres 17.11 + pgvector 0.8.6. The
      `rule_chunks` table for tier-2 search was added the same way, and
      `tests/unit/test_sql_stores.py` checks it against `api/sql/tables.py`
      like every other table.

## P5 — API and workers (§12, §8c)

- [x] `POST /api/v1/scans/listing` · `/scans/sync` · **`/scans` (multipart, verdict returned before the upload)** · **`/scans/bulk` (202 + a pollable receipt)** · `GET /scans/bulk/{job_id}`. The shared core is `api/scanning.py`, called by both the route and the bulk worker — §12's *"if it diverges, two products exist and only one is tested"* as an import rather than a promise
- [~] `GET /scans/{id}` **done**; the two report formats are P6
- [x] `POST /scans/{id}/corrections` — append-only; a test asserts the scan row is byte-identical afterwards
- [x] `GET /skus/lookup?phash=&barcode=` · `/skus/cache?district=&n=5000` — barcode first, then pHash at Hamming ≤ 8
- [x] `GET /search` — brand, barcode, date, district, rule, status; server-side pagination, newest first, CSV export
- [x] `GET /dashboard/{overview|brands|rules|categories|districts|health|review}` — all eight of §11's questions; brands sorts by high-severity count, not fail rate
- [~] `GET /summary` **done** (same computation as the dashboard, so screen and report cannot disagree); the PDF and DOCX renderings are P6
- [x] `POST /auth/login` `/refresh` — JWT; roles nest via `ROLE_RANK`; refresh tokens rejected as bearer credentials; identical reply and equal timing for unknown email vs wrong password
- [x] `GET /rules` — active rulepack, readable, unauthenticated (nothing in it is not a gazette)
- [x] `GET /healthz` `/metrics` — health reports **degraded**, not 503, when weights are absent; plus `GET /api/v1/chain/status` (supervisor+) so tamper-evidence is checkable
- [x] **Idempotent sync** — a replayed outbox returns `created=false` and appends **no second chain entry**; `chain_seq` assigned server-side; geo truncated before storage
- [x] `workers/` — Dramatiq + Redis. `broker.py` owns the topology and picks a `StubBroker` under pytest, so the actors are testable with no container; `drain()` runs a real `dramatiq.Worker` so the middleware runs on the same path a deployment uses
- [x] 🆕 **Two queues, one worker pool** (§8c) — `workers/middleware.py`. **Two queues alone do not do this:** Dramatiq runs one consumer per queue but shares the worker pool, and each consumer prefetches `threads × 2`, so a bulk backlog fills the pool and the correctly-prioritised interactive scan waits behind sixteen image ingestions. `BulkFairShare` therefore weights *execution*, capping in-flight `bulk` at half the pool with an exponential-backoff requeue for the overflow
- [x] 🆕 **Nothing delays the verdict** (§8c) — report render, `scan_count` and the evidence upload are all enqueued, never awaited. The bytes wait in `evidence/spool.py` (Redis, or a dict in one process) rather than in the queue message; a spool that refuses them falls back to an inline PUT, because a slow response is a far smaller problem than a missing photograph
- [x] 🆕 **Review queue is a worklist** — every `REVIEW` verdict lands there, **one click per rule** resolves it, and the resolution is stored as a labelled example for retraining. `POST /scans/{id}/review` + `ReviewStore` + `review_resolutions`; `api.analytics.review_queue` takes the resolved map, so a settled rule leaves the list and a scan leaves it only when every rule that asked for a human has an answer. The overview tile counts through the same filter as the list beneath it — they are computed in two places, which is exactly how they drift, and a test asserts they agree
- [x] Bulk path runs the **identical B1–B10 sequence** server-side — `workers.tasks.ingest_bulk_image` calls `api.scanning.run_scan`, the same function the HTTP route calls. A test asserts both produce the same `DeclarationSet` from the same bytes
- [~] `access_log` written on scan view, correction, sync, login and failed login; export is P6

### What P5 still needs

- [x] **The image upload path** — `POST /scans` and `/scans/bulk`. Multipart,
      MinIO, face blur and the queue, wired through `api/scanning.py` so the two
      channels cannot drift. The scan itself runs in `run_in_threadpool`: several
      hundred milliseconds of OpenCV holding the GIL inside an `async def` would
      pin the event loop and serialise every other officer's request behind it.
- [x] **Dramatiq with two queues** (§8c) — see above. `report_status="queued"`
      was already in the response contract, so the client needed no change.
- [~] **SQL-backed stores.** `api/sql/` implements every Protocol against
      Postgres 17 + pgvector: `tables.py` mirrors `db/schema.sql` as Core (a test
      parses both and asserts the columns agree, because a drifting mirror writes
      `NULL` into the forgotten column forever with nothing to notice), and
      `stores.py` holds §5's guarantees. Three things needed real thought:
      a **transaction-scoped advisory lock** around the chain append, since two
      workers reading the same tail fork the chain and a forked chain fails
      verification forever on records nobody edited; **`NUMERIC` → `Decimal`**,
      which canonicalises as a string and would turn every stored scan into a
      false tamper alarm; and **`EXISTS` rather than a join** for the verdict
      filters, which would otherwise multiply each scan row by its matching
      verdicts and inflate every dashboard count silently.
      **Now executed against a live Postgres 17.11 + pgvector 0.8.6**
      (2026-09-08). All 29 contract tests pass against the same assertions the
      in-memory store satisfies. Two of them had never actually held: the
      bulk-job fixture used a random UUID for `officer_id`, which the in-memory
      store accepts and a real foreign key does not — a test that passed for
      weeks and failed the first time it met a database.
- [x] Two schema gaps found while writing the SQL stores, both of which would
      have broken *only* on Postgres and both silently. `verdicts` had no
      `advisory` or `suppressed_by` column (D18), so the dashboard would have
      reported unit-symbol formatting as non-compliance and double-counted every
      suppressed measurement; and the two stores returned different dict shapes
      from `verdicts_for`, so `normalise_verdict` is now shared by both.
- [x] `GET /search`, `/dashboard/*`, `/summary` — built against the
      `ScanStore` Protocol, so the SQL implementation inherits them. The
      arithmetic lives in `api/analytics.py` as pure functions over facts, which
      is what stops the JSON view, the CSV export and the PDF summary computing
      three different non-compliance rates.
- [x] ⚠️ **Found and fixed 2026-09-09 (night): the PDF route returned JSON under
      a `.pdf` name.** `?format=pdf` answered `202 {"status":"rendering"}` when no
      worker had rendered one — and the demonstration stack has no worker — while
      the scan page offers it as `<a download="scan-<id>.pdf">`. A browser saves
      whatever comes back under that name whatever its status, so the officer got
      thirty bytes of JSON no viewer would open. The summary export had the same
      shape via a 503. Both now always return a PDF: `reports/pdf_fallback.py`
      (pure Python, `fpdf2`) renders where WeasyPrint's native libraries are
      absent, and `_pdf_response` renders inline when nothing is stored while
      still enqueueing the warm-up. Four route tests assert the **magic bytes**
      of all three formats, because `200` with a JSON body passes a status check
      and is still the bug. DOCX was never affected

- [x] Face blur on upload (§18) — `evidence/redact.py`, enforced in
      `api/scanning.prepare_evidence`, which fails **closed** on privacy and
      **open** on the record.
- [x] **SQL stores run against a live Postgres.** `docker compose up -d db`,
      then `AKSHAR_TEST_DATABASE_URL=... pytest`. 29 contract tests, all
      passing; the nine that used to skip now execute.
- [x] **`POST /scans/{id}/review` — the review queue closes.** §8b's *"one-click
      resolve, resolution stored as a labelled example for retraining"*. New
      `ReviewStore` Protocol with in-memory and SQL implementations, a
      `review_resolutions` table, migration `0002`, and `api/analytics.
      review_queue` taking the resolved map so a settled rule leaves the list.
      **One question per rule, not per scan** — a scan reaches the queue because
      named rules came back REVIEW, and a marginal MRP height and an unreadable
      net quantity are not settled by one click; the endpoint returns 409 for a
      rule that never asked. **Three decisions, not two**: `complies`,
      `does_not_comply`, `recapture`, because §8b issues REVIEW when a
      measurement lands inside tolerance and the honest answer there is often
      *photograph it again*. Supervisor and above; the scan is never touched, so
      the verdict still reads REVIEW and the evidence chain still verifies.
- [x] ⚠️ **Found and fixed: `POST /scans/{id}/corrections` persisted nothing.**
      It returned a 201 receipt with a `"Recorded as a new row"` note and dropped
      the row on the floor. The `corrections` table existed; nothing wrote to it.
      §14 rests its whole retraining argument on those rows being *"a labelled
      training example produced by somebody already doing the job"*, which was
      not true of a single one. Now stored through the same `ReviewStore`, with a
      test that asserts a correction survives the request.

## P6 — Reports (§13, §13b, M8)

- [x] One HTML template → WeasyPrint PDF **and** python-docx editable. The DOCX walks the report model directly rather than converting the HTML — an HTML-to-DOCX conversion produces a document whose every line is a nested table and which nobody can edit, and *editable* is what the problem statement asks for
- [x] Per-product report: identity, per-rule verdicts + gazette refs, measured heights **with the tolerance that decided FAIL vs REVIEW**, degradation tier, remediation keyed on the check type, and **the annotated photograph** — drawn on the *rectified* label, because `Declaration.box` is in rectified coordinates and the same boxes laid over the camera frame would be convincingly wrong
- [x] **Separate advisory block** for the 5 severity-`low` symbol checks. It is a *field on the model*, not a filter in the template, so the DOCX writer cannot forget it — a test asserts both renderings agree about what is a contravention
- [x] Mirrors Seventh Schedule Form A Parts A/E/F; Parts B/C/D **named** and marked *not applicable, declaration check only*. Omitting them would imply the package had been weighed
- [x] Violation summary (drive/district/period) → HTML + DOCX + PDF at `GET /summary/report`, built over the identical `api/analytics.summary()` call the JSON route makes. A null rate prints as an em dash and never as 0%, decided once in `reports/summary_model.percent` so neither renderer can report an unvisited district as compliant
- [x] Report generation is a **background job** — but only the format that needs it. HTML and DOCX render inline in tens of milliseconds; the PDF is rendered by `workers.tasks.render_report` onto the derived bucket and served from there, `202` + `Retry-After` until it exists

### Notes on the two that closed last

- [x] **The annotated photograph** — `evidence/annotate.py`, stored on the
      `derived_crop` tier by `workers.tasks.store_annotation`. Three things
      forced the design: the boxes are in **rectified** label space, so the
      exhibit is the flattened label rather than the photograph; it is drawn at
      **scan time**, because rectifying a second time later finds its own quad
      and would move every box; and the **redaction runs again** on it, since it
      is warped from the unredacted frame. Where rectification actually warped
      to the label the whole frame is the package, so a printed face is artwork
      and survives — where it fell through to `identity`, bystanders are back
      and are mosaicked.
- [x] **The violation summary** over a drive, district or period, over the
      *same* `analytics.summary()` the dashboard calls. All three formats render
      inline here, unlike the per-product PDF: a summary is an aggregate over
      whatever the filters selected at that instant, so there is no scan to
      store it against and a cached copy would answer tomorrow with yesterday's
      numbers.
- [x] Two gaps found while building this. `docker/api.Dockerfile` **did not
      exist** although `docker-compose.yml` referenced it, so §20's "docker
      compose up from a clean clone" would have failed at the build step; it now
      exists, installs Pango/cairo/harfbuzz and DejaVu, and **fails the build if
      the PDF renderer cannot render**. And `reports.render.pdf_available()`
      originally caught `ImportError` — WeasyPrint raises `OSError` from `cffi`
      when the native libraries are missing, so the guard let through exactly
      the failure it existed to contain.

## P7 — Retrieval (§15)

- [x] Structure-aware chunking on rule/sub-rule/clause/proviso/table hierarchy — `retrieval/chunker.py`. Rule 8(1) keeps its proviso, and the proviso is separately citable because **the proviso *is* the exclusion-zone rule**
- [x] **Tier 1** citation lookup by `rule_ref` — `retrieval/citations.py`, a dict, no index, no model. `GET /api/v1/rules/citation?ref=...` and `/api/v1/rules/{rule_id}`, unauthenticated and long-cacheable so the PWA can hold it offline at L1
- [x] **It never guesses.** `Rule 7(2)` never silently resolves to `Rule 7`: an enclosing provision is returned as `related` with `held=False`, and a citation into a gazette we do not hold **names that gazette** rather than returning a blank
- [x] Index keyed per document — thirteen gazettes have thirteen `Rule 2`s, and a global key made `ambiguous` fire across unrelated instruments
- [x] **Provenance travels with the clause** — `retrieval/provenance.py`. A chunk is `text-layer` or `ocr`; OCR'd text is searchable but carries *"verify against the page before citing"*, because a recogniser right 97% per line will eventually put a wrong digit in a height threshold
- [x] **Tier 2 hybrid**: Postgres `tsvector` (`websearch_to_tsquery`, `english`) + dense **`bge-small-en-v1.5`** (33M, 384-d, Apache-2.0, ONNX), RRF `k=60` — `retrieval/hybrid.py`, `retrieval/search.py`, `api/sql/rulebook.py`, `GET /api/v1/rules/search`
- [x] **No index on the rule corpus, and no reranker.** Both queries are sequential scans by choice; see the comment on `rule_chunks` in `db/schema.sql`
- [x] **Tier 3 extractive** — `retrieval/highlight.py` returns *offsets*, never marked-up text, so no renderer can alter a clause. Generative summary deliberately not built: §15 makes it optional and conditional, and the extractive default is the stronger position
- [x] Corpus: **all thirteen gazettes, 838 pages** — `scripts/ingest_gazettes.py`, `scripts/index_corpus.py`

### Tier 2 measured, not estimated

    principal display panel                    47 ms   Rule 7, 7(1), 7(2) — both retrievers, coverage 1.00
    how big must the letters on a package be   67 ms   Rule 7 — dense only; the statute never says "how big"
    can a unit symbol be written in capitals   63 ms   NS Rules Third Schedule item 7 — the clause our
                                                       four advisory unit-format rules actually cite

The middle row is the whole argument for hybrid in one line: BM25 returns
nothing for that question because none of those words appear in any gazette.
The first row is the argument for keeping BM25: an exact term of art comes back
ranked 1, 2, 3 with both retrievers agreeing.

### The corpus is now thirteen documents, and three numbers in §15 are wrong

§15 sizes the corpus at *"twelve gazette documents, 498 English pages, roughly
1,700 clause-level chunks [...] 2.7 MB as float32"*. Actual: **thirteen unique
documents, 838 pages of which 447 are readable English, 5,044 chunks, 7.4 MB.**
The nesting is the difference — a rule is emitted whole *and* as its sub-rules
and clauses — plus the 655-page General Rules the plan did not count.

**The architectural conclusion survives, which is the point of having sized
it.** Exact scan over 5,044 vectors is a few milliseconds; an HNSW build still
costs more than the scan. Recorded as D22.

### Audited: every word of every page read is inside a chunk

Asked directly — is anything from the thirteen instruments missing — and
measured rather than asserted. It was **94.51%**, and is now **100.00%** with
**zero** chunks citing a parent that does not exist. Four defects, all silent,
all in RESULTS.md:

- every line arriving while no rule was open was **discarded**, which inside a
  Schedule is most of it — the MPE table, the standard pack sizes, two thirds of
  the National Standards Rules;
- a Schedule was never a chunk, so **114 items cited a parent with no text**;
- three instruments produced **no chunks at all** — both commencement
  notifications and the General Rules corrigendum;
- the Schedule pattern required the word `THE`, so all **655 pages and
  seventeen Schedules** of the General Rules were filed as `Rule n` against a
  numbering that restarts in every Part.

And one in the other direction: the page-language test dropped **19 English
pages**, including the National Standards Seventh Schedule that rule 18 cites,
while admitting **20 pages of Devanagari mojibake**. Recorded as D24 and D25.

### Audited again: every provision is reachable under its own citation

Coverage was the wrong test to stop at, and asking the same question a second
way found five more defects. The National Standards Rules were at **100%
coverage while rules 4, 7 and 8 did not exist as citations** — the gazette
prints those as a bare `8.` with sub-rule `(1)` on the next line, so the rule
never opened and its sub-rules were read as a *second* `Rule 3(1)`, `Rule 3(2)`
and `Rule 6(2)`. The metre and the kelvin were filed under the metric-system
rule and the second, with a well-formed citation and fluent text over them.

Counting the rule numbers is what found it. Every principal Rules document had
a hole:

- **no heading at all** — National Standards rr. 4, 7, 8, and rr. 5 and 6 whose
  sub-rule (1) was being consumed as the heading;
- **a one-word heading** — General Rules r. 2 *Definitions* and r. 11 *Weights*,
  rejected by the two-word minimum that keeps `15. Soaps` out of the rules;
- **a colon for a stop** — Approval of Models `16: Deposit of Models`;
- **a fullwidth bracket** — the recogniser sets `(1)` as a CJK bracket on 212
  lines, and thirteen sub-rules were invisible behind it, r. 8(1) among them;
- **a line the detector never returned** — Approval of Models r. 10, missing
  from the OCR at 300, 450 and 600 dpi alike at a confidence of 0.98.

The first four are parser defects; the fifth is `sweep_gaps`, which re-reads the
bands no text box covers. Recorded as **D26** and **D27**.

Two defects of precision were fixed alongside them. A citation that resolves to
two provisions is a citation to neither, and there were **1,931** such rows: the
General Rules' Eighth Schedule is 126 pages of instrument specifications that
each number their clauses from 1, so `Eighth Schedule, item 3` named
twenty-three different things. Tracking `PART` and `APPENDIX` divisions brings
it to **1,161**; a table's column-number row (`1. 2. 3.`) and its decimal
tolerances (`2.0 to 3.5`) no longer open provisions at all.

- [x] OCR the scanned gazettes into `data/rulebook/extracted/` — done, 838 pages
- [ ] **391 pages are held but not readable English.** The recogniser is PP-OCR
      English/Chinese and has no Devanagari model; handed a Hindi page it emits
      CJK glyphs with high confidence. They are recorded in
      `data/rulebook/manifest.json` with the reason rather than dropped, and
      nothing in the rulepack cites them. Re-examined page by page in the audit:
      the English on them is the masthead, unit symbols inside Hindi sentences,
      a few figure captions, and — in one case — the English column headings of
      a form whose body is Hindi. **That last one is a real loss and it is the
      only one**; see RESULTS.md. Every rule and every Schedule is present in
      its English text
- [ ] Generative tier-3 summary (`Qwen2.5-3B` / `Llama-3.2-3B`, int4). Optional in §15; not built

## P8 — Web / PWA (§5, §11, M11)

Built 2026-09-09. `web/` — **14** Playwright tests green, `tsc --noEmit` clean, `eslint` clean. (The count said 9 while 12 existed and one of those had never passed: `camera.spec.ts` looked for a button reading "Upload a photograph" and `scanner.tsx` has said "Upload photographs" since the first commit. Found 2026-09-18 when the session fix made the rest of that file run again — a suite whose failures nobody is counting is a suite that is not being run.)

- [x] Next.js App Router · React 19 · TS 5.7 strict · Tailwind 4 · Recharts 2.15. **Two deviations, both stated:** Next is on **16.3.4**, not the 15.1 the plan pins — 15.1.12 carried a critical advisory whose fix landed only in 16.3.0, so the 15 line had no safe version. Upgraded 2026-09-09; `npm audit` now reports nothing that reaches the browser. **shadcn/ui was not installed**: its MCP server would not connect, and the six primitives we need (button, card, badge, table, field, alert) are hand-written in `web/src/components/ui/` in the same idiom, on `class-variance-authority` + `tailwind-merge`, with only `@radix-ui/react-slot` as a dependency. Nothing else in the registry was needed.
- [x] Types generated from OpenAPI (`npm run gen:api` → `web/src/lib/api/schema.gen.ts`) — and CI fails if the committed file is stale. The seven dashboard payloads return `dict[str, Any]` by design, so they are hand-declared in `web/src/lib/api/types.ts`, each naming the `api/analytics.py` function it must match
- [x] TanStack Query v5; no Redux, no Zustand, no store of any kind
- [x] All 13 routes: `/login` `/scan` `/scan/[id]` `/scan/bulk` `/scan/listing` `/products` `/products/[id]` `/search` `/dashboard/{overview,brands,brands/[brand],rules,categories,districts,health}` `/summary` `/rules` `/admin` `/queue` — plus `/offline`
- [x] Scan screen: verdict above the fold, annotated canvas overlay (declaration boxes red with measured height, PDP dashed), **latency shown** (server and device separately), **scale tier + coverage always visible**, REVIEW amber with a distinct glyph
- [x] Dashboard: 5 tiles (each a link, each with its period change) + trend + violations-by-rule + review queue; brands defaults to high-severity sort and carries the parent column; rules, categories, districts, health
- [x] 4 global filters as URL params; shareable links survive the sign-in redirect (tested)
- [x] Every table server-paginated (`?limit&offset`) with CSV export that ignores the page; every chart has a table view; **nothing auto-refreshes** — `refetchOnWindowFocus` and `refetchInterval` are off globally, and the one poll is the bulk job counter, which stops when the job does
- [x] Accessibility: 16 px floor enforced in the type scale, 44 px targets, keyboard nav with a skip link, and a **daylight mode** that is a third palette rather than a variant of light. Two Playwright tests assert the floor and the target size
- [x] PWA: Workbox 7 — models `CacheFirst` (safe only because the version is in the filename), API `NetworkFirst`, static chunks `StaleWhileRevalidate`, `/offline` `/scan` `/queue` fetched at install so they exist before they are needed
- [x] 🆕 **Identity and palette** — the mark is drawn as inline SVG (`web/src/components/brand.tsx`), the crimson-to-orange gradient is hoisted into one `<defs>` in the root layout, and `scripts/make_icons.py` is its raster twin on the same 64-unit grid. Three palettes rebuilt around it. The one hard constraint is written into `globals.css`: the brand is **wine**, FAIL is **scarlet**, and status is never carried by hue alone — otherwise a chrome painted in the brand colour competes with the only two signals on the screen that mean anything
- [x] 🆕 **Camera fixed** — `startCamera` assigned `srcObject` from the click handler while the `<video>` was still unmounted, so the ref was `null`, a guard swallowed it, and the element mounted with no source: permission granted, viewfinder black, nothing thrown or logged. The stream is now state and is attached by an effect (`web/src/lib/scan/use-camera.ts`), with a 20 s bound on a `getUserMedia` that never settles, a relaxed-constraint retry on `OverconstrainedError`, and a named diagnosis for each of six failures — the commonest being an **insecure context**, where the fix is a URL and not a permission. `--https` on the launcher covers that case. 3 Playwright tests
- [x] 🆕 **Viewfinder framing guide** — a dashed rectangle and one sentence on the glass. §18b measured 4.9–11.7 px/mm against a premise of ~24, and the whole of that gap is officers filling the frame with the marker card instead of the declaration
- [x] 🆕 **Navigation** — the current section is marked (`aria-current`, not colour alone) and the dashboard tabs carry the global filters across, which the layout's own docstring already promised and the bare `href`s were silently dropping. On a phone the eight links now scroll in one row instead of wrapping into three: the masthead was 200 px tall on a 390 px screen, a third of the first view of a tool whose primary device is a phone
- [x] 🆕 **Empty states** — a fresh deployment showed five zeroes, two blank chart frames and an empty queue, which is indistinguishable from a broken one. `EmptyState` tells "nothing scanned yet" apart from "these filters match nothing", because the next action differs
- [x] 🆕 **Found and fixed 2026-09-18: the two halves of the dashboard kept different clocks.** The browser's calls go through the proxy, which spends the refresh token on a 401 and retries; Server Components call `serverFetch` and had nothing behind them, because a Server Component cannot write a cookie and so could not keep a renewed token even if it asked for one. An access token lives **30 minutes** and a refresh token **14 days**, so anyone who left a tab open came back to a page reporting a dead session while the credential that would have renewed it sat unspent in the same jar. `middleware.ts` now reads the access token's `exp`, renews through `/auth/refresh` within 60 s of expiry, and writes the new pair to the **request** as well as the response — without that line the first page after renewal still renders with the dead token. The `exp` is read without verifying the signature and that is deliberate: it decides whether to spend a round trip, never what anyone may do, and `require_role` still decides that against the signed token. **Three outcomes, not two** — a rejected refresh signs the officer out, an *unreachable* API does not, because collapsing those into one `null` is how a thirty-second outage becomes every officer in the field being signed out; the renewal is bounded at 5 s, since this code sits in front of every navigation and an API that accepts the socket and then stops answering never fails on its own. Four cases measured against the live stack: a fresh session renews nothing, an expired access token renders the record with a new `HttpOnly` cookie, an expired refresh redirects to `/login?next=` with the session cleared, and a stopped API leaves the session alone and says the server is unreachable
- [ ] 🆕 Browser OCR via `ppu-paddle-ocr` — **not built.** The bundle manifest, the execution-path probe and the cache strategy are in place; the pipeline itself is not, and `web/src/lib/scan/engine.ts` says so in place of guessing. §8b's `NO_DATA`-never-a-guess rule does not relax in a browser
- [x] 🆕 **COOP/COEP headers** in `web/next.config.ts`, repeated in `docs/deployment.md` with the nginx trap (`add_header` in a location block discards inherited headers). A Playwright test asserts both the headers **and** `crossOriginIsolated` in the page
- [~] `onnxruntime-web` — the WebGPU/WASM-SIMD/threads probe is built (`web/src/lib/ocr/runtime.ts`), the path is recorded into `model_versions` as `runtimeTag`, and it is shown on `/queue`. The runtime package itself is not a dependency yet because nothing imports it; it goes in with the pipeline
- [~] IndexedDB outbox (`idb` 8), UUIDv7 written out by hand (`crypto.randomUUID` is v4 and would not sort), idempotent replay. **Verdicts sync; photographs do not** — the API has no route that attaches an image to a sealed scan record, and §6 hashes that record with its image fields inside, so filling them later breaks the chain at that row. `/queue` states this in words rather than showing a stalled progress bar
- [x] Offline SKU cache warming (`/skus/cache`, top 5,000, district-scoped) — manual from `/queue`
- [x] Cached bundle: precached shell **1.13 MB** across 28 files, models budgeted at ~44 MB. CI fails the build if `.next/static` + `public` exceeds 60 MB. (Next 16 emits stylesheets into `static/chunks/` rather than `static/css/`; the precache glob was directory-scoped and silently matched no CSS after the upgrade — workbox reports that as a *warning* and writes a valid worker with no stylesheet in it, so the only symptom is an unstyled offline page. The glob is now extension-scoped across all of `static/`.)

## P9 — Dataset and training (§14, §16)

- [x] Label Studio config: package box, PDP polygon, panel polygons, declaration boxes + field + script, **ChArUco marker card box** — `training/detector/label_config.xml`. Every label value is a member of a `contracts` Literal, so a box drawn in the tool maps onto the type the pipeline already uses with no translation step to get wrong
- [x] Annotation guide — `docs/annotation-guide.md`. Seven rules, each with the specific way of getting it wrong that it exists to prevent: cap height excludes descenders (a corner-to-corner box is 30-40% tall, *always in the same direction*, so every measurement clears the legal minimum); the MRP box covers the whole declaration but the height measurement uses the numerals; folds and curves take the largest flat run; `other` is never a guess; `marketing_text` is never `mrp`; manufacturer/packer/importer/consumer care are four fields; second annotator signs off the field names only, and the guide says which four things they check
- [x] `data/manifest.json` + corpus target tracker — written by `scripts/ingest_originals.py`, one row per frame with SHA-256, device, capture time, resolution, `millimetre_grade`, and the supersede link to the transcode it replaces. §16's target table is machine-readable beside it, and a row this script cannot count reports **null** rather than a guess: `unmet` and `unknown` are different states and nothing here knows whether a surface is curved
- [x] `scripts/audit_corpus.py` — survey before training: exact and near duplicates, sharpness and edge density (both denoised, see below), exposure clipping, resolution, and a contact sheet of the flagged frames
- [~] **469 photos / ~207 products RECEIVED 2026-09-07** — audit in `data/corpus/audit.json`. Clean: only **1** genuinely blank frame and **15** exact duplicate copies out of 469. Hindi and non-food both well represented.
- [~] ⚠️ **The 2026-09-07 set was WhatsApp-transcoded: max side 1600 px, EXIF stripped on all 469, re-encoded progressive JPEG.** **PARTLY RESOLVED 2026-09-09: 231 camera originals arrived** (LAVA LXX504 ×151, iPhone 13 ×80), full EXIF, 7.5-12 MP, ingested by `scripts/ingest_originals.py`. They supersede **221 of the 469**; **248 still have no original**. Measured on 40 matched pairs: median text line 33.4 → **86.7 px**, tenth-percentile line 17.6 → **52.9 px** — the bottom decile was sitting exactly on PP-OCR's ~16 px cliff. Regions detected changed by +1%, so detection was never the bottleneck; the small print was. **U1 is unaffected** — the sealed test split was never transcoded and its problem is the capture protocol, not resolution. See `docs/corpus.md`.
- [x] 🆕 **38 labelled declaration panels RECEIVED 2026-09-10** — `data/declaration_blocks/`, ingested by `scripts/ingest_declaration_blocks.py`, scored by `bench/declaration_blocks.py`. One photograph per pack, each showing the statutory panel, **every field read by eye and written down**: 255 labels over 38 frames in `ground_truth.json`, with a tracked JSON schema and a SHA-256 manifest, and the bench refuses to run if any image's bytes have moved since annotation. **This is the project's first accuracy measurement of any kind** — every vision figure before it was measured against the unlabelled corpus and is therefore a coverage figure, the pipeline compared against itself. Presence micro **F1 0.751, precision 0.981, recall 0.608**; Rule 6(1) mandatory recall 0.609; framing recall 0.947 (recall only — the set has no negatives, so no false-positive rate can be read off it). Two annotations are excluded from scoring in opposite directions: `blank_labels` (a printed label with no value after it — the *package* failing, not the extractor) and a null value (printed but illegible, or a cross-reference such as `See on Crimp`). The set carries two Rule 6(3) frames — a pasted-over MRP and a struck-through revised price — that nothing else in the project has. `RESULTS.md`, "38 labelled declaration panels"
  - **The one fix it earned.** `find_label_quad`'s area floor 0.12 → **0.20**. `rectify` prefers a quad over every method but a marker, so a 13%-of-frame barcode block was becoming the whole scan; `papad.jpg` recovered one legible line and exited L4 while its rectangular sibling `udadpapad.jpg` read 63. **0.50 was tried first and `tests/golden` rejected it** on a legitimate 36.6%-of-frame label — the golden suite doing exactly its job. Net +4 labels, one total-failure case removed, one field lost on `matches.jpg`; 1007 tests pass
  - **The three defects it exposed and did NOT fix,** each measured rather than guessed at: the MRP numeral is not associated with its label on 11 frames (`vision/classify/associate.py` reaches 4× line height; the gaps are 4.3-9.2, and relaxing the same-line test would make a lot number into a price — MRP precision is 1.00 today); M0 rejects 21 of 38 readable panels, above; and `generic_name` recall 0.04, of which 21 of 27 are cases the rulepack **deliberately** declines rather than read a brand as a generic name
- [!] **20-30 deliberately non-compliant / negative photos — user is supplying**
- [!] **40-photo ruler-measured test split — BLOCKED ON USER**
- [~] ⚠️ **REDO** `training/detector/` — **code complete, blocked on annotation.** `rtmdet-ins_tiny_akshar.py` (640 px, batch 16, AdamW 1e-3, 100 epochs, mosaic and hflip removed from the pipeline rather than probability-zeroed, RandomResize narrowed to 0.75-1.25 because scale *is* the measurement, `filter_empty_gt=False` so §14's ~15% detector negatives survive, checkpoint selected on `segm_mAP` because the PDP mask is what the homography is fitted to) plus `convert.py` (Label Studio → COCO instance segmentation; reads `annotations` and **refuses `predictions`**, splits by burst group so near-identical frames cannot straddle the line, and raises rather than skips if a `data/test_split/` frame appears in an export) and `training/requirements.txt` (mim-installed, which `pyproject.toml` already referenced and which did not exist). **Nothing can train until a person has drawn boxes** — `convert.py` currently reports all 479 tasks as carrying no completed annotation, which is correct
- [~] `training/classifier/train.py` — **code complete, blocked on annotation.** Two-layer encoder over the frozen 384-d MiniLM embedding, focal γ=2, AdamW 3e-4, cosine, 30 epochs, early stop on val **macro** F1 (accuracy would select the checkpoint that learned to say `manufacturer`). `FEATURE_DIM` and `CLASSES` are **imported** from `vision/classify/`, never restated, and an assertion fails the run if the built matrix disagrees — §15b's feature skew is silent and is the usual way a working classifier degrades. Splits by photograph, not by row. Reports per class and refuses to average, and prints a warning naming any class with no examples
- [~] `training/ocr/baseline.py` — §14 says *"don't start here"*, so this measures and there is deliberately no `train.py` beside it yet. **M4's speed half is done and is in `RESULTS.md`**; the CER half needs transcriptions, so `--worksheet` writes a CSV of what the recogniser read with an empty `truth` column beside it and `--cer` scores it, bucketed by a surface-type column a person fills from a fixed vocabulary. A blank `truth` is *not checked* and is dropped, never counted as agreement. That is the difference between "we have not measured CER" and "we cannot" — we can; it costs a person an hour
- [ ] Hard-negative set curated (`Rs. 20 OFF`, `24MRP07`, drained wt, best-before, manufacturer-vs-care, barcode digits)
- [ ] INT8 ONNX export + accuracy delta recorded (**ship FP16 if INT8 loses >1% mAP**)
- [ ] Corrections feed retraining — retrain end of week 4 and again week 6, report the delta

## P10 — Testing, bench, CI, docs (§4, §18, §18b, §20)

- [x] Unit tests: every check type, every status, boundaries — `tests/unit/test_check_sweep.py`, **62 tests**. Goes at the thirteen check *functions* directly, where `test_engine.py` goes through the rulepack: three of the thirteen (`min_width_ratio`, `clear_space`, `min_contrast`) are exercised by exactly one rule each and were one YAML edit from having no test at all. Asserts three invariants across all of them — a missing declaration is never a FAIL (except in the two presence checks, whose job it is, and that exception is pinned by its own test), nothing raises on an empty `DeclarationSet` or at tier C, and every FAIL says what it expected. Walks both sides of the `min_height_mm`, `min_contrast` and `value_in_range` thresholds including the REVIEW bands, and asserts all five statuses are reachable — REVIEW and NO_DATA are the two an accuracy-chasing implementation quietly drops
- [x] Golden-file tests — `tests/golden/`, **12 snapshots**. Ten drawn scenes plus the listing-text channel plus a meta-test that fails if a scene has no committed snapshot. Drawn rather than photographed because *fixed* has to mean the same bytes on a CI runner that has none of the corpus, and `tests/unit/synthetic.py` already exists for that reason. The scenes are the traps §14 names: a promotional graphic printed larger than the real MRP, a batch code reading `24MRP07`, a drained weight beside a net weight, plus tier C, steep perspective, kraft paper and 8 px print. Timings and clocks excluded, coordinates rounded to 1 px, **confidences kept** — a recogniser update that moves a confidence from 0.97 to 0.62 has changed behaviour
- [x] Contract tests — `tests/unit/test_contracts.py`, **13 tests**. §18's claim was true of most of the API and **not of the dashboard**, which `web/src/lib/api/types.ts` admits in its own header: those routes return `dict[str, Any]` and the browser's idea of their shape is hand-written, so *"nothing will tell us automatically"*. This is that something — it parses the TypeScript interfaces, runs the real analytics functions over synthetic scans, and compares key sets in both directions. The regression it would have caught already happened: `TrendPoint.rate` against a payload saying `non_compliance_rate`, which drew an empty chart grid and looked like *no data*. Also asserts every route declaring a `response_model` publishes a schema, and that `web_openapi.json` is not stale
- [x] `tests/test_boundaries.py`: `rules/` and `contracts/` import nothing forbidden — **unaffected by the switch, which is the point**
- [x] Benchmarks enforcing the §4 budget; **build fails on regression**
- [x] ⚠️ **REDO** Benchmark budgets — all three. Scale 70 → **55 ms** (ArUco corner detection is cheaper than the coin-ellipse fit it superseded). **B1 measured at 11.5 ms** against §18b M0's 15 ms, asserted against the acceptance figure rather than the 8 ms budget because M0 is what `RESULTS.md` has to quote. **WASM cache-miss row** enforced the only honest way without weights: §4's exit-two total decomposes into 141 ms that is identical on both backends and 895 ms of model time that is not, so the deterministic share is measured through `scan()` as one composition and asserted against 2000 − 895 ms — plus a test that re-derives both constants from §4's table, because the scale row already moved once
- [x] Playwright E2E incl. the aeroplane-mode offline run — **12 tests**, all green (9 plus the three camera regressions). The offline one takes a photograph with the context offline and asserts the L4 record survives a reload; the others cover the sign-in redirect keeping its filters, cross-origin isolation, the daylight palette, the skip link, the 16 px / 44 px floors and the manifest
- [x] GitHub Actions CI — four jobs: `python` (ruff, mypy strict on `contracts` + `rules`, pytest), `web` (typecheck, lint, build, 60 MB bundle budget), `contract` (**regenerates the OpenAPI types and fails if the committed file is stale**), `e2e`
- [x] `docs/architecture.md` — 2 pages, including a section naming the honest gaps
- [x] `docs/legal-decisions.md` — comma, litre symbol, NS r.18/kcal: what we declined and why
- [x] `docs/plan-migration.md` — AKSHAR → AKSHAR, every delta and what it invalidates
- [x] `docs/deployment.md` — carries the COOP/COEP headers, the `curl` that checks them, the nginx `proxy_pass_header` form, and what `require-corp` costs
- [~] `RESULTS.md` — accuracy AND latency, dated. **The advisory false-positive count is now measured** by `scripts/advisory_false_positives.py`, which runs the pipeline over the corpus originals, counts every advisory FAIL by rule, and prints the exact string that triggered each so a person can judge which are the packet's fault and which are the recogniser's — it measures and shortlists, it does not decide. Accuracy is still the gap: U1 is 0.499 mm on 4 of 40 frames against a ≤0.15 mm target, recorded with the decomposition of the misses
- [x] 🆕 **One-command demonstration stack** — `python scripts/run_demo.py` brings up the API on :8000 against the in-memory stores and the web app on :3000, with **no Docker, no Postgres, no Redis, no MinIO**. §20 asks for `docker compose up` from a clean clone and `docker/` still holds that; this is the path that survives Docker Desktop refusing to start on the morning of a demonstration, and it is not a special mode — it is the Protocol-typed stores and the `auto` storage backend being used as designed
- [x] 🆕 **`api/demo.py`** — a synthetic shelf: 3 officers, 16 SKUs across 10 brands and 6 districts, 260 scans over 75 days. **Off by default since 2026-09-09** (`--seed` to turn it on): invented brand names on a dashboard are easy to mistake for findings, and an empty instance is what a real deployment looks like on its first morning. Account creation was split out of it (`seed_accounts`) and is unconditional on the memory backend, because that backend has no migration and no registration route — without it the empty instance is not empty, it is bricked. **Not one verdict is hard-coded.** Each demo pack is a real `DeclarationSet` with real geometry, run through `rules.engine.evaluate` against the real rulepack, so the dashboard is drawn by the same code path a real inspection uses. Guarded three ways: off by default, refused in production, refused on the SQL backend, and `/healthz` says `DEMONSTRATION DATA` in its detail list whenever it is on
- [x] Submission checklist (§20) walked end to end — `docs/submission-checklist.md`. Twelve rows: **7 green, 4 amber, 2 red**. The reds are the demo video and the five-slide deck. The ambers are the ones worth acting on: the repository has **no commits at all** so "clean clone" has no meaning yet; migration `0002` has never been run against a live database (a fresh `compose up` is covered by `schema.sql`, an *upgrade* from `0001` is not); and §20's *"cross-checked by two people"* has had one. The walk also caught that **two beats of the scripted demo cannot be filmed as written** — the 0.13 mm figure at 1:55 is the target, not the measurement, and `RESULTS.md` says 0.499 mm on 4 of 40 frames

---

## §18b — the five open questions, each with a test and a date

Nothing here is a leap of faith. Every unknown closes with a measurement.

| # | Question | Pass | Fail ⇒ | When |
|---|---|---|---|---|
| **U1** | Millimetre accuracy from a photograph | MAE ≤ 0.15 mm **and p95 ≤ 0.25 mm** | > 0.5 mm ⇒ absolute height becomes a stretch goal, lead with the scale-free tier | **Day 5–7 — go/no-go** |
| U2 | Devanagari on stylised packaging | CER ≤ 0.15 flat printed | > 0.25 ⇒ fine-tune the recognition head only | Week 2 |
| U3 | In-browser latency | <700 ms WebGPU, <1300 ms WASM | Detector 640→512 px; ROI cap to top 4 | Week 2, then CI |
| U4 | RTMDet-Ins ONNX export | Exports | > 1 day of fighting ⇒ take a pre-exported ONNX | Week 2 |
| U5 | Foil, glare, crumple | CER recorded per surface | B1 gate + two-pass re-read + docTR cross-check | Week 2 |

**U1 marginal band:** MAE 0.15–0.35 mm ⇒ keep absolute measurement but widen the
`REVIEW` band to ±2× MAE. **The fallback holds regardless: 28 of 31 rules never
needed a scale**, and two of them — `min_width_ratio` and `clear_space` — are
checks nobody else has.

**Build order follows from U1.** B1 (capture quality) and marker-based tier A
come before everything else, because U1 is a day-7 decision and B1 is what stops
a bad frame from poisoning it.

---

## Blocked — needs the user

| # | What | Why it needs you |
|---|---|---|
| 1 | 400-photo corpus, 100 SKUs | Physical products must be photographed; targets in §16 |
| 2 | 40-photo ruler-measured test split, **ChArUco card in frame** | Physical measurement to 0.1 mm with a steel rule — the headline number |
| 3 | ~~LMPC amendment gazettes~~ **DOWNGRADED to verification.** §13a confirms GSR 128(E), 312(E), 734(E) and 748(E) individually and finds **no confirmed amendment changes any rule we encode**. Only the "23 Oct 2025 medical devices" claim is unverified, and it stays out of the pack until someone produces the gazette | Not a blocker |
| 4 | ~~Gazette PDFs~~ **SUPPLIED** in `rules_and_acts_docs/` (15 files) | — |
| 5 | TAT SPOC deadline confirmation (§18b) | 20 vs 30 September portal date |

**The small ask comes first**, and it is not 400 photos. It is **two or three**:
one real packet with a printed ChArUco marker card in frame, shot roughly
straight-on in normal light, plus the true MRP character height measured with a
ruler. That converts tier A from a synthetic number into a real millimetre
error, and it is the day-7 go/no-go on U1.
- [x] ⚠️ **Answered 2026-09-10: section 15b's second-head benchmark. The answer
      is no.** *"Benchmark whether a second English-only head earns its bundle
      size; do not assume it."* Same crops, our PP-OCRv5 Devanagari head against
      PP-OCRv4's 6,623-character Chinese/English head: not better, and worse on
      long lines (`'MDSTAN UNLIVPUTD (HUL)'` against `'STANUWU'`). RapidOCR's
      entire pipeline on the same photograph found 18 regions to our 33 and read
      them no better. Hand-cutting six declaration lines at their true extent and
      reading them in isolation changed nothing either, and 3x Lanczos changed
      nothing, as it cannot. Across 30 frames the proposal boxes measure 1.00x
      the height of the ink they contain and 7% of stacked pairs overlap, so the
      boxes are not inflated. On frames where the statutory print is ~11 px of
      cap height in a re-compressed JPEG, no change in this repository reads it
- [x] ⚠️ **Found and fixed 2026-09-10: `TOLL FREE` was a promotional phrase.**
      `_PROMOTIONAL` listed a bare `\bfree\b` and is a *hard negative*, tested
      before every field pattern with nothing downstream able to recover from
      it. Rule 6(2) makes a consumer-care contact mandatory and a toll-free
      number is how Indian packs print one, so the declaration was not
      mis-ranked, it was deleted. `SUGAR FREE`, `GLUTEN FREE`, `GUILT FREE` and
      `EXTRA VIRGIN` went the same way. Promotion is now recognised by the forms
      that are promotional; `50% EXTRA FREE` and `BUY 1 GET 1 FREE` still are
- [x] ⚠️ **Found and fixed 2026-09-10: `_PRIORITY` alone answered the wrong
      question.** Rank gave `BATCH No., MFD. & USE BY : SEE BELOW` and `Batch
      No., Mfd. & Use By Date:` to `expiry_date` because that entry sits higher,
      so Rule 6(1)(c)'s batch number was reported undeclared on a pack whose
      first printed word is BATCH; and it let `...and Mfg date)` at the end of a
      sentence outrank `For Consumer complaints,` at its start. Where a line is
      set, a declaration is introduced by its own label and the label comes
      first. Resolution is leftmost-match now, rank breaking ties -- which is
      where every reason written into `_PRIORITY` still applies, all of them at
      offset zero and all of them unchanged
- [x] ⚠️ **Found and fixed 2026-09-10: five more labels a pack prints that
      matched nothing.** `Commodity :  Toy` (Rule 6(1)(b), named **zero** times
      across 122 photographs), `DATE OF PKG.:` (6(1)(d) -- `pack\w*` takes
      packing and packaging but not the abbreviation), `Regd. Office & Consumer
      Cell:` (6(2)), `Manufacturing Address of PL:` (6(1)(a), which the
      `manufactur\w*` stem was reporting as a date), and a price with no caption
      at all -- `₹ 90/-` on a jam lid, `₹ 149.00` in a Mattel column. The price
      form is kept narrow in the one direction that matters: `/-` settles it,
      otherwise two decimals are required, and a trailing per-unit suffix drops
      `₹ 0.45/g` and `₹ 575.00/kg`, which are the *unit* sale price printed
      beside the MRP. Measured on perfect transcribed text: **26/34 -> 33/34**
- [x] ⚠️ **Measured 2026-09-10: none of that moved the verdicts.** 39 -> 40
      frames non-compliant, 101 -> 100 blocking FAIL. `locate` searches
      `searchable_text`, which is the field lines **plus the whole label**, so a
      presence check never depended on the caption. Classification fixes the
      exhibit an officer reads and almost nothing else. Recorded because it is
      the second tidy theory this week that the corpus cut down, and because it
      is worth knowing before anyone spends another day on patterns
- [x] ⚠️ **Found and fixed 2026-09-10: a country of origin was read as evidence
      of import.** `LMPC.IMPORTER.PRESENT` was conditioned on *any*
      `country_of_origin`, so seven frames raised a high-severity finding that no
      importer was named -- four of them printing `PRODUCT OF INDIA` or `MADE IN
      INDIA` on the face of the pack, one a Mattel carton reading `Country of
      Origin : INDIA` directly above its declaration column. Declaring where a
      thing was made is not declaring that it was brought in. `text_excludes_ref:
      domestic_origin` now carves it out, and `also_when_context: is_imported`
      still overrides the carve-out, because a pack can be imported and silent
      about it. **7 -> 2**, both remaining genuinely foreign
- [x] ⚠️ **Found and fixed 2026-09-10: one mis-read character removed a mandatory
      declaration.** `Maximum Retail Price: ₹ 149.00`, the largest type on a
      Mattel panel, came back at **0.93 confidence** as `'Maximum Retai Price:
      {149.00'`. `mrp_locate` spells `retail`; Rule 6(1)(e) was reported
      undeclared. Also `NET QOUANTITY`, `CONSUME CARE`, `Maketed By:`.
      `mend_label_noise` forgives one edit inside a word the pattern already
      spells -- whole words, five characters or more so `mrp`/`net`/`qty` stay
      strict, vocabulary derived from the pattern being run so there is still one
      definition. Presence only (a format finding is *about* the characters) and
      pixels only (`listing_text` has no recogniser to forgive). **8 declarations
      recovered across 122 frames**, all mandatory and all genuinely printed
- [x] ⚠️ **Found and fixed 2026-09-10: Rule 6(1)(b) does not require a caption,
      and we can only find a declaration by its caption.** 23 of 121 frames were
      failed for an undeclared generic name against packs printing `Chana Besan`,
      `AA 1015 R6P BATTERIES`, `Crunchy Spicy Potato Noodles` -- the generic name
      in substance, in display type, with nothing introducing it. Nothing here
      separates that from marketing copy, so "not declared" was a verdict about
      our own vocabulary. REVIEW on a photograph with that reason attached, FAIL
      still on `listing_text`. `uncaptioned_form_is_lawful` is set on this rule
      alone: of Rule 6(1)'s six it is the only one habitually set unlabelled
- [x] ⚠️ **Found and fixed 2026-09-10: a format finding quoted the wrong 120
      characters.** `strict_text` falls back to the whole label when the
      classifier produced no line for the field, and `found` took its first 120
      characters -- `'2-10\n7+\nFSC\nMX\nFSC* C161542\nBAVTRCKP...'`, the
      top-left corner of a toy box, naming nothing an officer could check. On
      that fallback the finding quotes the neighbourhood of the located label
- [x] ⚠️ **Checked and kept 2026-09-10: `LMPC.NETQTY.EXCLUSION_ZONE` is not a
      false accusation.** It is 40% of the remaining blocking FAILs and fires on
      every frame with a legible back panel, which is the shape of a defect, so
      it was checked against the gazette and the photographs instead of assumed.
      lmpc_2011 p.9 prescribes a clear space of one numeral height above and
      below and two to the left and right, which is what the rule carries; and
      the intruders it names are real printed matter -- `Month & year of Mfg. :
      11/2025` beside a Mattel net quantity, `MRP (incl. of all taxes): ₹35.00`
      directly under a Perfetti one. Indian declaration panels are set as a tight
      column and normal leading is less than a numeral height. Genuine, commonly
      violated, and one of the two rules that survive total failure of scale
- [ ] ⚠️ **Blocked on the user, restated 2026-09-10 with the measurement behind
      it.** `dataset034_withoutlabelboxes` is 122 files of which **119 are
      already in `data/corpus/images`** by dHash, every one 1600x1200 or smaller
      with EXIF stripped and a 185 KB median -- messaging transcodes, the same
      grade as the 248 frames `data/manifest.json` counts as `transcode_only`,
      and **0** of them match anything in `data/corpus/originals`. The batch is
      genuinely useful -- nothing is drawn on top, so it can be annotated -- but
      it does not raise capture quality, and capture quality is what the small
      print needs

- [x] ⚠️ **Built 2026-09-10: B1 had no check for what the camera was pointed
      at.** The gate has five faults -- `blur`, `glare`, `underexposed`,
      `overexposed`, `resolution` -- and every one is about *how* the photograph
      was taken. **40 of 122 corpus frames are sharp, well-lit, correctly
      exposed photographs of the brand face**, and the gate passes all of them,
      because as photographs they are fine. `vision/quality/framing.py` answers
      the other half after the read, because nothing in the raw pixels separates
      a sharp photograph of a declaration panel from a sharp photograph of the
      front of the pack -- you only know once you have looked. Two faults, two
      sentences: `no_declaration_panel` ("turn the pack over") below 20 read
      lines, `wrong_panel` ("this is the nutrition table") above it. On the
      corpus that splits **54 ok / 40 no_declaration_panel / 28 wrong_panel**,
      and the 40 match the 41 front-of-pack frames counted by eye. It sets no
      status and `rules/` does not import it -- asserted by a test -- and it is
      emitted only when **zero** declarations were found, because a frame naming
      two of six may equally be a package that declares two of six, and calling
      that a framing fault would hand every under-declared pack an alibi
- [ ] ⚠️ **Committed by the user 2026-09-10: 40-50 photographs framed on the
      declaration block**, transferred without a messaging app. This is the
      revised ask and it replaces "the same shots at full resolution", which was
      measured at **+8% usable lines / +4% named declarations** over 47 pairs
      with 13 of 47 reading *worse*. It is what finally gives M0 a positive
      class: 40 known-good framings against the 40 known-bad ones the corpus
      already contains is the labelled set §17's done-criterion has been waiting
      on, and `RESULTS.md` can then report a recall figure for B1 honestly.
      Annotation follows, on those photographs rather than on the current batch
