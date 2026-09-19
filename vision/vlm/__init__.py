"""The label reader: a vision model that reads the pack, and nothing more.

    "measure before building the model"            -- AKSHAR.md, section 15b

Measured on 2026-09-19, three packs from `data/declaration_blocks/`, scored
against the hand labels: the reader 17/17, the OCR path 1/17 with three values
confidently wrong. `provider.py` carries the table and the honey-jar case that
makes it matter.

This package produces `OcrLine` text and field assignments. It produces no
verdict, it is asked for none, and `rules/` does not import it. Absent is the
default and absent is fine -- with no reader installed the pipeline behaves
exactly as it did before this package existed.
"""

from vision.vlm import provider
from vision.vlm.prompt import Reading, build, parse
from vision.vlm.provider import (
    Availability,
    Reader,
    availability,
    encode,
    install,
    installed,
)
from vision.vlm.read import Applied, apply

__all__ = [
    "Applied",
    "Availability",
    "Reader",
    "Reading",
    "apply",
    "availability",
    "build",
    "encode",
    "install",
    "installed",
    "parse",
    "provider",
]
