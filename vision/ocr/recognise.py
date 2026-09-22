"""PP-OCRv5 `rec` — CTC recognition, run on ROI crops only.

Two heads, English and Devanagari, selected per region by `vision.ocr.script`.
Each is ~12 MB INT8 and neither ever sees the full photograph.

**Confidence is per-line and it is used, not decorated.** The mean of the
per-timestep maxima is what routes a crop to `crosscheck` for a second opinion,
what feeds `DeclarationSet.coverage`, and what stops a half-read MRP being
asserted as a violation. A recognition confidence is never allowed to become a
compliance decision — that is section 3's second principle — but it is entirely
allowed to decide whether we trust our own reading enough to report it.

**On character boxes.** CTC timesteps map to horizontal strips of the input, so
approximate character positions can be recovered from the argmax positions.
They are approximate: CTC has no alignment guarantee and blanks absorb width
unevenly. `vision.measure.characters` segments the same crop from its ink
instead, which is exact, and Rule 7(3)'s width ratio uses that. These positions
exist for the classifier's layout features, where approximate is fine, and are
deliberately not the ones the width rule measures.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from vision import runtime
from vision.measure import orientation
from vision.ocr.dictionary import load_dictionary
from vision.types import Image, Script

MODEL_FILENAMES: dict[Script, str] = {
    "latin": "ppocrv5_rec_devanagari.onnx",
    "devanagari": "ppocrv5_rec_devanagari.onnx",
}
"""One head, deliberately, and both scripts point at it.

PP-OCRv5's Devanagari mobile recogniser carries a 568-character table of which
**94 are ASCII** -- the digits, `A-Z`, `a-z` and the punctuation an MRP or a net
quantity is written with -- alongside 128 Devanagari characters. It reads
English, and section 15b says so: *"v5's Devanagari recogniser covers Hindi and
Marathi and handles English too. Benchmark whether a second English-only head
earns its bundle size; do not assume it."*

So this is the plan's default, not a shortcut around a missing file. A separate
Latin head is a 7.5 MB decision to be made **after** measuring CER with and
without it, and until that benchmark exists, shipping two heads would be
assuming the answer.

Both keys map to one path on purpose rather than collapsing to a single
constant: `runtime.load` caches by resolved path, so the second script costs no
extra memory and no second session, while the shape of the mapping still says
that the two scripts are separable and can be given separate heads the day the
benchmark justifies one."""

REC_HEIGHT = 48
"""PP-OCRv5 recognition input height. v3 used 32; using the wrong one resizes
every crop to the wrong aspect and costs a great deal of accuracy silently."""

REC_MAX_WIDTH = 1280
"""Widest tensor a single recognition run may be given, in pixels.

**This used to be 640 and it was silently destroying long lines.** `_prepare`
resizes a crop to `REC_HEIGHT` and scales the width by the aspect ratio, then
clamped that width to this number. Clamping a width while fixing the height is
not a resize, it is a horizontal squash: a 490x18 line of address text on
`gillete.jpg` has a natural target width of 1307 px, so at 640 every glyph in it
was compressed to 49% of its correct width before the model saw it.

Measured across the 38 hand-labelled declaration panels: **94 of 1290 detected
regions (7.3%) exceeded the old clamp**, by factors from 1.01x up to 1.96x. That
squash is the signature we were already seeing in the character-error bench --
CTC *dropping* characters rather than substituting them, which is what happens
when neighbouring glyphs merge into one column of ink, not what happens when a
model is merely weak. `Mktd. by ITC Limited, 37, J.L.` came back `Md by TC Lted
37`: the dropped letters are the narrow ones.

1280 covers every region in the corpus with room to spare, and anything still
wider than this is now **split** rather than squashed -- see `_split_spans`. The
cost is linear in tensor width and only 7% of crops pay it.
"""

REC_SPLIT_SEARCH = 0.12
"""How far either side of an ideal cut to hunt for a gap, as a fraction of the
piece width. Also the safety margin `_split_spans` leaves under `REC_MAX_WIDTH`,
since a cut that moves right by this much makes the piece before it that much
wider."""

REC_MAX_PIECES = 6
"""Most pieces one crop may be split into, however wide it is.

