# Annotation guide

For anyone drawing boxes in Label Studio for AKSHAR. Read it once before your
first photograph and keep it open for your first twenty.

Configuration: [`training/detector/label_config.xml`](../training/detector/label_config.xml).
Pre-labels: [`training/detector/tasks.json`](../training/detector/tasks.json).
Corpus and targets: [`data/manifest.json`](../data/manifest.json), AKSHAR.md §16.

---

## Why the rules below are rules

Two annotators looking at the same packet will disagree about roughly a fifth of
what they draw, and the disagreements are not random — they cluster on exactly
the decisions this project's accuracy claim rests on. A model trained on
inconsistent labels does not learn "it depends"; it learns the average of two
incompatible conventions, and then reports the average confidently.

So every rule here exists because there is a specific way to get it wrong that
looks reasonable at the time.

---

## What to draw, per photograph

Five things, in this order. The order matters only in that drawing the package
first makes the rest easier to place.

| # | Label group | What |
|---|---|---|
| 1 | `objects` → `package` | One box per pre-packaged commodity in frame |
| 1 | `objects` → `marker_card` | A box on the ChArUco card, if one is in shot |
| 2 | `panels` | A polygon per visible face: `pdp`, `side`, `back`, `top`, `bottom` |
| 3 | `declarations` | One box per declaration, labelled with its field |
| 4 | `script` | `latin`, `devanagari` or `other`, per declaration |

**Test split only:** the ruler-measured height in millimetres per declaration to
0.1 mm, plus the physical label width and height. That is recorded in
[`data/test_split/ground_truth.csv`](../data/test_split/README.md), not in Label
Studio, and it is the one number in this project no model may ever see.

---

## The seven rules

### 1. Cap height means top of a capital to the baseline

Rule 7(2) sets a minimum *height of letters*, and the height of a letter is not
the height of its bounding box.

```
    ┌── top of the capital  ──────────  ← measure from here
    │
    │   M R P   R s . 4 5 . 0 0
    │
    └── baseline  ───────────────────   ← to here
            g y p                       ← descenders. NOT included.
```

Excluded, always: descenders (`g j p q y`), the dot of an `i`, accents, and the
tail of a comma. Included: the full height of a digit, because digits are
cap-height by construction in every typeface you will meet on a packet.

**Why it is written down.** A box drawn round `MRP Rs. 45.00 (incl. of all
taxes)` and measured corner to corner is 30–40% taller than the cap height,
every time, in the same direction. That is not noise a model averages out — it
is a systematic bias, and it would put every measurement over the legal minimum
and every verdict at PASS.

### 2. The MRP box covers the whole declaration; the measurement uses the numerals

These are two different things and they are recorded separately.

- The **box** covers the complete declaration as printed, including `MRP`,
  the currency symbol, and `(inclusive of all taxes)` — because that is the text
  the classifier must learn to recognise as one declaration.
- The **height measurement** is taken on the **numerals only**: `45.00`.

**Why.** The qualifier is routinely printed at half the size of the price, and a
packet is not non-compliant because its small print is small. Measuring the
whole run would mix two type sizes and report neither.

### 3. Text across a fold: take the largest flat readable run

Packets crease, and a declaration that runs over a crease is foreshortened on
one side of it. Draw the box on the longest continuous run that lies flat.

Do not draw a box spanning the fold, and do not draw two boxes and hope
something downstream joins them. If no run is long enough to read, the label is
`other` — see rule 5.

**Why.** §8b's rectification is a homography, and a homography is only valid for
a planar surface. Text bent over a fold is not on one plane, so the measured
height on the far side of the crease is wrong by an amount nothing downstream
can recover.

### 4. Curved surfaces: the flat central band only

A bottle, a can, a tube. The same reasoning as the fold, continuously: only the
band facing the camera is close enough to planar to measure. Draw on that band.

If the declaration wraps out of that band, the readable part is what you box,
and the frame belongs in the curved-surface bucket §16 asks for at ≥25%.

### 5. `other` is for text you cannot read. It is never a guess

