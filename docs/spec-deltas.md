# Spec deltas

Places where the implementation had to go beyond, or diverge from, the literal
text of [AKSHAR.md](../AKSHAR.md). Every entry states what the plan says,
what the code does, and why.

This file exists so that no change to the plan happens silently. If a delta is
not listed here, it is a bug.

> **Plan switched 7 September 2026: MAAPDAND → AKSHAR.** Deltas recorded below
> were written against the superseded plan and some no longer describe a
> divergence — most obviously anything about the ₹5 coin, which the new §8b
> replaces with a printed ChArUco marker. They are kept rather than deleted,
> because a delta that was later resolved by a plan change is still a record of
> why the code looked the way it did. Entries affected are marked **superseded**
> in place. The plan-level diff is in [plan-migration.md](plan-migration.md).

---

## D1 — `PackageContext` is a new model

**Plan:** §9 freezes `DeclarationSet` with six fields and no package metadata.

**Code:** [`contracts/context.py`](../contracts/context.py) adds `PackageContext`,
passed alongside `DeclarationSet` into the engine.

**Why:** §13's applicability gate and nine individual rules reference facts that
are properties of the *package*, not of any declaration:

| Rulepack key | Needs |
|---|---|
| `exclude_if.category_in` | `category` |
| `exclude_if.consumer_type_in` | `consumer_type` |
| `package_type_rules` (Rule 24) | `package_type` |
| `exclude_if.net_quantity_gt` | parsed quantity |
| `skip_if.surface_in` (Rule 9(1)(b)) | `surface` |
| `variant_key: embossed` (Table I) | `declaration_style` |
| `only_if.sticker_or_overprint_detected` (Rule 18(5)) | that flag |
| `keyed_by: category` | `category` |
| Rule 7(4) disapplication | `other_law_mandates` |

Without it the six gates cannot run, and §13b is explicit that running retail
rules against a wholesale carton manufactures four false violations per scan.

Kept in a separate module from `declarations.py` so the frozen contract stays
visibly frozen.

---

## D2 — Additive fields on `Declaration`

**Plan:** §9 lists nine fields on `Declaration`.

**Code:** adds `char_boxes`, `numeral_box`, `is_embossed`.

**Why:** three checks the plan mandates cannot be implemented without them.

- `min_width_ratio` (Rule 7(3) proviso) compares each **character's** width to
  its height. Without per-character boxes there is nothing to compare, and the
  check would have to return NO_DATA always — which would silently delete one
  of the two scale-free rules the plan calls a safety net.
- `clear_space` (Rule 8(1) proviso) measures from the **numerals**, not from
  the whole declaration including "(inclusive of all taxes)". §16's annotation
  rules say this explicitly for measurement; the contract needed somewhere to
  put it.
- `is_embossed` selects the `embossed_mm` column of Table I.

All three default to empty/false, so nothing that ignores them breaks. Where
`char_boxes` is empty the check returns NO_DATA rather than guessing.

---

## D3 — `raw_text` on `DeclarationSet`

**Plan:** not mentioned.

**Code:** optional `raw_text` carrying the full concatenated label text.

**Why:** the locate/validate split needs it. A locate pattern must be able to
see text the classifier put in `other` — otherwise a mis-classified but clearly
printed MRP produces "MRP not declared", which §13 names as the single most
dangerous failure the system can produce.

---

## D4 — Additive fields on `Verdict`

**Plan:** §9 lists eight fields.

**Code:** adds `measured`, `threshold`, `tolerance`, `respondent`, `advisory`,
`suppressed_by`.

**Why:** each is required by something the plan asks for elsewhere.

- `measured`/`threshold`/`tolerance` — §11 requires the scan screen to show
  measured heights with tolerances, and §13 requires REVIEW near thresholds.
- `respondent` — Rule 18(5) is the **dealer's** offence, not the
  manufacturer's. §13b: "a different respondent on the notice, which matters
  for the report."
- `advisory` — §13c requires the five unit-symbol checks to render in a
  separate advisory block.
- `suppressed_by` — §13's `suppresses:` key needs somewhere to record that one
  measurement produced one verdict.

---

## D5 — Extension rules kept in a separate list

