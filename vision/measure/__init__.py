"""Measurement — deterministic geometry, no model anywhere in it.

Produces the four things `Declaration` carries and the rules read:

    height_px        cap_height.measure_cap_height / measure_numeral_height
    char_boxes       characters.character_boxes    (Rule 7(3) proviso)
    numeral_box      characters.numeral_box        (Rule 8(1) proviso, Table I)
    contrast_ratio   contrast.contrast_ratio       (Rules 9(1)(b), 18(5))

and converts the first into millimetres with a propagated tolerance, which is
what makes the REVIEW band mean something.
"""

from vision.measure.cap_height import (
    CapHeightResult,
    binarise,
    measure_cap_height,
    measure_numeral_height,
)
from vision.measure.characters import character_boxes, numeral_box
from vision.measure.contrast import contrast_ratio
from vision.measure.to_mm import GLYPH_SIGMA_PX, resolvable_threshold_mm, to_mm

__all__ = [
    "GLYPH_SIGMA_PX",
    "CapHeightResult",
    "binarise",
    "character_boxes",
    "contrast_ratio",
    "measure_cap_height",
    "measure_numeral_height",
    "numeral_box",
    "resolvable_threshold_mm",
    "to_mm",
]
