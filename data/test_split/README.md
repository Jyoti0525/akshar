# The ruler set — DO NOT TRAIN ON

Forty photographs of twenty packets, each with a ChArUco card in frame and the
MRP declaration measured with a steel rule. This is the evidence behind the one
accuracy number AKSHAR states out loud, and section 19 makes it the **day-7
go/no-go**: `MAE ≤ 0.15 mm, p95 ≤ 0.25 mm`.

Score it with:

    python scripts/u1_report.py data/test_split/ground_truth.csv --images data/test_split

## The seal

**Nothing in this directory may be trained on, tuned against, or used to pick a
threshold.** Not the detector, not the recognition head, not a hyper-parameter,
not a decision about which of two approaches looks better. The plan seals it
until day 36 for a reason it states plainly: *"if it leaks into tuning, the
headline number is fiction — and you will find that out while you are saying it
aloud."*

The corpus to develop against is `data/corpus/`. It is a different set of
packets, and it is large enough to make every choice this project needs to make.

## What is here

    images/<product>_<pack size>/front.jpg
    images/<product>_<pack size>/tilt.jpg
    ground_truth.csv

Two shots per packet, and the pair is not redundancy — it is what makes the
error decomposable. The printed digit did not change height between the two
frames, so any disagreement between the two AKSHAR readings is **ours alone**,
with no ruler involved. `u1_report.py` reports that as `repeatability`.
Subtract it from the total error and what remains is the reading error. A single
shot per packet cannot separate the two, which is why section 19 asks for 40
photographs of 20 SKUs rather than 40 of 40.

## How the ground truth got here

From the folder names the photographer used, parsed by
`scripts/seal_test_split.py` rather than retyped:

    <product>_<pack size>_mrpsize=<height in mm>

Retyping forty numbers is one transcription step, and a transcription error in
the ground truth is indistinguishable from a bad measurement by the pipeline —
it would show up as a large error on one frame and send somebody hunting through
the wrong half of the system. The original folder name is carried verbatim into
the `notes` column of every row, so the derivation can be checked by eye.

## Two things the numbers here cannot tell you

**The ground truth has its own resolution.** Twenty-two of the forty frames
carry a truth of exactly 1 mm or exactly 2 mm; only two SKUs are recorded to a
tenth. If those whole numbers are rounded rather than read, the ground truth
carries up to ±0.5 mm of its own error, and **no pipeline however good can score
an MAE of 0.15 mm against it** — the number would be measuring the rounding, not
the measurement. The two frames at 1.9 mm and 2.5 mm show the rule can be read
finer than that. Re-reading the packets to 0.1 mm is cheap and is the single
highest-value thing that can be done to this set.

**`measured_mm` does not say which glyph was measured.** Cap height, x-height
and full text height differ by a third or more on the same line of print, and
`vision/measure/cap_height.py` measures cap height specifically. A constant
disagreement of that kind appears in `u1_report` as `systematic bias` — a
signed number, deliberately, because a bias means something is systematically
wrong (the card printed at the wrong scale, or a different quantity being
compared) rather than that the measurement is noisy. **Read the bias before
reading the MAE.**

## Not in git

`.gitignore` keeps the frames and the ground truth out of the repository: the
photographs are of real products bought by real people, and the set is large.
This README and `ground_truth.schema.json` are tracked, so the shape of the set
survives even where the set itself does not.