Without a cap the piece count is unbounded in the aspect ratio, and aspect ratio
is not something the detector promises anything about. A 2000x2 sliver -- a rule
between two blocks of text, the edge of a barcode, a detector artefact on a
pack's fold -- has a natural width of 48,000 pixels and would be split into
forty-seven tensors, each of them a full recognition run, on a region containing
no text at all. The shipped corpus never produces one; that is not a reason to
let the cost be unbounded when a shop photograph does.

Six pieces is 7680 pixels of line at the recogniser's own scale, an aspect ratio
of 160:1. No line of print on a package is that long relative to its height.

When the cap binds, the crop is still divided into six -- it is not truncated,
and no text is dropped. The pieces are simply wider than `REC_MAX_WIDTH`, so
`_prepare`'s backstop squashes them, which is exactly the old behaviour applied
to a sixth of the crop at a time instead of all of it. Degrading to
strictly-better-than-before is the right failure mode for a cap.
"""

REC_GAP_ENERGY = 0.15
"""A column counts as a gap between words when its ink energy is below this
fraction of the crop's mean. Used only to decide whether a split earned a space
in the joined text -- see `_split_spans`."""

MIN_CONFIDENCE = 0.0

REC_BATCH = 16
"""Crops per ONNX run in `read_batch`."""

REC_PAD_RATIO = 1.5
"""How much wider than the narrowest member a bucket's widest may be."""


@dataclass(frozen=True, slots=True)
class Recognised:
    text: str
    confidence: float
    char_offsets: tuple[tuple[str, float, float], ...] = ()
    """(character, x_start_frac, x_end_frac) in crop-width fractions. Approximate
    — see the module docstring on why these are not used for Rule 7(3)."""


def _target_width(crop: Image) -> int:
    """The width this crop *wants*, from its aspect ratio. Unclamped."""
    h, w = crop.shape[:2]
    return max(REC_HEIGHT, int(np.ceil(REC_HEIGHT * (w / float(max(h, 1))))))


def _column_energy(crop: Image) -> np.ndarray:
    """Per-column ink energy, polarity-free.

    Standard deviation down each column. A column of plain background is
    uniform whether the pack is white card or black foil, so it scores near
    zero either way; a column through a glyph does not. Thresholding for "ink"
    would have to know which way round the print is. This does not.
    """
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return grey.astype(np.float32).std(axis=0)


def _split_spans(crop: Image) -> list[tuple[int, int, str]]:
    """Cut a too-long crop into pieces, at the gaps between words where it can.

    Returns `(x0, x1, separator)` per piece, in crop columns. The separator is
    what to put *before* that piece when the readings are joined: a space if the
    cut landed in genuine whitespace, nothing if it had to go through ink.

    **Why splitting rather than squashing.** A crop wider than `REC_MAX_WIDTH`
    used to be resized to fit, which compresses every glyph horizontally and
    merges neighbouring strokes into one column of ink. The recogniser does not
    report that as low confidence -- it reports a short, confident, wrong
    string, because merged glyphs decode as one glyph. Splitting keeps every
    character at its correct aspect and costs one extra ONNX run per piece.

    **Why the gap search.** A blind cut at the piece boundary lands wherever it
    lands, and a cut through the middle of a letter gives two half-glyphs that
    each decode as something. Hunting for the quietest column within
    `REC_SPLIT_SEARCH` of the ideal boundary puts the cut in the space between
    words on any normally-set line. When no quiet column exists -- a continuous
    1280-pixel run of ink at 48 pixels tall, which is a barcode or a rule rather
    than text -- the cut is taken anyway and costs at most the glyph it crosses.
    That is the honest trade: squashing cost the whole line.
    """
    width = int(crop.shape[1])
    budget = REC_MAX_WIDTH / (1.0 + 2.0 * REC_SPLIT_SEARCH)
    pieces = min(int(np.ceil(_target_width(crop) / budget)), REC_MAX_PIECES)
    if pieces <= 1:
        return [(0, width, "")]

    energy = _column_energy(crop)
    quiet = float(energy.mean()) * REC_GAP_ENERGY
    step = width / pieces
    radius = max(1, int(step * REC_SPLIT_SEARCH))

    cuts = [0]
    for i in range(1, pieces):
        ideal = round(i * step)
        lo = max(cuts[-1] + 1, ideal - radius)
        hi = min(width - 1, ideal + radius)
        if hi <= lo:
            cuts.append(min(max(ideal, cuts[-1] + 1), width - 1))
            continue
        window = energy[lo:hi]
        # Every column tied for quietest, then the one of those nearest the
        # ideal boundary -- so a run of blank columns is cut down its middle
        # rather than at whichever edge `argmin` happened to reach first, and
        # an evenly-inked crop still splits evenly.
        tied = np.flatnonzero(window <= window.min() + 1e-6)
        cuts.append(lo + int(tied[np.abs(tied - (ideal - lo)).argmin()]))
    cuts.append(width)

    spans: list[tuple[int, int, str]] = []
    for i in range(pieces):
        separator = "" if i == 0 else (" " if energy[cuts[i]] <= quiet else "")
        spans.append((cuts[i], cuts[i + 1], separator))
    return spans


