"""Recognition character dictionaries — one per script head.

    "Text recognition: PP-OCRv5 `rec` — English + Devanagari heads, ONNX INT8,
     ~12 MB each. Two heads, run only on ROI crops. Script chosen per-region by
     the detector's script classifier."                   -- section 15b

A CTC head emits class indices; the dictionary is what turns those into
characters. It is not an optional asset — the wrong dictionary against the
right weights produces fluent, confident gibberish rather than an error, which
is exactly the failure mode section 14 rejects VLMs for. So the dictionary is
loaded and its length is checked against the model's output width, and a
mismatch raises rather than decodes.

**Devanagari matters more than it looks.** Section 7 calls the language
requirement the one that catches everyone out: Rule 9(1) permits Hindi *or*
English, so a pack declaring only in Hindi is compliant, and a system that
reads only Latin would report every declaration missing on it. That is a false
accusation produced by a missing text file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from vision import runtime
from vision.types import Script

DICT_FILENAMES: dict[Script, str] = {
    "latin": "devanagari_dict.txt",
    "devanagari": "devanagari_dict.txt",
}
"""The table must match the head, and there is one head -- see `recognise`.

A dictionary is not interchangeable with another of the same length. Decoding
this model's logits against an English-only table would not raise: it would
return confident, wrong text, which is the failure mode `load_dictionary`'s
docstring already warns about one index at a time."""

BLANK = ""
"""CTC blank occupies index 0 in PaddleOCR's convention; the dictionary file
does not contain it, so it is prepended at load."""


@lru_cache(maxsize=8)
def load_dictionary(script: Script) -> tuple[str, ...]:
    """Character table for a script head, blank-prefixed and space-suffixed.

    PaddleOCR's layout is `[blank] + dict_lines + [' ']`. Reproducing it
    exactly matters: an off-by-one here shifts every character by one position
    in the table, so `250 g` decodes as `141 f` — plausible-looking output that
    no test would catch unless it asserted on real text.
    """
    filename = DICT_FILENAMES.get(script)
    if filename is None:
        raise runtime.ModelUnavailableError(f"no recognition dictionary for script {script!r}")

    path = runtime.resolve(filename)
    if not path.is_file():
        raise runtime.ModelUnavailableError(
            f"recognition dictionary {filename!r} not found at {path}. "
            f"It ships with the model bundle."
        )

    lines = Path(path).read_text(encoding="utf-8").splitlines()
    characters = [line for line in lines if line != ""]
    return (BLANK, *characters, " ")


def is_available(script: Script) -> bool:
    filename = DICT_FILENAMES.get(script)
    return bool(filename) and runtime.resolve(filename).is_file()


__all__ = ["BLANK", "DICT_FILENAMES", "is_available", "load_dictionary"]
