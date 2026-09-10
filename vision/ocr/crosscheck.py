"""Second opinion on low-confidence crops — server side only.

    "Cross-check: docTR `db_resnet50` + `crnn_vgg16_bn`, server only. Second
     opinion on low-confidence crops. Disagreement between engines is a
     confidence signal, and it never runs in the browser."   -- section 15b

**What disagreement actually buys us.** A single engine returning 0.62 on a
crop tells us it is unsure. Two independent engines returning *the same string*
at 0.62 tells us something quite different — that the reading is probably right
and the confidence is pessimistic. Two engines returning different strings tells
us not to report the value at all. Neither conclusion is available from one
engine's own confidence, which is why this is worth the latency.

**Never in the browser, and never on the fast path.** It runs on the bulk
e-commerce channel and on server-side re-analysis, where a few hundred
milliseconds is free and there is no officer waiting. Section 4's 561 ms budget
does not include it and must not.

**It cannot overrule; it can only withhold.** When the engines disagree, the
crop's confidence is lowered and it may drop below the threshold at which a
declaration is emitted at all — which yields NO_DATA, not FAIL. A disagreement
between two OCR engines is not evidence that a manufacturer did anything wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from vision.types import Image, OcrLine

LOW_CONFIDENCE = 0.70
"""Below this a line is worth a second opinion. Above it the two engines agree
often enough that the latency buys nothing measurable."""

AGREEMENT_FLOOR = 0.60
"""Below this similarity the readings are treated as a genuine disagreement."""


@dataclass(frozen=True, slots=True)
class CrossCheck:
    primary: str
    secondary: str | None
    agreement: float
    """1.0 identical, 0.0 nothing in common. `None` secondary means the second
    engine was unavailable, which is not a disagreement."""

    adjusted_confidence: float
    engines: tuple[str, ...]

    @property
    def disagreed(self) -> bool:
        return self.secondary is not None and self.agreement < AGREEMENT_FLOOR


def _normalise(text: str) -> str:
    """Compare what the law cares about, not what the typesetter did.

    Whitespace and case differences between two engines are not disagreements
    about the content; `250 G` versus `250 g` is one reading, not two. Case IS
    load-bearing for the unit-symbol rules (section 13c), but those judge the
    primary engine's output, not this comparison.
    """
    return "".join(text.split()).lower()


def similarity(left: str, right: str) -> float:
    """Normalised Levenshtein similarity in [0, 1].

    Hand-rolled rather than pulled from a library: it is fifteen lines, it runs
    on strings of length ~30, and it saves a dependency in a container that
    already carries three model runtimes.
    """
    a, b = _normalise(left), _normalise(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (ca != cb),
                )
            )
        previous = current

    return 1.0 - previous[-1] / max(len(a), len(b))


_PREDICTOR: object | None = None
"""Loaded once per process. docTR's predictor costs seconds to build."""


def is_available() -> bool:
    """Is docTR installed? It is an optional server-side extra, never bundled."""
    try:
        import doctr  # noqa: F401
    except ImportError:
        return False
    return True


def _read_with_doctr(crop: Image) -> str | None:  # pragma: no cover - optional extra
    try:
        import numpy as np
        from doctr.models import ocr_predictor
    except ImportError:
        return None

    global _PREDICTOR
    if _PREDICTOR is None:
        _PREDICTOR = ocr_predictor(
            det_arch="db_resnet50", reco_arch="crnn_vgg16_bn", pretrained=True
        )
    predictor = _PREDICTOR

    result = predictor([np.asarray(crop)])
    words = [
        word.value
        for page in result.pages
        for block in page.blocks
        for line in block.lines
        for word in line.words
    ]
    return " ".join(words) if words else None


def check_line(line: OcrLine, crop: Image) -> CrossCheck:
    """Re-read one crop with the second engine and reconcile.

    Returns a `CrossCheck` even when the second engine is absent, so the caller
    has one shape to handle rather than an optional.
    """
    secondary = _read_with_doctr(crop)
    if secondary is None:
        return CrossCheck(
            primary=line.text,
            secondary=None,
            agreement=1.0,
            adjusted_confidence=line.confidence,
            engines=(line.engine,),
        )

    agreement = similarity(line.text, secondary)
    if agreement >= AGREEMENT_FLOOR:
        # Independent corroboration: raise confidence toward, but never to, 1.0.
        adjusted = min(0.98, line.confidence + (1.0 - line.confidence) * agreement * 0.5)
    else:
        # Withhold, do not overrule. A low enough confidence stops the
        # declaration being emitted, which is NO_DATA — never FAIL.
        adjusted = line.confidence * agreement

    return CrossCheck(
        primary=line.text,
        secondary=secondary,
        agreement=agreement,
        adjusted_confidence=adjusted,
        engines=(line.engine, "doctr-db_resnet50+crnn_vgg16_bn"),
    )


def needs_check(line: OcrLine) -> bool:
    return line.confidence < LOW_CONFIDENCE


__all__ = [
    "AGREEMENT_FLOOR",
    "LOW_CONFIDENCE",
    "CrossCheck",
    "check_line",
    "is_available",
    "needs_check",
    "similarity",
]