**Plan:** §13's rulepack has 31 rules. §13b then names further provisions it
calls "worth building" (Rules 9(2), 9(3), 14, 16, 17, 31(1)-(2)) which never
made it into the YAML.

**Code:** they are implemented, in a separate `extension_rules:` block, using
only the thirteen permitted check types.

**Why:** the user asked for the complete plan with nothing skipped, and §13b
does ask for these. Keeping them in a second list means the counts quoted
throughout the plan — 31 rules, 28 surviving tier C, 13 check types — stay
true and auditable. `evaluate(..., include_extensions=False)` reproduces the
core pack exactly.

---

## D6 — `unit_by_commodity` table did not exist

**Plan:** `LMPC.QTY.UNIT_BY_COMMODITY` references `table: unit_by_commodity`,
but §13 never defines it. §13b says it has twenty-six entries and names five.

**Code:** the table is created with the five named entries marked
`confirmed: true` and the remainder marked `confirmed: false`, under
`verification: pending_gazette`.

**Behaviour:** an unconfirmed entry produces **REVIEW**, never FAIL. An
unlisted commodity produces **NOT_APPLICABLE**, never FAIL.

**Why:** §13a's whole discipline is that a value which cannot be traced to a
gazette does not get asserted. Shipping twenty-one guessed entries at FAIL
severity would be exactly the vendor-blog error the register exists to prevent.

**Blocked on:** the Fourth Schedule of LMPC 2011, read page by page.

---

## D7 — `standard_pack_sizes` grammar

**Plan:** §13 writes entries like `"+100 to 1000"` and `"+50"` with no grammar.

**Code:** documented in the rulepack and implemented in
[`rules/checks/in_table.py`](../rules/checks/in_table.py):

| Entry | Means |
|---|---|
| `250` | exactly 250 |
| `"+100 to 1000"` | then in steps of 100, up to and including 1000 |
| `"+1000"` | then any positive multiple of 1000 |
| `"+50"` | then any positive multiple of 50 above the last literal |

The table is marked `pending_gazette` (the plan itself calls it an extract), so
a mismatch is REVIEW rather than FAIL.

---

## D8 — `value_in_range` needed a second arm

**Plan:** §13 specifies `min_value: 0.1`, `max_value: 1000` from National
Standards Third Schedule item 10. §13b separately says *"A pack declaring
'0.5 kg' instead of '500 g' is non-compliant."*

**Problem found in testing:** `0.5` is inside `[0.1, 1000)`, so the range check
alone passes `0.5 kg`. The plan's own example would not have been caught.

**Code:** the check now has two arms —

1. item 10: the numerical value must fall in `[0.1, 1000)` — catches `1500 g`;
2. LMPC Rule 13(2)-(3): unit **selection** by magnitude, sub-kilogram in grams
   and sub-litre in millilitres — catches `0.5 kg`.

Both cite their own authority in the verdict.

---

## D9 — "28 of 31 rules" is about scale-independence, not enabled state

*(The reference object named below is superseded — AKSHAR §20 now asks "what if
the officer has no **marker card**?". The arithmetic and the conclusion are
unaffected: the question is what happens with no scale, whatever supplies it.)*

**Plan:** §20 answers "what if there's no scale reference?" with *"Twenty-eight
of the thirty-one rules still run."* §13c ships `LMPC.UNIT.LITRE_SYMBOL` **disabled**
because the litre symbol is disputed.

**Arithmetic:** 31 rules exist. 3 require millimetres. So 28 are
scale-independent — the claim is exactly right on that axis. But only 30 are
*enabled* by default, so 27 actually execute at tier C.

**Code:** the test asserts the claim on the axis it is about (31 total, 3
needing millimetres, 28 scale-independent) and separately asserts that nothing
except those three goes dark for want of scale.

**For the demo:** say *"twenty-eight of the thirty-one rules need no scale at
all"* rather than *"twenty-eight still run"*, which invites the follow-up.

---

## D10 — Check modules named after check types

**Plan:** §9 says `rules/checks/  # one file per check type`.

**Code:** literally thirteen files, each named for its check type, each
exporting `check()`. `tests/test_boundaries.py` asserts the registry and the
directory agree and that there is no fourteenth.

---

