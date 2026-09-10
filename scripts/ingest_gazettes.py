"""Ingest every gazette in `rules_and_acts_docs/` into the retrieval corpus.

    python -m scripts.ingest_gazettes                 # all documents, resumable
    python -m scripts.ingest_gazettes --only ns_2011  # one document
    python -m scripts.ingest_gazettes --manifest-only # rebuild outputs from cache

**Why every page and not just the cited ones.** The rulepack's provenance
register asserts things like *"a keyword scan across all 443 non-LMPC pages
found `pre-packed` zero times"*. That is the evidence behind nine NO IMPACT
rows, and right now it is unfalsifiable: the text it was computed from was used
to author rules and then thrown away. Holding the text turns those nine
assertions into a test that re-runs on every build. That is worth more than the
five advisory citations that first motivated this script.

**Nothing is silently dropped, and that is what `manifest.json` is for.** Every
page of every document gets a row — document, page, language, how the text was
obtained, how confident the reader was. Pages that do not enter the searchable
index (the Hindi halves of the bilingual gazettes) are *recorded with a reason*
rather than omitted, so "we ingested everything" is a claim that can be audited
instead of one that has to be trusted.

**Pages are rendered, not extracted.** Pulling the embedded image out of each
page is faster and works for most of these files, but `National_Std_Rules2019`
is not one image per page — it is dozens of small tiles (334x88, 51x27, ...) —
and image extraction returns fragments for it. Rendering the page composites
whatever is there, and it lets the 134 dpi scans be resampled up to something
the recogniser is happier with.

**OCR text is searchable but not quotable.** 795 pages of machine reading will
contain errors, and a statute quoted to an officer with a wrong digit is the
worst output this project can produce: a height threshold read as 6 mm instead
of 8 mm is a confident, specific, wrong notice. So every chunk carries how it
was obtained, and the UI is expected to mark OCR'd text for verification
against the page. Only text that has been checked against the original is
quotable without that caveat.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import re
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GAZETTES = ROOT / "rules_and_acts_docs"
RULEBOOK = ROOT / "data" / "rulebook"
EXTRACTED = RULEBOOK / "extracted"
CACHE = RULEBOOK / ".ocr_cache"
MANIFEST = RULEBOOK / "manifest.json"

DPI = 300
"""300 measured *faster* than 150 and 200 on these scans, not slower, because
the cost is per text line rather than per pixel and a sharper page yields
cleaner line boxes. It is also the most accurate of the three. There is no
trade-off to make here."""

THREADS_PER_WORKER = 2
"""Threads each OCR process may use. `workers * THREADS_PER_WORKER` should sit
near the core count; oversubscribing costs more than the parallelism buys."""

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
HINDI_PAGE_RATIO = 0.08
"""For a page read from an embedded *text layer*, where Devanagari arrives as
Devanagari and counting it is meaningful. The English pages of these gazettes
are not clean of Devanagari — they carry a Devanagari masthead and quote Hindi
terms — so the test is a ratio, not a presence check."""

ENGLISH_WORD_RATE = 8.0
"""For a page read by OCR, where counting Devanagari is worse than useless.

**The recogniser has no Devanagari model.** It is the PP-OCR English/Chinese
pair, and handed a Hindi page it does not fail — it confidently emits CJK
glyphs, `g F 3 3 市 市 3`. A Devanagari-ratio test on that output finds no
Devanagari and reports a Hindi page as English, which is how the first run of
this script nearly wrote three pages of mojibake into the indexed corpus.

So the script asks a question the output can answer: how often do common
English words appear per thousand characters? Measured over the six pages of
the Numeration Rules, whose language is known page by page:

    Hindi   pp. 1-3     0.0,  2.0,  2.6
    English pp. 4-6    16.0, 35.5, 44.3

A six-fold margin, against 0.84 versus 0.95 for mean recogniser confidence on
the same split. Confidence measures how sure the model is, which is the wrong
question to ask a model that is confidently wrong.

**Superseded, and kept because it explains the shape of the replacement.** A
rate per thousand characters is only meaningful where the page is prose. The
Schedules are not prose: they are tables of unit names and symbols, and they
score below this threshold while being perfectly readable English. It cost the
corpus the National Standards Seventh Schedule (C.G.S. units, page 73) and
three pages of the Ninth Schedule outright, and from the other direction it let
twenty pages of mojibake in. See `classify`.
"""

IDEOGRAPH = re.compile(r"[\u3400-\u9fff]")
"""What Devanagari actually comes back as.

Deliberately *not* fullwidth punctuation (U+FF00 and up), which appears on
genuine English pages wherever the recogniser reads `(` as a fullwidth bracket.
Counting those made English schedule pages look Chinese.
"""

MIN_ENGLISH_TOKENS = 12
"""Words of real English a page must carry before it is treated as readable.

An absolute count, not a rate. Every page of a bilingual gazette carries the
running masthead `THE GAZETTE OF INDIA:EXTRAORDINARY`, Hindi pages included, so
a *proportion* of English words scores a Hindi page whose body went entirely
unrecognised at 1.00 -- on four words. What separates a schedule of unit
symbols from a Hindi page is not the density of English but the presence of any.
"""

IDEOGRAPH_ALLOWANCE = 0.08
"""Ideographs tolerated per English word before a page is called Devanagari.

Not a fixed cap, because the English pages of these gazettes print a Hindi
header line: `general_rules_2011` page 569 carries four ideographs above 458
words of statute on water-meter testing, and a cap of two would have deleted
it. Scaling the allowance to the English content asks the question that
matters -- whether this is English with Hindi furniture, or Hindi with an
English masthead.
"""

VOCABULARY_FLOOR = 3
"""Times a word form must appear across trusted pages to count as English.
Filters the recogniser's own noise out of the reference vocabulary."""

