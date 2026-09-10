# The photo corpus — what arrived, and what it can be used for

**Received 2026-09-07: 469 photographs, ~207 distinct products, 70 MB.**
**Received 2026-09-09: 231 camera originals covering 221 of them** — see
*The originals arrived* below, which supersedes the WhatsApp finding for
those 221 frames and leaves it standing for the other 248.
Audited with `scripts/audit_corpus.py`; raw output in `data/corpus/audit.json`
and `data/corpus/audit_per_image.json`, flagged frames rendered to
`data/corpus/review_sheet.jpg`.

This document exists because the corpus is good for most of what we need and
unusable for one specific thing, and confusing the two would waste a week.

## What the audit found

| Measurement | Result |
|---|---|
| Readable images | 469 / 469 |
| Exact duplicate files | 15 pairs (30 files, 15 redundant) |
| Genuinely blank frames | **1** |
| Frames under 640 px | 0 |
| Exposure-clipped | 5 |
| Orientation | 385 portrait, 84 landscape |
| Resolution | median 1.15 MP, **max side never exceeds 1600 px** |
| EXIF present | **0 / 469** |
| Progressive JPEG | 452 / 469 |

The audit's own "distinct" range (436–451) is **not** a product count and the
script now says so on the line that prints it. A perceptual hash compares
layout, and two faces of the same carton look about as alike as two unrelated
cartons — angles are precisely what dHash cannot merge. The photographer's
count of ~207 products is the authoritative one; the range only bounds how much
redundancy sits in the set, which is what a train/test split needs to know.

The curation was good. Of 62 frames the audit flagged for review, 61 turned out
to be real product photographs — the heuristic was over-eager, not the corpus
dirty. Hindi and bilingual packs are well represented, and so is non-food:
toothpaste, an LED bulb, shampoo, face wash, cosmetics, a soap bar.

## The one real problem: these went through WhatsApp

Four measurements say so together, and they are conclusive:

1. **No image exceeds 1600 px on its long side.** Not "most" — none. A phone
   camera produces 3000–4000 px; a hard ceiling at exactly 1600 is a
   transcoder's, not a camera's.
2. **Every single file has had its EXIF stripped.** 0 of 469 retain camera
   model, focal length, capture time or orientation.
3. **452 of 469 are progressive JPEGs.** Phone cameras write baseline JPEG.
   Progressive is a re-encoder's output.
4. **Median file size 132 KB**, with quantisation tables around JPEG quality
   70–80 and chroma subsampling.

### What this costs us, precisely

**Nothing, for detection and segmentation.** RTMDet-Ins-tiny trains at 640 px.
Every one of these images is comfortably above that, and the compression
artefacts are the same ones a real scan will carry, since officers photograph
packages on phones. Training the detector, the panel segmenter and the field
classifier on this corpus is not a compromise — it is training on the
distribution we will actually see.

**A little, for recognition.** JPEG quantisation at quality ~75 attacks exactly
the thin strokes that small print is made of, and the smallest mandatory
declarations on a 1600 px frame sit near the legibility floor. Usable for
fine-tuning; expect the CER measured here to be pessimistic against a
locally-captured image.

**Everything, for millimetre ground truth.** §18b U1 — the day-7 go/no-go —
requires MAE ≤ 0.15 mm and p95 ≤ 0.25 mm on letter heights. At 1600 px across a
150 mm package that is roughly 10.7 px/mm, so a 1 mm letter is about eleven
pixels tall and a 0.15 mm budget is under two pixels. Sub-pixel corner
refinement can work at that scale; **JPEG re-compression on top of it cannot**,
because the 8×8 DCT blocking sits at the same spatial frequency as the
measurement. None of these frames contains a ChArUco card either, so they are
tier C throughout and 3 of the 31 rules would go dark regardless.

**U1 needs its own photographs and always did** — 40 frames, ruler-measured,
with the marker card in shot. That set is separate from these 469 and is still
outstanding.

## What we need, and what it is for

| Needed | Why | Blocking |
|---|---|---|
| The **originals** of these 469, transferred without a messaging app | Recovers ~4× linear resolution and EXIF; makes the corpus usable for recognition fine-tuning and for a real capture-quality baseline | No — detector training can start now |
| **40 ruler-measured photos** with a printed ChArUco card in frame | §18b U1, the day-7 millimetre go/no-go | **Yes**, for U1 only |
| **20–30 non-compliant / negative frames** | §16 wants 15% negatives; see below | No — user is supplying |

Google Drive, a zip over email, or a USB copy all preserve the originals. Any
messaging app repeats the transcode.

## On the negative set

The 20–30 "incorrect" images are not a loss-function trick — they are the
hardest and most valuable part of the corpus, and they do two distinct jobs that
should not be mixed:

**Frames with no package** (a shelf, a floor, a hand, a wall) train the
*detector* to return nothing. Section 4's second exit path — "no package,
~110 ms" — only exists if the detector can decline. A detector that has only
ever seen packages finds one in a photograph of a countertop, confidently.