If you cannot read it, it is `other`. Not "probably the batch number". Not "it's
where the MRP usually goes".

**Why.** §8b's rule is that `NO_DATA` is never a guess, and that rule is
worthless if the training data contains guesses. A model trained on plausible
inventions learns to invent plausibly, and the inventions arrive with high
confidence because the model was rewarded for them.

### 6. Promotional price graphics are `marketing_text`, never `mrp`

`₹20 OFF`. `SPECIAL PRICE ₹99`. `BUY 2 GET 1`. A starburst with a number in it.

These are `marketing_text`. The MRP is the maximum retail price declared under
Rule 6(1)(e), and it is one specific declaration, usually near the net quantity,
usually with the word `MRP` or `Retail Sale Price` or `अधिकतम खुदरा मूल्य` beside it.

**Why.** This is the single most damaging confusion available. A promotional
graphic is printed large and bold precisely so it catches the eye — including a
detector's — so a model that has learnt to call it `mrp` will *prefer* it over
the real declaration, measure the wrong characters, and pass a packet whose
actual MRP is printed at 1.2 mm. The hard-negative set §16 asks for is built
from exactly these, and `Rs. 20 OFF` is the first item on its list.

Related traps, all `other` or their own field, never `mrp`:

| On the packet | Label |
|---|---|
| `24MRP07` (a batch code containing the letters) | `batch` |
| Drained weight, or `Net wt when packed` | `net_quantity` |
| `Best before 9 months from packing` | `expiry_date` |
| The digits under a barcode | `other` |
| A manufacturer's address doubling as care address | see rule 7 |

### 7. Manufacturer, packer, importer and consumer care are four fields

They are printed as one paragraph on most packets, and they are four different
declarations under Rules 6(1)(a) and 6(1)(f). Draw them separately.

Where one address genuinely serves two roles the packet says so — *"Marketed
by ... Also for consumer complaints contact ..."* — and you draw two boxes over
the same text. Where it does not say so, do not infer it.

---

## Script labelling

`latin`, `devanagari`, or `other`. Per declaration, not per photograph — a
bilingual packet has some of each and that is the case §16 wants at ≥25%.

A declaration containing both scripts (`MRP ₹45 / अधिकतम खुदरा मूल्य ₹45` as one
run) is labelled by the script of the **numerals**, because the numerals are what
gets measured. If they are Devanagari digits, it is `devanagari`.

---

## Second-annotator sign-off

**Every photograph's field labels are signed off by a second annotator.** Not
the boxes — the *field names*. Geometry disagreements are visible and cheap;
a `marketing_text` labelled `mrp` is invisible and expensive, and rule 6 is
where the second pair of eyes earns its cost.

The reviewer checks four things and nothing else:

1. Is anything labelled `mrp` actually the MRP declaration? (rule 6)
2. Is anything labelled `other` genuinely unreadable, rather than unlabelled? (rule 5)
3. Are manufacturer / packer / importer / consumer care distinguished? (rule 7)
4. Does every declaration have a script?

---

## Pre-labels: correct them, do not trust them

`training/detector/tasks.json` carries model predictions for the corpus so the
first pass is correction rather than drawing from nothing. They come from
`scripts/prelabel_corpus.py`, which is a text detector plus a regex tier, and it
is wrong in two predictable ways:

- it proposes `other` for most regions, because the regexes are deliberately
  conservative — those need a real field name;
- it will occasionally propose `mrp` for a promotional graphic, because the
  regex sees a currency symbol and a number. **Deleting those is the highest
  value thing an annotator does on this project.**

A pre-label you leave alone is a label you have asserted. There is no third
state.

---

## Which frames to annotate first

`data/manifest.json` marks each frame `millimetre_grade: true` or `false`.

Annotate the `true` ones first. They are the camera originals — full sensor
resolution with intact EXIF — and they are the only frames a millimetre claim
may ever be drawn from. The `false` ones came through a messaging app that
downscaled them to a 1600 px long side and stripped the metadata; they are
still worth labelling for detection and panel segmentation, which are
scale-free, and `docs/corpus.md` records exactly what was lost.