BLOCK_DISTINCT_ENGLISH = 8
BLOCK_ENGLISH_RATIO = 0.55
"""What an English block on an otherwise Devanagari page must show to be kept.

**Distinct** words, not a count, and that is the whole point. These gazettes
are bilingual page by page, and a few carry an English table header above a
Hindi body -- `model_test_labs_2014` page 6 prints the column headings of the
Second Format, *PARTICULARS OF LABORATORY*, *Field of use*, *Equipment*, and
they appear nowhere else in the corpus. Judged whole the page fails, because
its eleven ideographs sit far above what `IDEOGRAPH_ALLOWANCE` permits for
fifteen English words; judged in blocks, the header is ideograph-free.

The threshold is set from the measurement, not from taste. Across every page
the corpus drops, nine pass the English test and fail on ideographs, and
scoring their ideograph-free blocks separates them cleanly: page 6 scores 13
distinct words at 0.81, and the next best block in the corpus scores 7. A word
*count* does not separate them at all -- `general_rules_2011` page 150 reaches
eight on four repeats of `max` inside a formula table, and page 268 on `kPa`
and `mm Hg` standing in Hindi sentences. Both are rejected here.

This is deliberately not the line-level salvage rejected in RESULTS.md. That
took any English-looking line from any dropped page and yielded 416 lines of
which ~10 were real. This takes a *contiguous, ideograph-free run* that reads
as English on its own, and across 838 pages it admits exactly one.
"""


@dataclass(frozen=True, slots=True)
class Source:
    """One gazette, identified from its masthead and notification number.

    `notification` is the citable identity of the instrument; the filename is
    an upload artefact and tells a reader nothing. These were read off page 1
    of each scan rather than inferred from the filenames, which are timestamps.
    """

    doc_id: str
    title: str
    notification: str
    filename: str
    register_id: str
    text_layer: str = "never"
    """`trust` uses the embedded text layer, `never` always OCRs, `probe` tests
    each page. Only three of the thirteen have any text layer at all and two of
    those are traps — see `TEXT_LAYER_NOTES`."""


TEXT_LAYER_NOTES = """\
Two of the three text layers in this corpus are worse than no text layer.

`5(i)` carries an OCR layer baked in by whoever scanned it which decodes to
`ftel eo do qflo-33004/99` — and page 4 of it scores *higher* on every
word-frequency test I tried than pages that are genuinely fine, because
garbage of that kind is dense in short words. The 2019 Approval-of-Models
amendment is worse still: page 1 uses a legacy Devanagari font encoding and
comes out as `jftLV<<h la<< Mh<< ,y<<&33004@99`, while page 2 is clean English.

So the policy is per document and written down, not inferred. A scalar
threshold that separated these six sample pages had a four-point margin, which
is not a margin at all across 838 pages.
"""

SOURCES: tuple[Source, ...] = (
    Source(
        doc_id="lmpc_2011",
        title="The Legal Metrology (Packaged Commodities) Rules, 2011",
        notification="G.S.R. 202(E), 7 March 2011",
        filename="9 The Legal Metrology (Package Commodities) Rules, 2011.pdf",
        register_id="1",
        text_layer="trust",
    ),
    Source(
        doc_id="ns_rules_2011",
        title="The Legal Metrology (National Standards) Rules, 2011",
        notification="S.O. 211(E), 31 January 2011",
        filename="stdrules-compressed_0_1732708966.pdf",
        register_id="2",
    ),
    Source(
        doc_id="ns_rules_2019_amdt",
        title="The Legal Metrology (National Standards) Amendment Rules, 2019",
        notification="G.S.R. 474(E), 5 July 2019",
        filename="National_Std_Rules2019_1732709005.pdf",
        register_id="3",
    ),
    Source(
        doc_id="numeration_2011",
        title="The Legal Metrology (Numeration) Rules, 2011",
        notification="G.S.R. 13(E), 7 January 2011",
        filename="3_0_0_1732709063.pdf",
        register_id="4",
    ),
    Source(
        doc_id="numeration_2011_amdt",
        title="The Legal Metrology (Numeration) Amendment Rules, 2011",
        notification="G.S.R. 109(E), 23 February 2011",
        filename="3(i)_0_1732709154.pdf",
        register_id="5",
    ),
    Source(
        doc_id="act_commencement_2010",
        title="Legal Metrology Act, 2009 — commencement",
        notification="S.O. 1(E), 31 December 2010",
        filename="1(iii)_0_1732708160.pdf",
        register_id="6",
    ),
    Source(
        doc_id="act_commencement_2011",
        title="Legal Metrology Act, 2009 — commencement rescinded and refixed",
        notification="S.O. 210(E), 31 January 2011",
        filename="1(iv)_1_1732708202.pdf",
        register_id="6a",
    ),
    Source(
        doc_id="general_rules_2011",
        title="The Legal Metrology (General) Rules, 2011",
        notification="G.S.R. 71(E), 7 February 2011",
        filename="6_0_1732709495.pdf",
        register_id="7",
    ),
    Source(
        doc_id="general_rules_2011_corr",
        title="Corrigendum to the Legal Metrology (General) Rules, 2011",
        notification="G.S.R. 317(E), 13 April 2011",
        filename="GeneralRule11_c_1745998483.pdf",
        register_id="8",
    ),
    Source(
        doc_id="approval_of_models_2011",
        title="The Legal Metrology (Approval of Models) Rules, 2011",
        notification="G.S.R. 183(E), 1 March 2011",
        filename="approval_of_models_rules_0_1732709311.pdf",
        register_id="9",
    ),
    Source(
        doc_id="approval_of_models_2019_amdt",
        title="The Legal Metrology (Approval of Models) Amendment Rules, 2019",
        notification="G.S.R. 823(E), 6 November 2019",
        filename="2019 Amendment Approval of models Rules_1732709395.pdf",
        register_id="9a",
        text_layer="probe",
    ),
    Source(
        doc_id="model_test_labs_2014",
        title="Notification under the Approval of Models Rules, rr. 3-5",
        notification="S.O. 824(E), 19 March 2014",
        filename="5(i)_0_1732709347.pdf",
        register_id="9b",
    ),
    Source(
        doc_id="iilm_rules_2011",
        title="The Indian Institute of Legal Metrology Rules, 2011",
        notification="G.S.R. 76(E), 8 February 2011",
        filename="4_0_1732709211.pdf",
        register_id="10",
    ),
)