def _prepare(crop: Image) -> np.ndarray:
    """One crop as a `(3, 48, W)` tensor, width set by the crop's aspect.

    The `REC_MAX_WIDTH` clamp survives only as a backstop. Callers split first,
    so a crop reaching here should already fit; if the gap search drifted a
    piece over the limit, squashing it slightly is better than emitting a
    tensor the batch cannot hold.
    """
    target_w = min(REC_MAX_WIDTH, _target_width(crop))

    resized = cv2.resize(crop, (target_w, REC_HEIGHT), interpolation=cv2.INTER_LINEAR)
    if resized.ndim == 2:  # pragma: no cover - crops arrive in colour
        resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)

    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    normalised = (rgb - 0.5) / 0.5
    return np.ascontiguousarray(np.transpose(normalised, (2, 0, 1)))


def _preprocess(crop: Image) -> np.ndarray:
    return _prepare(crop)[np.newaxis, ...]


def ctc_decode(logits: np.ndarray, table: tuple[str, ...]) -> Recognised:
    """Greedy CTC: argmax per timestep, collapse repeats, drop blanks.

    Greedy rather than beam search on purpose. A beam search with a language
    model would "correct" `24MRP07` into something more word-like, and that
    batch code is one of section 14's named hard negatives. On packaging text
    — codes, prices, quantities — a language prior is a liability.
    """
    if logits.ndim == 3:
        logits = logits[0]
    if logits.shape[0] < logits.shape[1] and logits.shape[0] == len(table):
        logits = logits.T  # (C, T) -> (T, C)

    indices = logits.argmax(axis=1)
    scores = logits.max(axis=1)

    characters: list[str] = []
    kept_scores: list[float] = []
    offsets: list[tuple[str, float, float]] = []
    steps = len(indices)
    previous = -1

    for step, index in enumerate(indices):
        index = int(index)
        if index != previous and index != 0 and index < len(table):
            char = table[index]
            characters.append(char)
            kept_scores.append(float(scores[step]))
            offsets.append((char, step / steps, (step + 1) / steps))
        previous = index

    confidence = float(np.mean(kept_scores)) if kept_scores else 0.0
    return Recognised("".join(characters), confidence, tuple(offsets))


ROTATE_ASPECT = orientation.ROTATE_ASPECT
"""Re-exported. The decision lives in `vision.measure.orientation`, because the
recogniser is no longer the only stage that has to know which way text runs --
every measurement downstream of the crop depends on the same answer, and two
copies of it would eventually disagree.

**Vertical text was being destroyed before it reached the model.** Recognition
resizes every crop to `REC_HEIGHT` and scales the width by the aspect ratio, so
a 58x508 region -- text running down the side of a pack, which is where net
quantity and batch codes very often sit -- became 48x48 and every glyph in it
was gone. Measured across 86 crops from the dev corpus, the empty-read rate
tracked the aspect ratio exactly:

    aspect (w/h)   <0.5    0.5-1    1-3    3-8    >8
    empty reads     52%      43%    31%    25%    0%

and 37% of all detected regions were taller than wide. This was not small print
failing to be legible; it was legible print being flattened.
"""


