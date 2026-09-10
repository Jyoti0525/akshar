"""M5, tier two — the only thing regex genuinely cannot do.

    "A trained head handles what regex genuinely cannot: manufacturer versus
     packer versus importer versus consumer care. All four are just addresses.
     The distinguishing signal is position and context, not vocabulary."
                                                        -- section 14

    "About 2M parameters — LayoutLMv3's 125M would overfit 400 photos badly.
     [...] Being able to say *we chose 2M over 125M because our corpus is 400
     images* is a better answer than the bigger number."   -- section 15b

**Four classes and no more.** This model is not a general field classifier. It
never sees an MRP, a date or a quantity, because regex already separates those
with a pattern anyone can read aloud, and handing them to a model would trade
explainability for nothing. It is invoked only when `regex_tier` finds an
address-shaped line it could not label.

**It cannot create a compliance decision.** It assigns `manufacturer` rather
than `packer`, and the *rules* then decide whether the required declaration is
present. Section 3, principle two, holds even here: the model says what the
text is, the rulepack says whether that is lawful.

**Abstention is a supported answer.** Below `MIN_CONFIDENCE` the head returns
None and the line stays `other`. The consequence is a rule reporting NO_DATA
for a declaration we could not identify — not a FAIL against a manufacturer
whose address we merely failed to categorise.
"""

from __future__ import annotations

import numpy as np

from contracts import FieldName
from vision import runtime
from vision.classify.features import FEATURE_DIM, build_features, median_cap_height
from vision.classify.regex_tier import FieldGuess
from vision.types import OcrLine

MODEL_FILENAME = "field_classifier_int8.onnx"

CLASSES: tuple[FieldName, ...] = ("manufacturer", "packer", "importer", "consumer_care")
"""Frozen order — the training script imports this exact tuple. Reordering it
relabels every prediction without changing a single weight."""

MIN_CONFIDENCE = 0.55
"""Below this the head abstains. Set above chance (0.25) by a clear margin:
between `manufacturer` and `packer` the model is often genuinely unsure, and an
unsure guess about who to address a legal notice to is worse than no guess."""


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=-1, keepdims=True)


def is_available(model_name: str = MODEL_FILENAME) -> bool:
    return runtime.available(model_name)


def classify_addresses(
    lines: list[OcrLine],
    embeddings: dict[int, np.ndarray],
    *,
    candidates: list[int],
    label_w: float,
    label_h: float,
    model_name: str = MODEL_FILENAME,
) -> dict[int, FieldGuess]:
    """Label address-shaped lines. Returns only the ones it is confident about.

    `candidates` are indices into `lines` that `regex_tier` could not resolve
    but which `is_address_like` accepted. `embeddings` maps those same indices
    to frozen MiniLM-L6 vectors, supplied by the caller so this module carries
    no sentence-transformer dependency.

    Raises `ModelUnavailableError` when the head is absent, which the pipeline
    treats as "regex tier only" rather than as a failure — section 15b is
    explicit that shipping without this model is an acceptable outcome if the
    patterns separate the fields well enough.
    """
    if not candidates:
        return {}

    model = runtime.load(model_name)
    median = median_cap_height(lines)

    usable: list[int] = []
    rows: list[np.ndarray] = []
    for index in candidates:
        embedding = embeddings.get(index)
        if embedding is None:
            continue
        rows.append(
            build_features(
                lines[index],
                embedding,
                label_w=label_w,
                label_h=label_h,
                median_cap_height_px=median,
            )
        )
        usable.append(index)

    if not rows:
        return {}

    batch = np.stack(rows).astype(np.float32)
    if batch.shape[1] != FEATURE_DIM:  # pragma: no cover - guarded in build_features
        raise runtime.ModelUnavailableError(
            f"feature width {batch.shape[1]} does not match the trained {FEATURE_DIM}"
        )

    logits = np.asarray(model.session.run(None, {model.input_name: batch})[0])
    probabilities = _softmax(logits)

    out: dict[int, FieldGuess] = {}
    for row, index in enumerate(usable):
        best = int(probabilities[row].argmax())
        confidence = float(probabilities[row][best])
        if confidence < MIN_CONFIDENCE:
            continue
        out[index] = FieldGuess(
            CLASSES[best],
            confidence,
            f"layout classifier ({model.version}); regex found an unlabelled address",
        )
    return out


__all__ = [
    "CLASSES",
    "MIN_CONFIDENCE",
    "MODEL_FILENAME",
    "classify_addresses",
    "is_available",
]