DUPLICATES = {
    "2019 Amendment Approval of models Rules_1732709395 (1).pdf": "approval_of_models_2019_amdt",
    "5(i)_0_1732709347 (1).pdf": "model_test_labs_2014",
}
"""Byte-identical re-uploads, confirmed by SHA-256 and skipped. Nine pages of
the 847 in the folder are duplicate scans; the corpus holds 838."""


@dataclass
class PageRecord:
    doc_id: str
    page: int
    source: str
    language: str
    chars: int
    confidence: float | None = None
    lines: int = 0
    note: str = ""
    text: str = field(default="", repr=False)

    def row(self) -> dict[str, Any]:
        """The manifest row — everything but the text itself."""
        data = asdict(self)
        data.pop("text")
        return data


# --------------------------------------------------------------------------
# reading one page
# --------------------------------------------------------------------------


_CLEAN = re.compile(
    r"\b(the|and|shall|section|rules?|under|such|which|government|of|in)\b", re.IGNORECASE
)


def word_rate(text: str) -> float:
    """Common English words per thousand characters. See `ENGLISH_WORD_RATE`."""
    stripped = text.strip()
    return 1000 * len(_CLEAN.findall(stripped)) / max(len(stripped), 1)


def devanagari_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return len(DEVANAGARI.findall(text)) / len(letters)


GAP_LINE_FRACTION = 0.75
"""How much of a line of text must fit in a vertical gap before we look in it.

Set below one because the detector's boxes are drawn around skewed text and
overlap each other by a few pixels, so an uncovered band always reads a little
shorter than the line that belongs in it. Set no lower because every band swept
costs a recognition pass, and the gap that hid rule 10 measured 0.96 of a line.
"""

GAP_MAX_LINES = 3.0
"""And how much must *not* fit in it.

A detector drops a line or two; it does not drop a paragraph. Anything
taller is a figure, a margin or the empty half of a sparse page, and those
are what the cost was going into: a Hindi page carries thirteen boxes, so
the runs between them measure nine and six and five lines, and each one was
paying for a recognition pass. Ingestion ran at 3.4 pages a minute.

Three lines rather than two because a dropped heading can wrap, and no higher
because the bound is doing the work: on one page of the General Rules it takes
the bands from twenty-one to eleven.

It has a cost, and it is a real one. The band holding `OF COMBINED LIQUOR
MEASURES` on p. 363 is nineteen lines tall, and this bound gives up on it. That
caption is on the figure page the corpus already sets aside, and the trade is
deliberate: the sweep exists to recover a line the detector dropped out of a
column of prose, not to read a drawing.
"""

PITCH_ANOMALY = 1.7
"""Line pitches this much above the page's own before a line is presumed lost.

**The coverage sweep above cannot find a single dropped line, and the geometry
says why.** The detector draws boxes far taller than the text in them: on p. 19
of the Approval of Models Rules the median box is 138 px while consecutive
boxes start 60 px apart, so every box overlaps its neighbour by more than half
a line. Painting those boxes into a coverage mask therefore paints the rows
where a missing line would have been, and no uncovered run appears at all --
the gap over the lost first line of rule 6(4) measures 0.18 of a line against a
threshold of 0.75. Four of the corpus's eight missing sub-rules sat behind
exactly that, and the sweep read past all four.

Box *tops* do not have this problem, because they track baselines rather than
ink extent. Sorted down a column they give the page's own line pitch, and a
missing line shows as one step of roughly twice it: 1813, 1873, 1934, 2054,
2114 -> 60, 61, **120**, 60.

1.7 rather than 2.0 so a skewed or short line still registers, and not lower
because paragraph and heading spacing on these pages reaches 1.5. Bounded above
by `GAP_MAX_LINES` for the same reason the coverage sweep is: a detector loses
a line, not a page.
"""

GAP_INK = 0.002
"""The fraction of a band that has to be darker than its own paper.

This removes genuinely blank paper and nothing else, and on these scans
that is a minority of the gaps -- measured across four pages, three bands
of fifty fell below it, at 0.0004, 0.0018 and 0.0075. The rest of what
`GAP_MAX_LINES` excludes is not blank at all: the runs between boxes on a
figure page measure 0.03 to 0.14, because they are full of drawings. So
this is worth its microseconds and it is not what makes the sweep
affordable; the height bound is.

Against the band's own 90th percentile rather than a fixed value, because
these scans range from white to a grey that would read as ink outright.
"""
GAP_CONFIDENCE = 0.80
GAP_MIN_WORDS = 2
"""Words a swept band must yield before its text is kept.

A dropped line of statute is a line of prose; a single word is the recogniser
reading a piece of a line it has already read. Sweeping page 21 of the Approval
of Models Rules recovers rule 8(8) -- *A code number shall be assigned to each
approved model* -- and, from overlapping bands, `numher`, `assianed` and
`Tmateiiarwitnwnichthe`.

`_already_read` cannot catch those. It compares longest common runs, and
`assianed` against the `assigned` it duplicates shares only `ass`, three
characters against the five its length demands. Requiring two words costs
nothing real and removes all three.
"""

GAP_MIN_CHARACTERS = 6
REREAD_REACH = 1.5
"""Line heights within which a repeated reading counts as the same line.

Set from the two failures it has to separate at once. A band re-read overlaps
the lines bounding it, so a genuine duplicate lands within a line of the
original -- `1.5` leaves room for the quarter-line pad at each end. And the
nearest parallel provision that shares its wording verbatim on page 319 of the
General Rules sits twelve lines away, so nothing legitimate is inside the reach.
"""

