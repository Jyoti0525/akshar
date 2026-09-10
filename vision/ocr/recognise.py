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

REC_MAX_WIDTH = 640
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


def _prepare(crop: Image) -> np.ndarray:
    """One crop as a `(3, 48, W)` tensor, width set by the crop's aspect."""
    h, w = crop.shape[:2]
    ratio = w / float(max(h, 1))
    target_w = min(REC_MAX_WIDTH, max(REC_HEIGHT, int(np.ceil(REC_HEIGHT * ratio))))

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
    """
    filename = MODEL_FILENAMES.get(script)
    if filename is None:
        raise runtime.ModelUnavailableError(f"no recognition head for script {script!r}")

    model = runtime.load(filename)
    table = load_dictionary(script)

    candidates = orientation.orientations(crop)
    best: tuple[Recognised, Image, int] | None = None

    for k, oriented in candidates:
        outputs = model.session.run(None, {model.input_name: _preprocess(oriented)})
        logits = outputs[0]

        # The class axis is whichever one matches the dictionary. Checking
        # `shape[-1]` alone would wrongly reject a (1, C, T) layout, which
        # `ctc_decode` transposes and handles perfectly well.
        if len(table) not in logits.shape:
            raise runtime.ModelUnavailableError(
                f"dictionary for {script!r} has {len(table)} entries but the model "
                f"emits {logits.shape}. Decoding with a mismatched table produces "
                f"confident nonsense rather than an error, so this is refused."
            )

        found = ctc_decode(logits, table)
        if k:
            # `char_offsets` are fractions along the crop's width, and for
            # rotated text that axis is the original height. Reporting them
            # would be quietly wrong; `vision.measure.characters` segments the
            # oriented crop from its ink instead, which is exact.
            found = Recognised(found.text, found.confidence, ())
        # An empty reading never wins on confidence, which is 0.0 for both.
        if best is None or (found.text.strip() and found.confidence > best[0].confidence):
            best = (found, oriented, k)

    assert best is not None  # candidates is never empty
    return best


def recognise(crop: Image, script: Script = "latin") -> Recognised:
    """The text alone, for callers with no pixels left to measure."""
    return read(crop, script)[0]


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

    # One work item per (crop, orientation). A portrait crop contributes two,
    # exactly as `read` tries two, so batching changes the cost and not the
    # answer.
    items: list[tuple[int, int, Image, np.ndarray]] = []
    for index, crop in enumerate(crops):
        for k, oriented in orientation.orientations(crop):
            items.append((index, k, oriented, _prepare(oriented)))

    widths = [item[3].shape[2] for item in items]
    order = sorted(range(len(items)), key=lambda i: widths[i])

    best: list[tuple[Recognised, Image, int] | None] = [None] * len(crops)

    for bucket in _buckets(widths, order):
        width = max(widths[i] for i in bucket)
        tensor = np.zeros((len(bucket), 3, REC_HEIGHT, width), dtype=np.float32)
        for row, i in enumerate(bucket):
            prepared = items[i][3]
            tensor[row, :, :, : prepared.shape[2]] = prepared

        logits = model.session.run(None, {model.input_name: tensor})[0]
        if len(table) not in logits.shape:
            raise runtime.ModelUnavailableError(
                f"dictionary for {script!r} has {len(table)} entries but the model "
                f"emits {logits.shape}. Decoding with a mismatched table produces "
                f"confident nonsense rather than an error, so this is refused."
            )

        for row, i in enumerate(bucket):
            index, k, oriented, _ = items[i]
            found = ctc_decode(logits[row], table)
            if k:
                # See `read`: offsets are fractions along the crop's width, and
                # on rotated text that axis is the original height.
                found = Recognised(found.text, found.confidence, ())
            current = best[index]
            if current is None or (
                found.text.strip() and found.confidence > current[0].confidence
            ):
                best[index] = (found, oriented, k)

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