def read(crop: Image, script: Script = "latin") -> tuple[Recognised, Image, int]:
    """Read one crop. Returns the reading, the crop **as read**, and its rotation.

    A portrait crop is tried in both rotations and the more confident reading
    wins -- see `vision.measure.orientation`. The winning orientation is handed
    back because every later measurement has to be taken on the same pixels the
    text was read from: cap height, character segmentation and contrast all
    assume horizontal text, and on a vertical crop all three measure the wrong
    axis. `k` is quarter-turns anticlockwise, so `unrotate_box` can carry the
    resulting geometry back to where it was found.

    Raises `ModelUnavailableError` if the head is absent.

    **One crop through the batch path, deliberately.** This used to be a second
    implementation of the same loop -- its own orientation trial, its own CTC
    decode, its own tie-break -- and once crops started being *split* there
    would have been two copies of the reassembly rule as well. Two copies of a
    decision eventually disagree, and a bench calling `read` would then be
    measuring something production never runs. The cost of delegating is the
    bucket padding `read_batch` applies, which is what production applies too.
    """
    results, _ = read_batch([crop], script)
    return results[0]


def recognise(crop: Image, script: Script = "latin") -> Recognised:
    """The text alone, for callers with no pixels left to measure."""
    return read(crop, script)[0]


@dataclass(frozen=True, slots=True)
class _Work:
    """One tensor to run: a single piece of one orientation of one crop."""

    crop: int
    rotation: int
    piece: int
    span: tuple[int, int]
    """Columns of the oriented crop this piece covers."""
    separator: str
    """What to put before this piece when the readings are joined."""
    crop_width: int
    tensor: np.ndarray


def _combine(parts: list[tuple[_Work, Recognised]]) -> Recognised:
    """Reassemble the pieces of one oriented crop into a single reading.

    Confidence is weighted by the characters each piece contributed rather than
    averaged flat. A piece that read two characters should not outvote one that
    read forty, and a flat mean would let a short confident fragment drag a long
    doubtful one upwards -- which is the direction that turns a bad read into an
    asserted violation.

    Character offsets are remapped onto the whole crop's width so that a split
    crop's offsets mean the same thing as an unsplit one's.
    """
    if len(parts) == 1:
        return parts[0][1]

    text: list[str] = []
    offsets: list[tuple[str, float, float]] = []
    weighted = 0.0
    chars = 0

    for work, found in parts:
        if not found.text:
            continue
        if text:
            text.append(work.separator)
        text.append(found.text)
        weighted += found.confidence * len(found.text)
        chars += len(found.text)

        x0, x1 = work.span
        width = float(max(work.crop_width, 1))
        for char, start, end in found.char_offsets:
            offsets.append(
                (char, (x0 + start * (x1 - x0)) / width, (x0 + end * (x1 - x0)) / width)
            )

    return Recognised("".join(text), weighted / chars if chars else 0.0, tuple(offsets))


def _buckets(widths: list[int], order: list[int]) -> list[list[int]]:
    """Split width-sorted work into batches that need little padding.

    Two limits, and the second is the one that matters. `REC_BATCH` caps the
    tensor; `REC_PAD_RATIO` closes a bucket as soon as its widest member is
    more than half again its narrowest, so a 640 px line of ingredients never
    pads a 48 px `10` out to thirteen times its own width. Padding is mid-grey
    in normalised space, and a crop that is mostly padding is a crop whose CTC
    timesteps are mostly describing nothing.
    """
    out: list[list[int]] = []
    current: list[int] = []
    for index in order:
        if current and (
            len(current) >= REC_BATCH
            or widths[index] > widths[current[0]] * REC_PAD_RATIO
        ):
            out.append(current)
            current = []
        current.append(index)
    if current:
        out.append(current)
    return out