GAP_OVERLAP = 0.5
"""What a recovered line has to clear to be believed.

Lowered from 0.6 once `_already_read` became position-aware, and only
because of that. Two readings of one line of print diverge more than a
prefix test allows for: `balances shall be as are speciffied in Part Il of
Eourth` and `...specified in Part Ii of Fourth` are the same line of page
319 read twice, and they share 24 characters against the 27 that 0.6
demanded, so the corpus kept both. Loosening the text test alone would have
started rejecting genuinely distinct provisions; loosening it inside a
one-line window cannot, because a different provision is never there.

A crop is padded past the gap on both sides, so it re-reads the neighbouring
lines and returns them clipped -- `approval in relation to any model, it sh`
against a line already held in full. Plain substring matching does not catch
those, because the two readings of the same print differ in a stray character:
`0273.15kelvin.` against `to 273.15 kelvin.`. So the test is the longest run in
common, and anything sharing `GAP_OVERLAP` of itself with a line already read
is the same line read again.

The confidence floor and the length are for the other failure -- a band of
blank paper, which comes back as `tc`, `assia`, `iPpioval`.
"""

GAP_SIMILARITY = 0.50
GAP_SIMILARITY_REACH = 0.6
"""How alike two readings of the *same place* on the page may be and still be
believed to be two different lines.

`GAP_OVERLAP` asks for a long *contiguous* run, and a badly garbled second
reading has none. `fal The slrfare of the weiahts shall be` is page 350's
`(a) The surface of the weights shall be` read again through a band the pitch
detector should never have opened; the two share ten characters where that
test demands sixteen, so the corpus kept both and the garbled one won a line
of its own.

**Likeness alone cannot decide it, and one threshold on its own does harm.**
Measured across the corpus the two populations overlap: nine garbled
duplicates score 0.54 to 0.95, and the opening line of the National Standards
definition of *physical constants* scores 0.56 against the line beneath it,
because consecutive lines of a statute repeat the statute's words. Set at 0.50
this test deleted that definition and the heading of rule 10 of the Approval of
Models Rules -- both of them lines the sweep had correctly recovered.

`GAP_SIMILARITY_REACH` is what makes the test safe: a second reading of one
line of print lands *on top of* the first, while a line the page genuinely
holds sits a full pitch away from its neighbours. So likeness is only allowed
to convict within 0.6 of a line height, where the same print read twice is the
only thing it can be. Outside that the longest-run test decides alone, exactly
as it did before.
"""