## D11 — the perceptual hash runs on a cheaply-flattened frame, not the raw one

**Plan:** §4's table lists `pHash + cache lookup` at 18 ms as the *first*
stage, and `Rectify` at 55 ms several rows below it, after detection. Read
literally that means the hash is computed on the raw camera frame.

**Problem:** a raw-frame hash is not invariant to the camera angle, and the
camera angle is the thing that varies most between two photographs of the same
packet. §15b rejects dHash and aHash for being lighting-sensitive under
"the lighting variation of shop photography"; perspective is the other axis of
exactly the same problem, and it is larger.

**Measured** (`tests/unit/test_vision_pipeline.py::test_phash_survives_the_angle_it_is_meant_to_survive`):

| Hashed on | Same pack, different angle | Different pack |
|---|---|---|
| Raw frame | **26** | 24 |
| Pre-normalised | **6** | **24** |

At a Hamming ≤ 8 threshold the raw-frame hash misses the cache on every
re-photograph, and 26-versus-24 means it cannot separate "same pack, moved the
camera" from "different product" at *any* threshold. Exit zero would
essentially never fire, and exit zero is what §4's whole speed argument rests
on.

**Code:** `vision/identify/phash.py::normalise_for_hash` finds the label quad
on a 256 px thumbnail and warps it before hashing. The resolution of the
apparent conflict is that §4's 55 ms is the cost of rectifying at *full*
resolution, which is only needed for measurement; the thumbnail flatten
measures **4.0 ms** (`bench/test_vision_latency.py`), well inside the 18 ms
budgeted for this stage. The expensive rectify still runs only on a cache miss.

---

## D12 — `OcrLine` carries its own measurements

**Plan:** §9 freezes `Declaration` with `height_px`, `numeral_box`,
`char_boxes` and `contrast_ratio`. It does not describe the intermediate type
between recognition and classification.

**Code:** `vision/types.py::OcrLine` carries `cap_height_px`, `numeral_box` and
`contrast_ratio` alongside the recognised text.

**Why:** all three are measured from the crop, and the crop exists during the
OCR pass. The alternative is for `classify` to re-crop every region from the
rectified image a second time purely to measure it. §4 gives the whole scan
561 ms; paying twice for the same pixels to keep an intermediate struct tidy is
not a trade worth making. Nothing about the frozen `Declaration` contract
changes — this is a type upstream of it.

---

## D13 — the field classifier reuses the rulepack's `locate` patterns

