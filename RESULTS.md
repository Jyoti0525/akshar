# RESULTS

Every measured number, dated, with the command that produced it.

**Rules for this file.** A number goes here only when it was measured on this
machine or in CI, never when it was estimated. Targets from the plan are listed
beside measurements so the gap is visible. A number with no date is not a
result. Nothing from the ruler-measured test split may appear here until day 36
(§19) — if it leaks into tuning, the headline number is fiction.

Legend: **measured** · *target* · `pending` (not yet measurable) · ~~struck~~ (measured, then invalidated by a plan change)

> **Plan switched 7 September 2026: MAAPDAND → AKSHAR.** One measured number
> below was invalidated by it — the scale tier A error, which was measured
> against a drawn ₹5 coin. §8b now specifies a printed ChArUco marker, so that
> figure describes code that is being replaced. It is struck through rather than
> deleted: a number that was true when measured stays in the record, marked. The
> plan-level diff is in [docs/plan-migration.md](docs/plan-migration.md).

---

## Rules engine latency — §4 performance budget

| Metric | Target | Fails above | Measured | Date | Machine |
|---|---|---|---|---|---|
| Rules engine, 37 rules | < 10 ms | 25 ms | **0.318 ms** (mean), 0.304 ms (median) | 2026-09-03 | Windows 11, Python 3.12.8 |
| Rulepack cold load | — | — | **29.2 ms** | 2026-09-03 | same |

Command: `pytest bench/ -q --benchmark-columns=mean,median,max`

Notes: 37 rules is the 31-rule core pack plus 6 extension rules, so this is a
harder case than the 30 rules the budget quotes. Headroom is roughly 31×. Cold
load is YAML parse plus regex compilation and happens once per process;
`cached_rulepack()` serves subsequent calls.

---

## Rulepack size — §5 offline bundle

| Metric | Target | Measured | Date |
|---|---|---|---|
| `rules/packs/lmpc_2011.yaml` | ~40 KB | **41,241 bytes** | 2026-09-07 |

The claim "the entire legal logic of the system is small enough to email" is on
a slide, so `tests/test_boundaries.py` asserts it stays under 100 KB.

---

## Rulepack coverage — §13

| Metric | Plan | Measured | Date |
|---|---|---|---|
| Core rules | 31 | **31** | 2026-09-03 |
| Extension rules (§13b) | not counted in the plan | **6** | 2026-09-03 |
| Check types | 13, "and no more" | **13** | 2026-09-03 |
| Rules needing millimetres | 3 | **3** | 2026-09-03 |
| Scale-independent rules | 28 of 31 | **28 of 31** | 2026-09-03 |
| Rules enabled by default | — | **30 of 31** (litre symbol disputed, §13c) | 2026-09-03 |

See [docs/spec-deltas.md](docs/spec-deltas.md) D9 on the "28 of 31" phrasing.

---

## Test suite

| Suite | Count | Result | Date |
|---|---|---|---|
| `tests/unit/test_engine.py` | 61 | **all pass** | 2026-09-07 |
| `tests/unit/test_vision_geometry.py` | 34 | **all pass** | 2026-09-07 |
| `tests/unit/test_u1_report.py` | 11 | **all pass** | 2026-09-07 |
| `tests/unit/test_reports.py` | 19 + 1 skipped | **all pass / skipped** | 2026-09-08 |
| `tests/unit/test_vision_pipeline.py` | 49 | **all pass** | 2026-09-08 |
| `tests/unit/test_vision_detect.py` | 19 | **all pass** | 2026-09-07 |
| `tests/unit/test_evidence_chain.py` | 32 | **all pass** | 2026-09-07 |
| `tests/unit/test_evidence_storage.py` | 21 | **all pass** | 2026-09-07 |
| `tests/unit/test_schema.py` | 54 | **all pass** | 2026-09-07 |
| `tests/unit/test_api.py` | 36 | **all pass** | 2026-09-07 |
| `tests/unit/test_analytics.py` | 35 | **all pass** | 2026-09-07 |
| `tests/unit/test_dashboard_api.py` | 41 | **all pass** | 2026-09-08 |
| `tests/unit/test_annotation.py` | 26 | **all pass** | 2026-09-08 |
| `tests/unit/test_summary_report.py` | 17 | **all pass** | 2026-09-08 |
| `tests/unit/test_retrieval.py` | 60 | **all pass** | 2026-09-08 |
| `tests/unit/test_tier2_search.py` | 22 | **all pass** | 2026-09-08 |
| `tests/unit/test_upload_path.py` | 47 | **all pass** | 2026-09-08 |
| `tests/unit/test_sql_stores.py` | 29 | **all pass, live Postgres** | 2026-09-08 |
| `tests/unit/test_ingest.py` | 23 | **all pass** | 2026-09-08 |
| `tests/test_boundaries.py` | 12 | **all pass** | 2026-09-08 |
| `bench/` | 6 | **all pass** | 2026-09-07 |
| **Total** | **636**, 14 skipped | **all pass** | 2026-09-08 |

**Nine of the ten skips are gone.** `docker compose up -d db` brought up
Postgres 17.11 + pgvector 0.8.6, and the SQL contract tests that had never
executed now run. Two of them failed on first contact with a real database: the
bulk-job fixture used a random UUID for `officer_id`, which the in-memory store
accepts and a foreign key does not. A test that passes only because the
implementation under it is permissive is not a passing test.

**The remaining skip is the PDF.** WeasyPrint installs on Windows and cannot render
there — it needs Pango, cairo and harfbuzz, which `docker/api.Dockerfile` now
installs and whose absence `reports.render.pdf_available()` reports rather than
raises. The HTML and DOCX paths have no native dependencies and are fully
tested, which matters because DOCX is the format the problem statement actually
names.

**The other 9 skips are the SQL half of the store contract, and they are a real gap
rather than a formality.** `api/sql/stores.py` has never executed against a
running Postgres — Docker was not available on this machine. The tests exist,
they assert exactly what the in-memory store already satisfies, and they run
with `AKSHAR_TEST_DATABASE_URL` pointed at a container. Until somebody does
that, "the SQL stores work" is a claim about code that has been read, not code
that has run, and it is written here that way on purpose.

`test_vision_detect.py` is new, and worth a note rather than a row. Before it,
`IMPLEMENTATION.md` claimed the detector decoder was *"verified against
synthetic tensors"* — **and there was no test for it at all.** A decoder with no
weights fails silently: the pipeline catches `ModelUnavailableError` and
degrades, so a transposed axis would have passed every other test here. The
claim was written, believed, and carried through a whole plan switch unchecked.
It is now true.

Writing the SQL stores turned up the same shape of problem twice more, and both
would have broken **only on Postgres**, silently. The `verdicts` table had no
`advisory` or `suppressed_by` column, so a deployment on the real database would
have reported unit-symbol formatting as non-compliance and counted every
suppressed measurement twice — the two rules §11's dashboard depends on most.
And the two stores returned different dict shapes from `verdicts_for`, so
`row["advisory"]` worked against one backend and raised `KeyError` against the
other. Both were found by writing one contract and running it against both
implementations, which is the entire argument for the Protocol.

Command: `pytest -q`

---

## Geometry — §17 M1, measured on synthetic photographs

**Read the caveat before quoting any of this.** These are measured against
synthetic labels drawn at a known pixel height and warped by a known
homography. They prove the *arithmetic* is right — no sign errors, no
coordinate-frame mix-ups, no descender counted into a cap height. They do not
and cannot prove real-world accuracy, which needs the ruler. Both numbers stay
separate in this file for that reason.

| Metric | Target (§17) | Measured | Date |
|---|---|---|---|
| M1 residual baseline skew after warping | < 2° | **0.00° max, 0.00° mean** over 8 distortions | 2026-09-07 |
| Skew before rectification (same photos) | — | **up to −4.97°** | 2026-09-07 |
| M1 quad recovery rate on the synthetic set | — | **8 of 8** found the label outline | 2026-09-07 |
| M1 rectification method when a marker is present | — | **`marker`**, preferred over `quad` | 2026-09-07 |
| ~~Scale tier A error vs the drawn coin diameter~~ | — | ~~< 8%~~ — **invalidated 2026-09-07**: tier A is a marker now, not a coin (§8b B3) | 2026-09-07 |
| Scale tier A error vs a rendered ArUco marker | — | **0.07%** | 2026-09-07 |
| Marker squareness after rectifying against it | — | **0.000** residual | 2026-09-07 |
| Cap height vs drawn height | — | **< 10%** | 2026-09-07 |
| **End-to-end mm recovery through the printed card** | *U1: ≤ 0.15 mm* | **0.034 mm** on a 1.80 mm digit | 2026-09-07 |

Command: `pytest tests/unit/test_vision_geometry.py -q`

The last row is the U1 loop run against itself: `scripts/make_u1_example.py`
builds a scene **in millimetres** — the MRP digits genuinely are 1.80 mm tall at
the rendered scale — puts the printed card beside the packet, and measures the
digits back through it. **It is synthetic and 0.034 mm is not the U1 number.**
U1 needs a real print, a real lens and a real steel rule, and that shoot has not
happened. What this does prove is that the card and the code agree about a
physical length, which is the failure it was written to catch.

It caught one immediately. The first card printed a ChArUco board whose *square*
was 25 mm, because `MARKER_EDGE_MM = 25.0` reads like the square. `tier_a`
measures the **ArUco marker inside** the square, which at OpenCV's usual 0.75
ratio is 18.75 mm — so the code divided by a length 33% larger than the one it
was looking at and returned **2.45 mm for a 1.80 mm digit**. Nothing about
detection showed it: all ten markers decoded, the scale resolved, the estimate
looked healthy. The card is now 34 mm squares carrying 25 mm markers, and a test
asserts the marker — not the square — matches the constant.

---

## pHash angle invariance — the D11 delta, measured

The same pack photographed from a different angle, 64-bit hash, match
threshold Hamming ≤ 8:

| Hashed on | Same pack, different angle | Different pack | Cache behaves? |
|---|---|---|---|
| Raw frame (as §4's table implies) | **26** | 24 | ✗ misses every re-photograph |
| Pre-normalised (D11) | **6** | **24** | ✓ hits, and still separates |

This is the measurement that justifies the delta: a raw-frame hash cannot tell
"same pack, moved the camera" from "different product", so exit zero would
essentially never fire. Date 2026-09-07.

---

## Vision latency — geometry only, no model weights

**Not the 561 ms end-to-end figure and must not be quoted as one.** The
detector and both OCR heads are absent, so this covers only the deterministic
geometry — identity, rectification, scale recovery. CPU-only, no GPU, so these
are pessimistic bounds on the browser numbers.

| Stage | Target (§4) | Fails above | Measured (mean) | Date |
|---|---|---|---|---|
| Cache hit (exit zero, no model) | < 100 ms | 200 ms | **12.6 ms** | 2026-09-07 |
| Pre-hash normalisation (D11) | must stay cheap | 40 ms | **4.0 ms** | 2026-09-07 |
| Identity (pHash + barcode) | 18 ms budget | 120 ms | **10.2 ms** | 2026-09-07 |
| Rectify + scale recovery | 125 ms (55+70) | 800 ms | **147.6 ms** | 2026-09-07 |

Command: `pytest bench/ -q --benchmark-columns=mean,median,max`

The pre-hash figure is the one that settles D11: 4.0 ms, not the 55 ms a full
rectify costs, so normalising before hashing does not breach the exit-zero
budget. Rectify-plus-scale is above §4's 125 ms line, but that table is a
WebGPU browser budget and this is CPU-only Python with `HoughCircles` scanning
a full-resolution frame; it is recorded honestly rather than adjusted.

---

## Third input channel — §3, listing text with no image

| Metric | Measured | Date |
|---|---|---|
| Rules evaluated on a text listing | **36 of 36** | 2026-09-07 |
| PASS / FAIL / NO_DATA / N-A | **22 / 0 / 8 / 6** | 2026-09-07 |
| Geometric rules returning FAIL | **0** (all 8 NO_DATA) | 2026-09-07 |

The same rulepack, the same engine, no pixels anywhere. Every geometric rule
abstains rather than failing, which is the NO_DATA-versus-FAIL principle
holding under the condition it was written for.

---

## Field classification — regex tier, §14 hard negatives

All six of section 14's named hard negatives are separated correctly, in both
scripts, with no model involved:

| Input | Classified | Date |
|---|---|---|
| `MRP Rs. 45.00 (inclusive of all taxes)` | `mrp` | 2026-09-07 |
| `Rs. 20 OFF` | `marketing_text` | 2026-09-07 |
| `Drained wt. 350 g` | `other` (not the net quantity) | 2026-09-07 |
| `24MRP07` | `batch` | 2026-09-07 |
| `MRP Rs. 45.00 Batch 24MRP07` | `mrp` (both present, price wins) | 2026-09-07 |
| `8901234567890` | `other` (barcode) | 2026-09-07 |
| `Best before 9 months from mfg` | `expiry_date`, strict pattern then fails it | 2026-09-07 |
| `अधिकतम खुदरा मूल्य 45.00` | `mrp` | 2026-09-07 |
| `शुद्ध मात्रा 250 g` | `net_quantity` | 2026-09-07 |
| `निर्माता: एक्मे फूड्स` | `manufacturer` | 2026-09-07 |
| `Acme Foods Pvt Ltd, Bhubaneswar, Odisha 751001` | `other` — abstains, routed to the layout head | 2026-09-07 |

Per-field F1 remains `pending`: that needs the annotated corpus, and these are
21 hand-chosen cases, not a measurement of accuracy on real labels.

---

## The layout head, tier two — §14, §15b, M5. Measured 2026-09-18

Three defects were found while building the weak-supervision path for this
head. Two of them were costing verdicts on every scan and neither needed a
model to fix.

### The head was unreachable code

`assemble.from_lines` has accepted `model_tier_predictions` since the tier was
written, and `vision/pipeline.py` never passed it. Dropping trained weights into
`data/models/` would have changed nothing at all, because nothing called the
classifier. Wired 2026-09-18 as `_layout_head`, which returns "regex tier only"
for each of the four reasons it cannot run and never raises.

### Train and serve were embedding in different vector spaces

`training/classifier/train.py` embedded with `all-MiniLM-L6-v2`;
`_layout_head` embeds with `bge-small-en-v1.5`. Both are 384-dimensional, so
`FEATURE_DIM` agreed, the assertion in `build_matrix` passed, and nothing
raised. A head trained through that path would have been queried in a space it
was never fitted to — scoring well on validation and predicting noise in
production, which is the exact silent skew `vision/classify/features.py` was
split into its own module to prevent.

Training now embeds through `retrieval.embed`, the same call the pipeline
serves with. **This is a deviation from §15b, which names MiniLM-L6.** The
serving side was taken as the fixed point because `bge-small-en-v1.5` is the
model that actually ships — 133 MB of it is already in `data/models/` for
retrieval, it is already ONNX, and it needs no torch at inference. MiniLM ships
nothing. It is the stronger model of the two on MTEB, and the plan's real
requirement — *"384-d, frozen"* — is met exactly.

### The candidate gate rejected the addresses the head exists to read

`is_address_like` scored three signals and required two: a company suffix, a
bare `\b\d{6}\b` PIN, or one of `road|street|nagar|marg|dist|district|state|india`.
It was written for a whole address and is applied to a single printed *line*,
and those are not the same string. An address on a pack runs down four or five
lines and the middle ones carry neither a company nor a city:

```
'DIST.: 24 PARGANAS (SOUTH), P.S. SONARPUR,'
'PIN-700 154, WEST BENGAL.'
'KANDUAH FOOD PARK, PHASE-I, WBIDC, P.O. SANKRAIL'
```

Measured over 80 random corpus photographs: of 76 continuation lines belonging
to a manufacturer the regex tier had *already identified by its caption*, **61
were rejected here** — 80%. Since this function gates the candidate list, those
lines were never offered to the head at all. No amount of training could have
recovered them; the classifier would never have seen them.

Two specific faults. `\b\d{6}\b` does not match `PIN-700 154`, because packs
print the PIN with a space in it. And two place words on one line counted once,
so a line saying both `DIST.` and `P.S.` scored the same as a line saying
neither.

Widened to four signals with distinct place tokens counted up to two. The
threshold stays at two, which is what keeps panel copy out. Verified against 11
real address lines drawn from the corpus and 12 lines of panel copy — nutrition
rows, ingredient lists, storage instructions, an FSSAI licence, an MRP and a net
quantity:

| | Address lines | Panel copy |
|---|---|---|
| before | 4 of 11 accepted | 0 of 12 leaked |
| after | **11 of 11 accepted** | **0 of 12 leaked** |

1038 tests pass unchanged. The gate feeds only `_layout_head`, so widening it
alters no verdict until a head ships.

### The head was trained by weak supervision, and it is not shippable

`training/classifier/harvest.py` labels addresses by distant supervision from
the regex tier. That is not the self-training `convert.py` forbids: the regex
tier holds no weights, was never fitted, and cannot have learned anything from
the head it supervises. The harvest calls `classify_lines` with no
`model_tier_predictions`, which is the only route a model opinion could take.

The labels propagate **downward**. A first attempt stripped the caption out of
a line and kept the remainder, which yielded 1 usable row in 60 photographs —
because packs print `Marketed By:` on a line of its own and the address on the
lines beneath it, so stripping leaves the empty string. What works is taking the
caption line's label and applying it to its continuation body, which is already
in the uncaptioned form the head meets at inference.

Harvested over all 469 corpus photographs (`data/test_split/` untouched, and the
script refuses that path outright):

| | rows |
|---|---|
| manufacturer | 45 |
| packer | 1 |
| importer | **0** |
| consumer_care | 19 |
| **total** | **65, from 33 of 469 photographs** |

Trained, split by photograph, 49 train / 16 validation:

| class | F1 |
|---|---|
| manufacturer | 0.846 |
| packer | 0.000 |
| importer | not present in validation |
| consumer_care | 0.400 |
| macro (measured) | **0.463** |

**§17 M5 asks for per-field F1 ≥ 0.85. Not met, and no weights were exported.**
`data/models/field_classifier_int8.onnx` is deliberately still absent, so the
pipeline continues to run regex-tier-only and says so.

This is a finding about the corpus, not about the architecture. Sixty-five
examples across 33 photographs cannot train a four-way classifier; one `packer`
and zero `importer` cannot train two of its four classes at all, and `importer`
is the class that decides whether Rule 6(1)(f) applies. A validation split of 16
rows cannot measure one either — 0.846 on `manufacturer` rests on a handful of
rows and should not be quoted as an accuracy.

What would change it is hand annotation, which is section 16's outstanding work:
the head needs address boxes labelled on the order of a few hundred packs, with
`packer` and `importer` deliberately sought out rather than sampled. Until then
the honest position is the one section 15b already allows — *shipping without
this model is an acceptable outcome if the patterns separate the fields well
enough* — with the gate fix above making the patterns reach materially further
than they did.

---

## Evidence chain — §17 M7, met in full

M7 is the one acceptance criterion in the plan that needs no corpus, no weights
and no photographs, so it is met rather than pending.

| Criterion (§17 M7) | Result | Date |
|---|---|---|
| `verify_chain()` detects a tampered historical record | **yes** — edited measurement, swapped image hash, altered rulepack version | 2026-09-07 |
| Detects deletion from the middle | **yes** — `SEQUENCE_GAP` + `BROKEN_LINK` | 2026-09-07 |
| Detects deletion from the front | **yes** — `SEQUENCE_GAP`, the easiest one to miss | 2026-09-07 |
| Detects two records transposed | **yes** — both hash correctly alone; only the links disagree | 2026-09-07 |
| Detects a forged genesis link | **yes** — `BAD_GENESIS` | 2026-09-07 |
| Canonicalisation is stable across key order, whitespace, timezone, Decimal | **yes** | 2026-09-07 |

Command: `pytest tests/unit/test_evidence_chain.py -q` (31 tests)

**The limit is tested too, and it is worth saying out loud rather than being
found.** A hash chain is tamper-*evident*, not tamper-*proof*. An actor with
full write access can rewrite a record and re-chain every record after it, and
the result verifies cleanly —
`test_a_wholesale_rewrite_verifies_which_is_why_the_head_is_published` asserts
exactly that. What defeats it is publishing the head digest outside the
database before the rewrite; the same test asserts the rewritten chain's head
no longer matches. That anchoring is still to be built.

---

## Storage — §6, the 14x claim

| Metric | Plan (§6) | Verified | Date |
|---|---|---|---|
| Repeat SKU uploads | nothing | **nothing** | 2026-09-07 |
| Shelf of 40 packets, 12 unique SKUs | 28 upload nothing | **28** | 2026-09-07 |
| Evidence original retention | 7 years | **2555 days** | 2026-09-07 |
| Derived crops | 2 years | **730 days** | 2026-09-07 |
| Compliant scans downscaled after | 90 days | **90** | 2026-09-07 |
| Hash and metadata | forever | **no expiry** | 2026-09-07 |

`REVIEW` scans keep a full-resolution original alongside `FAIL`, which is the
easiest thing here to get wrong: a REVIEW is a near-threshold measurement we
deliberately refused to convict on, so it is precisely the case a human will
re-examine and precisely the case where the photograph must still exist.

**Not yet measured on real data.** The ~2.1 GB per 10,000 scans figure depends
on real image sizes and a real repeat rate. What is verified is that the policy
routes each scan to the tier §6 specifies.

---

## Photo corpus — §14, §16, received 2026-09-07

469 photographs, ~207 products, 70 MB. Full write-up in `docs/corpus.md`;
raw audit in `data/corpus/audit.json`.

| Measurement | Result | What it means |
|---|---|---|
| Readable | 469 / 469 | — |
| Genuinely blank frames | **1** | curation was good |
| Exact duplicate files | 15 pairs | must not straddle a train/test split |
| Under 640 px | 0 | all usable for a 640 px detector |
| Max side, every image | **≤ 1600 px** | WhatsApp's ceiling, not a camera's |
| EXIF retained | **0 / 469** | stripped in transit |
| Progressive JPEG | 452 / 469 | re-encoder signature |
| Median size | 132 KB | ~q75 with chroma subsampling |

**Verdict: fine for detection and segmentation, marginal for recognition,
unusable for §18b U1.** At 1600 px across a 150 mm pack (~10.7 px/mm) a 0.15 mm
error budget is under two pixels, and JPEG blocking sits at the same spatial
frequency as the measurement. U1 needs its own 40 ruler-measured frames with a
ChArUco card in shot — outstanding.

## Retrieval — §15, measured against the rulepack and the corpus

### The corpus

All thirteen unique gazettes in `rules_and_acts_docs/` are ingested. Two of the
fifteen files are byte-identical re-uploads, confirmed by SHA-256.

| Measure | Value |
|---|---|
| Documents | **13** (§15 sized the corpus at 12) |
| Pages held | **838**, every one with a row in `data/rulebook/manifest.json` |
| Readable English pages | **448** |
| Devanagari pages held but unread | **390** — see below |
| Chunks | **5,267** (§15 estimated ~1,700 — [D22](docs/spec-deltas.md)) |
| Mean OCR confidence | 0.92 – 0.97 by document |
| Pages below 0.80 confidence | 3 of 448 |

Reproduce with `python -m scripts.ingest_gazettes --manifest-only`.

### Every word of every page read is reachable through a chunk

The claim that matters for this feature is not how many chunks there are but
whether any statute failed to become one. Measured by taking each document's
text after page furniture is stripped, and asking which words appear in no
chunk:

| Document | Words | Chunks | Unreachable |
|---|---:|---:|---:|
| general_rules_2011 | 165,100 | 4,388 | 98 |
| lmpc_2011 | 13,075 | 337 | **0** |
| ns_rules_2011 | 10,584 | 242 | 2 |
| approval_of_models_2011 | 5,085 | 161 | 1 |
| iilm_rules_2011 | 1,601 | 51 | **0** |
| model_test_labs_2014 | 1,018 | 34 | **0** |
| numeration_2011 | 752 | 18 | **0** |
| ns_rules_2019_amdt | 799 | 17 | **0** |
| approval_of_models_2019_amdt | 392 | 11 | **0** |
| general_rules_2011_corr | 206 | 1 | **0** |
| numeration_2011_amdt | 171 | 5 | **0** |
| act_commencement_2011 | 123 | 1 | **0** |
| act_commencement_2010 | 102 | 1 | **0** |
| **Total** | **199,008** | **5,267** | **101 — 99.95%** |

It was **94.51%** when the question was first asked, and three documents
produced no chunks at all. Every gap is in the table below.

**The 101 words now unreachable are not statute.** They arrived with the
thirteen pages re-read on 2026-09-09 and they are table rulings the recogniser
read as letters — `ili` 27 times, `ll` 19, `il` 14, `li` 19, and five broken
word-halves (`refere`, `functi`, `tiv`, `tive`, `rel`). None is a word of any
provision, and the figure is reported rather than rounded away because the
alternative is a 100% that is not true.

**No chunk points at a parent that does not exist.** 114 did: every Schedule
item cited a Schedule that had no chunk of its own, so `Second Schedule` — the
table of commodities that must be packed in specified quantities — resolved to
nothing.

### Tier 1 — citation lookup

A dictionary keyed on the `rule_ref` every verdict already carries. No index, no
embedding, no model — §15: *"we do not need to search for Rule 7(2); we know it
is Rule 7(2)."*

| Measure | Value |
|---|---|
| Rulepack citations resolving **exactly** | **34 of 34** (was 28 before the corpus landed) |
| Answered by the enclosing provision, labelled as such | **0** |
| Named as a gazette not held | **0** |
| Unanswered | **0** |

Reproduce with `python -m scripts.build_rulebook --check`.

`LMPC r.13(5)(i)` was the last one not resolving exactly, and it now does. The
gazette prints *"(5) (i) No system of units…"* on a single line, so the
sub-clause had no chunk of its own and the answer fell back to the enclosing
Rule 13(5) with `held=False`. Splitting a clause that shares its line with the
sub-rule opening it gives `Rule 13(5)(i)` and `Rule 13(5)(ii)` chunks of their
own, and every citation the rulepack makes is now answered by the provision it
names.

### Tier 2 — hybrid search, measured end to end

Postgres `tsvector` + `bge-small-en-v1.5` (384-d, ONNX), fused with RRF `k=60`,
no index and no reranker. 5,267 rows, every one carrying a vector.

| Query | Latency | Top result | Found by |
|---|---|---|---|
| `principal display panel` | 33 ms | Rule 7(1), Rule 7 | **both** |
| `how big must the letters on a package be` | 67 ms | Rule 7 | **dense only** |
| `can a unit symbol be written in capitals` | 63 ms | NS Rules Third Schedule item 7 | **dense only** |
| `maximum permissible error on net quantity` | 38 ms | LMPC First Schedule, item 2(1) | **both** |
| `what pack sizes may tea be sold in` | 42 ms | LMPC Second Schedule, item 8 | **dense only** |
| `C.G.S. units with special names` | 32 ms | NS Rules **Seventh Schedule** | **both** |
| `scale of fees for verification` | 36 ms | Approval of Models Rule 19 | **dense only** |

§15 estimated ~40 ms. The third row is the argument for hybrid in one line: BM25
returns nothing at all for that question, because none of those words appear in
any gazette. The first row is the argument for keeping BM25 anyway — an exact
term of art comes back with both retrievers agreeing.

**The last three rows returned nothing at all before the completeness audit.**
The MPE table and the pack sizes were text the chunker discarded; the Seventh
Schedule was a page the language test threw away. They are the reason to measure
retrieval by what it can reach rather than by how fast it answers.

### Nineteen defects found here, each of which would have shown an officer the wrong law in the right format

Recorded because the failure mode of this feature is silent.

| Defect | Effect |
|---|---|
| The Sixth Schedule renumbers from 1 | Its item 7 overwrote **Rule 7** — principal display panel, the rule behind every height check |
| A proviso was never closed by a new sub-rule | **Eight sub-rules vanished**, Rule 18(5) among them — the retailer's offence |
| `*(6)` carries an amendment footnote marker | **Rule 12(6)** was invisible, so `LMPC.QTY.BANNED_WORDS` cited a provision the index denied existed |
| `re.sub` consumed both fragments of a split word | **4 spacing repairs instead of 168**, and the count looked plausible throughout |
| OCR breaks the line after a rule number | The Numeration Rules lost **rules 1 and 2**, including r.2(3), which the rulepack cites |
| The fix for that joined a table's serial column | The LMPC Second Schedule was rebuilt **one row out of step** — item 14 became `14. 15. Soaps`, and items 6, 8 and 19 vanished. Caught by the chunk count moving 318 → 322 |
| The index was keyed on `ref` alone | Every gazette has a Rule 2. `Rule 3` returned two clauses from **two different instruments** and reported them as one ambiguous citation |
| Any line arriving while no rule was open was discarded | The **Schedules lost their tables**: the maximum-permissible-error table, the standard pack sizes (`100g, 200g, 500g, 1 kg…`), the Fifth Schedule sampling plan, and two thirds of the National Standards Rules. LMPC was 72% covered and the NS Rules 34% |
| A Schedule was a boundary, never a chunk | **114 chunks cited a parent that did not exist.** `LMPC Second Schedule` resolved to nothing |
| A document with no numbered rules produced nothing | Three instruments — both commencement notifications and the General Rules corrigendum — were **held, extracted, and entirely absent from the retriever** |
| The Schedule pattern required the word `THE` | The General Rules writes `SIXTHSCHEDULE` and `SEVENTH SCHEDULE - HEADING - A`. All **655 pages of it, seventeen Schedules**, were filed as `Rule n` against a numbering that restarts in every Part. Its Eleventh, Twelfth and Thirteenth Schedules had no ordinal in the list at all |
| A rule printed with no heading did not open | The gazette sets National Standards rr. **4, 7 and 8** as a bare number with sub-rule `(1)` on the next line. The rules did not exist, and their sub-rules were read as a *second* `Rule 3(1)`, `Rule 3(2)` and `Rule 6(2)` — **the metre and the kelvin filed under the metric-system rule and the second** |
| A heading and its sub-rule on one line | `5.(1) Base units of Mass- ...` made the whole sub-rule the heading, so **`Rule 5(1)`, the kilogram, was not a chunk** |
| A one-word heading was rejected | General Rules **r. 2 _Definitions_** and **r. 11 _Weights_**, and in the LMPC First Schedule the **maximum-permissible-error table** and three chunks around it |
| A colon where the gazette means a stop | Approval of Models **`16: Deposit of Models or its drawings`** — the rule that lets the Director call in an approved model — was not a rule |
| `SUB_RULE` reads an ASCII bracket | The recogniser sets `(1)` as a **fullwidth** bracket on 212 lines. **Thirteen sub-rules were invisible**, r. 8(1) among them |
| A heading carried its own sub-rule on the end | `15.Permitted units.(1) The units specified in the Fourth Schedule may` — the whole line became the heading. **35 rules across every instrument** lost sub-rule (1) while (2) and (3), printed on their own lines, were chunks. National Standards rr. 15, 18, 22, 23 and fourteen rules of the Approval of Models Rules among them |
| A provision opened at its own next level | `(5) (i) No system of units other than the International System of Units...` — **`Rule 13(5)(i)`, which the rulepack cites**, was not a chunk while `Rule 13(5)(ii)` was. Likewise `1.Alcoholic strength-(a)` in the National Standards Tenth Schedule |
| `i`, `l` and `1` are one glyph on a scan | **420 chunks were addressable only as `(ili)`, `(li)`, `(il)`, `(ll)`** — citations no officer could ever type. `Rule 2(ili)(i)` is a real provision of the National Standards Rules and there was no way to ask for it |

Four are worth their own note. The roman-numeral repair had to be talked out of
one letter: `(l)` is a clause, not a damaged `(i)` — Rule 2(l) of the Packaged
Commodities Rules is the definition of *retail sale* — and the first version of
the fix rewrote it, which cost three of the pack's citations before the guard
went in. The `*(6)` case first read as our *rulepack*
citing a sub-rule the gazette skips; it had not, the parser was wrong, and
telling those apart meant opening page 12 — which is why every chunk carries its
page number. The Second Schedule regression is the reason the primary source's
chunk count is asserted in a test: a schedule shifted by one row is a confident
answer about the wrong commodity. And the discarded-line defect had been sitting
behind a comment that read *"Preamble — real text, but not citable as a rule, so
it is not made to look like one"* — a defensible sentence about the four lines
before Rule 1, which was silently also throwing away every table in every
Schedule.

### Every sub-rule is now present too — 2026-09-08

The rule-number run below closed at the *rule* level. Run one level down, on
sub-rule numbers, it opened eight more holes, and closing them took four
separate fixes. **The corpus now carries no rule-number gap and no sub-rule gap
in any principal Rules document**, and 34 of 34 rulepack citations resolve
exactly.

| | before | after |
|---|---:|---:|
| Rules with a sub-rule gap | 8 | **0** |
| Chunks | 5,254 | **5,266** |
| Lines reading as reversed text | 5 | **1** (a masthead, stripped as furniture) |

**The recogniser turns single lines upside down.** PP-OCR classifies every line
crop as upright or inverted, and when it is wrong the line comes back reversed
glyph by glyph. Rule 17(1) of the Approval of Models Rules read `u jo jpo Que
jo jeodde go asodnd au ro () - 'essoau ou aeuo`, which is *ordinarily not
necessary. - (1) For the purpose of approval of any model of any* rotated 180°
— `asodnd` is `purpose`, `d` for `p` and `n` for `u`, read backwards. Rotating
the *page* does not help, because only the one line is flipped. Reading the
page with the classifier disabled recovers all three known cases at 0.99–1.00,
and the flipped readings scored 0.51–0.52, so the recogniser's own doubt is the
trigger.

**A text-only duplicate guard could never have recovered rule 8(2), and this
was the important one.** Page 319 of the General Rules prints rules 7, 8 and 9
as parallel provisions in *byte-identical* language, so `(2) The number, types
and specifications of such` is the text of three different sub-rules. The sweep
read rule 8(2) correctly and then threw it away as a duplicate of rule 7(2). No
amount of re-reading would ever have brought it back. The guard now matches on
position as well as text, and only because it does was it safe to loosen the
text threshold enough to also drop a genuine second reading of one line —
`speciffied … Eourth` beside `specified … Fourth`, which share 24 characters
where 0.6 demanded 27.

**The gap sweep was structurally blind to a single dropped line.** It marked
rows covered by a detection box and looked for uncovered runs — but the boxes
overrun the text badly: on page 19 of the Approval of Models Rules the median
box is 138 px tall while consecutive boxes start 60 px apart, so every box
overlaps its neighbour by more than half a line and paints the rows where a
missing line would have been. The gap over the lost first line of rule 6(4)
measured 0.18 of a line against a threshold of 0.75. Box *tops* do not have
this problem, because they track baselines: 1813, 1873, 1934, **2054**, 2114 —
60, 61, **120**, 60. Four of the eight sat behind exactly this.

**And the sweep emitted fragments of lines it had already read** — recovering
rule 8(8) also produced `numher`, `assianed` and `Tmateiiarwitnwnichthe`.
`_already_read` cannot catch those: `assianed` shares only `ass` with the
`assigned` it duplicates, three characters against the five its length demands.
A two-word minimum removes all three and costs nothing real.

**What this does not cover.** The pitch detector and the flip repair are new,
and they have run over the 39 re-read pages, not all 838. Nothing elsewhere
regresses — those pages are unchanged — but gaps of the same two classes may
exist in the 799 pages not re-read, and **the sequence audit cannot see them**:
it detects a break in a number run, and the Schedules where most of the corpus
lives are not numbered that way. That is a known, bounded ignorance, not a
clean sheet.

### Coverage was the wrong test to stop at

100% coverage says no *word* was lost. It does not say that the words are
reachable under the citation an officer would use, and the National Standards
Rules were at 100% while **rules 4, 7 and 8 did not exist**. The gazette prints
them as a bare `8.` with `(1)` beginning the next line; the rule never opened,
and its sub-rules attached to the rule before it. Nothing downstream could see
it — the text was fluent, the confidence 0.98, the citation well-formed. The
only symptom was that `Rule 3(1)` answered twice, with the metric-system rule
and with the definition of the metre.

So the corpus is now audited on a second question: **does every principal Rules
document carry an unbroken run of rule numbers?** Every one of them had a hole.

| Document | Rules | Was missing |
|---|---:|---|
| The Packaged Commodities Rules | 1–34 | — |
| The National Standards Rules | 1–33 | **4, 7, 8** — the metre, the ampere, the kelvin |
| The General Rules | 1–30 | **2, 11, 13** — *Definitions*, *Weights* |
| The Approval of Models Rules | 1–21 | **10, 16** — re-submission of a disapproved model; deposit of models |
| The IILM Rules | 1–10 | — |
| The Numeration Rules | 1–5 | — |

Rule 10 of the Approval of Models Rules is the one that was not a parser defect
at all — see below. The rest are five spellings the parser could not read, and
`tests/unit/test_retrieval.py` now fails if any run breaks again.

### A citation that resolves to two provisions is a citation to neither

**1,931 chunks shared a reference with another chunk of the same document.** The
General Rules' Eighth Schedule is 126 pages of instrument specifications —
filling machines, bulk meters, water meters, thermometers — and each one numbers
its clauses from 1, so `Eighth Schedule, item 3` named twenty-three different
provisions.

Tracking the `PART` and `APPENDIX` divisions the gazette prints brings it to
**1,161**. Two spurious sources went at the same time: a table's column-number
row (`1. 2. 3.` under `Sl. No. | Commodities | Quantities`, which was opening a
second *item 1* against baby food) and its decimal tolerances (`2.0 to 3.5`,
which opened an item at every measurement).

**What remains is honest ambiguity and is left alone.** The Sixth Schedule runs
one instrument specification straight into the next with no Part, Appendix or
Annexure between them — only a bolded caption the recogniser returns as ordinary
text. Numbering those ourselves would produce a citation the gazette does not
use, which is worse than the ambiguity: tier 1 currently refuses `Sixth
Schedule, item 5` and names the eight things it holds, and an officer can act on
that. A confident answer from an invented division number is not something they
can check.

### The recogniser dropped a whole line and reported 0.98 confidence

Page 22 of the Approval of Models Rules prints **`10. Re-submission of
disapproved model for approval. - (1) Where any model is`** in bold. RapidOCR
returns 42 boxes that step over it — at 300, 450 and 600 dpi alike. The page
then reads as though rule 9 ran on into rule 10's body, and rule 10 was not in
the corpus at all.

No confidence score falls, because everything that *was* read was read
perfectly. Only counting the rule numbers found it, and only opening the page
image proved it was the recogniser rather than the gazette.

`sweep_gaps` fixes it: mark the rows of pixels some text box covers, find the
runs nothing covers that are tall enough to hold a line, and read those bands
again on their own. The same recogniser finds the line immediately when the band
is all it is given. Two guards keep it from adding noise — a recovered line
sharing 60% of itself with a line already held is the same print read twice, and
a confidence floor removes the `tc`, `assia`, `iPpioval` that blank paper
returns. Measured at 0.7–2.8 s a page against 8–17 s for the first pass.

### A defect of the opposite kind: what the corpus wrongly contained

The rule for admitting a page was *common English words per thousand
characters*. A rate is only meaningful where the page is prose, and the
Schedules are not prose — they are tables of unit names and symbols. It went
wrong in both directions at once:

- **19 English pages were filed as Devanagari and dropped**, including the
  National Standards **Seventh Schedule** (C.G.S. units, page 73) and three
  pages of the **Ninth Schedule**. The Eighth Schedule went with it, because the
  gazette prints it on the same page. Rule 18 cites both, so the corpus held
  rules referring to Schedules it did not contain.
- **20 pages of Devanagari mojibake were admitted as English**, putting
  `hePhh h L by hhl 生 tehlh Le hebl` into an index whose entire value is being
  verbatim.

Both are now decided by two signals that must agree: how many real English words
the page carries — an absolute count, because a Hindi page's English masthead
scores 1.00 on a ratio — and how many CJK ideographs it carries per English
word, since Devanagari is what the recogniser turns into Chinese. Neither alone
works: ideographs alone drop the four dense English pages that print a Hindi
header line, and English alone keeps the mojibake.

### And one in the indexer rather than the parser

Loading 5,172 chunks into Postgres produced **2,341 rows**. The row key was
`doc_id::ref`, which is not unique — the General Rules is a compendium whose
every Part restarts at "1. Scope", so 2,763 chunks share a reference with
another — and `ON CONFLICT DO UPDATE` silently collapsed them. Tier 2 would have
been searching a corpus missing more than half its clauses, with the run
reporting success. Row identity and citation identity are now separate things.

### What the corpus does not contain

**390 Devanagari pages are held but unread.** The recogniser is PP-OCR
English/Chinese and has no Devanagari model; handed a Hindi page it does not
fail, it emits CJK glyphs — `g F 3 3 市 市 3` — with 0.67–0.84 confidence. A
Devanagari-ratio test on that output finds no Devanagari at all: across all 838
pages the recogniser emitted **zero** Devanagari characters, which is why the
language test cannot be a script test on the obvious script.

**These are the Hindi halves of bilingual gazettes.** The English half is the
same instrument, nothing in the rulepack cites them, and each page carries a
manifest row recording that it is held and why it was not read.

An earlier version of this section claimed *"no content is lost"*. That was
wrong, and the audit above is what found it: 19 pages of English — including a
Schedule the rules cite — had been classified as Hindi and dropped. The claim
now rests on a measurement rather than on the design intent, and the measurement
is the 100.00% coverage table above.

**All of them were re-examined page by page**, from the raw recogniser output rather
than from the classifier's verdict, and ranked by how much English each carries.
The most English on any of them is 24 words, and on inspection those words are
the masthead, the part-and-section line, and unit symbols left standing inside
Hindi sentences — `R T (values) 0.8 kPa(60mm Hg)`. Recovering those line by line
was tried and rejected: it yields 416 lines across 214 pages, of which perhaps
ten are real, and the other 406 are half-sentences that would enter an index
whose entire value is being verbatim. **A broken clause that looks like statute
is worse than a page recorded as unread.**

**One thing is knowingly given up, and it is the only one.**

`general_rules_2011` p. 363 is a figure captioned *OF COMBINED LIQUOR MEASURE*
carrying ten English words among the Hindi. It falls below the threshold, and
lowering the bar far enough to catch it readmits mojibake. A figure caption is
the right thing to lose at that exchange rate.

**`model_test_labs_2014` p. 6 was the one real loss, and it is now recovered.**
It carries the English column headings of the Second Format's table —
*PARTICULARS OF LABORATORY*, *Field of use*, *Equipment*, *Sr. No.* — which
appear nowhere else in the corpus.

It was never a Devanagari page. It is a *bilingual* page, and `classify` judged
it whole: 15 English words against a threshold of 12, but 11 ideographs against
an allowance of 2. Every one of those ideographs is in the Hindi body below;
lines 0–9, the entire table header, contain none. So a page that is 26% English
by line was discarded for the other 74%.

`english_block` now offers a second chance to a page that passes the English
test and fails only on ideographs: if its ideograph-free lines form one
contiguous run that reads as English on its own, that run is kept and the note
records how much of the page was left unread.

**The bar is a count of *distinct* words, and that is what makes it safe.**
Nine pages in the corpus reach the second chance. Page 6 scores 13 distinct
dictionary words at a 0.81 hit rate; the next best block in 838 pages scores 7.
A word *count* separates nothing — `general_rules_2011` p. 150 reaches eight on
four repeats of `max` inside a formula table, and p. 268 on `kPa` and `mm Hg`
left standing in Hindi sentences. Both are rejected. **Exactly one page in the
corpus is admitted this way**, which is the measurement that says the rule is
narrow enough to be worth having.

This is deliberately not the line-level salvage rejected above. That took any
English-looking line from any dropped page: 416 lines, of which ~10 were real.
This takes a contiguous block that reads as English by itself, and it admits
one page.

The recogniser still misreads two words of that header — *Moder of Weight
orMeastire* for *Model of Weight or Measure*. At 600 dpi it reads *Model*
correctly; *Meastire* is wrong at 300, 450 and 600 alike. Nothing is corrected
here: what the page is recorded as saying is what the recogniser read, and this
paragraph is the record of the difference.

**Every rule and every Schedule is present in its English text.** That is now a
measurement — the rule-number run above — and not an inference from the fact
that the gazettes are bilingual.

**OCR'd text is searchable but not quotable** — [D23](docs/spec-deltas.md). Only
the Packaged Commodities Rules, behind 29 of the 34 citations, comes from a
publisher's text layer.

### What a search for the *next* gap turned up — 2026-09-09

The sub-rule run above closed everything it can see. This is the record of
looking where it cannot, and of what looking cost.

**Four of the five candidate gaps were the audit's own bugs.** A run over
clause letters scored `(i)` as the ninth letter of the alphabet, so every rule
whose clauses are roman numerals reported `a` through `h` missing — ten false
gaps in five documents. A run over Schedule item numbers reported nineteen
schedules with holes; the text of every one of them is present, and the chunker
had simply not split the row. `Second Schedule, item 1` of the Packaged
Commodities Rules physically contains items 1 to 5, so the entry for bread is
in the corpus and searchable while `Second Schedule, item 3` resolves to
nothing. That is an addressability gap, and it is a different and smaller thing
than a missing rule.

Of the three that survived, none was a loss either:

| Reported | What it actually is |
|---|---|
| `Approval of Models r.2(1)(c)` | **Not in the gazette.** Page 16 prints (a), (b), (d). A drafting error in the Gazette of India, read faithfully. |
| `NS Rules r.2(1)(a)–(l)` | Present as `Rule 2(a)`…`Rule 2(k)`. The audit looked under the wrong parent. `(l)` is filed as a sub-rule because the recogniser read `(l)` as `(1)`. |
| `Model Test Labs r.2(1)(iii)` | All eleven instrument types are held. Two roman numerals in a table were mislabelled, `(ii)`→`(i)` and `(iii)`→`(ii)`. |

**A detector for dropped lines, built from the text alone, was mostly noise.**
A line the recogniser never saw leaves a scar — a marker with nothing after it,
or a sentence resuming mid-clause. That signature fires 207 times. Reading the
surrounding lines shows almost all of them are multi-column tables, where the
marker box is ordered between the first and second line of its own cell:
`Before checking a volumetric container / (b) / filling machine, the inside of
the basin or` is one provision, not a hole. **The signature is not usable as a
gate**, and it is recorded here so it is not built a second time.

### The recovery pass was adding corrupt lines, and now does not

Thirteen pages were re-read to test the pitch detector and the flip repair on
work they had never seen. They recovered **an entire sub-rule** — *(2) Only the
prefixes "kilo", "mega", "giga" and "tera" specified in the Third Schedule may
be used with the tonne*, sub-rule (2) of *Permitted unit of mass* on page 70 of
the National Standards rules. Before, that page ran from `equal to 1000
kilograms` straight to `Third Schedule may be used with the tonne`, and the
result still read as a complete sentence. No audit over numbering could have
found it, because Schedules are not numbered that way.

They also added twenty-three lines that were not there before, and **nine of
them were garbage**:

| Added | Already on the page |
|---|---|
| `fal The slrfare of the weiahts shall be` | `(a) The surface of the weights shall be` |
| `For better stablity and finist, the weiahts` | `(b) For better stability and finish, the weights` |
| `and the nrice for ono articla on ths` | `and thepricefor one article on the` |
| `fecordiro_the data_ahave_and` | `recording the data above and` |

Every one is a band re-read of a line the page already held. `_already_read`
compares *longest contiguous run*, and two readings of one line that diverge
this badly share no long run — the first pair shares ten characters where the
test demands sixteen — so all nine were admitted as new text. Over 838 pages
that is roughly two corrupted lines per page, written into the corpus in the
name of completeness.

`GAP_SIMILARITY` closes it by comparing overall likeness instead, inside the
same positional window the parallel-provision guard already uses. The two
populations separate cleanly: garbled duplicates score 0.54 to 0.95, the
genuine page-70 recovery scores 0.37. Re-running the same thirteen pages after
the change, **all nine garbled lines are rejected and the recovered sub-rule is
kept**. Ten tests hold the boundary, six of them the measured pairs above.

### Two addressability fixes, one made and one refused

**`(l)` read as `(1)` — fixed.** `l` and `1` are the same glyph, so a clause
`(l)` arrives as sub-rule `(1)` and is filed a level up under a parent the
gazette never printed. The National Standards Rules lost the definition of *SI
prefix* that way, and took `(m)` *special units* and `(n)* *supplementary
units* down with it — all three reachable only as `Rule 2(1)…`. The repair is
positional, because the text cannot decide it: a `(1)` directly following a
`(k)`, with no rule or Schedule heading between, continues an alphabetic run.
It fires in **five places, every one a real clause (l)** — the Bessel points,
the rated minimum fill, the dip stick's cross-section, the taximeter's
constant, and the SI prefix. `Rule 2(a)` through `Rule 2(n)` of the National
Standards Rules now run unbroken.

**Schedule table rows — deliberately not split.** `Second Schedule, item 1` of
the Packaged Commodities Rules physically contains items 1 to 5, so the entry
for bread is searchable while `Second Schedule, item 3` resolves to nothing.
Splitting it looks free and is not: the guard in `_ORPHAN_HEADING` exists
because an earlier attempt rebuilt the table one row out of alignment — *item
14 became `14. 15. Soaps`, and items 6, 8 and 19 vanished*. The numbers sit at
the start of a line, alone on a line, and at the **end** of a line
(`100g and there after in of multiples 100g. 4.`), and the column header reads
`1. 2. 3.`

It is also unnecessary. The Second Schedule's pack sizes are transcribed into
the rulepack by hand and cross-checked by two people, and the rulepack cites
`Rule 5, Second Schedule` whole, which resolves exactly. Splitting the rows
would buy a citation nothing makes, at the risk of a confident answer about the
wrong commodity. **Left as it is, on purpose.**

### What the full re-run costs, measured

| | |
|---|---|
| Twelve General Rules pages, six workers | **9 min 39 s** |
| Per page | **46 s** |
| All 838 pages | **~10.5 h** |
| The 405 pages that are OCR'd English | **~5.2 h** |

The 390 Devanagari pages and the 43 with a publisher's text layer cannot change
by being read again, so the second figure is the one that matters. It is four
times the old rate because `repair_flipped` runs a second full recognition pass
over any page carrying a doubtful line, and the pitch detector opens bands that
are read at roughly six times scale.

**The known ignorance is unchanged in kind and now has a worked example.** The
pitch detector and the flip repair have run over 52 pages of 838. Page 70 shows
what the other 786 may be holding; nothing but the full pass will say.

## Not yet measured

Everything below is `pending` and must not be quoted until it appears above
with a date.

### Accuracy — needs the corpus (blocked on physical work)

| Metric | Target (§17) | Status |
|---|---|---|
| Font-height mean absolute error, scale tier A | ≤ 0.15 mm | `pending` — needs the 40-photo ruler-measured split, **ChArUco card in frame** |
| Font-height error, **95th percentile** (§18b U1) | ≤ 0.25 mm | `pending` — new bar; the tail matters more than the mean |
| Rectification: printed lines off horizontal | < 2° | **met on synthetic photos**; `pending` on the 40 real ones |
| Detector package mAP@50 | ≥ 0.85 | `pending` |
| PDP mask IoU | ≥ 0.85 | `pending` |
| False positives on 60 negative photos | 0 | `pending` |
| OCR baseline CER by surface type | record before fine-tuning | `pending` |
| Field classifier F1, per field | ≥ 0.85 | `pending` |
| Field classifier F1, MRP | ≥ 0.90 | `pending` |
| False-positive count, 5 advisory checks | measure, §19 week 6 | `pending` |

### Latency — needs the models

| Metric | Target (§4) | Fails above | Status |
|---|---|---|---|
| Cache hit, in browser | < 100 ms | 200 ms | **12.6 ms server-side CPU**; `pending` in-browser |
| Cache miss, WebGPU | < 700 ms | 1200 ms | `pending` |
| Cache miss, WASM | < 1300 ms | 2000 ms | `pending` |
| Detection, INT8 @ 640 px | < 120 ms | — | `pending` |
| ROI-only OCR vs full-image | ≥ 5× faster | — | `pending` |
| Server bulk throughput | > 8 img/s/worker | 4 img/s | `pending` |
| Cached model bundle | < 60 MB | 100 MB | `pending` |

### Storage — needs real scans

| Metric | Target (§6) | Status |
|---|---|---|
| Storage per 10,000 scans | ~2.1 GB | `pending` |
| Cache hit rate on a real shelf | — | `pending` |

### Cost

| Metric | Value | Status |
|---|---|---|
| API fees per scan | ₹0 — all inference is local | by construction |
| What a paid vision API would have cost | — | `pending` (compute at demo time) |

## The ruler set, the OCR bundle, and where the eight crops were going — 2026-09-09

The 40 ruler-measured frames arrived and are sealed in `data/test_split/`
(3072×3072, ChArUco card in every frame, ground truth parsed from the
photographer's folder names by `scripts/seal_test_split.py` rather than
retyped). **Tier A returns a scale on 40 of 40**, decoding all ten DICT_4X4_50
markers in nearly every frame — e.g. `0.105 mm/px ±0.0034, rectify=marker`.

**The model bundle is real for the first time.** PP-OCRv6 `small_det` (9.88 MB)
and PP-OCRv5 Devanagari mobile `rec` (7.91 MB), both PaddlePaddle's own ONNX
exports under Apache-2.0, now pinned in `fetch_models.py` with URL *and*
sha256. The recogniser's CTC table is derived from the `inference.yml` that
ships beside the weights: 568 entries, which with PaddleOCR's blank at index 0
and space at the end is exactly the 570 the model's logits are wide. 94 of the
568 are ASCII, which is why there is one head and not two — §15b's *"benchmark
whether a second English-only head earns its bundle size; do not assume it."*
They are **not** named `_int8`; the published artifacts are fp32 and the sizes
match §15b's own estimates. Quantisation is a U3 decision, not a filename.

**Four artifacts were being fetched under names no loader ever opens**
(`ppocr_keys_en.txt` against `en_dict.txt`, `embed_pca_512.npz` against
`sku_pca_512.npz`, and `bge_small_en_v15.onnx` against the
`bge-small-en-v1.5.onnx` that was on disk and working). The failure is silent:
the fetch exits zero, the loader raises `ModelUnavailableError`, and the
pipeline degrades exactly as designed. `tests/unit/test_model_bundle.py` now
covers the dictionaries, the PCA basis and `retrieval/`, which the existing
boundary test did not.

**Two bugs the models exposed.**

1. *DBNet thresholds were PP-OCRv4's.* Ours were `0.3 / 0.6 / 1.6`; the config
   shipped beside the v6 weights declares `0.2 / 0.45 / 1.4`. On one frame:
   **3 text regions → 9.** A threshold set too high does not error; it drops the
   faintest print on the pack, which is what we exist to measure.

2. *The eight crops were being spent on the brand name.* `roi.rank_regions`
   ordered by pixel height, reasoning that declarations are set larger than
   ingredient lists. True — but the brand, the flavour and the promotional copy
   are larger still, so `MAX_REGIONS = 8` was exhausted before any declaration
   was reached. `protein_powder_400g` read `'8]'`, one stray Devanagari glyph
   and `'2'`; the same photograph at a cap of 40 gave up `'Net Quantity:'`,
   `'Bach No:'`, `'USE BY:'` and two dates. **Nothing was wrong with the
   recogniser.** Ranking now uses the one thing this project has that a generic
   OCR pipeline does not — a scale in millimetres and a statute that says how
   tall a declaration is (`roi.DECLARATION_BAND_MM`, 0.8–12 mm). The lower edge
   sits *below* Rule 7(3)'s 1 mm deliberately: undersized print is the violation
   we exist to catch, and a band starting at 1.0 mm would leave it unread and
   report a *missing* declaration instead of an *undersized* one — a vaguer
   finding, in the manufacturer's favour. Same budget, spent where the law says
   to look. Across the 20 front frames the crops now land on
   `'Net weight:'`, `'Lot No.:'`, `'USP ₹:'`, `'Uso:by:'`, `'R8.419'` and
   `'MRFTED By:HonasaCon'`.

**A negative result, recorded rather than shipped.** A model-free package-region
proposer was built to supply the crop RTMDet will eventually give us, on the
theory that §4's *"a twelve-megapixel photo is never processed whole"* was being
violated. Measured across all 20 front frames, it is **not the lever**: the packs
already fill 76–99% of the frame, so the text bounding box is the frame and
there is no crop to win (+6% regions overall; +211% on one dark, small-object
frame and −45% on others). Edge-blob tuning made it worse, not better — which is
precisely why the plan specifies a trained detector. The module was deleted
rather than left unwired.

**U1 is still not scorable, and the reason has moved.** It is no longer "no
model"; it is recognition accuracy on 1–2 mm print. These frames run about
9.5 px/mm, so a 1 mm declaration arrives ~10 px tall — under PP-OCR's practical
floor — and the regex field tier cannot match `'MP US?.'` to an MRP. Two frames
now yield a named declaration (`batch`, `net_quantity`) where none did before.

---

## The corrected 405-page re-read, and what it actually cost — 2026-09-09

The recovery detectors (`repair_flipped`, the pitch-band sweep) had run over 52
pages of 838. The full re-read is now done: 405 English pages, six workers,
about two hours. Three snapshots were kept so the result could be judged rather
than trusted — `.ocr_cache.pre405` (before the detectors were corrected),
`.ocr_cache.pass1` (the first sweep, whose `GAP_SIMILARITY` had no positional
guard), and `.ocr_cache` (the corrected sweep). `scripts/diff_ocr_caches.py`
compares all three and is the reason the numbers below are checkable.

| | pages | lines | chars |
|---|---|---|---|
| pre405 | 838 | 56,837 | 1,320,664 |
| pass1 | 838 | 56,865 | 1,322,042 |
| final | 838 | 56,867 | 1,322,156 |

**123 lines recovered against the baseline, and no statute lost.** Sixteen pages
came out *shorter*, which is the loudest signal a corpus can give, so every line
they lost was read by hand. All sixteen are garbage: twelve are truncated second
readings of the running header — `'TTIEGAZTTTEOFIN'`, `'THEOAZETTEOFIN'`,
`'DA : EXTRAORIN A DV'` — while the clean `THE GAZETTE OF INDIA: EXTRAORDINARY`
stays on the page; the remainder are `'Scneaule.'` beside `'Schedule.'`, plus
`'Cyinder'`, `'+CDLLAR'` and `'19 Feec for'`. Shrinkage here is the fix working.

**A correction to an earlier claim.** This section previously expected the
corrected sweep to restore two provisions `pass1` had deleted — the rule 10
heading of the Approval of Models Rules and the National Standards definition of
*physical constants*. It did not, because `pass1` had not deleted them. `final`
and `pass1` differ by **two lines, with none lost**:

    + general_rules_2011  p581  DIMENSIONAL AND SCALE REQUIREMENTS FOR
    + ns_rules_2011       p49   and the units of weights and measures specified…

The first is the missing first half of the clinical-thermometers heading, so
that check did pass. The other two lines were identified *analytically* as
scoring 0.52 and 0.56 against their neighbours and therefore at risk; they are
guarded by `test_a_line_a_pitch_away_is_not_a_duplicate_however_alike` and were
never actually absent from the corpus. The unit tests were right; the claim
about the cache was not.

**What the sweep does still let through, stated rather than hidden.** Of the 123
recovered lines, about five are garbled second readings of a line the page
already held — `'equai to or greater than'` beside `'equal to or greater than'`
(p448, 0.97), `"sys'om: shall detect"` beside `'system shall detect'` (p567,
0.93). They were already present in `pass1`, so they are the sweep's residual
rate, not a regression from the positional guard. **They are being left in.** The
asymmetry is deliberate and is the whole lesson of `GAP_SIMILARITY_REACH`: a
duplicate is visible noise an officer reads past, a deletion is invisible loss of
statute, and building a new deletion mechanism to remove three lines would
reintroduce exactly the risk that took a night to remove. Five noisy lines in
56,867 is the price of not deleting a provision.

Downstream: **5,270 chunks** (was 5,267), 13 of 13 documents held, **34 of 34
rulepack citations resolving exactly**, 0 unanswered. 658 tests pass, ruff clean.

The honest boundary is unchanged and worth repeating: the corpus is complete
against everything we know how to look for. No audit over rule numbering can
find a lost line inside a Schedule, which is why the re-read was worth two hours.

---

## Vertical text, a derived detector input, and a negative result — 2026-09-09

Three findings, in ascending order of how much they mattered.

### The detector input was throwing away the print we exist to measure

`detect_text.LIMIT_SIDE` was 640: every photograph was shrunk to 640 px on its
long side *before* the text detector saw it. The ruler frames are 3072 px, so a
1 mm declaration — the smallest Rule 7(3) allows — arrived about three pixels
tall. Measured on 25 dev-corpus photographs, 640 found 748 text regions where
1280 found 1054 (+41%).

What that sweep also produced is a number about the model rather than about the
corpus. Taking the detections at a 2560 input as the reference set and asking
what fraction each smaller input recovers, bucketed by the region's height *at
the input it was given*:

| height at detector input | ~5 px | ~6 px | ~12 px |
|---|---|---|---|
| recall | 0–15% | 68% | 92% |

**DBNet needs roughly ten pixels of line height.** That transfers to any
photograph, so the input size is now *derived* rather than tuned
(`detect_text.input_side`): the frame spans a known number of millimetres, the
smallest legal capital is 1 mm, a line is about 1.5× its cap height, and DBNet
needs ten pixels. Nothing in that chain was fitted to the test split — which was
the alternative, and would have made U1 a number the pipeline had been shaped to
rather than measured against.

**The ceiling binds on our own frames, and the test says so.** Sizing for 1 mm
print at 322 mm of frame wants ~2150 px; `LIMIT_SIDE_MAX` is 2048, so a 1 mm
declaration reaches the detector 9.5 px tall against a floor of 10. 2 mm print —
14 of the 20 SKUs — clears it comfortably.
`test_the_ruler_framing_asks_for_more_than_the_ceiling_allows` pins both halves
so the shortfall cannot be quietly forgotten.

The cost is real and is stated as a CPU cost, because section 4's budget is a
*browser* budget and this machine is not a browser:

| detector input | CPU ms | regions |
|---|---|---|
| 512 | 65 | 45 |
| 640 | 105 | 40 |
| 1280 | 1083 | 46 |
| 2048 | 3791 | 57 |

+43% more text for 36× the CPU. On CPU that is unaffordable against 561 ms. The
plan's answers are WebGPU and INT8 and **neither is measured yet**; until one is,
this is an honest recall/latency trade with the recall side chosen and the bill
unpaid.

### Two-pass detection: measured, and not worth it

Before raising the input, the obvious alternative was a coarse pass to locate the
text and a second high-resolution pass on that crop. Measured over 100 dev-corpus
photographs, the coarse text extent covers a median 60% of frame area — a median
**1.35× linear** gain. But a second pass costs 2× compute, while raising
`LIMIT_SIDE` by 1.35× costs 1.35² = **1.8×** for the identical gain. **Two-pass is
strictly worse than not shrinking so hard.** Recorded rather than built.

### Vertical text was being destroyed before the model saw it

The largest finding, and it was not a resolution problem at all. Recognition
resizes every crop to `REC_HEIGHT` and scales the width by the aspect ratio, so a
58×508 crop — text running down the side of a pack, where net quantity and batch
codes very often sit — became **48×48**, every glyph gone. Across 86 dev-corpus
crops the empty-read rate tracked aspect ratio and nothing else:

| aspect (w/h) | <0.5 | 0.5–1 | 1–3 | 3–8 | >8 |
|---|---|---|---|---|---|
| empty reads, before | 52% | 43% | 31% | 25% | 0% |

**37% of all detected regions were taller than wide.** A 508 px region returning
an empty string is not small print failing to be legible; it is legible print
being flattened.

PP-OCR rotates these before recognition and we never did. Fixed in
`recognise._orientations`. Because the plan does not bundle PP-OCR's `cls` angle
head, both rotations are read and the more confident wins — guessing one
direction would silently halve recall on packs whose text runs the other way, and
would fail looking like unreadable print rather than like a wrong assumption.

| | before | after |
|---|---|---|
| portrait crops empty | 52% | **8%** |
| all crops empty | 34% | **20%** |

One 30×477 crop went from `''` to `'Consumer Products Ld, Go'` at 0.89 confidence.

### U1, and what it is a statement about

Run on the sealed 40 *before* the rotation fix: **1 of 40 frames measured, MAE
2.824 mm, U1 NOT MET.** The report refuses to headline the readable subset —
*"a result from the readable subset is a statement about the easy half"* — which
is the behaviour that makes the number worth having. Re-run pending GPU.

### Retrieval, checked because the question was asked

pgvector 0.8.6, `embedding vector(384)`, `tsv tsvector` — hybrid dense + lexical
in one table, as section 13c argues for statute. The rule corpus carries **no
vector index deliberately** (line 1601). One honest caveat: that call was sized
for ~1,700 clauses and the corpus is now **5,270**, with exact cosine measured at
**23 ms**, not the 1.3 ms predicted. Still inside the ~40 ms hybrid budget, so the
decision stands — with a thinner margin than the plan assumed.

670 tests pass, ruff clean.

---

## One wrong assumption, in three places — 2026-09-09 (later)

Everything above about detector input was true and none of it was the main
problem. The main problem was a single assumption — **text on packaging runs
left to right** — baked into three separate places, each of which failed
silently and none of which looked like a bug.

**37% of detected regions are taller than wide.** Net quantity, batch codes and
MRP are very often printed down the side of a pack.

1. **The reader** resized every crop to a fixed height and scaled width by
   aspect ratio, turning a 58×508 column of print into 48×48. Empty reads fell
   from 52% to 8% on portrait crops once `recognise._orientations` rotated them.
2. **The ranker** measured "how tall is this line" as `box.h`. For vertical text
   that is the length of the *sentence*. On `turmeric_powder_10g` the MRP was
   detected, read as `'MRP():5-'` and classified `mrp` at 0.88 confidence — and
   then discarded, because at 17.5 mm it read as branding. Its actual print
   height is 5.7 mm. Fixed by `_line_height_px`, the minor axis, which for
   horizontal text is `box.h` again.
3. **The cropper** padded both axes by `box.h * CROP_PADDING`. On that same
   91×426 box that added 51 px to each side of a 91 px-wide crop, leaving the
   glyphs in 47% background.

A fourth, related fix: ranking *inside* the band was still "bigger first", which
reproduced one level down the exact bias the band was introduced to remove — the
5.7 mm MRP lost all eight crops to in-band print of 6.3 to 10.9 mm.
`STATUTORY_MAX_MM = 6.0` now prefers the sizes Rule 7(2) and 7(3) actually
legislate; above that is plausible but second in line.

### The post-processing bug the GPU exposed

Moving to CUDA bought only 1.8×, which was the clue. Split by stage at a 2048
input: preprocess 137 ms, **model 172 ms, post-processing 1747 ms**. Ten times
the cost of the network it was interpreting. `_regions_from_map` allocated a
full-frame mask per contour and averaged over every pixel of it — O(contours ×
frame). Scoring inside each contour's bounding box instead, which is what
PaddleOCR does, gives identical scores:

| detector input | post-processing before | after |
|---|---|---|
| 640 | 30 ms | 3 ms |
| 1280 | 178 ms | 5 ms |
| 2048 | 1747 ms | **14 ms** |

The 2048 detector pass is now **236 ms total on GPU** (123 pre + 99 model + 14
post), against 3791 ms on CPU before. **The recall/latency trade reported above
as "unaffordable" was mostly this bug, not physics** — 2048 now fits inside
section 4's 561 ms with room to spare. The browser figure is still unmeasured
and this is still a CPU-and-CUDA number, not a phone number.

`vision/runtime.py` now calls `ort.preload_dlls()`: the pip CUDA packages install
under `site-packages/nvidia/`, which Windows does not search, so the CUDA
provider failed to load, onnxruntime advertised it as available anyway, and
every session fell back to CPU **without raising** — a thirty-fold slowdown that
looks exactly like a machine with no GPU.

### U1, measured after each fix

| state | frames measured | MAE |
|---|---|---|
| before today | 1/40 (2%) | 2.824 mm |
| after rotation + derived input | 2/40 (5%) | 2.508 mm |
| after orientation-aware ranking | 1/40 (2%) | 2.191 mm |
| after statutory preference + crop padding | **4/40 (10%)** | **1.245 mm** |

Still **U1: NOT MET**, and the report still refuses to headline the readable
subset. Repeatability appears for the first time at 0.318 mm — the spread
between two shots of one packet, which is ours alone with no ruler in it.
670 tests pass, ruff clean.

## Chasing the assumption to the end of the codebase

The previous section found one wrong assumption — *text on packaging runs left
to right* — in three places and fixed them. The instruction that followed was
that there should not be a single casualty left, so the rest of the codebase was
swept for the same assumption rather than waiting for U1 to surface them one at
a time. It was in **seven** places, not three.

| where | what it did | how it failed |
|---|---|---|
| `measure/cap_height.py` | baseline = modal component *bottom* | vertical glyphs share a side, not a bottom; measured the glyph's width and called it height |
| `measure/characters.py` | segments by *columns* | vertical text puts every glyph in one column; one run where there were nine, count mismatch, geometry dropped |
| `measure/contrast.py` | ring thickness from `shape[0]` | on a tall crop that is the *length of the line*; the ring dilated far enough to sample neighbouring type as "background" |
| `classify/assemble.py` | `height_px = cap_height or box.h` | a 400 px "cap height" for 3 mm print |
| `classify/assemble.py` | `numeral_box.h` | the run-length of the numerals, not their height |
| `rules/checks/min_width_ratio.py` | `box.w / box.h` per character | **inverted**: a 6x18 glyph read 3.0 instead of 0.33 |
| `contracts/declarations.py` | `height_for_rules_px` | same inversion, feeding the Table I height rules |

The last two are the ones worth dwelling on. Every other instance loses a
measurement, and a lost measurement becomes NO_DATA, which is honest. Those two
*invert* a ratio, and the inversion runs in the direction that reports a
violating character as compliant. Rule 7(3)'s proviso exists precisely to catch
narrow type; on any declaration set down the side of a pack it was passing
everything. Nothing raised, and the number it produced looked entirely ordinary.

### The fix is structural, not seven patches

Patching seven sites is seven chances for them to disagree later. Instead the
crop is rotated to horizontal **once**, in `vision/ocr/roi.py`, before any
measurement is taken, and `vision/measure/orientation.py` owns both halves of
that: the decision, and the inverse transform that carries the resulting boxes
back to where they were found. Nothing downstream of the rotation knows it
happened — `cap_height`, `characters` and `contrast` were not modified to
understand rotation, they simply never see it any more.

Two things could not be handled that way, because they run in `rules/`, which
never imports `vision/`. For those, the rotation travels on the contract as
`Declaration.text_rotation_k` and `Declaration.glyph_size` performs the swap.
That is a measurement crossing the wall, not a decision: vision reports which
way the text ran, the rulepack still decides what follows.

`glyph_size` is deliberately not `min(w, h)`. That would be right for every
sideways case and wrong for an upright digit, which is also taller than it is
wide — so the rotation is consulted rather than inferred from the shape.
`tests/unit/test_vertical_text_measurement.py` pins this as an equivalence:
rotate the pixels, and every number out the far end must equal the number the
upright pack produced. A threshold test would have passed throughout the entire
period the bug existed.

### U1 after the sweep

    frames measured    4/40 (10%)      unchanged
    MAE                1.245 -> 0.527 mm      (target <= 0.15)
    p95                2.191 -> 0.896 mm      (target <= 0.25)
    repeatability      0.318 -> 0.118 mm
    systematic bias                -0.289 mm

**U1 remains NOT MET,** and the reason it is not met has changed. Accuracy
improved by roughly a factor of two on every measure, and repeatability — our
own spread between two shots of the same packet, with no ruler involved — is now
inside the U1 target it is compared against. What is left is not a measurement
error at all: 36 of 40 frames read no MRP declaration to measure.

### What is actually blocking U1 now

Tracing three failing frames end to end shows the loss is at **region
selection**, not detection, reading or measurement:

    horlicks_jar_500mg   83 regions proposed, 8 read
    yogabar_oats_725g   146 regions proposed, 8 read
    shampoo_400ml       176 regions proposed, 8 read

and the eight that were read are marketing copy — *"SPoRT is not a sacrilice It
is a privilege"*, *"Ourlabels ar honest"* — batch codes, and fragments. The
declarations are somewhere in the other 138. `MAX_REGIONS = 8` is section 4's
budget and is not the bug; the ranking that chooses which eight is, because it
ranks on geometry alone and geometry cannot tell a net quantity from a line of
body copy set at the same size.

This is a genuinely different problem from the one above and it is recorded
here without a fix, because the obvious fixes all involve choosing a threshold,
and the only frames that demonstrate the problem are in `data/test_split/`.
Those three frames were read to *diagnose* the failure; no threshold has been
taken from them, and none will be. Any discriminator has to be derived from the
statute or measured on the dev corpus, the way `input_side` was.

## Chasing U1 to its actual cause

The previous section left U1 at 4/40 with the loss at "region selection". That
diagnosis was half right and the half that was wrong mattered, so both the
correction and the evidence are recorded here.

### Four more bugs, each found by following the last one

**1. The orientation sweep (seven sites).** Documented above. U1 accuracy
roughly halved on every measure.

**2. Reading deeper did not help, which killed the ranking hypothesis.** The
bench read the top 24 regions instead of the top 8 and recall did not move at
all — recall@24 came back identical to recall@8. A declaration sitting just
below a cut-off would have appeared. Something else was wrong.

**3. DBNet proposes words; nothing assembled them into lines.** On a dev-corpus
pack:

    x=167 y=585  'MRP Rs.'      x=275 y=597  '10'
    x=172 y=678  'Batch No.:'   x=282 y=673  '060924'

Every fragment was detected, cropped and read correctly. Then `regex_tier` was
handed `'MRP Rs.'` alone, which declares nothing, and `'10'` alone, which is a
number with no field. Both came back `other`. The declaration was never
missing; it was never assembled. `vision/ocr/lines.py` now merges word
proposals into printed lines before the crop budget is applied.

It took two attempts. The first sorted along the reading axis and chained
neighbours in one pass, which interleaves the two columns of a label and merged
nothing at all. The second used union-find over every candidate pair and then
over-merged in the opposite direction: two consecutive lines of body copy
overlap *vertically* by 61%, well past the threshold, because DBNet's boxes are
loose. What separates them is that fragments of one line sit **beside** each
other while two lines sit **on top of** each other — a gap of -168 px along the
reading axis for lines 45 px tall. Both failures are pinned as tests.

**4. A word boundary is not a script boundary.** With merging in place, a
dev-corpus pack's MRP was read correctly as `MRP<U+0930> 15.00(incl. of all taxes)` —
the rupee sign came back as a Devanagari letter — and was *still* classified
`other`. `mrp_locate` ended in `\b`, and there is no word boundary between `P`
and a Devanagari letter, because both are word characters.

This is not only an OCR artefact. `MRP<U+0930><U+0941>. 15.00` is an ordinary bilingual
rendering and Rule 6 expressly permits Hindi, so a pack printed exactly as the
rules allow could not be located, and `LMPC.MRP.PRESENT` reported **"Retail
sale price not declared" against a pack that declares it**. A missed violation
is a missed case; a fabricated violation is an enforcement action against
someone who complied. Five locate patterns now use
`(?<![A-Za-z0-9])...(?![A-Za-z0-9])`, which is exactly as strict as a word
boundary for Latin and additionally allows a script change. `24MRP07` and
`MRP07` are still rejected. The strict *format* patterns were deliberately left
alone: they define what is lawful rather than what is present, and widening
lawfulness is not a change to make while chasing a recall number.

**5. Merging inflated the very number the ranking reads.** A merged region's
union box is taller than the type inside it — `MRP Rs.` (h=36) beside `10`
(h=32) unions to h=44, a 29% overstatement — and the ranking reads the box's
minor axis as the line height. Merging therefore *hurt* recall@8 on the dev
corpus (10% → 6%) while helping at depth. `TextRegion.line_height_px` now
carries the median height of the parts, and the ranking prefers it.

### Where U1 actually stands

    frames measured    4/40      unchanged
    MAE                0.499 mm  (was 1.245 before this work, target <= 0.15)
    p95                0.950 mm  (was 2.191, target <= 0.25)
    repeatability      0.228 mm

Coverage did not move. That is the finding, not a failure to report one, and
the crop budget is not what is holding it:

    crop budget    frames measured    MAE       cost
    8              4/40               0.499     1388 ms/frame
    24             6/40               0.879     2349 ms/frame
    48             9/40               1.340     3600 ms/frame

Reading six times as much finds the MRP on five more frames and measures all of
them *worse*. That is the signature of a recognition problem, not a selection
problem, and the trace confirms it directly. On `shampoo_400ml` the MRP block
is detected and cropped correctly:

    x=2144 y=1807 126x62  'MPEE'      <- 'MRP RS.'
    x=2380 y=1818 174x43  '559.00'    <- read perfectly, confidence 1.00
    x=2149 y=1846 141x53  'otal tes)' <- '(incl. of all taxes)'

The value reads at confidence 1.00. The label does not. Upscaling the crop 4x
before recognition moves `'MPE'` to `'MRPE'` and no further, so this is not
resolution — it is the INT8 mobile recognition head on Indian packaging type.
`'MRPE'` is correctly *not* matched, because `MRP` inside a longer Latin word
must not match; the recogniser turned `₹` into `E`.

**So U1 cannot be closed with heuristics, and no further heuristic will be
attempted.** The measurement chain is now good — repeatability of 0.228 mm is
inside the 0.25 mm target it is compared against, and that is our own spread
with no ruler involved. What is missing is character accuracy on the packs
themselves, and the plan's answer to that is fine-tuning on the corpus, which
needs labels. `scripts/prelabel_corpus.py` over `data/corpus/` is therefore the
next step and not a detour.

### A note on the dev bench's denominator

`bench/rank_recall.py` originally scored every sampled image, which is wrong:
the dev corpus is photographs of packs from every angle, and most faces of a
pack carry no MRP at all. The top of a sunscreen carton has a brand name, an
SPF claim and a barcode — finding no declaration there is correct behaviour,
not a miss. Recall is now reported over the frames that demonstrably contain a
findable declaration. The absolute numbers before that correction were
meaningless; the raw-versus-merged *delta* was not, and that is what chose
`GAP_RATIO`.

---

## 2026-09-09 — Four bugs between the pipeline and U1

The previous section concluded that U1 was blocked on recogniser character
accuracy and that no further heuristic would be attempted. That conclusion was
premature: it was drawn from an aggregate coverage number without looking at
what the pipeline had actually read on each frame. Section 18b asks for the
opposite — *"hunt the errors, do not wait for them. Pull the twenty worst cases
and look at them."* Dumping every line read on all forty ruler frames found
four defects, three of which were producing wrong measurements rather than
missing ones.

### First: which bar is actually failing

Two different thresholds had been reported as one number.

| | metric | measured on | bar | where |
|---|---|---|---|---|
| **U1** | mm error | frames where a declaration was found | MAE ≤ 0.15, p95 ≤ 0.25 | §18b, day-7 go/no-go |
| **MRP F1** | was it found | every frame | ≥ 0.90 | §18b, "after the build" |

"9 of 40" was being reported as U1. It is not U1; it is the coverage bar, and
it was dragging U1's error along with it because the frames that *did* produce
a number were producing bad ones. §18b's fail-path for U1 is explicit — MAE
above 0.5 mm means leading with the scale-free tier, and **28 of 31 rules never
needed a scale** — so U1 is not project-blocking in the way coverage is.

### 1. `numeral_box` was measuring the crop, not the figures

Rule 7(2) Table I and Rule 9 attach to the *numerals*, and
`Declaration.height_for_rules_px` preferred `numeral_box`, built by
`characters.character_boxes` from column runs. A column run's vertical extent
is whatever ink sits in those columns — the crop padding, the neighbouring line
it caught, the printer's rule underneath. Instrumenting the real pipeline on
`bodywash_bottle_300ml/tilt`:

    '449.00'   per-character heights [52, 41, 52, 52, 41, 42] px on a 52 px crop
    '07/2026'  per-character heights [55, 55, 55, 43, 55, 41, 43] px
    '14 JUL 26  17:03 04806'   [4, 38, 1, 3, 68, 22, 1, 20, 3, 1, ... 124]

The digits on that pack are about 19 px tall. The segmentation had found the
crop rather than the figures, and its only sanity check — *does the run count
match the text length* — could not see it, because the **columns** were right
and only the rows were wrong.

`cap_height.measure_numeral_height` already does this correctly: connected
components, anything spanning the crop rejected, clustered on the shared
baseline, median of the tall cluster. It was written, exported, named in
`vision/measure/__init__.py` as the source of `height_px`, and called by
nothing. It is now what `numeral_height_px` carries, all the way to the
contract. `numeral_box` stays, because `clear_space` needs to know *where* the
figures are, and it is no longer read as a measurement.

Being a scalar rather than a box, it is also immune to the axis confusion the
whole previous section was about: it is measured on the crop the text was read
from, where the glyphs are already upright.

`character_boxes` additionally now rejects a segmentation whose median glyph
height exceeds the line's own cap height by more than 1.5x, so Rule 7(3)'s
width-over-height ratio cannot be computed from the same noise. An inflated
height there makes a lawful character look too narrow — a false violation
against a compliant pack.

### 2. The declaration was being read and thrown away

On `bodywash_bottle_300ml/tilt` the pipeline read:

    (2171, 1591, 28, 24)   'o'        the MRP label, badly read
    (2297, 1597, 145, 42)  '449.00'   confidence 0.97

and reported the pack as declaring no retail sale price. `449.00` alone matches
no locate pattern, and rightly so — a bare number is a batch code as often as
it is a price. Across the ruler set this is the commonest way a declaration is
lost.

`vision/classify/associate.py` pairs a value-less field label with the nearest
figure printed beside or under it, **after** reading, when both fragments'
text is known. The boxes are not merged: the text joins so the rulepack's
format patterns see the whole declaration, and every pixel comes from the
value, because the union box spans the label, the gap and the figure. The label
is demoted to `other` so `no_duplicate_field` cannot fire on a split our own
detector introduced. It covers `net_quantity` on the same terms — this is not
an MRP patch.

### 3. `MRP2.00` was rejected by our own boundary guard

`match_box`, both shots, reads `MRP2.00 incl. of all taxes` — legible, correct,
and the whole declaration on one line. It classified as `other`. The locate
patterns guard with `(?![A-Za-z0-9])`, so a digit immediately after `MRP`
blocked the match. (A plain word boundary would have done the same.) The guard
exists for `24MRP07`, a named hard negative, and that is a digit on the
**left**.

The trailing guard now asks for the shape of the value instead of the class of
one character: a digit may follow if it forms an amount with paise, or is
followed by `/-`, or — for the quantity — carries a lawful unit symbol. Checked
against every case the guard was there for:

    'MRP2.00 incl. ofall taxes'  mrp            'MRP07'      batch
    'MRPरु. 15.00'               mrp            '24MRP07'    batch
    'Net Wt500g'                 net_quantity   'NetWt07'    other
    'MRP 5/-'                    mrp            'MRP07/2026' batch

### 4. One recognition head was being run twice

`MODEL_FILENAMES` and `DICT_FILENAMES` both map `latin` and `devanagari` to the
same file — deliberately, and the reasoning is in `recognise`. So "run both
heads when the script classifier is unsure" was decoding identical logits
against an identical table and choosing between two identical readings, at
double the cost. The candidate list is now deduplicated by resolved
(weights, dictionary), which leaves the shape of the decision intact for the
day a second head earns its bundle size.

### Batched recognition: 2.49x, measured

`recognise_batch` looped over `recognise`. Its docstring said batching *"would
need padding to a common width that costs more than it saves"* — an assumption,
never measured. The ONNX graph takes `(N, 3, 48, W)` with both N and W dynamic.
`read_batch` sorts work items by width, closes a bucket when its widest member
exceeds 1.5x its narrowest, and runs one session per bucket. Over 62 regions
from six dev-corpus photographs:

    sequential  3526 ms   56.9 ms/crop
    batched     1418 ms   22.9 ms/crop      2.49x

47 of 62 readings were identical. Of the 15 that differed, batched recovered a
trailing character more often than it lost one (`'NET CONTENT'` to
`'NET CONTENT:'`, `'CRO a'` to `'CRO at'`, `''` to `'syp'`) — right-padding
gives CTC extra timesteps at the end. So batching is **not** answer-preserving,
and the docstring says so rather than claiming it is.

### The crop budget was choosing which declaration to lose

`MAX_REGIONS = 8` came from §4's "four to eight crops", which was reasoned from
a per-crop recognition cost that no longer holds. Whole-frame cost across three
ruler-set photographs, after batching:

    crops read      23      66     113     151
    ms per frame  1339    1795    1947    1778

Six and a half times the regions for a third more time; the ~1.3 s that does
not move is detection and rectification. `MAX_REGIONS` is now 64.

§17's discipline is untouched — these are still the detector's regions, never
the photograph. What changed is the arithmetic the number 8 was derived from.
This does put a scan at ~1.8 s on this machine against §4's 561 ms, which is a
browser-latency claim (U3) that has never been measured in a browser, and whose
own fail-path in §18b is detector input 640 to 512, ROI capped at four, INT8
everywhere. That lever exists if latency turns out to bind. Spending it before
knowing a declaration can be found at all would be optimising the wrong thing.

### U1 after all of it — sealed forty, 2026-09-09

|  | before | after |
|---|---|---|
| frames measured | 2/40 (5%) | **9/40 (22%)** |
| declarations found | 9/40 | **14/40** |
| MAE | 0.238 mm | 0.332 mm |
| p95 | 0.277 mm | 0.773 mm |
| repeatability | 0.077 mm | **0.055 mm** |

The MAE moved the wrong way because the seven frames added are harder than the
two that were already passing; the two easy ones did not get worse. Two frames
are now inside a tenth of a millimetre of the steel rule:

    horlicks_jar_500mg/front    5.00 mm ruler    5.06 mm   error 0.062
    hammer_earphones/tilt       1.00 mm ruler    1.01 mm   error 0.008

**U1 remains NOT MET, and it is honest to say the physics is not the problem.**
Every remaining error is now a real measurement on a real declaration rather
than a fabricated one, which is the state the previous section's conclusion
should have been drawn from.

### The correction to the earlier claim

The earlier section's *"U1 cannot be closed with heuristics"* was drawn from the
wrong experiment — upscaling a rectified crop 4x tests interpolation of
information already lost, not whether the information exists. It stands only
for the label-recognition half. The measurement half had four bugs in it.

Of the 40 frames now: 9 measured, 5 found-but-not-measurable, 26 not found. The
largest single residual among the 9 that measured is *which* numerals on a line
get measured — on `MRP2.00 incl. of all taxes` every digit on the line joins the
tall cluster, and a 1.00 mm declaration reads as 1.50. Restricting the component
cluster to the columns of the value is the next measurement fix.

### Benchmark bugs found in the benchmark

`scripts/u1_report.py` chose among candidate declarations with
`max(matches, key=height_mm)` — the *tallest* reading, which is a scoring rule
that walks the reported error upward on purpose. It now takes the
best-supported reading (field confidence, then OCR confidence).

It also reported `"no scale recovered (tier A); card in frame?"` on seven frames
where the card was found perfectly and the *figure* was what was missing. A
benchmark that misnames its own failures is worse than one that only counts
them; the two causes are now reported separately.

### Segmenting inside the text band, not the padded crop

`character_boxes` scanned the whole padded crop for ink columns. The padding is
there so recognition has context and `contrast_ratio` has a background, and it
routinely catches the line above, the line below and the printer's rule under
the declaration — so ink appears in columns where this line has none, glyphs
merge into one run, and every run inherits the vertical extent of whatever else
was in frame.

`measure_cap_height` has already found where the line's glyphs sit, by modal
agreement among connected components, which a row profile could not do without
being pulled by the neighbouring line. Segmentation now works inside that band.
Alignment rate over every line read on all forty ruler frames:

    whole crop (before)   204 / 1991   10%
    text band  (after)    331 / 1991   17%

A 62% relative improvement, and it is the same structural move
`vision.measure.orientation` makes for rotation: establish the frame once and
let every stage downstream work inside it.

It did not move U1, because the lines it newly aligns are not the ones being
measured. It matters for Rule 7(3), which returns NO_DATA whenever alignment
fails, and it is what lets `measure_numeral_height` be told which columns hold
the digits.

### `measure_numeral_height` was not measuring numerals

Its method was "among baseline-aligned components, take the ones whose height
clusters at the top", on the reasoning that lining figures are full cap height.
They are — and so are the capitals of the label printed beside them. On every
line checked it returned the line's cap height to within half a pixel, which is
what that method reduces to.

It now takes the horizontal spans of the digit characters from
`character_boxes` and considers only components centred inside them: columns
from segmentation, heights from connected components, each method asked only
the question it can answer. Where segmentation did not align, the old fallback
remains, because a line that could not be segmented still has a measurable
figure more often than not.

### A hypothesis that was wrong: resolution

Section 18b's U1 premise is that *"at 12 MP with the pack filling the frame you
get ~24 pixels per millimetre... pixel density is not the limit."* Looking at
`moov_6g/front` rectified, the ChArUco card fills the sheet and the 6 g tube
occupies about 3% of the frame, so the obvious hypothesis was that the failing
frames are simply too small to read.

Measured across all forty, against whether the declaration was found:

    declaration FOUND      n=14   median glyph height 22.8 px
    declaration NOT found  n=26   median glyph height 19.3 px

The two populations overlap almost completely. `iodex_balm_25ml/front` gives
23.4 px of glyph and is not found; `hammer_earphones/tilt` gives 8.9 px and is.
**Resolution is not the discriminator, and the hypothesis is rejected.**

What the exercise did establish is that the premise itself is not met by this
corpus. Every one of the forty frames delivers between **4.9 and 11.7 px/mm** —
roughly what §18b attributes to a 1080p frame-filling shot, not to 12 MP —
because the inspection card, not the pack, is what fills the frame. That is a
capture-protocol observation to put to whoever shoots the next set, not an
explanation of these results.

### What the 26 unfound frames actually are

Counting regions read per frame separates them cleanly:

| | frames | regions read | what is wrong |
|---|---|---|---|
| detection-starved | 8 | 6–16 | `moov_6g`, `vicks_chocolate`, `iodex_balm`, `diet_coke_can` — small, curved, glossy. §8b already names this: a homography is valid for planar surfaces, and we are warping a standing tube and a can to the card's plane |
| recognition-limited | 18 | 20–105 | plenty of text read, no MRP label among it |

And the classifier is not losing anything once the label reads: over the forty
frames the MRP locate pattern matched on 14, and **all 14** were classified as
an mrp declaration. Every remaining loss is upstream of classification.

A price-shaped amount was read on 18 frames and a currency marker on 17, but
both a label *and* an amount on only 6. So a dozen frames have the price sitting
in the output with nothing beside it that reads as a label — `shampoo_400ml`
gives `'559.00'` at confidence 1.00 next to `'MPEE'`, three edits from `MRP RS.`
and unrecoverable. `vision/classify/evidence.py` was built for exactly this and
its own docstring already records that it does not rescue that line: two weak
signals are required, and a bare amount is one.

**This is the same conclusion the previous section reached, now reached from
measurements that are trustworthy.** It is a stronger claim than before because
four bugs that were corrupting the evidence have been removed first. The path to
the MRP F1 bar is §18b's U2 fallback — fine-tune the recognition head on our own
crops — and, for the eight curved-surface frames, §8b's honest limit: crop the
locally planar region rather than warping the whole frame to the card.

### One ground-truth item to re-check

`match_box` measures 1.50 mm against a recorded 1.00 mm, and the pixels are
internally consistent: the `M`, `R`, `P` and the `2`, `0`, `0` all come back
16–17 px tall on a frame whose scale is fixed by a ten-marker ChArUco fit at
0.0935 mm/px. The same scale pipeline reads `horlicks_jar_500mg/front` at
5.06 mm against a 5.00 mm rule and `hammer_earphones/tilt` at 1.01 against 1.00,
so it is not a per-frame scale error. Worth putting a rule on that matchbox
again before treating the 0.50 mm as our error.

---

## 2026-09-09 — The web application, and three things it refuses to fake

P8 was the last untouched phase in the plan. `web/` now holds a Next.js 15 App
Router PWA covering all thirteen routes section 11 names, and the numbers below
are measured on this machine rather than estimated.

### What was built

| | |
|---|---|
| Routes | 13 from section 11's table, plus `/offline` |
| Bundle, first load shared | **102 kB** |
| Heaviest route (`/dashboard`, two Recharts charts) | 226 kB first load |
| Precached shell | **1.35 MB across 47 files** — section 5 budgets ~6 MB outside the models |
| Model bundle, budgeted | ~44 MB, capped at 60 MB and enforced in CI |
| Playwright | **9 tests, all green**, including the aeroplane-mode run |
| `tsc --noEmit` | clean, `strict` + `noUncheckedIndexedAccess` |
| `eslint` | clean |
| Python suite after the fix below | **740 passed, 5 skipped**, 40.6 s |

### The service worker did not work, and nothing said so

`workbox-build`'s `injectManifest` **does not bundle**. It replaces the
`self.__WB_MANIFEST` placeholder and writes the file out; the `import` statements
at the top of the source survive verbatim. A service worker containing bare
specifiers fails at script evaluation, and the failure surfaces as:

    navigator.serviceWorker.ready   // never resolves
    getRegistrations()              // []

with no console error in the page, no failed network request, and an application
that is quietly not offline any more. It was found only because the Playwright
offline test hung on `serviceWorker.ready` — which is the argument for writing
that test first rather than last.

`scripts/build-sw.mjs` now bundles with Rollup into a self-contained IIFE and
injects into *that*. The `__WB_MANIFEST` identifier is added to terser's reserved
list, because a minifier that renames it leaves a worker that installs happily
and precaches nothing.

Second finding from the same test: **`/queue` was unreachable offline**, because
"cached on first visit" is worthless for a page the officer has never visited —
which is exactly the case for the queue. The worker now fetches `/offline`,
`/scan` and `/queue` at install, while it still has the network it was installed
with. Each is fetched individually inside a `try`, so one page that 401s cannot
fail the installation and leave the app with no worker at all.

### A test that hung instead of failing

`tests/unit/test_upload_path.py::test_the_render_worker_stores_into_the_derived_bucket`
had been deselected in the previous session as "environmental — Postgres
container down". It was not environmental. The `wired` fixture patches the scan,
SKU, spool, job and object stores onto `api.deps`, but `render_report` also calls
`get_user_store()` to put the officer's name on the report, and that one was
left unpatched — so it fell through to the SQL store and blocked on a connection
the machine does not have.

One line in the fixture. The file now runs in 17 s, and the full suite is 740
passing with **no deselections and no hang**, which matters more than the one
test: a suite that has to be started with a `-k` expression is a suite that stops
being run.

### Three things the interface refuses to fake

Each of these could have been a plausible-looking control. Each says what is
actually true instead, in the place where a wrong assumption would be formed.

**Photographs taken offline stay on the device.** Section 5 asks for *"verdicts
sync before photos"*, and the verdicts do. The photographs cannot follow: the API
has no route that attaches an image to a scan record that already exists, and it
cannot simply grow one, because section 6 hashes the scan record — `image_key`
and `image_sha256` included — into the chain in `evidence/chain.py`. Filling
those fields after the record is sealed changes the payload the hash was taken
over and breaks the chain at that row, which is precisely the failure the chain
exists to detect. Re-posting to `POST /scans` does not help either: a scan id we
already hold takes the replay path and returns the stored verdict without storing
anything. So `photo_state` is `held`, and `/queue` explains it in a paragraph
rather than showing a progress bar that never reaches the end. Closing it needs a
server-side decision about where a deferred evidence digest lives.

**On-device inference is not wired.** The model manifest, the
WebGPU/WASM-SIMD/threads probe and the `CacheFirst` strategy are all in place,
and the execution path is recorded into `model_versions` exactly as section 15b
requires. The pipeline is not, so an offline scan is recorded at tier L4 — the
photograph, its time and its location — and gets its verdict on sync. Section 8b's
rule is `NO_DATA`, never a guess, and that rule does not relax because the code
would be running in a browser.

**The brand-notification marker is not drawn.** Section 11 calls the
before-and-after view *"the most persuasive artefact this system can produce"*.
No notice date is stored anywhere in the schema, and `analytics.brand_detail`
already says why: it is a departmental action, not a scan fact. Drawing a
plausible line on that timeline would be fabricating the persuasive artefact
itself. The timeline is rendered ready for it and the caption says what is
missing.

The same discipline covers `/admin` (no user-management API exists, so the panel
says so instead of posting nowhere), `/products/[id]` (no single-SKU endpoint, so
it searches the warmed window and says when a SKU falls outside it), and the
review queue's one-click resolve (it records a real append-only correction, and
states that no route marks a review closed).

### Two additions to the backend, both small and both from section 11

- **`analytics.by_brand` gained a `trend` column.** Section 11's brands table
  names it between `Worst rule` and `Last scanned`, and it was not there. The
  period is split at its own midpoint and the non-compliance rate compared across
  the halves — deliberately not a slope over weekly buckets, because enforcement
  scanning is bursty and a regression over calendar weeks mostly measures which
  weeks anyone went out. It returns **null below six scans**, and the table prints
  "not enough data" rather than "flat": the three states a reader can act on are
  better, worse and *we do not know*, and collapsing the third is how a brand
  gets left alone because a column said nothing was happening. Computed
  server-side so the screen, the CSV and the PDF cannot disagree about the one
  column somebody will quote at a hearing.
- **A `web` service that actually builds.** `docker-compose.yml` pointed at a
  Dockerfile that did not exist and set `NEXT_PUBLIC_API_URL`, which would have
  put the API origin in the browser bundle. It now builds `docker/web.Dockerfile`
  and passes `AKSHAR_API_ORIGIN` server-side only.

### Dependency notes, stated rather than buried

- **shadcn/ui was not installed.** Its MCP server would not connect this session.
  The six primitives the app needs — button, card, badge, table, field, alert —
  are hand-written in `web/src/components/ui/` in the same idiom, on
  `class-variance-authority` + `tailwind-merge`, with `@radix-ui/react-slot` as
  the only Radix dependency. Nothing else from the registry was needed, and this
  is the difference between a listed dependency and a used one.
- **Next is pinned to `15.5.25`, not 15.1.** 15.1.12 carries a critical advisory
  whose fix landed in 16.3.0; 15.5.25 is the furthest the 15 line goes. The
  remaining upgrade is recorded as a deployment-blocking gap in
  `docs/deployment.md` §7 rather than left to be discovered by a scanner.
- Seven declared-but-unused packages were removed, `onnxruntime-web` among them.
  A dependency nothing imports is not a feature in progress; it goes in with the
  pipeline that uses it.

### CI

Four jobs. Three are the obvious ones — `python`, `web`, `e2e`. The fourth,
`contract`, is the one worth naming: it re-exports the OpenAPI schema from the
live FastAPI app, regenerates `schema.gen.ts`, and **fails if the committed file
differs**. Section 15b's promise is that *"frontend types cannot drift from
`contracts/`"*, and a generated file that is committed once and never regenerated
drifts silently. This is what turns that sentence into a property.

---

## 2026-09-09 (later) — a demonstration stack, Next 16, and four bugs the demo found

The web application existed and passed its tests. It had never been run against a
populated API, and that turned out to be the difference between "the tests pass"
and "the thing works".

### The seeded stack

`python scripts/run_demo.py` starts the API in-memory on :8000 and the web app on
:3000. No Docker, no Postgres, no Redis, no MinIO. This is not a mode written for
the demonstration; it is the Protocol-typed stores and `AKSHAR_STORAGE=auto` being
used as `api/repository.py` always said they could be.

`api/demo.py` fills it: 3 officers, 16 SKUs across 10 brands, 6 districts, 260
scans over 75 days. **No verdict in it is written by hand.** Each demo pack is a
real `DeclarationSet` — cap heights in millimetres, character boxes, panel
geometry, a Devanagari second script on about a third of packs — passed through
`rules.engine.evaluate` against `lmpc_2011.yaml`. The dashboard is drawn by the
same code path an inspection uses, and the numbers on it are the engine's:
**47.7% non-compliance across 260 scans, 33 high-severity findings, 9 awaiting
review**, degradation tiers **L0 217 / L2 26 / L4 17**.

The alternative — a list of pre-written verdicts — was ten lines of work and
would have made the dashboard a painting of a dashboard.

Three guards, because demonstration rows in a department's database would be
counted as inspections: off by default, refused when `AKSHAR_ENVIRONMENT` is not
development, refused on the SQL backend, and `/healthz` carries a
`DEMONSTRATION DATA` line whenever it is on.

### Four bugs, and not one of them was found by a test

**1. Every Server Component call to the API was failing.** `serverFetch` imported
`withQuery` from `client.ts`, which is `"use client"`. A Server Component may not
invoke a client function, so every dashboard view — overview, brands, rules,
categories, districts, health — threw, and `tryServerFetch` turned the throw into
the same polite "could not be loaded" panel that an expired session produces. It
survived review because nothing had ever rendered against a populated API.
`withQuery` now lives in `query.ts`, which declares neither directive, and
`tryServerFetch` logs the reason instead of swallowing it.

**2. The trend chart drew an empty grid.** `api/analytics.weekly_trend` emits
`non_compliance_rate`; the hand-declared `TrendPoint` in `types.ts` called it
`rate`. `point.rate` was `undefined` on every point, so Recharts rendered axes and
no line — which looks exactly like "no data". A hand-declared type that disagrees
with its payload fails silently and in the most misleading direction. The table
view now also shows the numerator and the denominator, because a table that only
repeats the percentage adds nothing to the chart above it.

**3. The service worker precached no stylesheet.** Next 15 emitted CSS to
`static/css/`; Next 16 emits it into `static/chunks/`. The precache glob was
directory-scoped, matched nothing after the upgrade, and `workbox-build` reports
that as a *warning* before writing a perfectly valid service worker with no CSS in
it. The only symptom is an unstyled page offline. Same shape as the
`injectManifest`-does-not-bundle failure earlier the same day: the service
worker's failures are all silent, and none of them fails a build.

**4. Verdicts carried the violation text even when they passed.** `rules/engine.py`
fell back to `rule.message` for any check that returned no detail of its own, so a
compliant pack produced rows reading `PASS — Net quantity not declared.` On screen
that is confusing; in a report served under section 14 it is a document stating an
offence and a clearance in the same line. Fixed at the engine, so the PDF and the
DOCX are fixed with it.

Two of these are dashboard-wide and neither was catchable without data. The seeded
stack paid for itself before it was finished.

### Next 15 → 16.3.4

The CVE recorded as deployment-blocking earlier on 2026-09-09 is closed; `npm
audit` reports nothing that reaches the browser. Two findings remain and both are
build-time only (`openapi-typescript` → `@redocly/openapi-core` → `js-yaml`),
running over a JSON file this repository generates from its own FastAPI app.

The upgrade cost three real changes rather than a version bump. `eslint-config-next`
16 exports native flat config and the `FlatCompat` shim does not merely become
redundant, it *breaks*: ESLint dies on a circular structure inside the plugin
objects, with no reference to our code anywhere in the trace. `NextConfig` no
longer accepts an `eslint` key. And React Compiler's `react-hooks/set-state-in-effect`
caught two components mirroring external state into `useState` from an effect —
both real. `ModeToggle` kept a copy of a `data-mode` attribute the DOM already had,
which is one flash of the wrong label on every load; it is now
`useSyncExternalStore` over the document. `OutboxPanel` wrote state after unmount
with no guard, and did three sequential awaits where one `Promise.all` does.

**9/9 Playwright green on 16.3.4**, 754 Python tests passing, `ruff` clean,
`mypy --strict` clean on `contracts` and `rules`.

### B1 — the capture-quality gate

Section 17's M0, built. Blur, exposure, glare and minimum resolution; no model;
the first step of `vision.pipeline.scan`, with a new `unusable` exit that still
produces the L4 record and still computes the perceptual hash and the barcode —
an evidence record nobody can match to a SKU is most of the way to worthless, and
a barcode routinely survives the blur that ruined the printed declaration.

| Frame | blur | glare | exposure | verdict |
|---|---|---|---|---|
| sharp, well-lit label | 0.82 | 0.00 | 1.00 | usable |
| **near-white pack, well-lit** | 0.84 | 0.00 | 1.00 | **usable** |
| out-of-focus (sigma 9) | 0.02 | 0.00 | 1.00 | blur |
| motion blur, 35 px horizontal | 0.06 | 0.00 | 1.00 | blur |
| motion blur, 35 px vertical | 0.04 | 0.00 | 1.00 | blur |
| under-exposed to 9% | 0.04 | 0.00 | 0.96 | blur + underexposed |
| specular highlight across label | 0.59 | 0.43 | 0.57 | glare + overexposed |
| 420 x 315 | 0.91 | 0.00 | 1.00 | resolution |

**7.5–8.5 ms** against section 4's 15 ms budget, and unchanged on an 8 MP frame,
because every statistic runs on a fixed-size working copy.

Two deviations from the plan's wording, both because the obvious implementation is
wrong in a way that only shows on real photographs.

**Blur is per-axis, not variance-of-Laplacian.** The Laplacian sums both second
derivatives, so a sideways hand-shake — which destroys the vertical strokes of the
digits and leaves the horizontal ones — still shows plenty of edge energy. The
35 px horizontal smear above scored **0.32** under a Laplacian against a 0.18
threshold and passed. Taking the second derivative along each axis and keeping the
worse one, it scores 0.06. Directional shake is the commonest bad frame in a shop,
so this is not an edge case.

**Exposure is measured by clipping, not by mean luminance.** A near-white pack —
salt, sugar, flour, most pharmaceutical cartons — photographs at a mean around 245
and is the easiest label in the country to read. A mean-based test rejects every
one of them while passing a grey pack photographed in a dark shop. There is a test
named for that specific false positive.

**The done-criterion is not met and cannot be yet.** Section 17 asks for at least
90% recall on the deliberately-bad subset and at least 98% pass on usable frames.
That subset is part of the 400-photograph corpus that has to come from the field,
so **no recall figure for B1 appears here** — every threshold is derived from the
physics of its measurement and from the frames we have, not fitted to a labelled
set, and the module says so in its own docstring. Until then the gate is
deliberately permissive: a false reject costs one retake, but a gate tuned tight on
guessed thresholds turns every difficult-but-readable frame into a retake, and an
officer sent back four times stops using the tool.

### Interface work

The rule identifiers were being title-cased into the UI: `Netqty . Si_units`,
`Mrp . Numeral_height`. Those are not abbreviations, they are a database
identifier with its punctuation swapped. All 38 rulepack ids now have a written
name — "Net quantity in SI units", "MRP numeral height", "Clear space around net
quantity" — with the id kept in the `title` attribute and `rule_ref` still
carrying the citation.

The scan record leads each row with the rule's name rather than its message, and
folds the settled rules into a `<details>`: thirty green rows above the fold push
the one amber row that needs a decision off the screen, which inverts the point of
the page. `@media print` opens every `<details>`, because a printed record is
evidence and evidence is not allowed to be folded.

The sign-in page now says what the tool is — the shelf-versus-artwork distinction,
"rules decide, models never", and L1 — and the five overview tiles say "no previous
period" once beneath the row instead of five times inside it.

The app icon is the letter अ set between two rules, on its baseline and its
shirorekha, generated by `scripts/make_icons.py`. Cap height measured against a
baseline is the one quantity this system exists to recover, so the mark is a
picture of the measurement rather than a monogram.

---

## 2026-09-09 (evening) — the logo, and a walk through every screen

### The identity

The mark is now the letter **A** in the logo's crimson-to-orange gradient, drawn
as inline SVG (`web/src/components/brand.tsx`) rather than fetched as a PNG: it
costs about 900 bytes in HTML that was already being sent, needs no second
request in the offline shell, and inherits the palette — which is what lets the
daylight mode flatten it to one high-contrast colour. `scripts/make_icons.py` is
its raster twin, drawing the same strokes on the same 64-unit grid at 4x and
downscaling, so the launcher icon and the masthead cannot drift apart without
somebody noticing.

**The one hard problem is written into `globals.css`.** The brand is a
crimson-to-orange gradient; FAIL is red and REVIEW is amber. Those three live in
the same quarter of the colour wheel, and a chrome painted in the brand colour
competes with the only two signals on the screen that mean anything. Three rules
keep them apart, and every value in the file obeys them:

1. the brand is **wine** (`#8e1b3a`, blue-shifted) and FAIL is **scarlet**
   (`#c2261b`, orange-shifted) — two hue steps apart, and the wine only ever
   appears as a solid fill on a control the officer pressed, the scarlet only
   ever as a tint behind text;
2. status is never carried by hue alone — every verdict already ships a glyph;
3. the gradient is reserved for identity. Nothing that reports a fact is painted
   in it.

Every pairing was checked against WCAG AA on its own ground and the measured
ratio is in the comment beside it. Dark mode takes its accent from the *other*
end of the same gradient, because `#8e1b3a` on `#1a0f13` is 2.3:1 and
unreadable; `#f98b5e` is 8.0:1 and is still the logo.

### The camera, which was genuinely broken

`startCamera` assigned `videoRef.current.srcObject` from inside the click
handler, and the `<video>` was only rendered once `cameraOn` had flipped to true.
The ref was therefore `null` at the moment of assignment, an
`if (videoRef.current)` guard swallowed it, and the element then mounted with no
source. The permission prompt appeared, the officer allowed it, and the
viewfinder stayed black. **Nothing threw and nothing was logged** — the button
was present, enabled and clickable throughout, which is why no test caught it.

The stream is now state and is attached by an effect, which is the only ordering
React guarantees. Four things went in with it:

- a **20 second bound** on `getUserMedia`. The specification puts none on it:
  while a permission prompt is open the promise is simply pending, and if the
  prompt never appears — a policy block, an embedded webview, a prompt opened
  behind another window — it stays pending for ever. That is what a dead button
  looks like.
- a **retry with relaxed constraints** on `OverconstrainedError`, because some
  laptop drivers report it even for `ideal` constraints, and any camera beats
  none.
- **six named diagnoses** instead of one sentence. The one that will actually
  happen is not a camera fault at all: an officer opening the app from a phone at
  `http://192.168.1.x:3000` has no `navigator.mediaDevices` to call, because it
  is only exposed in a secure context. The fix is a URL, and the message now says
  so. `scripts/run_demo.py --https` covers that case.
- **track release on unmount**, so the camera light goes off when the officer
  navigates away.

Three Playwright tests, stubbing `getUserMedia` with a canvas `captureStream` —
a real `MediaStream` with a real video track, because a plain mock object is
rejected by `srcObject` and would test nothing. The load-bearing assertion is
`videoWidth === 640`, which is only non-zero once a frame has decoded from an
attached source.

**And a framing guide on the glass.** Section 18b measured 4.9-11.7 px/mm on the
ruler corpus against a premise of about 24, and the whole of that gap is the
marker card filling the frame instead of the declaration. A dashed rectangle and
one sentence is the cheapest place to fix that — cheaper than any amount of
documentation nobody reads while holding a packet.

### Four more things found by walking the screens

**The masthead was 200 px tall on a phone.** An admin sees eight links; at 390 px
they wrapped onto three rows, so a third of the first screen of a tool whose
primary device is a phone held in a shop was navigation, above the one button the
officer came to press. The links now take their own full-width row and scroll
sideways in it; from `md` up they are inline. One `<nav>` element either way —
rendering the list twice and hiding one puts two identically-named landmarks in
the accessibility tree.

**The current section was not marked anywhere.** Not in the masthead, and not on
the six dashboard tabs — six identical pills, one of which you are already
looking at, on a screen whose whole purpose is slicing the same data six ways.
Now `aria-current="page"` plus weight and ground, not colour alone.

**The dashboard tabs were dropping the filters.** They linked to the bare path,
so moving from Brands to Rules silently reset the district, the category, the
severity and the date range. The layout's own docstring promises the opposite;
it was true of the filter component's state and false of the links beside it.

**`/products` reported zero scans for every SKU.** `scan_count` is bumped by a
Dramatiq task on the low queue, and the seed wrote scan rows directly without
it — so a page headed "most-scanned first" was ordered by a column that was
uniformly zero for all sixteen rows.

### The seed is now off by default

`python scripts/run_demo.py` brings up an **empty** instance; `--seed` fills it.
An empty instance is what a real deployment looks like on its first morning, and
it is the only state in which nothing on screen can be mistaken for a finding.

That change had one trap in it. `demo.seed` created the three sign-ins as well as
the shelf, and the in-memory backend has no migration, no fixture and no
registration route — so turning the seed off would have made the empty instance
not empty but bricked. Account creation is now `seed_accounts`, split out and
unconditional on the memory backend, and `/healthz` reports the two facts
separately: `DEMONSTRATION ACCOUNTS` (three fixed sign-ins with a published
password) and `DEMONSTRATION DATA` (a synthetic shelf). Production still refuses
to boot on that backend at all.

With nothing in it the dashboard used to be five zeroes, two blank chart frames
and an empty queue, which is indistinguishable from a broken one — and the first
person to see that screen is whoever has just installed the thing. `EmptyState`
now tells "nothing scanned yet" apart from "these filters match nothing", because
the next action differs: one is *scan something*, the other is *widen the range*.

### Green

754 Python tests, `ruff` clean, `mypy --strict` clean on `contracts` and `rules`,
`tsc` and `eslint` clean, the production build clean at 28 precached files and
1.16 MB, and **12 Playwright tests** — the nine that existed plus the three new
camera ones.

---

## 2026-09-09 (late) — the originals, and the training path in front of them

### 231 camera originals

Received and ingested by `scripts/ingest_originals.py`, which is a new script
because taking delivery of photographs makes a *provenance claim* — that this
full-resolution frame is the same photograph as that transcoded one, and
supersedes it — and a claim like that belongs in code that can be re-run and
argued with rather than in a drag-and-drop.

| | |
|---|---|
| Unique originals | **231** |
| Devices | LAVA LXX504 ×151 (1840×4096) · Apple iPhone 13 ×80 (4032×3024) |
| EXIF intact | 231 / 231 — make, model, capture time, focal length |
| Transcodes superseded | **221 of 469** |
| **Transcodes still with no original** | **248** |
| Live corpus frames | **479** = 231 millimetre-grade + 248 transcode-only |

The delivery contained a 324 MB zip whose 151 members were byte-identical to
151 of the loose files; the ingest deduplicates by SHA-256, so unpacking it by
hand would have doubled a third of the corpus silently. Of 362 candidate
original↔transcode pairs, 290 matched at dHash distance 0 and the worst was 5 —
a transcode-pair distribution, not a coincidence one. Every distance is kept in
`data/manifest.json` so the tail can be re-examined without re-running.

`data/manifest.json` is also §16's corpus target tracker. A row it cannot count
reports **null**, not a guess: `photos` says 479 against a target of 400 and
`test_split_skus` says 20 against 20, while `curved_surfaces`,
`hindi_or_bilingual` and `non_food` say *unlabelled*, because nothing in the
repository knows whether a surface is curved and a heuristic that guessed would
put a fabricated number under a real measurement. `unmet` and `unknown` are
different states.

### What the resolution actually buys — 40 matched pairs, both through the detector

| | transcode | original | |
|---|---|---|---|
| Linear resolution | 1600 px | 4032–4096 px | **2.56×** |
| Median text line | 33.4 px | **86.7 px** | 2.6× |
| **10th-percentile line** | **17.6 px** | **52.9 px** | **3.0×** |
| Text regions detected | 1,199 | 1,216 | **+1%** |

The last row is the one that matters and it is the one that looks like nothing.
**Detection was never the bottleneck.** A text region is a blob, and a blob
survives a downscale — the detector finds essentially the same regions in both.
What changed is what the *recognition* head is handed. PP-OCR's practical floor
is around 16 px of line height; the bottom decile of every transcoded frame was
at 17.6 px, which is above the cliff with no margin at all for a curved surface,
a glare patch or a fold. That decile is now at 52.9 px.

So what the originals fix is the small print, which is the print Rule 7(2) is
about.

**What they do not fix: U1.** The §18b millimetre error is measured on
`data/test_split/`, and those 40 frames were never transcoded — 3072×3072 with
EXIF intact, and always were. This file already rejected resolution as the
discriminator there: found and not-found overlap almost completely, 22.8 px of
glyph against 19.3 px. That gap is the capture protocol, and no sensor fixes it.

### M4, half two — ROI-only OCR against reading every region

Section 17 asks for *"the ROI path at least 5× faster than full-image on the
same photos"*. Measured on 20 originals, and the interesting part is that the
answer depends on the scale tier:

| detection sized for | input px | regions found | crops read | ROI ms | all ms | saving |
|---|---|---|---|---|---|---|
| tier C, no marker | 640 | 14 | 8 | 510 | 861 | **1.69×** |
| 0.1 mm/px — §18b's own figure | 2048 | 28 | 8 | 559 | 2119 | **3.79×** |

**The 5× criterion is not met — best 3.79× — and the mechanism is worth more
than the number.** The ROI saving is `regions the detector proposes ÷ crops we
choose to read`, and the numerator is set by `detect_text.input_side`, which §8b
derives from the recovered scale. At tier C it returns its 640 px floor, a
4032 px frame is detected at a 6.3× downscale, only fourteen regions survive,
and skipping half of them saves half the time. Give it the scale the marker card
recovers and detection runs at 2048 px, twice as many regions appear, the ROI
path still reads its eight, and the saving more than doubles.

**So the ROI argument is strongest exactly where the pipeline is healthiest, and
weakest at tier C where everything else is weakest too.** That is worth saying
out loud rather than quoting one number: the officer who forgets the marker card
loses the millimetre rules *and* most of the speed argument at the same time.

Reaching 5× needs the numerator above 40 regions per frame, which means either a
larger detector input — and 2119 ms of naive recognition already says what that
costs — or a smaller crop budget, which trades recall for latency. §4's own
pre-registered fallback (line 2021) is the second: *"ROI count to top 4 by
confidence"*. That would put the saving at 7.6× and is a decision to take with a
measured coverage number in hand, not now.

The per-crop cost matches §4: 70 ms per crop against a budget of 290 ms for
four. These runs are CPU-only with no GPU, which `bench/test_vision_latency.py`
already establishes as a pessimistic bound rather than an optimistic one.

The first version of this measurement was worse than wrong. It timed the ROI
path against `recognise.read(whole_frame)` and reported the ROI path as **eight
times slower**. That number was real and meaningless: the recognition head
resizes its input to a fixed 48 px height, so a 4032 px frame becomes a 48 px
smear, costs one cheap forward pass and reads nothing. It is still reported, as
`degenerate_whole_frame_ms`, so the next person to try the obvious comparison is
told why it is not the one to make.

### The training path, written and blocked

Three modules that cannot run until somebody has drawn boxes, and are complete
so that the day somebody does is not also the day the training code gets
written.

**`training/detector/convert.py`** — Label Studio → COCO instance
segmentation. It reads `annotations` and **refuses `predictions`**: the 16,367
regions in `tasks.json` are machine proposals, and a pipeline that trained on
its own guesses would be measuring its own opinion. Run against `tasks.json`
today it correctly reports all 479 tasks as carrying no completed annotation and
exits non-zero. It splits by burst group rather than by frame, so several shots
of one packet cannot straddle the train/val line, and it **raises rather than
skips** if a `data/test_split/` path appears in an export — a sealed-split leak
is a reason to stop, not to filter.

**`training/detector/rtmdet-ins_tiny_akshar.py`** — the mmdet config. What is
written out is only what departs from upstream: mosaic and hflip *removed from
the pipeline* rather than probability-zeroed (mosaic fabricates scenes with four
marker cards; text does not mirror), `RandomResize` narrowed to 0.75–1.25
because scale is the measurement, `filter_empty_gt=False` so §14's ~15% detector
negatives survive the dataloader that would otherwise silently drop exactly
them, and the checkpoint selected on `segm_mAP` rather than `bbox_mAP` because
the PDP mask is what §8b's homography is fitted to. `training/requirements.txt`
now exists — `pyproject.toml` had referenced it for two days.

**`training/classifier/train.py`** — the four-way address head. `FEATURE_DIM`
and `CLASSES` are imported from `vision/classify/`, never restated, and an
assertion fails the run if the built matrix disagrees; §15b's feature skew is
silent and is the ordinary way a working classifier degrades after deployment.
Early stop on validation **macro** F1, not accuracy, because `manufacturer`
appears on nearly every packet and `importer` on a handful. Per-class F1 is
reported and never averaged into one number, and a class with no examples gets a
warning rather than a 0.0 that would quietly drag the macro down.

**`docs/annotation-guide.md`** — seven rules, each written around the specific
way of getting it wrong that it exists to prevent. The load-bearing one is cap
height: a box drawn corner-to-corner round `MRP Rs. 45.00 (incl. of all taxes)`
is 30–40% taller than the cap height *always in the same direction*, so it is
not noise a model averages out — it is a systematic bias that would put every
measurement over the legal minimum and every verdict at PASS.

### The review queue closes

§8b's *"one-click resolve, resolution stored as a labelled example for
retraining"* was a button that posted a correction with a guessed field name,
because the endpoint did not exist. It does now: `POST /scans/{id}/review`, a
`ReviewStore` Protocol with in-memory and SQL implementations, a
`review_resolutions` table, migration `0002`, and `review_queue` taking the
resolved map so a settled rule leaves the list.

Three decisions, not two — `complies`, `does_not_comply`, `recapture`. §8b
issues REVIEW when a measurement lands inside tolerance of a threshold, 1.96 mm
against 2.00 mm, and the honest answer to that is frequently neither verdict but
*photograph it again with the card flat*. Forcing that into a binary would put a
coin-flip into an enforcement record and then feed the coin-flip back into
training as a labelled example.

One question per rule, not per scan: a marginal MRP height and an unreadable net
quantity are two judgements, and the endpoint returns 409 for a rule that never
asked for review. The scan itself is untouched — its verdict still reads REVIEW
afterwards, because it is hashed into the evidence chain and rewriting it would
make `verify_chain` fail at that row, correctly.

**And a bug found on the way in.** `POST /scans/{id}/corrections` returned a 201
receipt reading *"Recorded as a new row; the scan itself is unchanged"* and then
dropped the row. The `corrections` table existed. Nothing wrote to it. §14 rests
its entire retraining argument on those rows being *"a labelled training example
produced by somebody already doing the job"*, and not one had ever been kept.

### Tests: 87 new, and two of them found things

| | |
|---|---|
| `tests/unit/test_check_sweep.py` | **62** — every check type, every status, both sides of every threshold |
| `tests/unit/test_contracts.py` | **13** — API responses against the types the browser was compiled with |
| `tests/golden/` | **12** — ten drawn scenes plus the listing-text channel plus a meta-test |
| `tests/unit/test_api.py` | **+8** — review resolution, and the correction that is now stored |

**The check sweep** goes at the thirteen check functions directly, where
`test_engine.py` goes through the rulepack. Three of the thirteen —
`min_width_ratio`, `clear_space`, `min_contrast` — are exercised by exactly one
rule each, and those are the ones §13 calls *"the rules only this architecture
can check"*. They were one YAML edit away from having no test at all.

Writing it corrected three of my own assumptions rather than the code's: `0.1 kg`
is non-compliant (arm 2 of `value_in_range` requires grams below a kilogram, so
the "lower bound passes" case needed `0.1 g`); `min_contrast` has a ±0.2 REVIEW
band of its own, mirroring the millimetre one; and `present` failing with
`found=None` is right, because the absence *is* the finding. The invariant was
narrowed to say so rather than the check changed.

**The contract tests** close a gap `web/src/lib/api/types.ts` documents in its
own header — the dashboard routes return `dict[str, Any]` and the browser's idea
of their shape is hand-written, so *"nothing will tell us automatically"*. This
parses the TypeScript and compares key sets in both directions against the real
analytics functions. The regression it would have caught has already happened
once: `TrendPoint.rate` declared against a payload saying
`non_compliance_rate`, which drew an empty chart grid and looked like *no data*.

It also found a live gap on its first run: `POST /scans/bulk` publishes its
schema under 202, not 200, so a naive check reported the one correctly
asynchronous endpoint in the API as broken. The test looks at any 2xx now.

**The golden files** are drawn, not photographed, because *fixed* has to mean
the same bytes on a CI runner that has none of the corpus. The scenes are §14's
traps: a promotional graphic printed larger than the real MRP, a batch code
reading `24MRP07`, a drained weight beside a net weight. The snapshots record
what the pipeline currently believes, warts included — `MRP Rs. 45.00` comes back
as `MeP R8 450` and classified `other`, and `NET WT 250 g` is script-detected as
Devanagari. Both are now pinned, so the day either changes, somebody has to say
why.

### Benchmarks, §4's table as it now stands

| | |
|---|---|
| Scale | 70 → **55 ms** (ArUco corners are cheaper than the coin-ellipse fit they replaced) |
| **B1 capture gate** | **11.5 ms** measured, against §18b M0's 15 ms |
| WASM cache miss | enforced against 2000 − 895 ms of budgeted model time |

The WASM row is the one that needed thought, because the model stages are not in
the process. §4's exit-two total decomposes into 141 ms identical on both
backends (B1 8 + pHash 18 + rectify 55 + scale 55 + rules 5) and 420 ms of model
time on WebGPU that becomes 895 ms on WASM. The deterministic share is measured
through `scan()` as one composition rather than five timings added up — the
stages hand each other images, and a change that makes `rectify` return a copy
instead of a view costs real milliseconds no per-stage benchmark would see — and
asserted against the ceiling minus the budgeted model time. A separate test
re-derives both constants from §4's table, because the scale row already moved
once and a hand-derived constant that rots takes the ceiling with it.

### The advisory false-positive count — and the bug it found

§18 asks for a false-positive count on the advisory checks, with the reason
attached: they fire often by design, and an unmeasured advisory block is how a
tool loses an officer's trust. `scripts/advisory_false_positives.py` runs the
pipeline over the corpus originals, counts every advisory FAIL by rule, and
**prints the exact string that triggered each one** — because the number that
matters is not how many advisories were raised but how many were the packet's
fault, and only a person looking at the pack can answer that.

**Before, on 40 frames** (35 produced a `DeclarationSet`):

| rule | FAIL | PASS | rate |
|---|---|---|---|
| `LMPC.UNIT.SYMBOL_SPACE` | 7 | 28 | 20% |
| `LMPC.UNIT.SYMBOL_CASE` | 4 | 31 | 11% |
| `LMPC.NUM.DIGIT_FORM` | 2 | 33 | 6% |
| `LMPC.UNIT.SYMBOL_PLURAL` | 0 | 35 | 0% |
| `LMPC.UNIT.SYMBOL_STOP` | 0 | 35 | 0% |

13 findings over 35 frames, 0.37 per frame. **Then the strings:**

```
LMPC.UNIT.SYMBOL_CASE   'G'    'M'    'M'    'M'
LMPC.UNIT.SYMBOL_SPACE  '0g'   '2g'   '0g, 0mg, 3g, 5g, 9g'   '6g'   '5g'
LMPC.NUM.DIGIT_FORM     '३'    '१, ४'
```

**Eleven of the thirteen had no classified net quantity at all.** `SYMBOL_CASE`
fired on a bare `G` and three bare `M`s lifted out of unrelated words.
`SYMBOL_SPACE` fired on `16g` from a nutrition panel's serving size and on `0g`
fragments. `DIGIT_FORM` fired on Devanagari numerals printed in lawful Hindi
body text.

Every one is a false positive, and they share one cause: `regex_absent` and
`symbol_case` both fell back to `ds.raw_text` through `strict_text` when the
classifier had not identified the field the rule names. That fallback is right
for `regex` — a *format* rule still wants to judge whatever MRP-shaped text is
on the pack — and wrong here, because both of these ask *"does this appear
**inside this declaration**"* and a label is covered in text that is not that
declaration.

`symbol_case` is its own check type rather than a `regex_absent` rule, so the
first pass at the fix missed it and it kept firing on the four bare capitals.
Re-running the measurement is what caught that; reasoning about the fix would
not have.

**The advisories are how it was found; they are not where it mattered most.**
Three of the eight are not advisory: `LMPC.QTY.BANNED_WORDS` (Rule 12(6)),
`LMPC.QTY.BANNED_UNITS` (Rule 13(4)) and `LMPC.QTY.WHEN_PACKED` (Rule 11(4)).
The last of those would have reported a packet as declaring its quantity at the
time of packing because the words "when packed" appeared *somewhere* on the
label. That is a real allegation against a manufacturer, made from a string in
the wrong place.

`regex_absent` now returns **NO_DATA** when the field it targets was not read.
§8b, applied where it was being violated: absence of evidence is not evidence of
a violation, and we did not read the net quantity declaration, so we cannot say
what is or is not printed inside it. `scope: label` is the opt-in for a rule
that genuinely means "nowhere on the pack"; **no shipped rule sets it**, and
`test_no_shipped_rule_opts_into_the_whole_label_search` fails if one ever does.

**After the fix, same 40 frames:**

| rule | FAIL | PASS | NO_DATA |
|---|---|---|---|
| `LMPC.UNIT.SYMBOL_SPACE` | **2** | 1 | 32 |
| `LMPC.UNIT.SYMBOL_CASE` | 0 | 3 | 32 |
| `LMPC.NUM.DIGIT_FORM` | 0 | 6 | 29 |
| `LMPC.UNIT.SYMBOL_PLURAL` | 0 | 3 | 32 |
| `LMPC.UNIT.SYMBOL_STOP` | 0 | 3 | 32 |

**13 findings became 2. 0.37 per frame became 0.06.** And both survivors are
inside a declaration that was actually read, which is the only place these rules
can honestly speak:

```
'6g'  <- 'NTRTONAL INFORMATION Qty.(pprox.) evesize 16g'   conf 0.854
'5g'  <- 'Net Weight: 103.5g'                              conf 0.971
```

The second is a **true positive**: `103.5g` has no space, and NS Third Schedule
item 7(1)(d) requires one. The first is a nutrition panel's serving size that
the classifier labelled `net_quantity` — a real defect, but now it is a
*classifier* defect showing up where a classifier defect belongs, rather than a
rule reading the wrong part of the label. That relocation is the whole value of
the fix.

**What this does not settle.** 32 of the 35 frames read no net quantity at all,
so most of these rules now correctly say NO_DATA rather than correctly say PASS.
The advisory block is quiet because the classifier is quiet, and the second of
those is the real problem — the same one MRP coverage has. When classification
improves, this measurement must be re-run, and the count will go up for good
reasons as well as bad ones.

---

## 2026-09-09 (night) — six false accusations in one scan, and the PDF that would not open

Two defects found by the user scanning a real packet through the running app,
which is the only test that had not been run.

### One: the pack declared everything, and we said it declared nothing

An ITC Dark Fantasy Yumfills 242 g pack, photographed hand-held without the
marker card. The report came back **Non-compliant** with six FAILs:

| | |
|---|---|
| Retail sale price not declared | Rule 6(1)(e), **high** |
| Net quantity not declared | Rule 6(1)(c), **high** |
| Name and address of manufacturer not declared | Rule 6(1)(a), **high** |
| Common or generic name not declared | Rule 6(1)(b) |
| Month and year of manufacture not declared | Rule 6(1)(d) |
| Consumer care details | Rule 6(2) |

**The pack carries every one of them.** They are legible in the photograph. What
the recogniser returned was:

```
'METAWEIHT: 2429'   <- NET WEIGHT: 242 g
'MARKETED BY T'     <- MARKETED BY ITC LIMITED
'MFD.BY:ITC'        'wYVNOvr 9I'   'DCLA'   'A EA'   'CFRO'   'GE'
```

Nothing was missing from the package. The label had not been read, and every
one of those six lines is an allegation against a manufacturer generated by our
own failure to read.

**Why it reached the rules engine as a verdict.** The scan was reported L2, not
L3, because `coverage` was 0.80 against a 0.60 floor — and `coverage` is the
fraction of proposed regions the recogniser was *run on*, not a measure of
whether anything came back. We run it on nearly everything we propose, so it
sits near 1.0 whatever the output.

**Three cheaper signals were measured before settling on one**, over fourteen
frames:

| signal | on a frame of pure noise | on frames that read well | separates? |
|---|---|---|---|
| `coverage` | **1.00** | 0.72–0.97 | no |
| median recogniser confidence | **0.995** | 0.50–0.90 | no, inverted |
| word-shape fraction | 0.67 | 0.51–0.89 | no |

CTC confidence is the worst of the three: it scored three lines of pure noise at
0.995. It is confidently wrong, which is exactly what §8's *"blur destroys the
evidence before the confidence is computed"* predicts.

**What does separate them is the question the check is actually asking.** A
retail package carries all six of Rule 6(1)'s declarations — that is what makes
them mandatory. So the test is how many of the six we managed to identify:

| frame | mandatory declarations identified |
|---|---|
| `bodywash_bottle_300ml` | 4 |
| `IMG_0686` | 4 |
| `dark_fantasy_yumfills_242g` | 2 |
| `IMG_0679` | 1 |
| six others | **0** |

A second signal was added to the degradation ladder at the same time —
`vision.degradation.legible_fraction`, the share of read lines carrying
word-shaped text — and it is worth recording that **it currently fires on
nothing**. Across those fourteen frames it scored 0.51 to 0.89 against a 0.50
floor, including the pure-noise frame, because a garbled line still contains
three-letter fragments. It is a second independent route to L3 for a failure
mode this corpus has not yet produced, and lowering the floor until it fired on
a chosen photograph would be fitting to a sealed split.
`test_the_legibility_floor_currently_fires_on_nothing_in_the_corpus` asserts
that and fails if a future recogniser change makes it live, so the note is
re-read rather than discovered during a demonstration.

`rules/checks/_common.reading_supports_an_absence` is what actually withholds
the false accusations. It refuses a presence FAIL when fewer than half the
mandatory declarations were located, and at L3/L4 regardless — §5 confines L3 to *"verdicts on what was read"*, and a missing
declaration is a verdict on what was **not**. The denominator is read out of the
rulepack rather than listed in the check, so it cannot drift from the rules being
evaluated.

Half is a round number, stated rather than fitted. `data/test_split/` is sealed
and a threshold chosen to make a particular photograph pass is precisely the
fitting that seal exists to prevent.

**Effect, same frames:**

| frame | non-advisory FAILs before | after |
|---|---|---|
| `dark_fantasy_yumfills_242g` | 6 | **1** |
| `coariander_powder_11g` | 7 | **1** |
| `dettol_sanitiser_52ml` | 7 | **0** |
| `diet_coke_can_330ml` | 7 | **0** |
| `IMG_0679` | 8 | **3** |
| `IMG_0680` | 7 | **0** |
| **`bodywash_bottle_300ml`** | **6** | **6** |

The last row is the one that proves this is not a switch-off. `bodywash`
identified four of the six, so it read the label, so its remaining absences are
findings and they still fire. And the one surviving finding on the demo pack is
`LMPC.DATE.FORMAT` — a *format* judgement on a date we actually read, which is
the only kind of thing a partly-read label can honestly support.

**What this does not fix.** The reading itself. Most frames still identify zero
or one declaration, `RESULTS.md` already records MRP coverage below the 0.90
bar, and `detector weights unavailable; geometry-only region proposal` appears
on every frame because RTMDet has never been trained — §16's P9 row. The scans
now say *"this label was not read well enough to say anything is missing"*,
which is true, and it is a far better thing to say in front of a judge than six
fabricated contraventions. It is not a working measurement.

### Two: the PDF was a JSON file with a .pdf name

`GET /scans/{id}/report?format=pdf` answered `202 {"status": "rendering"}`
whenever no worker had already rendered one — and the demonstration stack has no
worker. The scan page offers the report as
`<a href=... download="scan-<id>.pdf">`, and **a browser following a `download`
link saves whatever comes back under that name**, whatever its status or content
type. Thirty bytes of JSON arrived on the officer's disk called `scan-<id>.pdf`.

The dashboard's summary export had the same shape with a different cause: it
returned `503` when WeasyPrint could not load, saved as
`violation-summary.pdf`.

WeasyPrint needs Pango, cairo and harfbuzz. `docker/api.Dockerfile` installs
them; a Windows machine without the GTK runtime cannot import it at all —
`cannot load library 'gobject-2.0-0'`.

Both routes now always return a PDF:

- `reports/pdf_fallback.py`, pure Python via `fpdf2`, carrying the same content
  as the DOCX and saying on the page that it is the fallback so two AKSHAR
  reports that look different can be told apart;
- `_pdf_response` renders inline when nothing is stored, and still enqueues the
  warm-up so the next request gets the cheap path. A slow response is a smaller
  problem than a corrupt file.

The fallback looks for a Unicode TrueType face and, finding none, transliterates
to latin-1 **and says so in the document** — `₹` becomes `Rs.` rather than being
dropped, and anything else outside latin-1 is marked rather than deleted. A
report that has lost the Hindi must admit it. DOCX was never affected: it was
already returning a valid 38 KB zip.

Four route tests now assert the magic bytes of all three formats rather than the
status code, because `200` with a JSON body would pass a status check and still
be the bug.

---

## 2026-09-10 — why nothing was being classified, measured four ways

The user's complaint was blunt and correct: the previous night's work made the
system *honest* about failing without making it read any better. This is the
attempt to find the actual wall, by measurement rather than by argument.

The symptom, from a real scan: **4.6% of read lines were assigned a field.**
Across 33 frames, 716 lines read, 33 classified. A retail back panel carries
eight to twelve declarations, so we should have found two to three hundred.

### Candidate one: the pattern list — real, and much smaller than it looked

Hand-checked against phrasings printed on real Indian packaging:

| printed on the pack | classified as |
|---|---|
| `Retail Sale Price Rs 20` | **other** |
| `MFD.BY:ITC LIMITED` | **other** |
| `Mfd. By: Britannia` | **other** |
| `FOR FEEDBACK/COMPLAINT CONTACT:` | **other** |
| `UBD: 13 APR 2027` | **other** |
| `MFD:14 AUG 2026` | **other** |
| `MADEININDIA` | **other** |
| **`MFG BY ABC Foods`** | **`mfg_date`** |

The first is the worst: `retail sale price` is **Rule 2(m)'s own term**, and
`mrp_locate` could not match it — the alternation read `max(imum)? retail price`
and the printed phrase has `sale` in the middle. A pack declaring its MRP in the
exact words of the rule was reported as declaring none.

The last is not a gap but a **bug**: `MFG BY <company>` classified as a *date* at
0.88 confidence, because `mfg` matched `mfg_date_locate` before
`manufacturer_locate` was ever consulted — a company name handed to a
date-format check. Fixed with a negative lookahead: `MFG BY` names a
manufacturer, `MFG:` introduces a date, and the word after decides.

Two of the fixes had to be made twice, which is worth recording because both
failures were the same shape. Widening `made\s*in\b` to `made\s*in\s*[a-z]` made
`MADEININDIA` match and broke `MADE IN INDIA`, because the single `[a-z]`
consumed one letter and the trailing `\b` then landed *inside* the country name.
And `(complaint|...|feedb)` followed by `(?![A-Za-z0-9])` could never match
`Complaints` or `Feedback` — the lookahead forbade the rest of the word it had
just matched. A trailing boundary assertion after a widened alternation is a
trap; both are now `\w*`-terminated.

Result on hand-checked phrasings: **16 → 24 of 25**. The twenty-fifth is
`DRAINED WT 350 g` returning `other`, which is correct — §14's hard-negative
table requires exactly that, and the test expectation was wrong. `Rs. 20 OFF`
still returns `marketing_text` and `BATCH 24MRP07` still returns `batch`.

**But the corpus says this was not the main lever.** Harvesting the 716 read
lines for text that *looks* like a declaration and matched nothing found only
**10 lines, 1.4%** — and most were OCR damage rather than phrasing:
`'MADEININDIA'`, `'CUSTOMERCAN0:'`, `'MRPUSP  (Perg)'`, `'Cuslomer Care'`.

### Candidate two: the detector's input size — the real lever, and it was backwards

`detect_text.input_side` returned the 640 px floor whenever no scale had been
recovered, on the reasoning that with no millimetre there is nothing to derive
from. The reasoning is sound and the conclusion was inverted: a 4032 px
photograph was detected at a **6.3× downscale**, so the 1 mm print Rule 7(2)
exists to measure fell below a pixel — never proposed, so never read, so never
classified. Not knowing how small the print is, is a reason to keep resolution.

Fifteen corpus frames, same recogniser, same patterns, only the input size
changing:

| detector input | detect ms | regions | lines read | declarations found |
|---|---|---|---|---|
| 640 px (old tier C) | 21.7 | 14 | 326 | 15 |
| 2048 px | 225.2 | 42 | 562 | **23** |

**And the two changes compound in one direction only:**

| | 640 px | 2048 px |
|---|---|---|
| old patterns | 15 | 19 |
| new patterns | **15** | **23** |

The pattern fixes bought **nothing** at 640 px. You can only match text you
actually read. Resolution first, patterns second — together **15 → 23, +53%**.

**The latency is affordable for a stated reason.** §4 budgets 110 ms for
detection and 225 ms breaks it. Tier C is precisely the state in which the three
`min_height_mm` rules already return NO_DATA, so that budget is protecting a
measurement which is not being taken; what is scarce at tier C is recall. §4's
own pre-registered lever moves the other way for the other case — *"detector
input to 512 px"* when latency blows — and this is its mirror. The frame's own
long side is the ceiling, clamped into `[640, 2048]`, so a small photograph is
never upscaled into detail it does not contain.

### Candidate three: framing — helps where the pack is small, and only there

Two-pass detection (find the text, crop to it, detect again inside the crop):

| frame | text crop as share of frame | lines before → after |
|---|---|---|
| `IMG_0680` | 20% | 9 → **58** |
| `IMG_0679` | 21% | 46 → 62 |
| `coariander_powder_11g` | 96% | 23 → 30 |
| `dark_fantasy_yumfills_242g` | 75% | 53 → 55 |

It is a large win exactly when the pack is small in frame and nothing at all
when it already fills it — which is the capture-protocol observation §18b made
about px/mm, arriving from a second direction. Not shipped: a blind
union-of-text crop also lost a declaration on `IMG_0679`, so this belongs behind
the trained package detector rather than a heuristic.

### What none of it fixes

**~1.5 declarations found per frame, against eight to twelve printed.** The
remaining loss is not the pattern list and not the input size. It is the
recogniser turning `NET WEIGHT: 242 g` into `'METAWEIHT: 2429'`, `MRP RS.` into
`'MPEE'`, and much of a back panel into `'wYVNOvr 9I'`, `'DCLA'`, `'A EA'`.

That is §14's M4, in the order §14 states it: *record baseline CER by surface
type, fine-tune only what fails, recognition head only, CTC.*
`training/ocr/baseline.py` is written and waiting on transcriptions. And B2 has
never been trained at all — `detector weights unavailable; geometry-only region
proposal` appears on every frame in every run above, which is also why
*"Declarations on the display panel"* is permanently NO_DATA.

Both need annotation. That is not a deflection; it is what the measurement says.

### A note on the dataset offered for training

43 photographs were supplied as a labelled set. The photographs are excellent —
flat-on, sharp, label filling the frame, which is the capture protocol this
project has been asking for. **They cannot be trained on**, for four reasons
found by running the pipeline over them:

1. The annotations are **rendered into the pixels** as coloured boxes with text
   tags. There is no coordinate file.
2. The tags **occlude the declarations**, and the OCR reads them: the pipeline
   returned `'Produet Name'`, `'Net Quantity'`, `'Veg Symbol'`, `'Lot Number'`
   and assigned `mfg_date` from a tag reading `'Date of Packing'`. Training on
   these would teach the model that the words "Net Quantity" in a green box *are*
   the net quantity declaration.
3. The taxonomy is inconsistent between images and is not
   `contracts.FieldName` — one frame carries 13 classes, another 12 different
   ones including `Decorative Element` and `Product Image / Visual`. One boxes
   MRP, USP, Mfg Date and Contents as a single `Product Details` region, which
   makes Rule 7(2)'s numeral-height measurement impossible.
4. At least one frame is rotated 180°.

What is needed is the same 43 photographs **without the overlay**, plus the
annotations as a file.

---

## 2026-09-10 (later) — the verdicts we were not entitled to reach

A real scan came back **Non-compliant** with a page of findings, and the boxes
drawn on the pack were captioned `other` almost without exception. Both
complaints were correct. Neither had a single cause, so this is what each one
turned out to be, in the order the evidence forced.

### The overlay: 50 captioned boxes, 48 of them saying nothing

`evidence/annotate.py` drew a full coloured box with a caption for **every**
declaration in the set, and `vision/classify/assemble.py` puts every recognised
line into that set — including the ones it declined to name. On an Amul ghee
tin that is 50 boxes reading "Unclassified text" over the nutrition table, the
storage instructions and several single characters the recogniser invented,
with the two that carry the verdict buried among them.

The module docstring already had the answer — *an unlabelled rectangle is
better than a mislabelled one* — so unnamed text is now drawn as a thin grey
outline and never captioned. It stays on the exhibit, because how much of the
panel we read is part of the record, but it is drawn as context rather than as
a finding. Same frame, after: **2 captioned, 48 outlined.**

### The verdict: what a photograph entitles you to say

75 FAILs across 52 corpus frames. Sorted by cause rather than by rule, four
distinct defects, each measured before it was touched.

**1. Format checks judged our OCR, not the printer.** 25 of the 75 — the single
largest source. Two separate faults inside that:

*Locate and validate read different evidence.* `locate` searches the whole
label; `strict_text` searches only the lines classified into the field. A
declaration split across two regions was located on the label and then judged
on the fragment:

| judged | on the label |
|---|---|
| `'MFD*'` | `06/2026` |
| `'Mfd.& Aktd. by:'` | `05-2026` |
| `'Mfg. Month & Year'` | `09/2025` |

Three frames failed for a malformed date we had read correctly. The strict
pattern is now retried against the same text `locate` succeeded on.

*And the remaining 22 were about print, decided from OCR.* Format rules ask how
something is **printed** — case, spacing, separators. The same corpus read
`Serving size` as `'Servingsize'`, `For C.A. No.` as `'ForCA. No.'`, and
`MFG. BY PERFETTI VAN MELLE INDIA PVT LTD` as `'MFG.BYPERFETI VAN
MFIEINDIAPVTITDBTMT'`. Per-declaration OCR confidence was tested as a gate and
does not separate the populations:

| | n | min | median | max |
|---|---|---|---|---|
| format FAIL | 27 | 0.47 | 0.84 | 1.00 |
| format PASS | 5 | 0.75 | 0.96 | 0.97 |

The same answer CTC confidence gave on the noise frame. A threshold drawn
through that overlap would be a fudge, so on a channel we recognised ourselves
a format mismatch is now **REVIEW**: kept, listed with the text we read, amber,
routed to a human. On `listing_text` there is no recogniser in the way and it
is still FAIL — section 8's wall paying for itself.

**2. The contrast estimator was miscalibrated by up to 35%.** `min_contrast`
took the *mean* luminance of the binarised ink and of the background ring. At
the pixel sizes a 1 mm character occupies in a shop photograph both samples are
dominated by the anti-aliased edge, so the ink mean is pulled toward the paper
and the ring mean toward the ink. Measured against published WCAG values:

| ink/paper | true | measured | error |
|---|---|---|---|
| 0/255 | 21.00 | 13.66 | −35% |
| 60/255 | 11.03 | 7.49 | −32% |
| 110/255 | 5.10 | 4.02 | −21% |
| 150/255 | 2.96 | 2.56 | −13% |

On 1178 corpus declarations it never exceeded **10.35** and put **68% below the
3.0 threshold** — two thirds of all printed matter on legible retail packaging
reported illegible under Rule 9(1)(b). Sampling the ink and paper *colours*
(20th/80th percentiles) instead of averaging a blurred mask returns the
published value exactly, and the corpus distribution moves to median 3.78,
max 16.47, 63.6% above threshold. `LMPC.CONTRAST.NUMERALS`: **10 → 6**.

**3. The rulepack contradicted itself about the litre.**
`LMPC.UNIT.LITRE_SYMBOL` ships `enabled: false` — the gazette gives `l`, BIPM
accepts `L`. `LMPC.UNIT.SYMBOL_CASE` reached the same symbol through its own
lower-case list and failed `Net Content: 1L (905 g)` anyway. A rule switched
off has to stay off however it is reached; the decision now lives in one table.

**4. Advisory findings carried the red headline.** `api/analytics.py` excludes
`advisory: true` from every published violation count; `rules.engine.is_compliant`
and the web's `overallStatus` did not. The same scan could read "Non-compliant"
on screen and sit outside the violation tables on the dashboard. No corpus
frame was carried into non-compliance by advisories alone on the day this was
found — it would have started mattering on the first clean pack.

### The locate patterns: phrasings we could not match

A declaration whose phrasing no pattern matches is a declaration reported
**absent**. Nine were found by sweeping phrasings printed on real packs:

| printed | was | now |
|---|---|---|
| `Date of Packaging: 02/07/2026` | other | `mfg_date` |
| `Packaging Date: 02/2026` | other | `mfg_date` |
| `Date of Import: 07/2026` | other | `mfg_date` |
| `Month & Year of Manufacture` | `manufacturer` | `mfg_date` |
| `NAME OF COMMODITY:` | other | `generic_name` |
| `In case of any complaint, contact:` | other | `consumer_care` |
| `REACH US:` | `manufacturer` | `consumer_care` |
| `B.NO.:` | other | `batch` |
| `Manufactured & Packed by:` | `packer` | `manufacturer` |

`Date of Packaging` is the one that matters most: it is on a very large share
of Indian food packs, `mfg_date_locate` read `date\s*of\s*(mfg|packing)`, and
*packaging* is not *packing*. Rule 6(1)(d) was reported undeclared against
packs declaring it plainly. Hand-checked sweep: **41/51 → 50/51**.

The 51st is `Product Name: Dark Fantasy Yumfills`, deliberately left as `other`.
That introduces the **brand**; Rule 6(1)(b) requires the **generic** name. A
locate pattern may be too narrow — that costs a false accusation we can see and
fix — but not too wide, which costs a violation nobody ever hears about.

`generic_name` also turned out to have **two** definitions: a local copy in
`vision/classify/regex_tier.py` reading `(common|generic) name` while the pack
had grown `Name of Commodity`. The engine reported the declaration present and
the extractor classified the line `other`, so the report showed no such
declaration on a pack that had one. That is precisely the divergence the
module's own docstring forbids; the local copy is gone.

### Rule 8(1) proviso: an `s` is not printed information

The net quantity exclusion zone was reporting `13 intrusion(s): 14; s; a`.
B2 has no trained weights — every scan logs `geometry-only region proposal` —
so a good number of the boxes it proposes are one character of nothing. Two
fixes: an intruder must look like a word or a number, and a declaration's own
label (demoted to `other` by `vision.classify.associate` after being joined to
its figure) is no longer counted as crowding the declaration it belongs to.
What survives is real printed matter — `NO ARTIFICIAL COLOURS`, `STORE IN A
COOL DRY PLACE` — sitting inside the zone, which is the finding the proviso
exists for.

### Rule 7(2) is a floor, and always was

Asked directly, so it is now asserted directly. A 5 g pack requires 1 mm:

| MRP numerals | verdict |
|---|---|
| 0.4 mm | FAIL |
| 0.9 mm | REVIEW — inside our own 0.15 mm error |
| 1.0 mm | PASS |
| 3.0 mm | PASS |
| 12.0 mm | PASS |

And the band follows the declared quantity, not the pack: the same 3 mm numeral
is lawful at 5 g and at 300 g and unlawful at 900 g. Guarded by
`tests/unit/test_false_accusations.py`.

### Where it lands

| | before | after |
|---|---|---|
| frames reported non-compliant | 21 / 52 | **16 / 52** |
| total FAIL | 75 | **48** |
| total REVIEW | — | 28 |

Nothing was hidden to get there: 27 of the 28 REVIEWs are the format findings,
still listed with the text we read.

### What none of it fixes, again

**6.1% of read regions carry a field name.** On the Amul tin the exhibit shows
neat outlines over `Marketed by: Gujarat Co-operative Milk Marketing Federation
Ltd.` and `Contact our Customer Care Executive at: 1800 258 3333` — and the
recogniser returned `'Jssad'`, `'GCM Ld.Anand-38001'`, `'CATNECOMWEN'` and
`'.coop'`. The regions were found, the crops were read, and nothing came back.

The classifier is now right about text it is given. It is not being given the
text. That is section 14's M4 and the never-trained B2, both waiting on
annotation.

---

## 2026-09-10 (later still) — 122 photographs, and where the report is wrong

A second batch of photographs arrived at `dataset034_withoutlabelboxes`, this
time without the annotation overlay burned into them. What follows is what they
turned out to be, what they let us measure that we could not measure before, and
the six defects that came out of it.

### What the batch is

| | |
|---|---|
| files | 122 |
| already in `data/corpus/images` (dHash ≤ 6) | **119** |
| genuinely new frames | 3 |
| resolution | 1600x1200 or smaller; 84 of 122 at exactly 1600x1200 |
| EXIF | stripped on every file |
| median file size | 185 KB |
| matching frames in `data/corpus/originals` | **0** |

Every marker of a messaging transcode, and the same grade as the 248 frames
`data/manifest.json` already counts as `transcode_only`. So the batch does not
raise the capture quality; what it does give us, for the first time, is 122
clean frames with nothing drawn on top — which is what an annotation set and an
honest end-to-end measurement both need.

### Reading: three hypotheses, all three wrong

**The recognition head is not the bottleneck.** Section 15b asks for a benchmark
before a second head is shipped — *"benchmark whether a second English-only head
earns its bundle size; do not assume it"* — so it was run. Same crops from our
own detector, our PP-OCRv5 Devanagari head against PP-OCRv4's Chinese/English
head (6,623 characters, English-heavy), on the Kissan jam bottle:

| ours (v5 devanagari) | theirs (v4 ch) |
|---|---|
| `'MDSTAN UNLIVPUTD (HUL)'` | `'STANUWU'` |
| `'SAFOEMAALCUNT'` | `'FOELEUNT'` |
| `'TAME POSTRAIVEST CARE'` | `'TANEPETHARVESTCAR'` |
| `'BADTN FSTOUAACTER OF'` | `'ENTNIDHARACIR'` |

Not better; on the long lines, worse. Running RapidOCR's **whole** pipeline on
the same photograph — its own DBNet, its own recogniser, its own tuned
post-processing — found **18 regions against our 33** and read them no better.
A second Latin head does not earn its bundle size on this evidence. Section
15b's question is answered, and the answer is no.

**Nor is it the crops.** The proposals do carry slivers of the lines above and
below, so six lines of the declaration block were cut out by hand at their true
extent and read in isolation:

| printed | read from a hand-cut single line |
|---|---|
| `MKTD. BY: HINDUSTAN UNILEVER LTD. (HUL),` | `'ADSIANUNLIVLID NUL'` |
| `MAHARASHTRA. FOR MFR. & PKG. UNIT` | `'TAFOMAALGUNIT'` |
| `ADDRESS, READ THE FIRST CHARACTER OF` | `'NTEADTNEENSTCHARACTERD'` |

Upscaling 3x with Lanczos changed nothing, as it cannot: interpolation adds no
information. Across 30 frames the proposal boxes are **1.00x the height of the
ink they contain** (p75 1.11x) and only **7% of vertically stacked pairs
overlap** at all. The boxes are not inflated. That declaration is ~11 px of cap
height in a re-compressed JPEG, and it is not recoverable by any of these three
levers.

That is worth stating plainly because it bounds the rest: **on the frames where
the statutory print is small, no software change in this repository will read
it.** What the batch is good for is everything above the recogniser — and that
turned out to be where the false report actually lives.

### Classification, measured with no OCR at all

Six declaration panels were transcribed by eye from the photographs, exactly as
printed, and handed straight to the classifier. If a declaration cannot be named
when the characters are given perfectly, the camera is not the problem.

**26 of 34 required declarations were named.** The eight that were not:

| printed | was | should be |
|---|---|---|
| `TOLL FREE 1800-103-1644` | `marketing_text` | `consumer_care` |
| `TOLL FREE NO.1800 121 0511 OR E-MAIL` | `marketing_text` | `consumer_care` |
| `BATCH No., MFD. & USE BY : SEE BELOW` | `expiry_date` | `batch` |
| `Batch No., Mfd. & Use By Date:` | `expiry_date` | `batch` |
| `For Consumer complaints, Write (indicating Batch No. and Mfg date)` | `mfg_date` | `consumer_care` |
| `Commodity :  Toy` | other | `generic_name` |
| `DATE OF PKG.:` | other | `mfg_date` |
| `Regd. Office & Consumer Cell:` | other | `consumer_care` |
| `Manufacturing Address of PL:` | `mfg_date` | `manufacturer` |

**`TOLL FREE` is the one that matters most.** `_PROMOTIONAL` listed a bare
`\bfree\b`, and it is a *hard negative* — tested before any field pattern, with
nothing downstream able to recover from it. Rule 6(2) makes a consumer-care
contact mandatory and the overwhelmingly common way an Indian pack prints one is
a toll-free number, so the declaration was not mis-ranked, it was deleted. The
same word sits in `SUGAR FREE`, `GLUTEN FREE`, `GUILT FREE`; `extra` sits in
`EXTRA VIRGIN`. Promotion is now recognised by the forms that are actually
promotional, and `50% EXTRA FREE` and `BUY 1 GET 1 FREE` still are.

**And `_PRIORITY` was answering a different question than packaging asks.**
Rank alone gave both combined labels to `expiry_date` because that entry sits
higher, so Rule 6(1)(c)'s batch number was reported undeclared on a pack whose
first printed word is BATCH; and it let two words at the end of a sentence
outrank the label the sentence opens with. Where a line is set, the declaration
is introduced by its own label and the label comes first. **Resolution is now
leftmost-match, with rank breaking a tie** — which is exactly where every reason
written into `_PRIORITY` still applies: `Packed by`, `Imported by` and
`Manufactured by` all resolve at offset zero, unchanged.

After the nine pattern and resolution fixes: **33 of 34.** The one remaining is
`Marketed by`, which has no field of its own — `FieldName` carries manufacturer,
packer and importer and no `marketer` — so it is recorded under `manufacturer`,
as `manufacturer_locate` has always intended. That is a modelling limit, not a
defect, and `tests/unit/test_declaration_naming.py` says so rather than
tolerating it quietly.

### And it barely moved the verdicts

Over all 122 frames, before and after those nine fixes:

| | before | after |
|---|---|---|
| frames reported non-compliant | 39 / 121 | 40 / 121 |
| blocking FAIL | 101 | 100 |

**The engine does not read the classifier's fields.** `locate` searches
`searchable_text`, which is the field lines *plus the whole label*, so a
presence check never depended on the caption. The classification work fixes the
exhibit — the boxes an officer reads — and almost nothing else. That is worth
knowing before anyone spends another day on patterns.

So the false report was found by reading the findings themselves.

### Four defects in the rules layer

**1. A country of origin was read as evidence of import.**
`LMPC.IMPORTER.PRESENT` was conditioned on `{field: country_of_origin, present:
true}` — *any* country of origin. Seven frames raised a high-severity finding
that no importer was named; four of them print `PRODUCT OF INDIA` or `MADE IN
INDIA` on the face of the pack and one is a Mattel carton reading `Country of
Origin : INDIA` directly above the declaration column. Declaring where a thing
was made is not declaring that it was brought in. The condition now carries
`text_excludes_ref: domestic_origin`; `also_when_context: is_imported` still
overrides it, because a pack can be imported and silent about it and the officer
knows more than the label does. **7 -> 2**, and the two remaining are foreign.

**2. One mis-read character removed a mandatory declaration.**
A Mattel carton prints `Maximum Retail Price: ₹ 149.00` in the largest type on
the panel. The recogniser read it, at **0.93 confidence**, as:

    'Maximum Retai Price: {149.00'

`mrp_locate` spells `retail`. `Retai` is not `retail`. Rule 6(1)(e) was reported
undeclared. Three more of the same shape: `NET QOUANTITY` (an inserted `O`),
`CONSUME CARE` and `Maketed By:` (a dropped `R` and `r`).

Widening the pattern one observed misreading at a time is what produced the nine
unmatched phrasings earlier the same day, and it cannot anticipate the next
dropped character. `mend_label_noise` instead forgives **one edit inside a word
the pattern itself already spells** — a statement about the recogniser rather
than about the language. It is bounded: whole words only, five characters or
more (`mrp`, `net` and `qty` are left strict, because at three characters one
edit reaches `mrs`, `map` and `nut`), and only against the vocabulary derived
from the pattern being run, so there is still one definition of what an MRP
label looks like. Presence only — a format finding is *about* the characters and
mending them first would be judging text we invented — and pixels only, since
`listing_text` has no recogniser to forgive. **8 declarations recovered across
122 frames**, every one of them mandatory and genuinely printed.

**3. The generic name is habitually printed with no caption, and we can only
find a declaration by its caption.** 23 of 121 frames were failed for an
undeclared generic name. A besan pack prints `Chana Besan`; a battery card
prints `AA 1015 R6P BATTERIES`; a namkeen prints `Crunchy Spicy Potato
Noodles` — the generic name in substance, in display type, with nothing
introducing it. Rule 6(1)(b) requires the common or generic name; it does not
require the word "Commodity" anywhere. Nothing available here separates an
uncaptioned generic name from marketing copy, so "not declared" was a verdict
about our own vocabulary. It is now **REVIEW** on a photograph, with that reason
on the finding, and still **FAIL** on `listing_text`, where a field is either in
the listing or it is not. Of Rule 6(1)'s six this is the only one habitually set
without a label, and `uncaptioned_form_is_lawful` is set on that rule alone.

**4. A format finding quoted the wrong 120 characters.** `strict_text` falls
back to the whole label when the classifier produced no line for the field, and
`found` took the first 120 characters of it. The Mattel carton's MRP finding
read `'2-10\n7+\nFSC\nMX\nFSC* C161542\nBAVTRCKP\nor\nMC\n684173-A ...'` — the
top-left corner of the box, naming nothing an officer could check. On that
fallback the finding now quotes the neighbourhood of the located label instead.

### Where it lands

| | before | after |
|---|---|---|
| frames reported non-compliant | 39 / 121 | **38 / 121** |
| blocking FAIL | 101 | **70** |
| REVIEW | 74 | 104 |

| rule | before | after |
|---|---|---|
| `LMPC.GENERIC.PRESENT` | 25 FAIL | **0 FAIL** (23 REVIEW) |
| `LMPC.IMPORTER.PRESENT` | 7 | **2** |
| `LMPC.CARE.PRESENT` | 11 | 10 |
| `LMPC.MRP.PRESENT` | 5 | 4 |
| `LMPC.NETQTY.PRESENT` | 1 | 1 |
| `LMPC.NETQTY.EXCLUSION_ZONE` | 28 | **28** |

### The finding that is not a defect

`LMPC.NETQTY.EXCLUSION_ZONE` is now 40% of all remaining blocking FAILs and it
fires on every frame with a legible back panel, which is exactly the shape of a
false accusation — so it was checked against the gazette and against the
photographs rather than assumed.

The statutory text, `data/rulebook` lmpc_2011 p.9:

> Provided that the area surrounding the quantity declaration shall be free from
> printed information. (a) above and below by a space equal to at least the
> height of the numeral in the declaration, and (b) to the left and right by a
> space at least twice the height of numeral in the declaration.

`vertical_multiple: 1.0` and `horizontal_multiple: 2.0` of the numeral height
are what the rule says. And what the check names as intruding is real printed
matter, checked by eye against the frames:

| frame | reported intruders |
|---|---|
| Mattel UNO | `Month & year of Mfg. : 11/2025`; `Commodity :`; `Toy` |
| Perfetti Juzt Jelly | `MRP (incl. of all taxes): ₹35.00 (₹0.48/g)` |

Both are correct. Indian declaration panels are routinely set as a tight column
with normal leading, and normal leading is less than a full numeral height. This
is a genuine and very commonly violated provision, it is one of the two rules
that survive total failure of scale recovery, and it is the kind of finding
nobody else produces. **It stays.**

### What none of it fixes

The 122 frames are the same messaging transcodes we already had. On the frames
where the declaration panel is legible the report is now defensible; on the
frames where it is 11 px of cap height, the recogniser returns nothing usable
and no change in this repository alters that. Section 14's M4 and the
never-trained B2 still want annotation, and both still want capture at the
resolution section 4 assumes.

## Where the reading limit actually is — 2026-09-10

Four measurements, run to answer one question from the user: *"after doing these
will we get the result we are hoping for?"* Three of them killed a theory of
mine, and the fourth is the one that matters.

### Resolution is worth 8%

The 231 camera originals (4032×3024 and 4096×1840) against their own messaging
transcodes, reproduced here rather than assumed — long side 1600, JPEG quality
binary-searched to the observed 185 KB median, landing on 182 KB — and both
copies through an identical pipeline.

| over 47 pairs | transcode | original | change |
|---|---|---|---|
| usable lines (conf ≥ 0.90, ≥ 8 chars) | 308 | 331 | **+8%** |
| mandatory declarations named | 62 | 66 | **+4%** |

19 frames read better at full size, **13 read worse**, 15 unchanged. The earlier
claim in this file that capture resolution is the binding constraint is wrong at
the margin that matters: it is worth eight percent, not a step change.

### Our own detection ceiling is not the constraint either

`detect_text.LIMIT_SIDE_MAX` clamps DBNet's input, so a 4032 px original is
downscaled to 2048 before detection. Sweeping the ceiling on 14 originals:

| input ceiling | 1600 | 2048 | 3072 | 4096 |
|---|---|---|---|---|
| regions proposed | 256 | 257 | 252 | 270 |

Flat past 2048. The docstring's claim that the ceiling *"is a latency decision
and not a recall one"* is now measured rather than asserted.

### Tiling does not rescue it

2×2 tiles at 20% overlap, mandatory declarations unioned across tiles, 12 frames:
**13 → 14**. One frame went from 17 usable lines to 56 and gained a single
declaration. There is no more text to find.

### What does separate the frames

Not line height, which runs backwards:

| | frames recovering 4+ of six | frames recovering none |
|---|---|---|
| median print height (% of frame) | **1.62%** | 2.07% |
| median text regions | **54** | 16 |

The frames that fail do not have smaller print. They have less of it, because
the declaration panel is not in the photograph. Counted over the 122 frames:
**41 are front-of-pack** — brand face, no statutory block anywhere in shot,
verified by eye on a contact sheet. Of the 80 that do show a back panel, **31
name none of Rule 6(1)'s six**, and ten of those read eight or more confident
lines: `'NUTRITIONAL FACTS'`, `'How to make a tasty & nutritious PediaSure
drink'`, `'SCAN THE ... INSIDE & EARN'`. One read **62** confident lines and
named nothing.

The engine handles this correctly and the number is worth recording: across
those 41 front-of-pack frames it raises **one** blocking FAIL. It does not
accuse a package whose panel it never saw.

### What was built from it

B1's gate has five faults and every one is about *how* the photograph was taken.
None of them catches a sharp, well-lit, correctly-exposed photograph of the
wrong side of the pack, and that is 40 of 122 frames. `vision/quality/framing.py`
answers the other half **after** the read, because nothing in the raw pixels
distinguishes a sharp photograph of a declaration panel from a sharp photograph
of a brand face — the mirror image of blur, which must be caught before the read
because the recogniser's own confidence cannot see it.

| framing verdict on the 122 frames | count |
|---|---|
| a declaration was found | 54 |
| `no_declaration_panel` — turn the pack over | **40** |
| `wrong_panel` — this is the nutrition table | 28 |

The 40 are an independent corroboration of the 41 counted by eye. `SPARSE_REGIONS`
is 20, and it only chooses between two sentences after the frame has already been
found to carry no declaration, so being wrong about it costs wording rather than a
verdict: frames naming at least one declaration have 26 regions at the tenth
percentile against a median of 19 for frames naming none.

It sets no status, `rules/` does not import it, and it fires only when **zero**
declarations were found. A frame naming two of six may equally be a package that
declares two of six, and no signal available to us separates those — calling the
first a framing fault would hand the second an alibi.

### What is still owed

M0's done-criterion in §17 wants a recall figure against a deliberately-bad
subset, and `RESULTS.md` still reports none, because the labelled set does not
exist. The corpus now supplies the negative class — 40 known-bad framings. The
user has committed to 40–50 photographs framed on the declaration block, off the
phone without a messaging app, which supplies the positive one.

## Walking round the pack — 2026-09-10

The framing fault built earlier today can tell an officer that the declaration
panel was not in shot. It does not solve the problem, because it still asks the
officer to aim, and the objection that started the day was precisely that they
will not: *"an officer will not take care of these things right soo we need to
make our system designed soo strong that it handles these kinda things too
wihtout failing."*

So: **one pack, two or three photographs, evidence unioned, rules evaluated once
on the union.** `vision/context.py` holds the frames, `vision/multiframe.py`
unions them, and the officer's job changes from "aim at the declaration panel"
to "walk round the pack" — which is a thing people actually do.

### Why the union and not a vote over per-frame verdicts

The obvious alternative is to evaluate each photograph and combine the verdicts.
It needs no contract change and it is unsound in the direction that matters.

| pack | frame 1 | frame 2 | best-status wins | worst-status wins | union |
|---|---|---|---|---|---|
| lawful MRP on front, higher one pasted on back | PASS | FAIL | **clears it** | FAIL | FAIL |
| lawful pack, second shot missed the MRP | PASS | FAIL (absent) | PASS | **convicts it** | PASS |

There is no rule over verdicts that is right in both rows, because the verdicts
were computed against different evidence and the law is about the package rather
than about the photograph. Union the evidence and evaluate once and both come
out right.

### The three ways a union could fabricate a violation

Each photograph has its **own** rectified coordinate space. `Declaration.box`
documents itself as living in rectified label space; what it could not say until
now is that there is more than one such space in a scan. So `frame_id` travels
with every declaration, and three checks consult it before comparing:

| check | without the guard | with it |
|---|---|---|
| `clear_space` (Rule 8(1) proviso) | a line from frame 2 lands in frame 1's exclusion zone by arithmetic coincidence | intruders must come from the same photograph |
| `same_panel` (Rule 8(1)) | grouping "judged" across photographs of different sides | **NO_DATA** when the declarations span frames |
| `no_duplicate_field` (Rule 6(3)) | one price read twice, one digit misread, reported as two printed prices | **REVIEW** across frames, FAIL still within one |

The third is the sharpest: a naive union hands Rule 6(3) exactly the evidence it
exists to punish — two contradicting prices — manufactured on a lawful pack out
of our own OCR error. `clear_space` is the most expensive: it is 40% of the
blocking FAILs on the field corpus, so multiplying its chances by the number of
shots taken would have been the worst mistake available here.

A fourth was closed the same way. Every measurement check iterates its
declarations and keeps the **worst** outcome, which is right on one photograph
and wrong across several: three shots give three chances for one soft crop to
produce a FAIL, so an officer taking more care would make the pack look worse.
`measured_for` takes a measurement from one photograph per field — best
calibrated, then most confidently classified, then earliest. What it gives up is
stated where it lives: a duplicate declaration on a second panel is judged once.

### Measured — and the corpus cannot answer the friendly question

The obvious experiment is "does unioning three shots of one pack recover more
declarations". **The corpus cannot answer it**, and it is worth saying why
rather than fudging a grouping: the filenames carry WhatsApp *transfer* times,
not capture times. 462 of 468 consecutive gaps are zero or one second, the whole
batch arrived in four bursts, and nothing in it says which frames are the same
packet. That is the same dataset gap already recorded — there are no multi-angle
sets in what we have.

What the corpus can answer is the question that actually decides whether this is
safe, and it answers it harder. Union frames of **different packs** — the worst
input this will ever see, far worse than anything an officer produces — and
count the blocking FAILs. Seeded, 40 groups of 3, 117 frames read:

| | best single frame | union |
|---|---:|---:|
| mandatory declarations found | 57 | **61** |
| blocking FAILs (union vs *any* single frame raising it) | 36 | **33** |
| groups where the union raised a FAIL no frame raised | — | **1** |

**The union raises fewer blocking FAILs than the frames do individually, on
input designed to break it.** The three guards hold.

The single exception is not a guard failure and is worth reading carefully.
Group 21 raised `LMPC.READABLE.THROUGH_CONTENTS`, and the cause is
`reading_supports_an_absence` **lifting**: on each frame alone, fewer than half
of Rule 6(1)'s six declarations were located, so the guard withdrew every
absence as ours rather than the manufacturer's. The union located more, the
guard lifted, and the absence became reportable. On three photographs of one
pack that is the correct answer and it is the quiet win of this whole change —
`test_three_thin_photographs_together_can_support_an_absence` asserts it. On
three photographs of three *different* packs it is an artefact of the pairing.

Note what class it is in. **Presence is the one kind of finding the union can
legitimately move in the FAIL direction**, because establishing presence is what
the union is for. It cannot move a measurement or a box comparison that way;
that is what the guards above are.

### The evidence chain, and a bug it caught

Every frame is evidence, so every frame's digest is in the record: `scans.frames`
(migration `0003`, nullable JSONB) carries one entry per photograph with its own
`image_sha256`, and the chain covers the row. **NULL rather than `[]` on a
single-frame scan** — the chain hashes the keys a payload carries, so a
`frames: null` appearing on every existing row would make `verify_chain` report
CONTENT_ALTERED on records nobody touched.

Which is exactly what the first live multi-frame scan did, for a different
reason, and the chain caught it:

```
CONTENT_ALTERED at seq 2: stored digest d65446fbdbd8... but the content
hashes to 86494aeea75f...; this record was edited after it was written
```

Not `frames`. **`coverage`.** `scans.coverage` is a Postgres NUMERIC, and a
Python float with seventeen significant digits does not survive the round trip:
`0.9722222222222222` is read back as `0.972222222222222`, the row re-hashes to a
different digest, and the chain reports tampering on a record nobody edited.
Latent since the column existed — a single frame's coverage is one ratio and
often round-trips; a union's is the **mean** over several frames and needs the
full seventeen digits nearly every time. Fixed at `CHAIN_SAFE_DP = 6`, with a
regression test that applies the same narrowing without needing a database.

This is the alarm in this system that must never cry wolf. An auditor who has
seen CONTENT_ALTERED fire spuriously will not believe it when it is real.

### Verified end to end

Against the real stack — Postgres, MinIO, the hash chain — three photographs
posted to `POST /scans` as one scan:

```
seq 6 | frames 3 | frame_count 3 | coverage 0.786364
  frame 0  read=True  2026/09/10/<scan>.jpg
  frame 1  read=True  2026/09/10/<scan>/frame-01.jpg
  frame 2  read=True  2026/09/10/<scan>/frame-02.jpg
chain status: {"checked": 7, "ok": true}
```

One scan row, one chain entry, three evidence objects, 36 verdicts evaluated
once on the union. **1006 tests pass, 14 skipped** (36 new), `tsc --noEmit` clean.

---

## 38 labelled declaration panels — the first accuracy this project has had — 2026-09-10

The user delivered 38 photographs, one per pack, each showing the statutory
declaration panel: `38_images_asked withproperlabelling`. Every one has now been
read by eye and what is printed on it written down field by field.

That is the difference between coverage and accuracy, and until today this
project only had coverage. Every vision number in this file above was measured
against the corpus, which is unlabelled, so each one is the pipeline compared
against *itself* — how many regions were proposed, how many declarations were
named, how those counts moved when something changed. A frame where four
declarations are named may be a frame carrying six, and nothing in the corpus
can say which. These 38 can.

```
python scripts/ingest_declaration_blocks.py "38_images_asked withproperlabelling"
python bench/declaration_blocks.py
```

* `data/declaration_blocks/ground_truth.json` — the labels (tracked)
* `data/declaration_blocks/ground_truth.schema.json` — what a label may say (tracked)
* `data/declaration_blocks/manifest.json` — SHA-256 of every image (tracked)
* `data/declaration_blocks/images/` — the photographs (gitignored, as the corpus is)

The bench refuses to run if any image's hash has moved since annotation, so a
number here is tied to the bytes it was computed against.

### The set

38 packs: biscuits, soap, tea, ghee, cheese, rice, papad, pickle, sugar, salt,
matches, detergent, shampoo, lip balm, a razor, a lunch box, an LED lamp, pens,
a pencil box. 29 JPEG, 8 WebP, 1 PNG; 400×400 to 4220×2376. Some are the user's
own photographs — held in the hand, tilted, creased, half-lit — and some are
e-commerce renders on a white sweep. Both belong: the officer's phone and the
listing channel are both inputs the system takes.

Four frames earned their place on their own:

| Frame | Why |
|---|---|
| `camlin.webp` | Two MRPs on one panel — `New MRP ₹29.00` pasted above `MRP ₹30.00`. Rule 6(3). |
| `whisper.jpg` | `₹480` struck through beside `₹375.00`, on one line, at 400×400. |
| `rice.jpg` | `Mfg & Consumer Cared By:` printed with **nothing after it**. |
| `pickle.jpg` | `Batch No.` printed with nothing after it; two dates handwritten in ballpoint. |

Those last two are recorded in a separate `blank_labels` field and excluded from
scoring in both directions. A missing value there is the *package* failing, not
the extractor, and counting it as a miss would penalise the pipeline for being
right.

### Headline

**Measured 2026-09-10, Windows 11, Python 3.12.8, 255 field labels over 38 frames.**

| Metric | Target | Before | After the fix below |
|---|---|---|---|
| Declaration presence, micro F1 | — | 0.735 | **0.751** |
| — precision | — | 0.980 | **0.981** |
| — recall | — | 0.588 | **0.608** |
| Rule 6(1) mandatory recall | — | 0.593 | **0.609** |
| Framing recall (B1) | — | 35/37 | **36/38 = 0.947** |
| M0 capture gate, pass rate on usable photos | *≥ 98%* | 17/38 | **17/38 = 0.447** |
| MRP presence F1 | *≥ 0.90* | 0.83 | **0.81** |
| MRP *value* read correctly | — | 16/38 | **15/38 = 0.39** |
| Median scan | < 3 s | 1170 ms | **1165 ms** |

Read the precision column before anything else. **0.98: the pipeline almost
never claims a declaration that is not there.** Across 255 labels it invented
**three**, and all three are the same mistake: `frshcream.jpg`, `honey.jpg` and
`santoor1.jpg` each declare a manufacturing date and no expiry, and each had a
date read as an `expiry_date`. For an enforcement tool that is the right side to
be wrong on, and it is the constraint every fix below had to respect.

Recall is 0.61 and that is the honest state of the extractor today. Two of the
38 frames were read completely.

### Four defects, with evidence

**1. A box printed on the label was being taken for the label. Fixed.**

`rectify` prefers a quad over every method except a marker, so whatever
`find_label_quad` returns becomes the whole scan — everything outside it is
discarded before a region is proposed. The floor on quad area was 12% of the
frame.

The search returns a quad on 4 of the 38. Three cover 13%, 13% and 35%: a
barcode block, a coded sticker, a nutrition table — real printed rectangles
*inside* the panel. The fourth covers 86% and is the label.

`papad.jpg` is the case in full. Its label is an octagon, so it never matches as
a quad in its own right; the nutrition table inside it does. The scan rectified
to 13% of the frame, recovered **one legible line**, and exited at tier L4 —
*"Nothing legible was recovered."* Its 100 g sibling `udadpapad.jpg` — same
brand, same layout, same pixel size, rectangular label — read **63 lines** and 7
of 8 fields.

`_MIN_QUAD_AREA_FRAC` 0.12 → **0.20**. `papad.jpg` now reads 64 regions and 6 of
8 fields; the L4 is gone and all 38 frames now produce declarations.

**0.50 was tried first and `tests/golden` rejected it**, failing on
`no_marker_tier_c` — a 760×520 label on a 1200×900 canvas, 36.6% of frame, an
ordinary pack-on-a-counter framing that must keep its rectification. That is
what the golden suite is for and it did its job. 0.20 sits between the two junk
quads at 0.13 and the smallest known real label at 0.366, with margin on both
sides. Pinned by `test_a_box_printed_on_the_label_does_not_become_the_label`.

The change is not free and the table above shows the cost: `matches.jpg` loses
one field, because that pack is small in the frame and cropping to the interior
box was accidentally acting as a zoom on 1 mm print. Net **+4 labels**, one
total-failure case removed, one field lost.

**2. The MRP label is found and the numeral is not attached. Not fixed.**

This is the largest single gap, and the reason MRP value accuracy is 0.39 while
MRP *presence* is 0.81. On 11 frames the extractor returns exactly this:

```
agarbati.webp   want 150.00   read 'MRP₹'
bajaj.jpg       want 745.00   read 'MRP'
milksoap.jpg    want 480      read 'M.R.P.₹'
honey.jpg       want 335.00   read 'MRP NRs.'
santoor.jpg     want 300.00   read 'MRP ₹:'
```

The label was detected, read and correctly classified. The figure is printed in
a value column some distance away and was never joined to it.
`vision/classify/associate.py` exists for precisely this and is not firing.
Measuring the gap on each frame shows **it is not one cause**:

| Frame | Value in the OCR output? | Gap ÷ line height | Fails on |
|---|---|---|---|
| `bajaj.jpg` | yes, `₹ 745.00 (incl…` | 8.2 | `GAP_RATIO` = 4.0 |
| `honey.jpg` | yes, `335.00` | 9.2 | the gap *and* the same-line test |
| `santoor.jpg` | yes, `300 .00` | 7.7 | the gap *and* the same-line test |
| `agarbati.webp` | yes, `150.00` | 4.3 | the same-line test |
| `milksoap.jpg` | **no** | — | never read |
| `cheese.jpg` | **no** (dot matrix) | — | never read |

So widening `GAP_RATIO` fixes one of six. The rest need the same-line overlap
test relaxed — and on `honey.jpg` the lot number `NB00246` sits at ratio 9.4 on
the *same line* as the MRP label while the price sits at 9.2 off it. Relax the
test and that pack's lot number becomes its maximum retail price. That is the
false positive `associate.py`'s own docstring warns about, and MRP precision is
currently 1.00.

**Trading 1.00 precision for recall on an enforcement tool is the wrong
direction to be casual about.** Left as measured, with the numbers above, as its
own piece of work.

**3. M0 would reject 21 of 38 readable declaration photographs.**

§18's bar is *"passes ≥98% of usable photos"*. Every frame in this set is a
usable photograph of a declaration panel — that is what was asked for and what
arrived. The gate passes **17 of 38**. Of the 21 it rejects, **20 pass the
framing gate**, so the system's own two halves disagree: one says the panel is
in shot, the other says the photograph is not worth reading.

```
resolution  15      glare  11      overexposed  10     (a frame can carry several)
```

The faults are legible. `resolution` fires on the small crops and the web
renders — `whisper.jpg` is 400×400 and every one of its declarations is
readable. `glare` and `overexposed` fire on the white-sweep e-commerce renders
and on flash against glossy film: the detector is measuring the background, not
the label.

The bench runs with `quality_gate=False`, so this is measurement and not
behaviour — nothing was rejected. But with the gate on, more than half of this
delivery would be handed back to the officer as unusable. **The complementary
half of §18's bar — "rejects ≥90% of the deliberately-bad subset" — still cannot
be measured, because no deliberately-bad frames have been delivered.** Both
halves have to move together, so this is not a threshold to nudge against one
set.

**4. `generic_name` recall is 0.04, and most of that is by design.**

1 of 27. Broken down, 21 of the 27 are cases the rulepack **deliberately
declines**:

* **17** print the generic name in uncaptioned display type — `UDAD PAPAD`,
  `SCENTED SANITARY PADS`, `DETERGENT CAKE`. `generic_name_locate` requires a
  caption on purpose; guessing from display type would read a brand as a generic
  name and turn a real violation into a pass.
* **6** caption it `Product:` or `Product Name:`, which the pattern excludes for
  the same reason — `Product : CLARA VINTAGE 4` is a brand.

Four are genuine gaps in the pattern: `Commodity Name : BOILED RICE` (the
pattern wants `name of commodity`; the word order here is reversed) and
`CONTENTS : TEA` (not a form the pattern covers). One, `bajaj.jpg`, read the
word `COMMODITY` as a region of its own with the colon detected separately — the
same association failure as defect 2, arriving in a different field.

So the honest figure is **1 of 6 recoverable**, not 1 of 27, and the annotation
and the rulepack are measuring different things. Recorded rather than quietly
reconciled: the ground truth says what is printed on the pack, and it should go
on saying so.

### What this does not measure

* **Framing precision.** Every frame here shows a panel, so there are no
  negatives. 0.947 is a recall and no false-positive rate can be read off it.
* **Millimetres.** All 38 land at tier L2 — no marker, no stored dimensions — so
  every absolute-height rule returns NO_DATA. U1 is `data/test_split/`'s job and
  that stays sealed.
* **The package detector.** `detector_rtmdet_ins_tiny_int8.onnx` does not exist
  yet — P9 is blocked on annotation — so all 38 ran on the geometry-only
  fallback for the package region, which is also what production does today. The
  text detector and both recognisers are the real models.
* **Anything out of sample.** The rectify fix was found on these 38 and
  validated against `tests/golden` and the full suite, not against a held-out
  split. 38 frames is too few to split honestly; the claim is "no regression
  across 1007 tests", not "generalises".

**1007 tests pass, 14 skipped** (1 new).

---

## Why a compliant pack was being called non-compliant — 2026-09-10 (later)

The user reported it plainly: *"its still giving non compliant while the thing is
compliant."* The 38 labelled panels make that answerable for the first time —
for every blocking FAIL, the ground truth can be asked whether the declaration
the rule says is missing is actually printed on the pack.

```
python bench/false_accusations.py
```

### The measurement

**38 packs, before any fix:**

| | |
|---|---|
| Blocking FAILs raised | **63** |
| — presence claims, refutable from ground truth | 32 |
| — **demonstrably FALSE** | **16** |
| — geometry/duplication, needs an eye | 31 |
| Packs with at least one false accusation | **10 of 38** |
| Packs with a clean sheet | **9 of 38** |

**Half of every presence accusation was false.** That is the honest headline and
it is what the user was seeing.

Only presence rules can be refuted mechanically. A first version of this bench
scored the geometric rules too and called `LMPC.MRP.OVERSTICKER` false on
`camlin.webp` — whose panel genuinely carries two prices. The rule was right and
the bench was wrong; it now reports those as needing an eye instead.

### Two causes, and they are not the same kind of problem

**Cause 1 — the exclusion zone was measuring the wrong rectangle. Fixed.**

`LMPC.NETQTY.EXCLUSION_ZONE` was the single largest accuser: **18 of the 63**.
Rule 8(1)'s proviso is defined in *numeral* heights — one above and below, two
either side. `clear_space` anchored on `subject.numeral_box or subject.box`, and
when the numerals could not be separated it silently used the whole declaration
line.

Measured across the 18: **14 were anchored on the whole line.**

```
rice.jpg      anchor 1373x277  ->  zone +-277 vertical, +-554 horizontal
              (the numerals of "26 KG" are about 60 px tall)
honey.jpg     anchor  533x183  ->  zone +-183 / +-366
milksoap.jpg  anchor  725x101  ->  zone +-101 / +-202   on 'CONTENTS : TEA'
```

Four to five times the statutory zone in every direction, sweeping in text
printed nowhere near the figures. `Declaration.numeral_height_px` already states
the rule the codebase follows everywhere else: *"None means the figures were not
separable, and the height rules then return NO_DATA. That is the honest answer
[...] a fabricated height costs someone a false violation."* A fabricated
exclusion zone costs exactly the same thing. `clear_space` now returns NO_DATA
rather than guessing an anchor.

`LMPC.NETQTY.EXCLUSION_ZONE` **18 → 4**. The four that remain had a real numeral
box. `test_real_printed_matter_in_the_zone_is_still_reported` still asserts FAIL,
so the rule has not been defanged — three existing tests had to be given an
explicit numeral box, because their fixtures had none and were reaching the
intrusion logic only through the fallback being fixed.

**Cause 2 — the consumer-care telephone pattern matched 8 of 19 real numbers.
Fixed.**

Rule 6(2) makes the telephone mandatory, so a pattern that misses one is a
high-severity FAIL against a pack printing its helpline in plain sight.
Transcribing all 19 telephone numbers off the 38 panels and testing the shipped
pattern:

```
as shipped   real numbers matched  8/19       non-numbers matched  4/16
candidate    real numbers matched 19/19       non-numbers matched  0/16
```

It missed every common Indian grouping — `1800-10-22-221` (HUL),
`1800 425 444 444` (ITC), `1-800-4254449` (Britannia), `022-6691 6929` (Parle),
`(022) 68404021` (Lijjat), `+91-75064-96604` (Plum).

**And it was wrong in the other direction too, which is worse.** With no digit
boundaries, `[6-9]\d{9}` matched a substring of the FSSAI licence
`10012022001320` and of the barcode `8904150193600` — so a pack declaring **no**
consumer-care telephone could satisfy Rule 6(2) on its licence number. The
rewritten pattern is anchored between non-digits and has three branches
(toll-free, landline, mobile). 20 new tests, one per real number and one per
decoy.

### After both fixes

| | Before | After |
|---|---|---|
| Blocking FAILs raised | 63 | **48** |
| Demonstrably false | 16 | **15** |
| `LMPC.NETQTY.EXCLUSION_ZONE` | 18 | **4** |
| `LMPC.CARE.PRESENT` false | 4 | **3** |
| Packs with a clean sheet | 9 | **13 of 38** |

### What is left, and why it is not a rulepack problem

Of the 15 false accusations that remain, **14 are a field we never read**:

```
pack                falsely accused of    did we extract it?
camlin.webp         LMPC.MFR.PRESENT      no - never read
ghee.jpg            LMPC.MFR.PRESENT      no - never read
ghee.jpg            LMPC.CARE.PRESENT     no - never read
jimjam.jpg          LMPC.MFR.PRESENT      no - never read
parleg.jpg          LMPC.MFR.PRESENT      no - never read
whisper.jpg         LMPC.MRP.PRESENT      no - never read
...
```

This is `bench/declaration_blocks.py`'s recall figure arriving as a verdict.
Manufacturer extraction recall is **0.38**; when the pipeline finds no
manufacturer, the manufacturer is usually still there. The rule is behaving
correctly on the evidence it was handed. The evidence is wrong.

**`reading_supports_an_absence` is the guard that should catch this and it fires
on only 10 of the 38.** Its test is `located * 2 < len(mandatory)` — strictly
fewer than half of Rule 6(1)'s six. Extraction locates 3.6 of 6 on average,
which is just over the line, so the guard stands down and the two or three
declarations we failed to read are reported as missing.

**That threshold has deliberately not been touched.** Its own docstring says
why: *"Half is a round number and it is stated rather than fitted [...] a
threshold chosen to make a particular photograph pass is the exact fitting that
seal exists to prevent."* Raising it to four-of-six or five-of-six would
suppress most of these — and would suppress genuine findings with them, on a
tool whose output is an enforcement action. That is a policy decision about
which error is worse, it belongs to the user and not to a threshold sweep over
38 images, and the fix that needs no policy at all is to raise extraction recall
so the guard never has to arbitrate.

**1028 tests pass, 14 skipped** (20 new).

---

## The cheese carton — four more false-accusation bugs, from one screenshot — 2026-09-10 (evening)

The user scanned a Parag cheese carton in the running app and it came back
**Non-compliant** with two blocking FAILs, against a pack that declares
everything Rule 6(1) asks for. The screenshot also showed most of the annotated
regions labelled `other`, and two numbers rendered as `13.00 mm` and
`required 0.00 mm`.

Four separate defects, each measured on that frame and then across all 38.

### 0. The running server was two hours stale

The API process started 09:38; the day's fixes landed 11:58. **Before reading
any code, check the process start time** — this is the second time a stale
uvicorn has cost a diagnosis. See `docs/` and the local-stack notes.

### 1. Rule 7(3) was measured on a Devanagari diacritic

`LMPC.CHAR.WIDTH_RATIO` FAIL, `found="0.286 (character 'ः')"`. The recogniser
read `MRP ₹` as `'MRP रः'`, and the visarga — 0.286 of its own height — failed
the pack.

The gazette says *"the width of the **letter or numeral** shall not be less than
one third of its height"*. A visarga is neither, and neither is a colon, a rupee
sign, a bracket or a per-cent sign. The check excluded characters by a hand
written list of nine Latin characters in the rulepack; **anything not on that
list was measured**, and the things not on it are exactly the things that are
narrow by nature.

`min_width_ratio` now measures only `ch.isalnum()` — true for Latin and
Devanagari letters and digits, false for marks (Mn, Mc), punctuation (P\*) and
symbols (S\*). The rulepack's `exclude_chars` is trimmed to the gazette's own
carve-out, `1 i I l`, because the rest is now structural rather than excused by
name.

### 2. The net-quantity label was joined to a refrigeration instruction

This one caused three visible symptoms from a single mistake.

`Net Weight:` was classified `net_quantity` at 0.88, correctly. `associate`
then looked for its value and picked

```
'ALWAYS KEEP UNDER REFRIGERATION (BELOW 4C. ON OPENING, T...'
```

over `'200 g (7.05 oz)'` printed directly beside it — because
`ASSOCIABLE["net_quantity"]` asked only *"does this fragment carry a figure"*,
the refrigeration line contains the `4` of `4°C`, and its box centre sat 133 px
from the label against 229 px for the real value. **The nearest fragment
carrying a digit is not the nearest fragment carrying a quantity**, and on a
food panel the difference is a temperature, a licence number or a date.

The cost of that one join:

* the officer's report labelled the refrigeration sentence **net quantity**;
* the real `200 g (7.05 oz)` was left as **other** — the `other` labels the user
  was pointing at;
* Rule 8(1)'s exclusion zone was anchored on the resulting **568×97 px** box
  spanning three printed lines.

Rule 7 quantities are a number **and a unit**. `ASSOCIABLE["net_quantity"]` now
requires one; `mrp` stays a bare figure, because a price is one. Checked against
12 real quantity strings from the 38 panels and 6 decoys off the same panels
(licence numbers, dates, pin codes, a helpline): 18/18 correct.

### 3. A ratio and a count were both printed as millimetres

```
Clear space around net quantity     13.00 mm    required 0.00 mm
Character width to height            0.29 mm    required 0.33 mm
```

The first is a count of intruding regions; the second a width-to-height ratio.
`rule-rows.tsx` piped every verdict's `measured`/`threshold` through
`millimetres()`, which appends `mm` unconditionally. The numbers were right and
the unit was invented by the renderer. `required 0.00 mm` is not a quantity
anyone can check, and a report that prints one reads as a broken tool.

`Verdict.unit` (`mm` | `ratio` | `count` | `cm2`, default `mm`) is declared by
the check that did the measuring — `min_width_ratio` and `min_contrast` are
ratios, `clear_space` a count — carried through `CheckOutcome`, stored in a new
`verdicts.unit` column (migration `0004`), and rendered by a new
`quantity(value, unit)`. A `Literal`, so a new check cannot introduce a fourth
unit no formatter knows how to print.

**`test_a_verdict_survives_a_round_trip_through_the_schema` caught the missing
column before the migration was written**, which is exactly what that test is
for. The evidence chain is untouched: `verdicts` rows are not part of the
canonical payload `evidence/chain.py` hashes.

### Result on that frame, and on all 38

`cheese.jpg`: **2 blocking FAILs → 0**, and all eight of its declarations
extracted. Compliant, with three REVIEWs.

| | Start of day | Now |
|---|---|---|
| Blocking FAILs over 38 packs | 63 | **47** |
| Demonstrably false | 16 | **15** |
| Packs with a clean sheet | 9 | **15 of 38** |
| `LMPC.NETQTY.EXCLUSION_ZONE` | 18 | **3** |

**1028 tests pass, 14 skipped.** `tsc --noEmit` clean.

### The one still standing: `LMPC.CHAR.WIDTH_RATIO`

Five packs still fail it, and the character it fails on is now visible in every
case:

```
camlin.webp     0.280 ('t')      honey.jpg    0.250 ('t')
pickle.jpg      0.176 ('e')      surfexcel    0.176 ('N')
udadpapad.jpg   0.091 ('N')
```

These split into two different problems and neither should be fixed by reflex:

* **`t` at 0.25–0.28 is a real measurement.** `character_boxes` measures each
  glyph's own ink extent, not the line height, and a lowercase `t` has an
  ascender — tall, thin, and genuinely under a third of its own height. It is
  the same shape family as the gazette's own carve-out, `1 i I l`, which simply
  does not enumerate `t`, `f`, `j` or `r`. **Extending that list is a legal
  interpretation and the rulepack's editing rules require a source-register
  entry for it** — not a patch at the end of an afternoon.
* **`N` at 0.091 is 11:1 and impossible for printed type.** That is
  `_split_wide_runs` cutting one ink run into slivers to match the character
  count. A measurement bug, fixable, and it needs its own careful pass rather
  than a floor invented to make five photographs pass.

## The second pass that scored better by reading less — 2026-09-18

B7 asks for *"low-confidence crops re-cropped from original full-resolution
pixels and re-read"*. It is built, it works, and it is **switched off**, and this
section is why — because the first version of it was actively harmful in a way
that no test would have caught and the acceptance criterion looked obviously
correct.

### The rule that rewarded the failure it was meant to exclude

The safety property seemed unarguable: keep the second reading only when it is
**more confident** than the first. A pass that can only raise confidence cannot
make anything worse, so it is free to leave switched on.

`ctc_decode` computes confidence as the **mean of the kept per-step scores**:

```python
scores = logits.max(axis=1)
...
confidence = float(np.mean(kept_scores)) if kept_scores else 0.0
```

A decoder that drops the characters it finds hardest therefore comes back with a
**higher** score, for a shorter and worse reading. "More confident" and "better"
are not the same quantity, and on small print they point in opposite directions.

Measured over 20 corpus frames, the confidence-only rule made **17 text changes**
of which one was right:

| first pass | conf | second pass | conf |
|---|---|---|---|
| `Ske Inernatonal: B-57, Lawrence Ro` | 0.74 | `SkeInterationat: -57Lence Rod` | 0.75 |
| `c.N 1310010409` | 0.56 | `  No 130029` | 0.58 |
| `N 310` | 0.43 | `N2` | 0.50 |
| `[014814` | 0.76 | **`1014814`** | 0.90 |

The second row is a licence number losing four digits, on an enforcement record,
scored as an improvement. The last row is the one genuine fix in the set.

**The corpus found this, not the tests.** Every unit test passed throughout: the
stub returned a more confident reading and the code kept it, exactly as designed.
What was wrong was the design, and the only thing that could say so was running
it over real labels.

### What it became

Two conditions now, and the first is the one that matters:

- **A second reading may not be shorter than the first.** Characters dropped are
  evidence dropped, and the metric actively rewards dropping them.
- **It must win by `MIN_CONFIDENCE_GAIN` (0.10).** A gain of 0.01 on a mean of a
  dozen softmax scores is rounding, not a better reading.

The crop was wrong too, in a way that explains the direction of the damage.
Warping straight from the photograph to the recogniser's 48 px input is a large
downsample through `warpPerspective`, which has no area filter and therefore
aliases — small print turns to moiré and reads *worse* than the thrice-resampled
version it was replacing. It now resamples at the quad's native density and
reduces with `INTER_AREA`, which integrates over source pixels instead of
sampling every sixth row.

Same 20 frames after both fixes: **2 text changes**, one of them the `[014814`
fix. The golden suite, which had shifted by `ocr_confidence 0.33 → 0.35`, went
back to passing untouched — the margin refuses that gain as noise, which is the
guard doing its job rather than a snapshot being re-recorded.

### And then it was measured, and it does not pay for itself

Two questions, asked separately.

**Does it help?** The bench was run twice, back to back, over the 38 hand-labelled
declaration panels — the only ground truth this project has.

| | second pass off | second pass on |
|---|---|---|
| presence micro F1 | 0.7506 | **0.7506** |
| precision / recall | 0.981 / 0.6078 | **0.981 / 0.6078** |
| mrp value accuracy | 19/38 | **19/38** |
| net_quantity | 25/34 | **25/34** |
| mfg_date | 14/32 | **14/32** |

Every per-field precision and recall identical. The two bench JSONs differ in
their timing fields and **in nothing else**.

**What does it cost?** Timed in isolation over those panels: **median 0.2 ms**,
because on most scans no line falls below the threshold and the pass never
starts. But it fired on **4 of 14** frames, and when it fires it costs **336 ms
on average, up to 953 ms** — against section 4's 561 ms budget for the entire
scan.

On 70 unlabelled corpus frames (1,915 lines) it changed 11 texts. Some are
plainly right — `[014814`→`1014814`, `6`→`760`, `A=`→`59.82`. At least one is
plainly wrong — `THORN`→`THDEA`. **The rest cannot be scored, because the corpus
has no ground truth**, which is the entire reason the 38 labelled panels exist.

So: a third of scans paying a third of a second, for eleven changes in two
thousand lines that nobody can adjudicate, against a labelled set that puts the
effect at exactly zero. `second_pass.ENABLED = False`, with the measurement
written into the constant's docstring and the call left wired in
`vision/pipeline.py` behind it. Turning it on is one boolean.

**What would settle it** is the set already asked for. The 38 panels are
close-ups whose rectification barely resamples, which is precisely where this
pass has least to offer; full-resolution photographs of *angled* declaration
blocks would put those eleven changes on a measured footing in either direction.
Until then the honest position is that B7 is finished and unproven, which is a
different thing from finished and good.

## A marker that was not there — 2026-09-18 (evening)

Found while answering a question about why the pre-labels say `other` so often.
The question was about annotation. The answer turned out to be a scan that
returned nothing from a photograph that contained everything.

### What happened

`IMG_0640.JPG` is a sharp 3024×4032 photograph of the back of a Pepsi can: the
ingredients, the nutrition table, `MFD. BY`, `MKT. BY`, the FSSAI licence,
`NET QUANTITY: 300 ml`, the MRP line, and a consumer-care address with a
helpline. The full pipeline read **zero lines**, exited at tier **L4**, and
produced the message *"Nothing legible was recovered."*

The text detector was not the problem. Run directly on the same file it proposes
**47 regions**, and `read_regions` reads **43** of them.

The image handed to OCR was **31 × 168 pixels**.

`cv2.aruco.detectMarkers` had found a marker on the can — a 68 × 56 px patch,
**0.03% of the frame**, its four edges measuring 66, 34, 33 and 48 px. There is
no marker card in that photograph. There is no marker card anywhere in this
corpus; the card has not been printed yet. `rectify` took that false positive,
mapped its corners to a square, applied the homography to the whole frame, and
collapsed a 12-megapixel photograph into a sliver.

### Why nothing caught it

`warp_to_marker` already refuses a degenerate warp — in one direction:

```python
if out_w < 8.0 or out_h < 8.0:
    return None
if out_w > w * _MAX_WARP_GROWTH or out_h > h * _MAX_WARP_GROWTH:
    return None  # grazing angle: the plane runs to the horizon
```

The growth guard is relative and the shrink guard is **absolute, at 8 pixels**.
`31 × 168` clears it comfortably. What is wrong with that output is not its size
but its size *relative to the frame that produced it*, and nothing measured that.

The fix is the growth guard read backwards, using the same constant rather than
a new one: a plane that collapses by more than the factor we already refuse to
let it grow by is degenerate for the same reason, whether the marker is real or
imagined.

```python
if out_w * _MAX_WARP_GROWTH < w or out_h * _MAX_WARP_GROWTH < h:
    return None
```

### Measured over the 231 camera originals

Markers were detected on **3 frames**. **All three are false positives** — the
corpus contains no marker card — and all three damaged the scan.

| frame | marker | rectified to | before | after |
|---|---|---|---|---|
| `IMG_0640.JPG` | 0.031% of frame | 31 × 168 | L4, **0** declarations | L2, **43** |
| `IMG_0713.JPG` | 0.023% of frame | 18 × 419 | L4, **0** declarations | L2, **43** |
| `IMG_0704.JPG` | 0.086% of frame | 684 × 3000 | L3, **5** lines | unchanged |

The third is left alone deliberately. It collapses to 17% of the frame's area,
not 0.04%, so it clears the guard — and it is still being harmed: the raw frame
offers 69 regions and the marker path yields 5. Tightening the threshold until
that case flips too would be fitting a constant to three photographs.

### What is deliberately not fixed

**Marker acceptance itself.** `detect_markers` already takes a `marker_ids`
argument and its docstring already anticipates this exact failure — *"a stray
marker in the frame — on another product's packaging, on a shelf tag — would
otherwise be measured as if it were the reference"* — but it defaults to `None`
because an officer may be issued a card from any batch. That is a real
trade-off and it belongs to whoever runs the deployment.

More to the point: **this corpus contains zero true positives.** A false-positive
rate of 3 in 231 is measurable; a precision figure is not, and neither is a size
floor, until a real card has been photographed. Printing
`data/marker_card/akshar_card_A4.png` is already on the outstanding list, and it
is what makes this tunable rather than guessable.

## 37 hand-drawn frames, and the metric that was measuring a drawing convention — 2026-09-18 (night)

The first Label Studio export arrived: 37 frames, 265 declaration boxes, two
hours of work. It is the project's second independent ground truth after the 38
declaration panels, and the first at **box** level rather than field presence.

### Neither model can be trained on it, and the scripts said so themselves

`training/detector/convert.py`: **37 package boxes, zero panel polygons.** The
RTMDet-Ins config selects its checkpoint on `segm_mAP`, which needs masks. There
are none.

`training/classifier/train.py` refused outright:

```
9 labelled address declarations
  manufacturer 5   packer 1   importer 0   consumer_care 3
Too few examples to train.
```

Both refusals are the tools working. A head trained on 9 examples across four
classes, one of which has none, would confidently never predict `importer`.

### The annotation is real work, which is worth recording

Compared against the proposals each task started from:

| | |
|---|---|
| annotations byte-identical to the machine's proposal | **0 / 37** |
| machine boxes deleted | **671** |
| boxes drawn by hand | **186** |
| median time per frame | **172 s** (2 hours total) |

Nothing was rubber-stamped. `docs/annotation-guide.md` warns that *"a pre-label
you leave alone is a label you have asserted"*; that did not happen here.

### The metric that lied

Scored the obvious way — box matching at IoU ≥ 0.5 — the pipeline reports:

    recall    88/265 = 33.2%
    precision 88/1088 = 8.1%

Both are artefacts. The two sides are drawing different things:

    annotator boxes are 6.4x the area of the pipeline's
    pipeline boxes sitting inside one annotator box: median 1, mean 2.3, max 51

The guide says *one box per declaration*, and a consumer-care declaration is a
four-line address. The pipeline emits **lines**, because that is what
`vision/ocr/lines.py` assembles and what the classifier reads. A generous box
around four lines and a tight box around the first line describe the same
declaration and overlap at an IoU near 0.15. **Reporting that as a miss measures
a drawing convention, not a defect** — and a "detector" at 8% precision would
have sent someone chasing the wrong bug for a day.

`bench/annotated_frames.py` therefore scores **containment**: did the pipeline
put text inside the region the annotator marked, and did it give it the same
name. `--iou` still prints the IoU view, with a pointer to the docstring, so the
convention gap is visible rather than hidden.

### What it actually says

| | |
|---|---|
| pipeline put text inside the box | **209/265 = 78.9%** |
| …and gave it the same name | **184/209 = 88.0%** |
| end to end | **184/265 = 69.4%** |

**And the number that matters, which the three above flatter.** 207 of the 265
boxes are `other`, and both sides agreeing that a trademark notice is not a
declaration is agreement about nothing anyone will be prosecuted over. On the 58
boxes the annotator gave a real name:

    24/58 = 41.4%

That is the honest figure, and the per-field breakdown says where it goes:

| field | found | named |
|---|---|---|
| `net_quantity` | 9/9 | **5/9** |
| `barcode` | 6/6 | **1/6** |
| `mrp` | 2/4 | **0/4** |
| `batch` | 2/5 | **0/5** |
| `expiry_date` | 1/3 | **0/3** |
| `manufacturer` | 3/5 | 2/5 |
| `nutrition` | 4/4 | 4/4 |

The pipeline **finds** the text 78.9% of the time. It is naming it that fails,
and it fails in one direction: `barcode → other` ×5, `net_quantity → other` ×4,
`batch → other` ×2, `mrp → other` ×2. Only twice did it name something the
annotator called `other`, and never did it swap one real field for another.

That shape is the regex tier behaving as designed — high precision, low recall,
`other` whenever nothing matched — and it is exactly the recall the layout head
exists to add. Which is the thing that cannot be trained yet.

## One pack, scanned by the user, found two bugs the corpus had not — 2026-09-19

A single salt packet, scanned through the running app, with the annotated
evidence image read by eye. It exposed two defects that 469 corpus frames, 38
labelled panels and 37 hand-annotated frames had all missed.

### `Packed & Marketed By:` was a manufacturing date

```
'Packed & Marketed By:'  ->  mfg_date (0.88)
    reason: matched mfg_date locate pattern on 'Packed'
```

A Rule 6(1)(a) packer declaration handed to a date-format check. `mfg_date_locate`
already carries a guard against exactly this, written after `MFG BY ABC Foods`
classified as a date — but it was spelled `(?!\s*(&\s*)?(by|pkd)\b)`, which
blocks `Packed & by`, a thing no pack prints, and not `Packed & Marketed By`,
which a great many print. The guard now reaches across one optional role word,
and `packer` gains the phrasing outright.

### `Use Before` matched nothing

The expiry pattern read `best\s*(before|by)|use\s*by` — three of the four
combinations. `Use Before` is as common on Indian packs as `Use By`, and it was
being read, named `other`, and Rule 6(1)(d)'s date left unevaluated.

### And the measurement that matters

Both fixes came from a pack in **neither** ground-truth set. Scored on the 38
held-out panels:

| | before | after |
|---|---|---|
| presence micro F1 | 0.7506 | **0.7685** |
| recall | 0.6078 | **0.6314** |
| precision | 0.9810 | **0.9817** |
| `expiry_date` F1 | 0.67 | **0.82** |
| `packer` | 0.00 / 0 of 2 | **P 1.00, R 0.50** |
| expiry value accuracy | 5/22 | **7/22** |

Recall rose and precision did not fall, which is the shape a real fix has: it
did not trade one for the other.

**This is also the clearest evidence so far that the rule tier is not being
fitted to its test sets.** The previous round of fixes came from the 37
annotated frames, improved that set (41.4% → 46.6%) and left the held-out panels
untouched — the honest reading of which was "improved what guided it, and
nothing else". This round came from a pack outside both sets and moved the
held-out number. Fresh data keeps finding real bugs, which is what a
*non*-overfitted rule tier looks like.

### What the same scan could not do, and why none of it is a naming bug

Seven checks reported **Not measured**, all of them height rules, all for one
reason: `No scale was recovered (tier C)`. There is no marker card in the
photograph because the card has not been printed. That is a sheet of A4, not a
code change, and it converts seven `NO_DATA` rows into real millimetre
measurements on every scan thereafter.

Two values sat in boxes named `other` while their captions were named correctly
— `Net Wt.` found, `: 1 KG` not; `Batch No.` found, `MKM A068891` not. That is
the caption-to-value association gap already measured on 2026-09-10 (the MRP
numeral unassociated on 11 of 38 frames, `associate.py` reaching 4x line height
against observed gaps of 4.3-9.2). It is a known defect with a known cause and
it is not the classifier failing to name text; it is two boxes that were never
joined.