**Frames with a package that genuinely breaks a rule** — a missing MRP, an
absent net quantity, no manufacturer address, print below the Rule 7(2) height —
are not detector training at all. They are *end-to-end* test cases, and they are
the only way to show a `FAIL` is produced for the right reason rather than
because OCR missed a line. That distinction is the whole `NO_DATA` vs `FAIL`
split: absence of evidence is not evidence of a violation, and a real violation
is the only thing that proves we can tell the two apart.

So when the negatives arrive, it helps to know which of the two each one is. If
a pack genuinely violates something, a one-line note on *what* is wrong turns it
from a photograph into a labelled test case.

## The originals arrived — 2026-09-09

**231 camera originals, 909 MB, two devices.** Ingested with
`scripts/ingest_originals.py`, which matched each one to the transcode it
replaces by dHash and wrote `data/manifest.json`.

| | |
|---|---|
| Unique originals received | **231** |
| Devices | LAVA LXX504 (151, 1840×4096) · Apple iPhone 13 (80, 4032×3024) |
| EXIF intact | **231 / 231** — make, model, capture time, focal length |
| Transcodes now superseded | **221 of 469** |
| Transcodes still with no original | **248** |
| Live corpus frames | **479** (231 millimetre-grade + 248 transcode-only) |

Two things about the delivery are worth recording. A 324 MB zip inside it held
151 files that were **byte-identical** to 151 of the loose ones — the ingest
deduplicates by SHA-256, so unpacking it by hand would have doubled a third of
the corpus silently. And the dHash match distances were 0 for 290 of 362
candidate pairs with a worst case of 5 bits, which is a transcode-pair
distribution rather than a coincidence one; the manifest keeps every distance so
the tail can be re-examined without re-running the ingest.

### What the resolution actually buys — measured, not asserted

40 matched original/transcode pairs, both run through the text detector, region
heights compared:

| | transcode | original | |
|---|---|---|---|
| Linear resolution | 1600 px | 4032–4096 px | **2.56×** |
| Median text line | 33.4 px | **86.7 px** | 2.6× |
| **10th-percentile line** | **17.6 px** | **52.9 px** | **3.0×** |
| Text regions detected | 1,199 | 1,216 | +1% |

The last row is the important one and it is the one that looks least impressive.
**Detection was never the bottleneck** — the detector finds essentially the same
regions in both, because a text region is a blob and a blob survives a
downscale. What changes is what the *recognition* head is handed. PP-OCR's
practical floor is around 16 px of line height, and the bottom decile of every
transcoded frame was sitting at 17.6 px: technically above the cliff, with no
margin for a curved surface, a glare patch or a fold. In the originals that same
decile is at 52.9 px.

So the honest summary of what the originals fix is: *the small print*. Which is
the print Rule 7(2) is about.

### What they do not fix

**U1 is unaffected.** The §18b millimetre error is measured on
`data/test_split/`, whose 40 frames were never WhatsApped — they are 3072×3072
with EXIF intact and always were. `RESULTS.md` already rejected resolution as
the discriminator there: the found and not-found populations overlap almost
completely (median glyph 22.8 px against 19.3 px). That gap is the capture
protocol — the marker card fills the frame instead of the declaration — and no
amount of sensor resolution changes it.

**The corpus is not complete.** 248 of the 469 still have no original behind
them, so a little over half of what we hold is millimetre-grade. Every frame
carries `millimetre_grade: true` or `false` in `data/manifest.json`, and
`docs/annotation-guide.md` tells annotators to work the `true` ones first.

## Housekeeping worth doing

- **15 exact duplicate files.** Listed in `audit.json` under
  `exact_duplicate_groups`; the second file of each pair is byte-identical to
  the first. Harmless in training but they must not straddle a train/test split,
  which would leak.
- **1 blank frame**: `WhatsApp Image 2026-09-07 at 19.51.48 (1).jpeg`
  (edge density 0.0004 — nothing in shot).
- **20 near-duplicate groups**, 53 frames. These are the same shot rather than
  the same product, and they belong on the same side of a split too.

Nothing here is deleted automatically. The audit ranks and reports; a person
confirms.

## A note on the audit script itself

The first version measured sharpness with a plain variance-of-Laplacian and
ranked a *featureless dark blur* at the corpus median, because sensor noise in
an underexposed frame is high-frequency content and the metric cannot tell it
from a printed serif. It now denoises with a 3×3 median first and reports edge
density alongside, and requires both signals to agree before calling a frame
featureless — low edges alone would flag a plain white carton, low sharpness
alone would flag a soft photograph of a real pack.

Every threshold in it is a percentile of *this* corpus, never an absolute. A
dark navy tea box photographed perfectly scores below a busy biscuit wrapper
photographed badly, so an absolute cut-off silently discards good photographs of
plain packages. The script shortlists; it does not decide.