**Plan:** §13 defines `*_locate` patterns for the rules engine ("locate, then
validate"). §14 separately says regex handles MRP, dates, net quantity, batch
and country of origin in the classifier. The plan does not say whether these
are the same patterns.

**Code:** `vision/classify/regex_tier.py` loads the rulepack and uses its
`mrp_locate`, `net_quantity_locate`, `mfg_date_locate`, `consumer_care_locate`
and `manufacturer_locate` patterns directly.

**Why:** a locate pattern's stated job is *"is this declaration on the pack?"*,
which is the classification question word for word. Two separate definitions
could drift, and the drift would surface as a rule reporting a declaration
missing while the report displays it on screen — the most confusing possible
failure for an officer. It also inherits the bilingual behaviour for free: the
rulepack stores one regex per script and tries both, so a Hindi-only label is
classified by the Devanagari pattern without the classifier deciding a language
in advance.

This does **not** breach the extraction/decision wall, which runs the other
way: `vision/` may import `rules/` (a pure layer, no OpenCV), while `rules/`
importing `vision/` would drag OpenCV into the decision layer and break the
listing-text channel. `tests/test_boundaries.py::test_rules_never_import_vision`
asserts the direction.

**Two ordering bugs this surfaced,** both caught by tests and both worth
recording because each silently deleted a mandatory declaration:

- `mfg_date_locate` contains `manufactur\w*`, so with `mfg_date` ranked above
  `manufacturer`, "Manufactured by: Acme Foods Pvt Ltd, Bhubaneswar" was
  classified as a manufacturing *date*. The Rule 6(1)(a) name-and-address
  declaration vanished.
- With `batch` ranked above `mrp`, the line "MRP Rs. 45.00 Batch 24MRP07" was
  claimed by the batch pattern and the MRP vanished. A batch code standing
  alone is still caught earlier, by the hard-negative pass.

---

## D14 — bcrypt is called directly; `passlib` is not used

**Plan:** §15b lists `passlib[bcrypt]>=1.7.4` in the backend stack.

**Problem:** passlib 1.7.4 is the current release and dates from October 2020.
Its bcrypt backend probes the library during initialisation by hashing a
73-byte string; bcrypt 4.1+ raises `ValueError: password cannot be longer than
72 bytes` instead of truncating. The result is not a subtle incompatibility —
the **first call to `hash_password` fails**, and every test in `test_api.py`
errored at collection.

**Code:** `api/security.py` calls `bcrypt` directly. Three lines, one fewer
dependency, and no unmaintained wrapper between us and the primitive.

**And one thing was fixed rather than inherited.** bcrypt silently ignores
everything past the 72nd byte of a password, so two passphrases sharing a long
prefix are the *same credential*. That is not hypothetical for this project: a
Devanagari passphrase reaches 72 bytes in about 24 characters. `_prehash` runs
SHA-256 then base64 first, giving bcrypt a fixed 44-byte input in which every
byte of the original participates. base64 rather than the raw digest because a
raw digest can contain a NUL and bcrypt truncates at the first one, which would
quietly shrink the key space.

**Alternative rejected:** pinning `bcrypt<4.1` to satisfy passlib. That freezes
a security-relevant library at a 2023 release to keep a 2020 wrapper working,
in a system holding enforcement evidence.

---

## D15 — `synced_at` is inside the record hash

**Plan:** §10 lists `synced_at` as a column; §6 does not say what is hashed.

**Bug this records.** The first implementation of `InMemoryScanStore.save`
stamped `synced_at` onto the row *after* `append()` had hashed it. Every stored
record then carried a field its digest had never seen, and `verify_chain`
reported `CONTENT_ALTERED` on records nobody had touched — caught by
`test_the_chain_stays_verifiable_across_a_partial_replay`.

This is the failure `evidence/chain.py` names as **worse than having no chain**:
*"a false alarm teaches people to ignore the alarm."* Here it would have taught
a department to ignore an evidence-tampering warning.

**Code:** the field is set before hashing, and the invariant is stated rather
than patched — **everything in a stored row is inside its hash.** An exclusion
list would also have worked and is much harder to keep true, because every new
column is a chance to forget one.

`tests/unit/test_evidence_chain.py::test_a_column_added_after_hashing_is_detected`
guards it at the chain level too, so the next store implementation cannot
rediscover it.

---

## D16 — `scans.category`, so a verdict can be reproduced

**Plan:** §10's `scans` table carries `sku_id`; `category` lives on `skus`.
§11's categories view aggregates non-compliance per category.

**Problem.** The category is not a property of the SKU as far as a verdict is
concerned — it is an *input to the decision*. `PackageContext.category` gates
which rules may lawfully be applied (Second and Fourth Schedule commodity
tables, the unit-symbol tables, the Rule 7(2) height bands). Two things follow:

1. A scan with no matched SKU still has a category, because the officer or the
   listing supplied one and the engine used it. Under the SKU-join alone those
   scans vanish from §11's Q4 entirely — and unmatched scans are exactly the
   ones a repository is thinnest on.
2. Without it stored, **a verdict cannot be re-derived from its own record.**
   §14 is unambiguous about what that costs: *"a finding you cannot reproduce is
   a finding you cannot defend."* The rulepack version and the model versions are
   already stored for this reason; the category belongs beside them.

**Code:** `scans.category TEXT`, nullable. `InMemoryScanStore._facts_for` reads
the scan's own category first, falls back to the joined SKU's, and only then to
`"unclassified"` — so the dashboard tells the truth about what was actually
evaluated rather than what the SKU row happens to say today.

Additive and nullable, so no existing row or query changes meaning.

## D17 — `bulk_jobs`, because a 202 needs somewhere to point

**Plan:** §12 specifies `POST /scans/bulk`; §8c puts bulk ingestion on the low
queue and says *"nothing delays the verdict"*. No table is named for tracking
the resulting work.

**Problem.** The request returns before any of the images are scanned — that is
the whole point of the low queue. So the response is a receipt, and a receipt
with nothing behind it leaves a client polling an endpoint that cannot answer.
Worse, the obvious substitute is wrong: deriving progress by counting the
`scans` rows a job produced can never reach the total, because a **failed**
image produces no scan row at all. One unreadable file in a folder of three
hundred then yields a job that is permanently at 299/300 with no error anywhere
— a hang, not a failure, and the hardest kind to be handed at 9 pm.

**Code:** `bulk_jobs` (counters plus a JSONB list of human-readable errors) and
`bulk_job_scans` (the scans it produced, with a real foreign key so a scan
cannot be deleted out from under the receipt claiming it). `BulkJobStore` in
`api/repository.py` is the Protocol; `record_result` must be atomic, since it is
called from several Dramatiq worker threads at once and the obvious
read-modify-write loses increments.

Additive: two new tables, no existing row or query changes meaning.


## D18 — the `verdicts` table stores the columns the dashboard counts on

**Plan:** §10's schema sketch gives `verdicts` its rule id, citation, status and
severity. §11 then defines the dashboard's three counting rules — advisory
findings are not non-compliance, a suppressed verdict is not counted at all, and
`NO_DATA` is neither a pass nor a failure — and §13 requires the measured height
to be printed with the tolerance that decided FAIL against REVIEW.

**Problem.** Those two halves did not meet. `contracts.Verdict` carries
`advisory`, `suppressed_by`, `message`, `respondent`, `measured`, `threshold`
and `tolerance`; the table stored none of them. Everything worked in the
in-memory store, which keeps the whole dict — so the failure appeared **only on
Postgres**, and appeared quietly: `row["advisory"]` came back missing, every
advisory verdict counted as a contravention, and the country's most-broken rule
became "capitalising the litre symbol". A report re-rendered from the database
would also have printed "0.82 mm, required 1 mm" with no error bar, dropping the
number that chose REVIEW over FAIL.

Found by the SQL contract test, which is the only place the two backends are
asked the same question.

**Code:** seven columns added to `verdicts`, plus
`verdicts_countable_idx ... WHERE NOT advisory AND suppressed_by IS NULL` so the
filter the dashboard applies to nearly every query is the one the index serves.
`api/repository.normalise_verdict` gives both stores one shape, because the
underlying bug was that they returned two.

Additive: new columns on an existing table. Nothing that was stored before
changes meaning.


## D19 — U1 also has to check that the error bar is honest

**Plan:** §18b sets U1 as mean absolute error ≤ 0.15 mm and p95 ≤ 0.25 mm on the
40 ruler-measured frames.

**Problem.** Both are measures of *accuracy*, and the decision the system
actually makes is not "what is the height" but "is the height above the
threshold". `rules/checks/min_height_mm.py` makes that decision with a band:
a measurement within `tolerance` of the threshold is REVIEW, not FAIL. So the
**tolerance** is what stands between a compliant pack and a wrongful conviction,
and it is the only part of this that generalises to the thousands of packets
nobody will ever measure with a rule.

Nothing in §18b checks it. A system whose tolerance is systematically five times
too narrow can post an excellent MAE while turning every borderline compliant
pack into a FAIL, and the acceptance criterion as written would pass it.

**Code:** `scripts/u1_report.py` reports **coverage** alongside MAE and p95 —
the share of frames whose true height fell inside the tolerance claimed for that
frame — and requires ≥ 90%. It also reports **signed bias** separately from
absolute error, because a constant offset means the printed card is the wrong
size rather than the measurement being noisy, and absolute error cannot tell
those apart. That distinction is not hypothetical: it is exactly how the
25 mm-square/18.75 mm-marker card bug presented.

The report additionally **names** every frame whose truth fell outside its
tolerance, because at n=40 the 95th percentile is the 38th value and one or two
blunders sit below every threshold here. That is the resolution of the
statistic, not a bug, and the response is a person reading those frames rather
than a fourth gate invented on the spot.

Additive: a stricter report against the same 40 frames. §18b's two criteria are
unchanged and still both required.

---

## D20 — one composited annotation instead of four to eight separate crops

**Plan:** §6's storage table lists the derived tier as *"the 4–8 declaration
ROIs, ~40 KB"*, and §13 asks the per-product report to carry *"the annotated
photo"*.

**Problem.** Taken literally those are two different artefacts, and only one of
them is the thing the report can actually lay out. A page of four to eight
disconnected crops shows a reader each declaration in isolation — which loses
the fact that the MRP sits on the principal display panel, and that is itself a
finding under Rule 8(1). It also costs eight objects and eight round trips to
render one page.

**Code:** `evidence/annotate.py` draws every declaration box on the rectified
label and `evidence/storage.annotation_key` stores the one image, still on the
`derived_crop` tier, at the same two-year retention, in the same derived bucket,
at roughly the same size. `crop_key` is unchanged and unused for now: a future
reviewer UI that zooms one declaration will want the individual crops, and
nothing here forbids storing both.

Two consequences worth naming, because neither is obvious:

*The exhibit is the rectified label, not the photograph.* Every
`Declaration.box` is in rectified coordinates — `contracts/declarations.py` says
so, because a box in raw camera space cannot be converted to millimetres by a
single scalar. Drawing those numbers onto the original frame would put every
rectangle somewhere plausible and wrong.

*It is drawn at scan time and never re-derived.* Rectifying the same photograph
again at report time would find its own label quad, and a quad differing by a
few pixels moves every box, so the exhibit would point at text the measurement
never touched.

Additive: a new key convention on an existing tier. No retention rule, bucket or
schema changes.

---

## D21 — the annotation is redacted separately from the photograph

**Plan:** §18 requires faces blurred on upload, and `evidence/redact.py`
implements it with the geometric rule that separates a bystander from printed
artwork: a face inside the package box is on the packaging and is kept.

**Problem.** The annotated label is warped out of the **unredacted** frame, so
the blur applied to the evidence copy is in different coordinates and does not
carry across. A derived image published in a report could therefore contain a
bystander whom the evidence copy had already protected — the privacy failure
arriving through the one artefact most likely to be circulated.

**Code:** `api/scanning.prepare_annotation` runs `redact_faces` again on the
drawn image, and switches the package box on how rectification actually went:

- `marker`, `quad` or `detector_box` — the frame *is* the package, so the box is
  the whole image and a printed face is kept, exactly as on the evidence copy.
  Blurring the Amul girl here would delete label content from the picture whose
  purpose is to show the label.
- `identity` — no warp happened, the frame is still the whole photograph, and
  anybody standing behind the shelf is a bystander again.

It fails closed on the same rule as the evidence copy: no redaction, no stored
image, and the scan record is unaffected.

Additive: a second call to an existing function. No new policy.

---

## D22 — the corpus is 5,044 chunks, not 1,700; the conclusion drawn from 1,700 still holds

**§15 says:** *"Twelve gazette documents, 498 English pages, roughly **1,700
clause-level chunks.** At 384 dimensions that is 2.7 MB as float32"* — and then
uses that number to reject an index: *"Exact cosine over 1,700 vectors takes
about 1.3 ms on CPU. An HNSW or IVF index would take longer to build than brute
force takes to run."*

**What is actually there**, after ingesting every gazette in
`rules_and_acts_docs/`:

| | §15 | measured |
|---|---|---|
| documents | 12 | **13** (two files are byte-identical re-uploads of others) |
| pages | 498 English | **838 held, 448 readable English** |
| chunks | ~1,700 | **5,044** |
| float32 | 2.7 MB | **7.4 MB** |

Two causes, and only one of them is a surprise. The plan did not count the
655-page General Rules, which is half the corpus by page count. And the chunker
**nests**: a rule is emitted whole *and* again as each of its sub-rules,
clauses and provisos, because §15 requires exactly that — *"one chunk per
sub-rule, provisos and explanations attached to their parent"* — so a rule with
six sub-rules yields seven chunks, not one.

**The delta is in the numbers, not in the decision.** Exact cosine over 5,044
vectors is a few milliseconds rather than 1.3, and measured end-to-end tier-2
latency is 47–67 ms against §15's ~40 ms estimate. An HNSW build still costs
more than the scan, so `rule_chunks` carries no vector index and no GIN index
on its `tsvector`, exactly as planned. Nothing about "we sized the corpus before
choosing an architecture" stops being true — the sizing was three times off and
the architecture it chose is still the right one, which is a better outcome than
being right about the number.

**What it does change:** §15's *"the whole corpus fits in browser memory"* is
7.4 MB float32 rather than 2.7, or 1.9 MB quantised to int8. Still fine for the
PWA, and worth knowing before the offline bundle is budgeted at §5's ~50 MB.

---

## D23 — OCR'd statute is searchable but not quotable

**§15 does not distinguish** between clauses by how they were obtained, because
when it was written the corpus was one document with a publisher's text layer.

**Ten of the thirteen gazettes carry no extractable text at all** — measured,
not assumed: every page of them returns under 200 characters from
`page.get_text()`. Of the three that do carry one, `lmpc_2011` is a clean
publisher's layer and is trusted; `approval_of_models_2019_amdt` is probed per
page; and `model_test_labs_2014` encodes its Hindi in a legacy non-Unicode font,
so its layer returns `panrrcur-ens 9F LN0HPII` where the page prints
*PARTICULARS OF LABORATORY* — our own OCR reads that page better than its text
layer does.

That leaves **405 of the 448 readable pages read by a recogniser** averaging
0.92–0.97 confidence per line. That is good, and it is not verbatim. A wrong
digit in a height threshold is a confident, specific, wrong notice served on a
manufacturer.

So every `Chunk` and every `Citation` carries how its page was read
(`retrieval/provenance.py`), tier 1 and tier 2 both return it, and OCR'd text
is displayed with *"Machine-read from a scanned gazette. Verify against the
page before citing."* The alternative — presenting both identically — is the
overclaiming the project's own source register warns about: *"an earlier
register wrote 'read' against a document that had only been sampled."*

Only the Packaged Commodities Rules, the primary source and the one behind 29 of
the pack's 34 citations, is quotable without the caveat.

## D24 — a Schedule is a citable unit, and it does not carry its items

**§15 names the chunk boundaries** as *"rule, sub-rule, clause, proviso,
Table"*, and sets the nesting rule that each level is emitted on its own and
included in its parent, so `Rule 8` answers a question about Rule 8 and `Rule
8(1) proviso` answers a narrower one.

Schedules are not in that list, and the omission cost more than it looks. A
Schedule was treated as a boundary — something that changed how the *next* rule
number was read — and never as a unit in its own right. Three consequences,
none of them visible from the outside:

1. Every line arriving while no rule was open was dropped, and inside a Schedule
   that is most of it. The maximum-permissible-error table, the standard pack
   sizes, and two thirds of the National Standards Rules were never chunked.
2. 114 chunks pointed at a `parent_ref` that had no chunk, so an officer
   following an item up to its Schedule got nothing.
3. A document with no numbered rules produced no chunks at all — which silently
   excluded three of the thirteen instruments.

So `Schedule` and `Preamble` are chunk kinds. **A Schedule's chunk is its front
matter, not its contents**, and that is the one place this departs from §15's
nesting rule. A rule carries its sub-rules because they are one provision read
together — the proviso to Rule 8(1) *is* the clear-space rule, which is §15's
own argument for structural chunking. A Schedule is not that: it is a container
of independent specifications. Carrying its items made the General Rules' Eighth
Schedule a single **416 KB** chunk whose embedding described its first four
hundred words and whose `tsvector` approached the type's one-megabyte ceiling.
The largest chunk is now 42 KB and is a genuine single specification.

Measured consequence: coverage of the text the corpus holds went from 94.51% to
**100.00%**, with no chunk citing a parent that does not exist.

## D25 — the language of a scanned page is decided over the corpus, not the page

**§15 assumes a corpus in one language.** The gazettes are bilingual, printed
Hindi-first, and the recogniser has no Devanagari model — so which half of each
document is readable has to be *decided*, and the decision was made per page
from the density of common English words.

That is a fair question to ask of prose and the wrong one to ask of a Schedule,
which is a table of unit names and symbols. It dropped 19 English pages,
including the National Standards Seventh Schedule that rule 18 cites, and
admitted 20 pages of mojibake.

Deciding it needs a vocabulary, and the only vocabulary that knows what `erg`,
`poise`, `deuteron` and `Vanaspati` are is the corpus itself. So classification
is a **second pass**: every page is recognised, a vocabulary is learned from the
pages no criterion disputes — 85% Latin, confidently read, no ideographs, which
mojibake cannot reach — and every page is then judged against it on two signals
that must agree. An absolute count of English words, because a Hindi page's
English masthead scores 1.00 on a ratio; and ideographs per English word,
because Devanagari is what this recogniser turns into Chinese.

The cost is that ingestion can no longer decide a page in isolation. That is
inherent: the question *"is this readable English"* was never answerable from
one page of a bilingual gazette.

## D26 — a provision has to be citable, not merely present

**§15 defines a chunk as `{doc_id, rule_ref, parent_ref, text}`** and treats
retrieval as solved once the text is in one. Coverage — every word of every page
reaching some chunk — was therefore taken as the completeness test, and it
reached 100%.

It is not the completeness test. The National Standards Rules sat at 100%
coverage while rules 4, 7 and 8 did not exist as citations. The gazette prints
those three as a bare `8.` on a line of its own, with sub-rule `(1)` beginning
the next line, and a rule with no heading did not open. Their sub-rules were
then read as a **second** `Rule 3(1)`, `Rule 3(2)` and `Rule 6(2)`, so the metre
and the kelvin were filed under the metric-system rule and the second. Nothing
downstream could see it: the text was fluent, the citation well-formed, and the
only symptom was that one ref answered twice.

So the corpus is audited on two questions, not one. Coverage asks whether any
statute was lost. **The sequence runs ask whether any provision became
unreachable** — rule numbers, then sub-rule numbers, then clause letters — and
they are what found something. At every level the cause was the same: the
gazette prints a provision in a shape the parser did not read.

- No heading at all: `8.` then `(1)` on the next line.
- A one-word heading: `2. Definitions`, `11. Weights`.
- A colon for a stop: `16: Deposit of Models`.
- A fullwidth bracket where the recogniser preferred one to `(`.
- **The heading carrying its own sub-rule** — `15.Permitted units.(1) The units
  specified...`, which cost 35 rules their sub-rule (1).
- **A provision opening at its own next level** — `(5) (i) No system of units
  other than the International System of Units...`, which is `Rule 13(5)(i)`
  and is cited by the rulepack.
- **`i`, `l` and `1` read as one glyph**, leaving 420 chunks addressable only as
  `(ili)`, `(li)` or `(ll)`.

The last of those is a repair to the transcription rather than to the parser,
and it is bounded tightly for a reason: `(l)` is a clause letter, not a damaged
`(i)`. Rule 2(l) of the Packaged Commodities Rules defines *retail sale*.
Rewriting it broke three of the pack's citations, so the rule now
refuses to touch a single character, refuses pure digits, and accepts only `ii`
and `iii` as results.

`tests/unit/test_retrieval.py` holds all of it.

## D27 — the recogniser can drop a line and report nothing wrong

**§15 treats OCR output as the input to retrieval** and reasons about its
*accuracy* — confidence scores, the `read_as` caveat, what may be quoted. It
does not consider that a line might be missing altogether.

Page 22 of the Approval of Models Rules prints `10. Re-submission of
disapproved model for approval. - (1) Where any model is` in bold. RapidOCR
returns 42 boxes that step straight over it, at 300, 450 and 600 dpi alike, at a
mean confidence of 0.98. The page then reads as though rule 9 ran on into rule
10's body, and rule 10 is not in the corpus at all. No confidence score falls,
because the text that *is* there was read perfectly.

`sweep_gaps` closes it: mark the rows of pixels some box covers, find the runs
nothing covers that are tall enough to hold a line, and read those bands again
on their own. The same recogniser that skipped the line finds it immediately
when the band is all it is given.

Two things make it safe rather than a source of noise. The crop is padded, so it
re-reads its neighbours and returns them clipped; a recovered line sharing 60%
of itself with a line already held is the same print read twice and is dropped.
And a band of blank paper comes back as `tc`, `assia`, `iPpioval`, which a
confidence floor and a minimum length remove.

The cost is one extra recognition pass per gap — about 3 seconds a page against
8 to 17 for the first pass.