def read_batch(
    crops: list[Image], script: Script = "latin"
) -> tuple[list[tuple[Recognised, Image, int]], float]:
    """Read many crops in one pass each. Same answers as `read`, far fewer runs.

    Section 8b's B7 begins *"first pass batches every detected crop at working
    resolution"*, and until now it did not: `recognise_batch` looped over
    `recognise`, which is one ONNX run per crop -- two for a portrait crop,
    because both rotations are tried. On a real pack that is roughly seventy
    runs of a model whose per-run cost is dominated by session overhead rather
    than by arithmetic, measured at **38.2 ms per crop**.

    The ONNX graph takes `(N, 3, 48, W)` with N and W both dynamic, so the only
    obstacle was that crops have different widths. They are sorted by width and
    bucketed, which bounds the padding, and each bucket is one run.

    **This is what makes reading everything affordable, and reading everything
    is what removes the ranker.** A crop budget exists only because reading is
    expensive; every heuristic that decides *which eight regions to read* is a
    chance to discard the declaration, and on the ruler set it was taking that
    chance. Cheap reading deletes the question rather than answering it better.

    Returns the same triples `read` returns, in the caller's order, plus the
    elapsed milliseconds.
    """
    started = time.perf_counter()
    if not crops:
        return [], 0.0

    filename = MODEL_FILENAMES.get(script)
    if filename is None:
        raise runtime.ModelUnavailableError(f"no recognition head for script {script!r}")
    model = runtime.load(filename)
    table = load_dictionary(script)

    # One work item per (crop, orientation, piece). A portrait crop contributes
    # two orientations exactly as before; a crop too wide for one tensor now
    # contributes several pieces of each, and `_combine` puts them back
    # together. Splitting happens here rather than in `_prepare` because the
    # bucketing below has to see each piece as its own tensor.
    items: list[_Work] = []
    oriented_by: dict[tuple[int, int], Image] = {}
    for index, crop in enumerate(crops):
        for k, oriented in orientation.orientations(crop):
            oriented_by[(index, k)] = oriented
            for piece, (x0, x1, separator) in enumerate(_split_spans(oriented)):
                items.append(
                    _Work(
                        crop=index,
                        rotation=k,
                        piece=piece,
                        span=(x0, x1),
                        separator=separator,
                        crop_width=int(oriented.shape[1]),
                        tensor=_prepare(oriented[:, x0:x1]),
                    )
                )

    widths = [work.tensor.shape[2] for work in items]
    order = sorted(range(len(items)), key=lambda i: widths[i])

    readings: list[Recognised | None] = [None] * len(items)

    for bucket in _buckets(widths, order):
        width = max(widths[i] for i in bucket)
        tensor = np.zeros((len(bucket), 3, REC_HEIGHT, width), dtype=np.float32)
        for row, i in enumerate(bucket):
            prepared = items[i].tensor
            tensor[row, :, :, : prepared.shape[2]] = prepared

        logits = model.session.run(None, {model.input_name: tensor})[0]
        if len(table) not in logits.shape:
            raise runtime.ModelUnavailableError(
                f"dictionary for {script!r} has {len(table)} entries but the model "
                f"emits {logits.shape}. Decoding with a mismatched table produces "
                f"confident nonsense rather than an error, so this is refused."
            )

        for row, i in enumerate(bucket):
            readings[i] = ctc_decode(logits[row], table)

    # Pieces back into whole readings, then the most confident orientation.
    grouped: dict[tuple[int, int], list[tuple[_Work, Recognised]]] = {}
    for work, found in zip(items, readings, strict=True):
        assert found is not None  # every item landed in exactly one bucket
        grouped.setdefault((work.crop, work.rotation), []).append((work, found))

    best: list[tuple[Recognised, Image, int] | None] = [None] * len(crops)
    for (index, k), parts in grouped.items():
        parts.sort(key=lambda part: part[0].piece)
        found = _combine(parts)
        if k:
            # `char_offsets` are fractions along the crop's width, and for
            # rotated text that axis is the original height. Reporting them
            # would be quietly wrong; `vision.measure.characters` segments the
            # oriented crop from its ink instead, which is exact.
            found = Recognised(found.text, found.confidence, ())
        current = best[index]
        # An empty reading never wins: its confidence is 0.0.
        if current is None or (
            found.text.strip() and found.confidence > current[0].confidence
        ):
            best[index] = (found, oriented_by[(index, k)], k)

    # `orientations` never returns an empty tuple, so every crop was tried.
    assert all(candidate is not None for candidate in best)
    results = [candidate for candidate in best if candidate is not None]

    return results, (time.perf_counter() - started) * 1000.0


def recognise_batch(crops: list[Image], script: Script = "latin") -> tuple[list[Recognised], float]:
    """The text alone, for callers with no pixels left to measure."""
    results, elapsed = read_batch(crops, script)
    return [found for found, _, _ in results], elapsed


def is_available(script: Script = "latin") -> bool:
    filename = MODEL_FILENAMES.get(script)
    return bool(filename) and runtime.available(filename)


__all__ = [
    "MODEL_FILENAMES",
    "REC_HEIGHT",
    "Recognised",
    "ctc_decode",
    "is_available",
    "read",
    "read_batch",
    "recognise",
    "recognise_batch",
]