def sweep_gaps(image, result: list, ocr) -> list:
    """Look again at the bands the detector left empty, and read what is there.

    **The detector can miss a whole line and report nothing wrong.** Page 22 of
    the Approval of Models Rules prints `10. Re-submission of disapproved model
    for approval. - (1) Where any model is` in bold, and RapidOCR returns 42
    boxes that step straight over it -- at 300, 450 and 600 dpi alike, so it is
    not a question of resolution. The page then reads as though rule 9 ran into
    rule 10's body, and rule 10 does not exist in the corpus at all. Nothing
    downstream can detect that: the text is fluent, the confidence is 0.98, and
    only counting the rule numbers gives it away.

    So: mark every row of pixels some box covers, find the runs nothing covers
    that are tall enough to hold a line, and read those bands again on their
    own. Cropping is what makes it work -- the same recogniser that skipped the
    line finds it immediately when the band is all it is given.

    Done per column, because a gap in the left column of a two-column page sits
    beside text in the right and would never show up in a full-width mask.

    Recovered boxes carry their absolute coordinates so `order_columns` places
    them in reading order like any other line.
    """
    import numpy as np

    if not result:
        return result

    heights = sorted(max(p[1] for p in box) - min(p[1] for p in box) for box, _, _ in result)
    line = heights[len(heights) // 2]
    if line <= 0:
        return result

    height, width = image.shape[0], image.shape[1]
    mid = width // 2
    bands = ((0, mid), (mid, width)) if two_column_page(result, width) else ((0, width),)
    # Normalised exactly as `_read_band` normalises what it recovers. They were
    # once folded differently, and every clipped re-read of an existing line got
    # through: punctuation alone was enough to break the comparison.
    # (folded text, vertical centre). The position is load-bearing: these
    # gazettes print parallel provisions in identical words, and a purely
    # textual guard reads one as a duplicate of the other. See `_already_read`.
    seen = [
        (_fold(text), sum(p[1] for p in box) / len(box)) for box, text, _ in result
    ]

    recovered: list = []
    for x0, x1 in bands:
        boxes = [
            box
            for box, _, _ in result
            if x0 <= sum(p[0] for p in box) / len(box) < x1
        ]
        if not boxes:
            continue
        covered = np.zeros(height, dtype=bool)
        for box in boxes:
            ys = [p[1] for p in box]
            covered[max(0, int(min(ys))) : min(height, int(max(ys)) + 1)] = True

        top = None
        for row in range(height + 1):
            filled = row < height and covered[row]
            if not filled and top is None:
                top = row
            elif filled and top is not None:
                if line * GAP_LINE_FRACTION <= row - top <= line * GAP_MAX_LINES:
                    recovered += _read_band(image, ocr, top, row, x0, x1, line, seen)
                top = None

        # And again by pitch, which finds what the mask above cannot: a single
        # dropped line between two boxes tall enough to cover its rows.
        for band_top, band_bottom, pitch in _pitch_bands(boxes):
            recovered += _read_band(
                image, ocr, band_top, band_bottom, x0, x1, pitch, seen
            )
    return result + recovered


def _pitch_bands(boxes: list) -> list[tuple[int, int, float]]:
    """Where a column's line pitch skips a beat, and the band that beat occupied.

    Uses box *tops*, which track baselines, rather than box extents, which on
    these scans overrun the text by more than half a line. See `PITCH_ANOMALY`.
    """
    import statistics
    from itertools import pairwise

    tops = sorted(int(min(p[1] for p in box)) for box in boxes)
    if len(tops) < 4:
        return []
    steps = [b - a for a, b in pairwise(tops) if b > a]
    if len(steps) < 3:
        return []
    pitch = statistics.median(steps)
    if pitch <= 0:
        return []

    out: list[tuple[int, int, float]] = []
    for above, below in pairwise(tops):
        step = below - above
        if not (PITCH_ANOMALY * pitch <= step <= GAP_MAX_LINES * pitch):
            continue
        # The lost line starts about one pitch below the box above it, and the
        # band runs to where the next box begins.
        out.append((int(above + pitch * 0.6), int(below + pitch * 0.4), pitch))
    return out


def _read_band(image, ocr, top: int, bottom: int, x0: int, x1: int, line: float, seen: set) -> list:
    """Recognise one uncovered band and return whatever was not already read.

    The band is padded by a quarter of a line so ascenders and descenders the
    neighbouring boxes clipped are not cut in half, which then means the crop
    can re-read a neighbour -- hence `seen`.
    """
    import numpy as np

    pad = int(line * 0.25)
    top = max(0, top - pad)
    bottom = min(image.shape[0], bottom + pad)
    if bottom - top < 8:
        return []

    band = image[top:bottom, x0:x1, :]
    paper = np.percentile(band, 90)
    if float((band < paper - 60).mean()) < GAP_INK:
        return []  # blank paper; see GAP_INK

    found, _ = ocr(band)
    out = []
    for box, text, score in found or []:
        key = _fold(text)
        if len(text.split()) < GAP_MIN_WORDS:
            continue
        if len(key) < GAP_MIN_CHARACTERS or float(score) < GAP_CONFIDENCE:
            continue
        centre = top + sum(p[1] for p in box) / len(box)
        if IDEOGRAPH.search(text) or _already_read(key, centre, seen, line):
            continue
        seen.append((key, centre))
        out.append(([[p[0] + x0, p[1] + top] for p in box], text, score))
    return out


FLIP_CONFIDENCE = 0.70
"""Below this, a line is re-read with the angle classifier switched off.

**PP-OCR classifies every line crop as upright or upside down, and when it is
wrong the line comes back reversed, glyph by glyph.** Rule 17(1) of the Approval
of Models Rules reads `u jo jpo Que jo jeodde go asodnd au ro () - 'essoau ou
aeuo`, which is *ordinarily not necessary. - (1) For the purpose of approval of
any model of any* rotated 180 degrees -- `asodnd` is `purpose`, `d` for `p` and
`n` for `u`, read backwards. Rotating the whole page does not fix it, because
only the one line is flipped; the fix is to read that line without the
classifier.

The threshold is the recogniser's own doubt. Every flipped line found scores
around 0.5 while the same crop read with the classifier off scores 0.99 or
better:

    17(1)  0.52 -> 1.00        21(2)  0.51 -> 0.99        iilm 7(2)  -> 0.99

0.70 leaves room above the three measured cases without re-reading text that is
merely faint. Nothing is replaced unless the second reading scores *higher* than
the first, so a line the classifier got right cannot be made worse, and a page
with no doubtful lines is left byte-identical. That is what makes it sound to
repair the affected pages alone rather than read all 838 again.

Devanagari lines are skipped: they come back as CJK glyphs whichever way up they
are read, and there are thousands of them.
"""


def repair_flipped(image, result: list, ocr) -> list:
    """Replace lines the angle classifier turned over with an unclassified read.

    **The whole page is re-read, not the suspect line.** Cropping to the box and
    recognising that was tried and is worse in both directions: with detection
    on, a tight crop often detects nothing and the repair silently does not
    happen (rule 17(1)); with detection off, the recogniser returns confident
    rubbish that passes a score test -- `S  e  s  s    as` became `hea` at 0.99,
    and a clean sweep of rule 21(2) degraded to `(2)Notwithstanding suchrepel
    anythindneoranyaction taeorurportdt`. A score is not a quality signal for a
    crop with no detection behind it.

    Read as a page, detection has its context back and every one of the three
    known flips comes out at 0.99 or better. The cost is one extra recognition
    pass, paid only on pages that carry a doubtful line.

    Only the doubtful boxes are replaced, matched to their counterparts by
    position. A page whose lines all read confidently is returned untouched.
    """
    suspects = [
        index
        for index, (_, text, score) in enumerate(result)
        if float(score) < FLIP_CONFIDENCE and not IDEOGRAPH.search(text)
    ]
    if not suspects:
        return result

    upright, _ = ocr(image, use_cls=False)
    if not upright:
        return result

    out = list(result)
    for index in suspects:
        box, _, score = result[index]
        match = _same_line(box, upright)
        if match is not None and float(match[2]) > float(score):
            out[index] = (box, match[1], float(match[2]))
    return out


def _same_line(box, candidates: list):
    """The candidate box covering the same strip of page as `box`, if any."""

    def span(quad):
        ys = [p[1] for p in quad]
        xs = [p[0] for p in quad]
        return min(ys), max(ys), min(xs), max(xs)

    top, bottom, left, right = span(box)
    height = max(bottom - top, 1)
    best = None
    for candidate in candidates:
        c_top, c_bottom, c_left, c_right = span(candidate[0])
        overlap = min(bottom, c_bottom) - max(top, c_top)
        if overlap < height * 0.5:
            continue
        if min(right, c_right) - max(left, c_left) <= 0:
            continue
        if best is None or overlap > best[0]:
            best = (overlap, candidate)
    return best[1] if best else None


def _fold(text: str) -> str:
    """Letters and digits only -- two readings of one line of print differ in
    their punctuation more than in anything else."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _already_read(
    key: str, centre: float, seen: list[tuple[str, float]], line: float
) -> bool:
    """Is this the same print as a line we hold, read a second time?

    **Same words is not enough; it has to be the same place on the page.** The
    General Rules print rules 7, 8 and 9 as parallel provisions in identical
    language, so `(2) The number, types and specifications of such` is the text
    of three different sub-rules on page 319. A text-only guard rejected the
    recovery of rule 8(2) as a duplicate of rule 7(2), and no amount of
    re-reading could ever have brought it back.

    A genuine second reading of a line lands on top of the first, so a match is
    only believed within a line of where we already hold it.
    """
    need = GAP_OVERLAP * len(key)
    reach = max(line * REREAD_REACH, 1.0)
    tight = max(line * GAP_SIMILARITY_REACH, 1.0)
    for other, other_centre in seen:
        distance = abs(centre - other_centre)
        if distance > reach:
            continue
        compare = SequenceMatcher(None, key, other, autojunk=False)
        match = compare.find_longest_match(0, len(key), 0, len(other))
        if match.size >= need:
            return True
        # A garbled second reading shares no long run with the clean one, so
        # the test above lets it through. Overall likeness catches it.
        if distance <= tight and compare.ratio() >= GAP_SIMILARITY:
            return True
    return False


def two_column_page(result: list, width: float) -> bool:
    """Is this page set in two columns?

    Shared by `order_columns`, which needs it to decide reading order, and by
    `sweep_gaps`, which needs it to decide how wide to crop. They disagreed
    once: the sweep cropped every page at the midline, so on a single-column
    page it recovered `10. Re-submission of-disapproved` and left `model for
    approval. - (1) Where any model is` on the far side of the cut.
    """
    if not result:
        return False
    mid = width / 2
    tol = width * 0.04
    left = right = crossing = 0
    for box, _, _ in result:
        xs = [point[0] for point in box]
        if min(xs) < mid - tol and max(xs) > mid + tol:
            crossing += 1
        elif sum(xs) / len(xs) < mid:
            left += 1
        else:
            right += 1
    return left >= 5 and right >= 5 and crossing <= 0.12 * len(result)


def order_columns(result: list, width: int, height: int) -> tuple[str, float]:
    """Sort recognised lines into reading order, two columns aware.

    **This is the difference between a corpus and noise.** The gazettes set
    most pages in two columns, and lines sorted by y alone interleave the two
    into alternating half-sentences. `chunk_document` would then see a rule
    heading followed by text from the facing column and attach the wrong body
    to the right citation, which is the exact failure this whole package exists
    to prevent.

    A page is only treated as two-column when almost no line spans the gutter.
    A centred schedule heading crossing the middle is enough to fall back to
    plain y-order, because mis-ordering a single-column page is a much smaller
    error than splitting one that was never in columns.
    """
    if not result:
        return "", 0.0

    boxes = []
    for box, text, score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        boxes.append(
            {
                "x0": min(xs),
                "x1": max(xs),
                "xc": sum(xs) / len(xs),
                "y": sum(ys) / len(ys),
                "text": text,
                "score": float(score),
            }
        )

    mid = width / 2
    tol = width * 0.04
    crossing = [b for b in boxes if b["x0"] < mid - tol and b["x1"] > mid + tol]
    left = [b for b in boxes if b not in crossing and b["xc"] < mid]
    right = [b for b in boxes if b not in crossing and b["xc"] >= mid]

    two_column = two_column_page(result, width)

    if two_column:
        header = sorted((b for b in crossing if b["y"] < height * 0.15), key=lambda b: b["y"])
        footer = sorted((b for b in crossing if b["y"] >= height * 0.15), key=lambda b: b["y"])
        ordered = (
            header
            + sorted(left, key=lambda b: b["y"])
            + sorted(right, key=lambda b: b["y"])
            + footer
        )
    else:
        ordered = sorted(boxes, key=lambda b: b["y"])

    text = "\n".join(b["text"] for b in ordered)
    confidence = sum(b["score"] for b in ordered) / len(ordered)
    return text, confidence


def read_page(doc, page_index: int, source: Source, ocr) -> PageRecord:
    page = doc[page_index]
    number = page_index + 1

    if source.text_layer in ("trust", "probe"):
        embedded = page.get_text().strip()
        if embedded and (source.text_layer == "trust" or _layer_is_clean(embedded)):
            return PageRecord(
                doc_id=source.doc_id,
                page=number,
                source="text-layer",
                language="hi" if devanagari_ratio(embedded) > HINDI_PAGE_RATIO else "en",
                chars=len(embedded),
                lines=embedded.count("\n") + 1,
                note="embedded text layer",
                text=embedded,
            )

    import numpy as np

    pix = page.get_pixmap(dpi=DPI)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    result, _ = ocr(image)
    # Before the sweep, so a line the classifier flipped is repaired in place
    # rather than looking to the sweep like a gap that is already covered.
    result = repair_flipped(image, result or [], ocr)
    # Before ordering, because a recovered line has to take its place in the
    # column it came from rather than be appended at the end.
    result = sweep_gaps(image, result, ocr)
    text, confidence = order_columns(result, pix.width, pix.height)

    # A Devanagari page comes back as confident nonsense rather than as an
    # error, so the attempt is kept in the cache but never promoted to the
    # corpus. Recording it as Hindi text we hold would be a lie about the one
    # property this corpus is for.
    #
    # **The decision is not made here.** Telling a schedule of unit symbols
    # from a page of Devanagari needs the corpus vocabulary, which does not
    # exist until every page has been read, so this records the reading and
    # `classify` rules on it. What is written here is provisional and every
    # field it sets is overwritten by that pass.
    return PageRecord(
        doc_id=source.doc_id,
        page=number,
        source="ocr",
        language="en",
        chars=len(text),
        confidence=round(confidence, 4),
        lines=len(result or []),
        note=f"rapidocr @ {DPI} dpi",
        text=text,
    )


def _layer_is_clean(text: str) -> bool:
    """Only used for `probe` documents, and only ever to *accept* a layer.

    Deliberately strict. A page that fails falls through to OCR, which costs
    twenty seconds; a page that wrongly passes puts mojibake into a corpus
    whose entire value is being verbatim. The asymmetry sets the threshold.
    """
    stripped = text.strip()
    if len(stripped) < 400:
        return False
    return word_rate(stripped) >= 20.0 and devanagari_ratio(stripped) < 0.02


# --------------------------------------------------------------------------
# workers
# --------------------------------------------------------------------------


def cache_path(doc_id: str, page: int) -> Path:
    return CACHE / doc_id / f"{page:04d}.json"


def _worker(args: tuple[str, list[int]]) -> tuple[str, int, int]:
    """Read a slice of one document. Each process owns its own recogniser.

    Raising the recogniser's own thread count changed nothing measurable, which
    says the model does not parallelise internally and the machine's other
    cores are idle. Process-level parallelism is therefore the only lever that
    works, and it is close to linear.
    """
    doc_id, pages = args
    source = next(s for s in SOURCES if s.doc_id == doc_id)

    # Set before the runtime is imported, because it reads these at load.
    # Left alone, every worker opens a thread pool the size of the whole
    # machine: six workers on sixteen cores asked for ninety-six threads and
    # delivered 3.7 pages a minute, against 15 for the same six workers kept
    # to their own lane. It is also why raising the thread count in the
    # single-process benchmark made it slower rather than faster.
    import os

    os.environ.setdefault("OMP_NUM_THREADS", str(THREADS_PER_WORKER))
    os.environ.setdefault("OPENBLAS_NUM_THREADS", str(THREADS_PER_WORKER))
    os.environ.setdefault("MKL_NUM_THREADS", str(THREADS_PER_WORKER))

    import pymupdf
    from rapidocr_onnxruntime import RapidOCR

    ocr = RapidOCR(intra_op_num_threads=THREADS_PER_WORKER)
    doc = pymupdf.open(GAZETTES / source.filename)

    done = 0
    for index in pages:
        target = cache_path(doc_id, index + 1)
        if target.exists():
            continue
        record = read_page(doc, index, source, ocr)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(record), ensure_ascii=False), encoding="utf-8")
        done += 1
    return doc_id, done, len(pages)


def pending(source: Source, total: int) -> list[int]:
    return [i for i in range(total) if not cache_path(source.doc_id, i + 1).exists()]


# --------------------------------------------------------------------------
# deciding which pages are readable English
# --------------------------------------------------------------------------

TOKEN = re.compile(r"[A-Za-z]{3,}")
TRUSTED_LATIN = 0.85
TRUSTED_CONFIDENCE = 0.90
"""What makes a page safe to learn English from.

Mojibake tops out around 0.62 Latin because the recogniser mixes Chinese into
it, so a page that is 85% Latin, carries no ideographs and was read confidently
cannot be a Hindi page. That is a strict enough filter to bootstrap from
without circularity: the vocabulary is built only from pages no criterion
disputes, and is then used to judge the pages that are actually in question.
"""


def ideographs(text: str) -> int:
    return len(IDEOGRAPH.findall(text))


def latin_share(text: str) -> float:
    body = [c for c in text if not c.isspace()]
    if not body:
        return 0.0
    return sum(1 for c in body if c.isascii() and c.isalpha()) / len(body)


def english_vocabulary(records: Iterable[PageRecord]) -> frozenset[str]:
    """The word forms of these gazettes, learned from their unambiguous pages.

    A general dictionary would not do. Half of what has to be recognised here
    is `erg`, `dyne`, `poise`, `stokes`, `deuteron` and `Vanaspati`, and a page
    of those is exactly the page the old rate test threw away.
    """
    counts: Counter[str] = Counter()
    for record in records:
        text = record.text
        trusted = record.source == "text-layer" or (
            latin_share(text) >= TRUSTED_LATIN
            and (record.confidence or 0.0) >= TRUSTED_CONFIDENCE
            and ideographs(text) == 0
        )
        if trusted:
            counts.update(word.lower() for word in TOKEN.findall(text))
    return frozenset(word for word, n in counts.items() if n >= VOCABULARY_FLOOR)


def english_tokens(text: str, vocabulary: frozenset[str]) -> int:
    return sum(1 for word in TOKEN.findall(text) if word.lower() in vocabulary)


def english_block(text: str, vocabulary: frozenset[str]) -> str | None:
    """The English region of a bilingual page, or None if it has none.

    Returns the *longest* qualifying run rather than every one of them. A page
    that genuinely carries English carries it in one place -- a header, a table,
    a form -- and stitching several runs together would join text across the
    Hindi that separates them, which is the one thing a corpus read for quotation
    must not do. See `BLOCK_DISTINCT_ENGLISH` for how the bar was set.
    """
    runs: list[list[str]] = []
    run: list[str] = []
    for line in text.splitlines():
        if IDEOGRAPH.search(line):
            if run:
                runs.append(run)
            run = []
        else:
            run.append(line)
    if run:
        runs.append(run)

    best: tuple[int, str] | None = None
    for candidate in runs:
        body = "\n".join(candidate)
        words = [word.lower() for word in TOKEN.findall(body)]
        if not words:
            continue
        hits = [word for word in words if word in vocabulary]
        if len(set(hits)) < BLOCK_DISTINCT_ENGLISH:
            continue
        if len(hits) / len(words) < BLOCK_ENGLISH_RATIO:
            continue
        if best is None or len(set(hits)) > best[0]:
            best = (len(set(hits)), body)
    return best[1] if best else None


def classify(records: Sequence[PageRecord]) -> list[PageRecord]:
    """Decide, over the whole corpus at once, which pages are readable English.

    **This is a second pass on purpose.** Judging a page needs a vocabulary,
    and the vocabulary comes from the corpus, so no per-page function called
    during recognition can do it. The cost is one pass over text already in the
    cache; the benefit is that a schedule of C.G.S. unit symbols and a page of
    Devanagari are told apart by *what is on them* rather than by how densely
    the words `the` and `shall` happen to occur.

    Two signals, and both must agree:

    - **enough English**, so a Hindi page carrying only the running masthead is
      not promoted on four words;
    - **few enough ideographs for that much English**, because Devanagari comes
      back as Chinese and nothing else on these pages does.

    Both are needed. Ideographs alone would drop the four dense English pages
    that print a Hindi header, and would keep the Hindi pages the recogniser
    rendered as bare numerals. English alone would keep the mojibake.
    """
    vocabulary = english_vocabulary(records)
    out: list[PageRecord] = []
    for record in records:
        if record.source == "text-layer":
            out.append(record)
            continue
        found = english_tokens(record.text, vocabulary)
        marks = ideographs(record.text)
        readable = found >= MIN_ENGLISH_TOKENS and marks <= max(2, IDEOGRAPH_ALLOWANCE * found)
        if readable:
            out.append(replace(record, source="ocr", language="en", note=f"rapidocr @ {DPI} dpi"))
            continue

        # A bilingual page whose English sits in one ideograph-free block: keep
        # the block and say so. Only offered to pages that already carry enough
        # English to pass the first test, so a Devanagari page whose masthead is
        # its only Latin text is never a candidate.
        block = (
            english_block(record.text, vocabulary) if found >= MIN_ENGLISH_TOKENS else None
        )
        if block is not None:
            kept, whole = len(block.splitlines()), len(record.text.splitlines())
            out.append(
                replace(
                    record,
                    source="ocr-block",
                    language="en",
                    chars=len(block),
                    text=block,
                    note=(
                        f"English block of a bilingual page: {kept} of {whole} lines kept, "
                        f"{marks} CJK glyphs in the Devanagari body left unread"
                    ),
                )
            )
            continue

        out.append(
            replace(
                record,
                source="not-read",
                language="hi",
                note=(
                    f"not readable English: {found} English words, {marks} CJK glyphs "
                    "(Devanagari page, or one the recogniser did not read)"
                ),
            )
        )
    return out


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------


def assemble() -> list[dict[str, Any]]:
    """Write one file per document, and the manifest covering every page.

    **Only pages that were actually read reach `extracted/`.** A Devanagari
    page that the recogniser rendered as CJK glyphs is held in the cache, is
    listed in the manifest with the reason it could not be read, and is kept
    out of the directory `CitationIndex.from_directory` globs. Putting it in
    would hand the chunker — whose rule, sub-rule and proviso patterns are all
    written for the English text — a page of noise to attach to a citation.

    The distinction the manifest draws is between *held* and *readable*, and
    every page in the folder is held.
    """
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    # Read every page of every document *before* classifying any of them. The
    # vocabulary that decides what counts as English is learned from the whole
    # corpus, and a document read on its own would be judged against its own
    # few pages -- the Numeration Rules would have three English pages to learn
    # English from.
    held: dict[str, list[PageRecord]] = {}
    for source in SOURCES:
        records = [
            PageRecord(**json.loads(path.read_text(encoding="utf-8")))
            for path in sorted((CACHE / source.doc_id).glob("*.json"))
        ]
        if records:
            held[source.doc_id] = records

    decided = classify([r for records in held.values() for r in records])
    by_doc: dict[str, list[PageRecord]] = {}
    for record in decided:
        by_doc.setdefault(record.doc_id, []).append(record)

    for source in SOURCES:
        records = by_doc.get(source.doc_id, [])
        if not records:
            continue

        # The primary source keeps the hand-verified file it already has: 28 of
        # the rulepack's 34 citations resolve against it, and rewriting it from
        # a fresh reading would put those at risk for no gain.
        if source.doc_id != "lmpc_2011":
            readable = [r for r in records if r.source != "not-read"]
            if readable:
                body = "\n".join(f"<<<PAGE {r.page}>>>\n{r.text}" for r in readable)
                (EXTRACTED / f"{source.doc_id}.txt").write_text(body + "\n", encoding="utf-8")

        rows.extend(r.row() for r in records)

    MANIFEST.write_text(
        json.dumps(
            {
                "documents": [asdict(s) for s in SOURCES],
                "duplicates_skipped": DUPLICATES,
                "pages": rows,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return rows


def verify_duplicates() -> None:
    digests: dict[str, str] = {}
    for path in sorted(GAZETTES.glob("*.pdf")):
        digests[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for copy, doc_id in DUPLICATES.items():
        original = next(s.filename for s in SOURCES if s.doc_id == doc_id)
        if copy in digests and digests[copy] != digests[original]:
            raise SystemExit(f"{copy} is no longer a byte-identical copy of {original}.")


def summarise(rows: list[dict[str, Any]]) -> None:
    header = f"{'document':32s} {'held':>5s} {'read':>5s} {'hindi':>6s} {'conf':>6s}"
    print(f"\n{header}\n{'-' * len(header)}")
    for source in SOURCES:
        mine = [r for r in rows if r["doc_id"] == source.doc_id]
        if not mine:
            continue
        read = [r for r in mine if r["source"] != "not-read"]
        scores = [r["confidence"] for r in read if r["confidence"] is not None]
        conf = f"{sum(scores) / len(scores):.3f}" if scores else "  -   "
        print(
            f"{source.doc_id:32s} {len(mine):5d} {len(read):5d} "
            f"{sum(r['source'] == 'not-read' for r in mine):6d} {conf:>6s}"
        )

    read = [r for r in rows if r["source"] != "not-read"]
    low = [r for r in read if (r["confidence"] or 1.0) < 0.80]
    print(
        f"\n{len(rows)} pages held, {len(read)} readable English, "
        f"{len(rows) - len(read)} not readable here (Devanagari, or a page the "
        f"recogniser returned nothing English from)."
    )
    if low:
        print(f"{len(low)} readable pages below 0.80 confidence:")
        for row in sorted(low, key=lambda r: r["confidence"] or 0)[:15]:
            print(f"    {row['doc_id']:30s} p{row['page']:<4d} {row['confidence']:.3f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="one doc_id")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--manifest-only", action="store_true")
    args = parser.parse_args(argv)

    verify_duplicates()
    sources = [s for s in SOURCES if not args.only or s.doc_id == args.only]

    if not args.manifest_only:
        import pymupdf

        jobs: list[tuple[str, list[int]]] = []
        outstanding = 0
        for source in sources:
            path = GAZETTES / source.filename
            if not path.exists():
                print(f"  MISSING  {source.filename}", file=sys.stderr)
                continue
            total = pymupdf.open(path).page_count
            todo = pending(source, total)
            outstanding += len(todo)
            for start in range(0, len(todo), 8):
                jobs.append((source.doc_id, todo[start : start + 8]))

        print(f"{outstanding} pages to read across {len(sources)} documents.")
        if outstanding:
            started = time.time()
            finished = 0
            with mp.Pool(processes=args.workers) as pool:
                for doc_id, _done, size in pool.imap_unordered(_worker, jobs):
                    finished += size
                    rate = (time.time() - started) / max(finished, 1)
                    print(
                        f"  {finished:5d}/{outstanding}  {doc_id:28s} "
                        f"~{(outstanding - finished) * rate / 60:5.1f} min left",
                        flush=True,
                    )

    summarise(assemble())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
